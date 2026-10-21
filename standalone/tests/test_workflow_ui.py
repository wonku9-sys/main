"""Real keyboard, draft, return and count flows for the new workflow screens."""
from datetime import date
from decimal import Decimal

import pytest
from PySide6.QtCore import QCoreApplication, QDate, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMainWindow

from pos2.store import Store
from pos2.workflow_ui import ClosingsPage, CountEditor, CountsPage, LedgerPage, ReportPage, TradeDialog, TradesPage


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance
    for widget in instance.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    instance.processEvents()


@pytest.fixture
def shop(tmp_path):
    store = Store(tmp_path / "workflow.db")
    store.setup_admin("owner", "관리자", "StrongPassword2026!")
    supplier = store.save_partner({"kind": "supplier", "code": "SUP", "name": "축산 공급사"})
    customer = store.save_partner({"kind": "customer", "code": "CUS", "name": "식당 판매처"})
    product = store.save_product({"code": "P1", "name": "삼겹살", "barcode": "000000012345", "base_unit": "kg", "purchase_price": 10000, "sale_price": 18000})
    pack = store.save_unit({"product_id": product, "name": "박스", "barcode": "000000098765", "factor": "5", "purchase_price": 48000, "sale_price": 85000})
    window = QMainWindow()
    window.store, window.messages = store, []
    window.notify = window.messages.append
    yield store, window, supplier, customer, product, pack
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    store.close()


def test_hid_scan_deduplicates_retains_leading_zero_and_never_saves(app, shop):
    store, window, _, _, product, pack = shop
    dialog = TradeDialog(window, "purchase")
    dialog.show()
    dialog.focus_scan()
    for barcode in ("000000012345", "000000012345", "000000098765", "000000098765"):
        QTest.keyClicks(dialog.scan, barcode)
        QTest.keyClick(dialog.scan, Qt.Key.Key_Return)
        app.processEvents()
    assert len(dialog.line_rows) == 2
    assert dialog.line_rows[0]["product"].currentData() == product
    assert dialog.line_rows[0]["qty"].text() == "2"
    assert dialog.line_rows[1]["unit"].currentData() == pack
    assert dialog.line_rows[1]["qty"].text() == "2"
    assert dialog.line_rows[1]["price"].text() == "48000.00"
    assert store.documents() == []
    assert dialog.saved_id is None and dialog.isVisible()
    dialog.reject()


def test_unknown_scan_does_not_create_product_or_transaction(app, shop, monkeypatch):
    store, window, *_ = shop
    warnings = []
    monkeypatch.setattr("pos2.workflow_ui._warn", lambda _, error: warnings.append(str(error)))
    dialog = TradeDialog(window, "purchase")
    dialog.scan_barcode("999999999999")
    assert warnings and "바코드" in warnings[-1]
    assert len(store.products()) == 1
    assert store.documents() == []
    assert len(dialog.line_rows) == 1


def test_tab_scan_is_a_scan_not_focus_change_or_save(app, shop):
    store, window, *_ = shop
    dialog = TradeDialog(window, "purchase")
    dialog.show()
    dialog.focus_scan()
    QTest.keyClicks(dialog.scan, "000000098765")
    QTest.keyClick(dialog.scan, Qt.Key.Key_Tab)
    app.processEvents()
    assert dialog.line_rows[0]["unit"].currentData() == shop[-1]
    assert dialog.scan.text() == "" and dialog.isVisible()
    assert dialog.saved_id is None and store.documents() == []
    dialog.reject()


def test_draft_then_post_changes_stock_only_after_explicit_confirmation(app, shop, monkeypatch):
    store, window, supplier, _, product, _ = shop
    monkeypatch.setattr("pos2.workflow_ui._confirm", lambda *_: True)
    dialog = TradeDialog(window, "purchase")
    dialog.partner.setCurrentIndex(dialog.partner.findData(supplier))
    dialog.scan_barcode("000000012345")
    dialog.line_rows[0]["qty"].setText("2.500")
    dialog.line_rows[0]["price"].setText("11000")
    dialog.paid.setText("10000")
    dialog.save(False)
    draft_id = dialog.saved_id
    assert draft_id and store.document(draft_id)["status"] == "draft"
    assert store.products()[0]["stock_qty"] == "0.000"
    assert store.document(draft_id)["payments"] == []
    loaded = TradeDialog(window, "purchase", store.document(draft_id))
    loaded.save(True)
    assert loaded.saved_id == draft_id
    persisted = store.document(draft_id)
    assert persisted["status"] == "posted" and persisted["total"] == 27500
    assert len(persisted["payments"]) == 1
    assert store.products()[0]["stock_qty"] == "2.500"
    readonly = TradeDialog(window, "purchase", persisted)
    assert readonly.readonly and not readonly.scan.isEnabled()
    assert not readonly.line_rows[0]["qty"].isEnabled()


def test_date_change_preserves_manual_price_until_confirmed_quote_apply(app, shop, monkeypatch):
    store, window, *_ = shop
    dialog = TradeDialog(window, "purchase")
    dialog.scan_barcode("000000012345")
    row = dialog.line_rows[0]
    row["price"].setText("12345")
    dialog.date.setDate(dialog.date.date().addDays(-1))
    assert row["price"].text() == "12345"
    monkeypatch.setattr("pos2.workflow_ui._confirm", lambda *_: False)
    dialog.apply_quotes()
    assert row["price"].text() == "12345"
    monkeypatch.setattr("pos2.workflow_ui._confirm", lambda *_: True)
    dialog.apply_quotes()
    assert row["price"].text() == "10000.00"


