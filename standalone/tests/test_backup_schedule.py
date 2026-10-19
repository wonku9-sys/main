from datetime import datetime, timedelta, timezone
from pathlib import Path
import json

import pytest
from PySide6.QtCore import QTime
from PySide6.QtWidgets import QApplication, QMessageBox

from pos2.app import MainWindow
from pos2.backup_schedule import DEFAULT_BACKUP_SCHEDULE, validate_schedule
from pos2.store import Store


@pytest.fixture
def shop(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = Store(tmp_path / "seoyoung-standalone-v2.db")
    store.setup_admin("owner", "관리자", "Owner-Password-2026!")
    yield app, store
    for widget in app.topLevelWidgets():
        if isinstance(widget, MainWindow):
            widget._backup_runtime_enabled = False
            widget.navigation.suspended = True
        widget.close()
    store.close()


def policy(store, **changes):
    value = {**DEFAULT_BACKUP_SCHEDULE, **changes}
    store.save_settings({"backup_schedule": value})
    return value


def at(day, clock="19:59"):
    return datetime.fromisoformat(f"2026-10-{day:02d}T{clock}:00+09:00")


def test_daily_once_only_and_missed_days_catch_up_once(shop):
    store = shop[1]
    assert store.run_scheduled_backup(at(19)) is None
    first = store.run_scheduled_backup(at(19, "20:00"))
    assert Path(first).is_file()
    assert store.run_scheduled_backup(at(19, "20:30")) is None
    assert store.run_scheduled_backup(at(20)) is None
    assert store.run_scheduled_backup(at(24, "10:00"))
    assert store.run_scheduled_backup(at(24, "10:30")) is None
    assert len(store.backup_files()) == 2
    assert all(row["kind"] == "정기 자동" and row["managed"] for row in store.backup_files())
    assert store.inspect_backup(first)["counts"]["users"] == 1


def test_multiple_weekdays_and_interval(shop):
    store = shop[1]
    policy(store, frequency="weekly", weekdays=[0, 2])
    assert store.run_scheduled_backup(at(19)) is None  # Monday
    assert store.run_scheduled_backup(at(19, "20:01"))
    assert store.run_scheduled_backup(at(20, "21:00")) is None
    assert store.run_scheduled_backup(at(21, "20:01"))
    policy(store, frequency="interval", every_days=3)
    assert store.run_scheduled_backup(at(22, "20:01"))
    assert store.run_scheduled_backup(at(24, "21:00")) is None
    assert store.run_scheduled_backup(at(25, "20:01"))


def test_manual_mode_still_allows_exit_and_manual_backup(shop):
    store = shop[1]
    policy(store, mode="manual")
    assert store.run_scheduled_backup(at(19, "23:00")) is None
    result = store.backup_on_exit()
    assert Path(result).is_file() and "종료백업" in Path(result).name
    assert store.backup_files()[0]["kind"] == "종료 자동"
    assert Path(store.create_backup()).exists()
    policy(store, mode="manual", on_exit=False)
    assert store.backup_on_exit() is None


@pytest.mark.parametrize("changes", [
    {"mode": "online"}, {"mode": []}, {"frequency": []}, {"frequency": "monthly"},
    {"time": "25:01"}, {"time": "8:00"}, {"time": 20}, {"time": "20:00+09:00"},
    {"weekdays": [True]}, {"weekdays": [7]}, {"frequency": "weekly", "weekdays": []},
    {"every_days": 0}, {"every_days": 366}, {"every_days": True}, {"on_exit": 1},
])
def test_invalid_schedule_is_atomic(shop, changes):
    store = shop[1]
    before = store.settings()
    with pytest.raises(ValueError):
        store.save_settings({"store_name": "저장 금지", "backup_schedule": {**DEFAULT_BACKUP_SCHEDULE, **changes}})
    assert store.settings() == before


def test_failed_attempt_cleans_partial_and_retries_after_five_minutes(shop, monkeypatch):
    store = shop[1]
    backup = store._backup_file
    def fail(path):
        backup(path)
        raise ValueError("디스크 오류 검증")
    monkeypatch.setattr(store, "_backup_file", fail)
    with pytest.raises(ValueError):
        store.run_scheduled_backup(at(19, "20:00"))
    assert not list(store._backup_directory().glob("*.pending"))
    assert not store.backup_files()
    monkeypatch.setattr(store, "_backup_file", backup)
    assert store.run_scheduled_backup(at(19, "20:01")) is None
    assert store.run_scheduled_backup(at(19, "20:05"))


def test_staff_system_backup_without_settings_or_restore_authority(shop):
    store = shop[1]
    store.save_user({"code": "staff", "name": "직원", "password": "Staff-Password-2026!", "role": "staff", "permissions": []})
    store.login("staff", "Staff-Password-2026!")
    assert Path(store.backup_on_exit()).is_file()
    assert store.run_scheduled_backup(at(19, "20:00"))
    for method in (store.settings, store.backup_files):
        with pytest.raises(PermissionError):
            method()
    with pytest.raises(PermissionError):
        policy(store, mode="manual")


def test_settings_controls_save_reload_and_exit_backup_includes_saved_edits(shop, monkeypatch):
    app, store = shop
    window = MainWindow(store)
    window.show()
    window.enable_runtime()
    window.open_page("settings")
    page = window.current_page
    page.backup_frequency.setCurrentIndex(page.backup_frequency.findData("weekly"))
    for i, box in enumerate(page.backup_weekdays):
        box.setChecked(i in (1, 4))
    page.backup_time.setTime(QTime(18, 30))
    page.fields["store_name"].setText("종료 전 저장 매장")
    monkeypatch.setattr("pos2.navigation.ask_unsaved", lambda *_: QMessageBox.StandardButton.Save)
    window.close()
    assert not window.isVisible()
    assert store.backup_schedule()["weekdays"] == [1, 4]
    files = store.backup_files()
    assert len(files) == 1 and files[0]["kind"] == "종료 자동"
    assert store.inspect_backup(files[0]["path"])["store_name"] == "종료 전 저장 매장"


def test_exit_backup_failure_can_cancel_exit(shop, monkeypatch):
    _, store = shop
    window = MainWindow(store)
    window.show()
    window.enable_runtime()
    def fail():
        raise ValueError("저장공간 없음")
    monkeypatch.setattr(store, "backup_on_exit", fail)
    monkeypatch.setattr(QMessageBox, "question", lambda *_: QMessageBox.StandardButton.No)
    assert not window.close() and window.isVisible()
    assert store.actor and not window._exit_backup_done
    monkeypatch.setattr(QMessageBox, "question", lambda *_: QMessageBox.StandardButton.Yes)
    assert window.close() and not window.isVisible()


def test_schedule_survives_restore_and_invalid_policy_is_rejected(shop):
    store = shop[1]
    saved_policy = policy(store, frequency="weekly", weekdays=[2, 5], time="16:30")
    file = store.create_backup()
    policy(store, mode="manual", on_exit=False)
    store.restore_backup(file, "Owner-Password-2026!")
    store.login("owner", "Owner-Password-2026!")
    assert store.backup_schedule() == saved_policy
    store.db.execute("UPDATE settings SET value=? WHERE key='backup_schedule'", (json.dumps({"mode": "unknown"}),))
    store.db.commit()
    invalid = store.create_backup()
    with pytest.raises(ValueError, match="설정"):
        store.inspect_backup(invalid)
