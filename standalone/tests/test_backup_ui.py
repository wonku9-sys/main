from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QInputDialog, QMainWindow, QMessageBox

from pos2.app import MainWindow
from pos2.catalog_ui import SettingsPage
from pos2.store import Store
from pos2.workflow_ui import PartnerPicker, ProductPicker, TradeDialog, TradesPage


@pytest.fixture
def shop(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    store = Store(tmp_path / "data-v2" / "seoyoung-standalone-v2.db")
    store.setup_admin("owner", "관리자", "Owner-Password-2026!")
    window = QMainWindow()
    window.store, window.messages, window.restored = store, [], []
    window.notify = window.messages.append
    window.finish_restore = window.restored.append
    monkeypatch.setattr(QMessageBox, "warning", lambda *_: QMessageBox.StandardButton.Ok)
    yield app, store, window
    for widget in app.topLevelWidgets():
        widget.close()
    store.close()


def test_settings_backup_list_and_selected_restore_with_short_warning(shop, monkeypatch):
    _, store, window = shop
    page = SettingsPage(window)
    page.backup()
    assert page.backup_grid.rowCount() == 1
    selected = page.backup_grid.selected()
    assert Path(selected["path"]).parent == store.path.parent / "backups"
    store.save_member({"code": "LATER", "name": "백업 이후 회원"})
    warnings = []
    monkeypatch.setattr("pos2.catalog_ui._confirm", lambda parent, title, text: warnings.append(text) or True)
    monkeypatch.setattr(QInputDialog, "getText", lambda *_: ("Owner-Password-2026!", True))
    page.restore_selected()
    assert len(warnings) == 1 and "주의" in warnings[0] and "현재 자료" in warnings[0]
    assert len(warnings[0]) < 250
    assert len(window.restored) == 1
    assert Path(window.restored[0]["safety_backup"]).exists()
    assert store.actor is None
    store.login("owner", "Owner-Password-2026!")
    assert not store.members("LATER")


@pytest.mark.parametrize("cancel_at", ["file", "warning", "password"])
def test_cancelled_restore_leaves_database_and_backup_count_unchanged(shop, monkeypatch, cancel_at):
    _, store, window = shop
    page = SettingsPage(window)
    file = store.create_backup()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_: ("" if cancel_at == "file" else file, ""))
    monkeypatch.setattr("pos2.catalog_ui._confirm", lambda *_: cancel_at != "warning")
    monkeypatch.setattr(QInputDialog, "getText", lambda *_: ("Owner-Password-2026!", cancel_at != "password"))
    store.save_member({"code": "KEEP", "name": "유지"})
    page.restore()
    assert store.members("KEEP")
    assert len(store.backup_files()) == 1
    assert not window.restored


def test_weekly_deletion_notification_is_shown_and_no_notice_for_no_deletion(shop, monkeypatch):
    _, store, _ = shop
    window = MainWindow(store)
    window.show()
    notices = []
    monkeypatch.setattr(QMessageBox, "information", lambda parent, title, text: notices.append((title, text)))
    monkeypatch.setattr(store, "run_backup_retention", lambda: {"deleted": ["old1.db", "old2.db"], "failed": [], "kept": 15})
    window.maintain_backups()
    assert len(notices) == 1 and "2개" in notices[0][1] and "15개" in notices[0][1]
    monkeypatch.setattr(store, "run_backup_retention", lambda: {"deleted": [], "failed": [], "kept": 15})
    window.maintain_backups()
    assert len(notices) == 1


def test_purchase_period_and_supplier_lookup_filter_and_all_supplier_reset(shop, monkeypatch):
    _, store, window = shop
    first = store.save_partner({"kind": "supplier", "code": "001", "name": "한돈 공급사"})
    second = store.save_partner({"kind": "supplier", "code": "002", "name": "한우 공급사"})
    product = store.save_product({"name": "삼겹살"})
    dates = [date.today() - timedelta(days=n) for n in (2, 1, 0)]
    ids = []
    for when, partner in ((dates[0], first), (dates[1], first), (dates[2], second)):
        ids.append(store.post_document({"kind": "purchase", "date": when.isoformat(), "partner_id": partner, "lines": [{"product_id": product, "qty": "1", "unit_price": 10000}], "paid": 3000}))
    page = TradesPage(window, "purchase")
    page.start.setDate(QDate(dates[1].year, dates[1].month, dates[1].day))
    page.end.setDate(QDate(dates[2].year, dates[2].month, dates[2].day))
    page.refresh()
    assert page.grid.rowCount() == 2 and "20,000" in page.summary.text()
    assert not page.partner_lookup.icon().isNull()
    def choose(dialog):
        assert dialog.for_filter
        dialog.search.setText("001")
        rows = [dialog.grid.item(i, 0).data(Qt.ItemDataRole.UserRole) for i in range(dialog.grid.rowCount())]
        dialog.selected_record = next(row for row in rows if row["id"] == first)
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(PartnerPicker, "exec", choose)
    page.pick_filter_partner()
    assert page.grid.rowCount() == 1
    assert page.grid.item(0, 0).data(Qt.ItemDataRole.UserRole)["id"] == ids[1]
    page.partner_filter.setCurrentIndex(0)
    assert page.grid.rowCount() == 2


def test_purchase_registration_selects_supplier_then_existing_catalog_product(shop, monkeypatch):
    _, store, window = shop
    supplier = store.save_partner({"kind": "supplier", "code": "001", "name": "한돈 공급사"})
    product = store.save_product({"name": "삼겹살", "specification": "500g", "purchase_price": 10000, "supplier_id": supplier})
    page = TradesPage(window, "purchase")
    calls = []
    def supplier_pick(dialog):
        assert not dialog.for_filter
        dialog.search.setText("한돈")
        dialog.grid.selectRow(0)
        dialog.choose()
        calls.append("supplier")
        return QDialog.DialogCode.Accepted
    def product_pick(dialog):
        dialog.search.setText("500g")
        dialog.grid.selectRow(0)
        dialog.choose()
        return QDialog.DialogCode.Accepted
    def trade_popup(dialog):
        assert dialog.partner.currentData() == supplier
        calls.append("trade")
        dialog.pick_product()
        assert dialog.line_rows[0]["product"].currentData() == product
        assert dialog.line_rows[0]["price"].text() == "10000.00"
        assert store.documents() == []
        return QDialog.DialogCode.Rejected
    monkeypatch.setattr(PartnerPicker, "exec", supplier_pick)
    monkeypatch.setattr(ProductPicker, "exec", product_pick)
    monkeypatch.setattr(TradeDialog, "exec", trade_popup)
    page.new_trade()
    assert calls == ["supplier", "trade"]