def test_partial_return_draft_reopen_preserves_original_line_link(app, shop, monkeypatch):
    store, window, supplier, _, product, _ = shop
    original = store.post_document({"kind": "purchase", "date": date.today().isoformat(), "partner_id": supplier, "lines": [{"product_id": product, "qty": "3", "unit_price": 10000}], "paid": 0})
    dialog = TradeDialog(window, "purchase_return", source=store.document(original))
    dialog.line_rows[0]["qty"].setText("1.250")
    assert dialog.line_rows[0]["price"].isReadOnly()
    assert not dialog.line_rows[0]["unit"].isEnabled()
    dialog.save(False)
    draft = store.document(dialog.saved_id)
    loaded = TradeDialog(window, "purchase_return", draft)
    assert loaded.payload()["lines"][0]["source_line_id"] == store.document(original)["lines"][0]["id"]
    monkeypatch.setattr("pos2.workflow_ui._confirm", lambda *_: True)
    loaded.save(True)
    assert store.document(loaded.saved_id)["status"] == "posted"
    assert store.products()[0]["stock_qty"] == "1.750"


def test_saved_payment_can_be_voided_from_detail_with_reason(app, shop, monkeypatch):
    store, window, supplier, _, product, _ = shop
    identifier = store.post_document({"kind": "purchase", "date": date.today().isoformat(), "partner_id": supplier, "lines": [{"product_id": product, "qty": "1", "unit_price": 10000}], "paid": 3000})
    dialog = TradeDialog(window, "purchase", store.document(identifier))
    dialog.payments_grid.selectRow(0)
    monkeypatch.setattr("pos2.workflow_ui.QInputDialog.getText", lambda *_: ("입금 오류 정정", True))
    monkeypatch.setattr("pos2.workflow_ui._confirm", lambda *_: True)
    dialog.void_payment()
    assert store.document(identifier)["cash_paid"] == 0
    assert store.document(identifier)["payments"][0]["voided"] == 1
    assert dialog.payments_grid.export_rows()[0][5] == "취소"


def test_count_sort_uses_product_identity_and_persists_before_apply(app, shop):
    store, window, _, _, first, _ = shop
    second = store.save_product({"code": "AAA", "name": "목살", "base_unit": "kg", "purchase_price": 15000})
    dialog = CountEditor(window)
    dialog.inputs[first].setText("2.500")
    dialog.inputs[second].setText("1.250")
    dialog.grid.sortItems(0, Qt.SortOrder.DescendingOrder)
    dialog.save()
    count = store.count(dialog.saved_id)
    assert count["status"] == "draft"
    assert {r["product_id"]: r["counted_qty"] for r in count["items"]} == {first: "2.500", second: "1.250"}
    assert all(p["stock_qty"] == "0.000" for p in store.products())
    store.apply_count(dialog.saved_id)
    assert {p["id"]: p["stock_qty"] for p in store.products()} == {first: "2.500", second: "1.250"}


def test_pages_show_real_records_and_numeric_print_export_data(app, shop, tmp_path):
    store, window, supplier, customer, product, _ = shop
    store.post_document({"kind": "purchase", "date": date.today().isoformat(), "partner_id": supplier, "lines": [{"product_id": product, "qty": "2", "unit_price": 10000}], "paid": 1000})
    store.post_document({"kind": "sale", "date": date.today().isoformat(), "partner_id": customer, "lines": [{"product_id": product, "qty": "0.500", "unit_price": 18000}], "paid": 9000})
    purchases = TradesPage(window, "purchase")
    purchases.refresh()
    assert purchases.grid.rowCount() == 2  # One voucher and the fixed totals row.
    assert purchases.grid.export_rows()[0][6] == 20000
    assert purchases.grid.export_rows()[1][6] == 20000
    ledger = LedgerPage(window)
    ledger.partner.setCurrentIndex(ledger.partner.findData(supplier))
    ledger.refresh()
    assert "19,000" in ledger.summary.text()
    report = ReportPage(window)
    report.refresh()
    assert report.grid.rowCount() >= 1
    target = report.grid.to_pdf(tmp_path / "report.pdf", "실제 거래 분석")
    assert target.read_bytes().startswith(b"%PDF-")
    counts = CountsPage(window)
    counts.refresh()
    closings = ClosingsPage(window)
    closings.refresh()
    assert "9,000" in closings.cash_summary.text()


def test_trade_only_and_inventory_only_roles_do_not_leak_or_block_pages(app, shop):
    store, window, *_ = shop
    store.save_user({"code": "cashier", "name": "계산원", "password": "CashierPassword2026!", "role": "staff", "permissions": ["trade"], "active": True})
    store.save_user({"code": "counter", "name": "재고 담당", "password": "CounterPassword2026!", "role": "staff", "permissions": ["inventory"], "active": True})
    store.logout()
    store.login("cashier", "CashierPassword2026!")
    dialog = TradeDialog(window, "sale")
    assert dialog.products and dialog.partner.count() > 1
    page = ClosingsPage(window)
    assert page.tabs.isTabEnabled(0) and not page.tabs.isTabEnabled(1)
    page.refresh()
    store.logout()
    store.login("counter", "CounterPassword2026!")
    inventory = ClosingsPage(window)
    assert not inventory.tabs.isTabEnabled(0) and inventory.tabs.isTabEnabled(1)
    inventory.refresh()
