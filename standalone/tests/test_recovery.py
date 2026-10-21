from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import os
import shutil
import sqlite3

import pytest

from pos2.demo import seed, DEMO_CODE, DEMO_PASSWORD
from pos2.store import Store
import pos2.recovery as recovery


@pytest.fixture
def shop(tmp_path):
    store = Store(tmp_path / "data-v2" / "seoyoung-standalone-v2.db")
    seed(store)
    yield store
    store.close()


def table_rows(db, table):
    return [tuple(row) for row in db.execute(f'SELECT * FROM "{table}" ORDER BY rowid')]


def test_managed_folder_listing_and_complete_restore_with_safety_copy(shop):
    source = shop.create_backup()
    assert Path(source).parent == shop.path.parent / "backups"
    tables = [row[0] for row in shop.db.execute("SELECT name FROM sqlite_master WHERE type='table'") if row[0] not in {"audit", "restore_state", "code_sequences"}]
    expected = {table: table_rows(shop.db, table) for table in tables}
    shop.save_member({"code": "AFTER", "name": "백업 이후 회원"})
    member = shop.members()[0]
    shop.adjust_points(member["id"], 777, "백업 이후")
    details = shop.inspect_backup(source)
    result = shop.restore_backup(source, DEMO_PASSWORD, details["digest"])
    assert shop.actor is None and result["restart_required"]
    assert Path(result["safety_backup"]).is_file()
    assert {table: table_rows(shop.db, table) for table in tables} == expected
    shop.login(DEMO_CODE, DEMO_PASSWORD)
    assert not shop.members("AFTER")
    assert shop.db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert shop.db.execute("PRAGMA foreign_key_check").fetchall() == []
    saved = Store(result["safety_backup"])
    try:
        saved.login(DEMO_CODE, DEMO_PASSWORD)
        assert saved.members("AFTER")
    finally:
        saved.close()
    assert len(shop.backup_files()) == 2


def test_old_v201_release_backup_is_accepted_without_modifying_it(shop, tmp_path):
    legacy = tmp_path / "v2.0.1.db"
    shop.backup(legacy)
    connection = sqlite3.connect(legacy, isolation_level=None)
    connection.execute("PRAGMA foreign_keys=OFF")
    from pos2.currency import MONEY_COLUMNS
    triggers = connection.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name IN ('inventory_closes','inventory_close_lines','cash_closes')").fetchall()
    for name, _ in triggers:
        connection.execute(f'DROP TRIGGER "{name}"')
    for table, columns in MONEY_COLUMNS.items():
        connection.execute(f'UPDATE "{table}" SET ' + ",".join(f'"{column}"="{column}"/100' for column in columns))
    for _, sql in triggers:
        connection.execute(sql)
    connection.execute("ALTER TABLE products DROP COLUMN price_basis")
    connection.execute("ALTER TABLE document_lines DROP COLUMN price_basis")
    connection.execute("ALTER TABLE documents DROP COLUMN rounding_mode")
    connection.execute("DROP TABLE supplier_group_members")
    connection.execute("DROP TABLE supplier_groups")
    connection.execute("DROP TABLE supplier_profiles")
    connection.execute("DROP TABLE restore_state")
    connection.execute("DROP TABLE code_sequences")
    connection.execute("DROP TABLE product_categories")
    connection.execute("ALTER TABLE payments DROP COLUMN supplier_settlement_id")
    connection.execute("DROP TABLE supplier_settlements")
    connection.execute("ALTER TABLE products DROP COLUMN retirement_target")
    connection.execute("PRAGMA user_version=200")
    connection.close()
    original = legacy.read_bytes()
    info = shop.inspect_backup(legacy)
    assert info["schema_version"] == 200
    shop.restore_backup(legacy, DEMO_PASSWORD, info["digest"])
    assert legacy.read_bytes() == original
    shop.login(DEMO_CODE, DEMO_PASSWORD)
    assert len(shop.products()) == 6
    assert shop.db.execute("PRAGMA user_version").fetchone()[0] == recovery.SCHEMA_VERSION


@pytest.mark.parametrize("fault", ["plain", "foreign", "future", "missing_admin", "modified_trigger", "bad_json", "bad_fk", "damaged"])
def test_invalid_backups_never_replace_live_data_or_create_safety_copy(shop, tmp_path, fault):
    source = tmp_path / f"{fault}.db"
    if fault == "plain":
        source.write_bytes(b"not a database")
    else:
        shop.backup(source)
        db = sqlite3.connect(source, isolation_level=None)
        if fault == "foreign":
            db.execute("PRAGMA application_id=17")
        elif fault == "future":
            db.execute("PRAGMA user_version=999")
        elif fault == "missing_admin":
            db.execute("UPDATE users SET active=0")
        elif fault == "modified_trigger":
            db.execute("DROP TRIGGER point_entries_immutable_update")
        elif fault == "bad_json":
            db.execute("UPDATE settings SET value='oops' WHERE key='point_step'")
        elif fault == "bad_fk":
            db.execute("PRAGMA foreign_keys=OFF")
            db.execute("UPDATE document_lines SET product_id=9999999")
        db.close()
        if fault == "damaged":
            source.write_bytes(source.read_bytes()[:300])
    before = table_rows(shop.db, "products"), table_rows(shop.db, "documents")
    with pytest.raises(ValueError):
        shop.restore_backup(source, DEMO_PASSWORD)
    assert before == (table_rows(shop.db, "products"), table_rows(shop.db, "documents"))
    assert not shop.backup_files()
    assert shop.actor["role"] == "admin"


def test_same_file_password_and_changed_preview_are_blocked(shop, tmp_path):
    with pytest.raises(ValueError, match="현재 사용"):
        shop.inspect_backup(shop.path)
    source = shop.create_backup()
    with pytest.raises(ValueError, match="비밀번호"):
        shop.restore_backup(source, "wrong")
    info = shop.inspect_backup(source)
    db = sqlite3.connect(source)
    db.execute("UPDATE products SET memo='changed after preview'")
    db.commit()
    db.close()
    with pytest.raises(ValueError, match="변경"):
        shop.restore_backup(source, DEMO_PASSWORD, info["digest"])
    assert len(shop.backup_files()) == 1


def test_restore_rejects_in_use_wal_source_and_unprivileged_user(shop, tmp_path):
    source = tmp_path / "selected.db"
    shop.backup(source)
    wal = Path(str(source) + "-wal")
    wal.write_bytes(b"active wal")
    with pytest.raises(ValueError, match="사용 중"):
        shop.inspect_backup(source)
    shop.save_user({"code": "staff", "name": "직원", "role": "staff", "password": "Staff-Password-2026!", "permissions": ["catalog"]})
    shop.login("staff", "Staff-Password-2026!")
    with pytest.raises(PermissionError):
        shop.restore_backup(source, "Staff-Password-2026!")
    with pytest.raises(PermissionError):
        shop.backup_files()


def test_restore_invalidates_another_open_session_and_preserves_code_sequence(shop):
    source = shop.create_backup()
    other = Store(shop.path)
    try:
        other.login(DEMO_CODE, DEMO_PASSWORD)
        identifier = shop.save_product({"name": "백업 후 코드"})
        code = next(p["code"] for p in shop.products() if p["id"] == identifier)
        shop.delete_product(identifier)
        shop.restore_backup(source, DEMO_PASSWORD)
        with pytest.raises(PermissionError, match="복원"):
            other.products()
        shop.login(DEMO_CODE, DEMO_PASSWORD)
        new = shop.save_product({"name": "복원 후 코드"})
        new_code = next(p["code"] for p in shop.products() if p["id"] == new)
        assert int(new_code[1:]) > int(code[1:])
    finally:
        other.close()


def test_copy_failure_rolls_back_to_safety_copy(shop, monkeypatch):
    source = shop.create_backup()
    shop.save_member({"code": "KEEP", "name": "유지할 회원"})
    original_copy = recovery._copy_database
    calls = []
    def injected(src, dst, timeout=10):
        calls.append(True)
        if len(calls) == 1:
            raise sqlite3.OperationalError("simulated I/O failure")
        return original_copy(src, dst, timeout)
    monkeypatch.setattr(recovery, "_copy_database", injected)
    with pytest.raises(ValueError, match="이전 자료로"):
        shop.restore_backup(source, DEMO_PASSWORD)
    assert shop.members("KEEP")
    assert len(shop.backup_files()) == 2


def test_weekly_retention_keeps_latest_fifteen_and_does_not_touch_external_files(shop):
    start = datetime(2026, 10, 19, tzinfo=timezone.utc)
    assert not shop.run_backup_retention(start)["due"]
    files = []
    for i in range(20):
        file = Path(shop.create_backup())
        os.utime(file, ns=(1_800_000_000_000_000_000 + i * 1_000_000, 1_800_000_000_000_000_000 + i * 1_000_000))
        files.append(file)
    external = files[0].parent / "사용자가 보관한 원본.db"
    shutil.copy2(files[0], external)
    assert not shop.run_backup_retention(start + timedelta(days=6, hours=23))["deleted"]
    result = shop.run_backup_retention(start + timedelta(days=7))
    assert len(result["deleted"]) == 5
    assert all(file.exists() for file in files[-15:])
    assert all(not file.exists() for file in files[:5])
    assert external.exists()
    assert not shop.run_backup_retention(start + timedelta(days=8))["due"]


@pytest.mark.parametrize("count", [0, 1, 15])
def test_retention_never_deletes_fifteen_or_fewer(shop, count):
    start = datetime(2026, 10, 19, tzinfo=timezone.utc)
    shop.run_backup_retention(start)
    for _ in range(count):
        shop.create_backup()
    result = shop.run_backup_retention(start + timedelta(days=7))
    assert not result["deleted"]
    assert len(shop.backup_files()) == count


def test_corrupt_retention_state_resets_schedule_without_deleting(shop):
    folder = shop._backup_directory()
    (folder / ".retention.json").write_text("invalid", encoding="utf-8")
    result = shop.run_backup_retention()
    assert not result["deleted"] and not result["due"]
    assert json.loads((folder / ".retention.json").read_text())["keep"] == 15
