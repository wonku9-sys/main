"""Supplier-scoped catalog popup, photo-style purchase grid and actual balances."""
from datetime import date
from decimal import Decimal

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMainWindow, QMessageBox

from pos2.store import Store
from pos2.workflow_ui import ProductPicker, TradeDialog


@pytest.fixture
def shop(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    store = Store(tmp_path / "purchase.db")
    store.setup_admin("owner", "관리자", "Owner-Password-2026!")
    first = store.save_partner({"kind": "supplier", "code": "S01", "name": "서영 축산", "business_no": "123-45-67890"})
    second = store.save_partner({"kind": "supplier", "code": "S02", "name": "다른 공급사"})
    product = store.save_product({"name": "한돈 삼겹살", "specification": "500g 냉장", "supplier_id": first, "base_unit": "kg", "barcode": "000012345", "purchase_price": 10000, "sale_price": 18000})
    other = store.save_product({"name": "등심", "supplier_id": second, "purchase_price": 20000})
    unassigned = store.save_product({"name": "공급사 미지정"})
    unit = store.save_unit({"product_id": product, "name": "박스", "barcode": "000098765", "factor": "5", "purchase_price": 48000, "sale_price": 85000})
    window = QMainWindow()
    window.store = store
    window.notify = lambda *_: None
    monkeypatch.setattr(QMessageBox, "warning", lambda *_: QMessageBox.StandardButton.Ok)
    yield app, store, window, first, second, product, other, unassigned, unit
    for widget in app.topLevelWidgets():
        widget.close()
    store.close()


def make_dialog(shop):
    dialog = TradeDialog(shop[2], "purchase")
    dialog.partner.setCurrentIndex(dialog.partner.findData(shop[3]))
    return dialog


def ids(picker):
    return {picker.grid.item(row, 0).data(Qt.ItemDataRole.UserRole)["id"] for row in range(picker.grid.rowCount())}


def test_supplier_only_default_and_uncheck_all_including_unassigned(shop):
    dialog = make_dialog(shop)
    picker = ProductPicker(dialog)
    assert picker.supplier_only.isChecked()
    assert ids(picker) == {shop[5]}
    assert "서영 축산" in picker.supplier_label.text()
    picker.supplier_only.setChecked(False)
    assert ids(picker) == {shop[5], shop[6], shop[7]}
    picker.search.setText("500g")
    assert ids(picker) == {shop[5]}
    picker.search.setText("등심")
    assert ids(picker) == {shop[6]}
    picker.supplier_only.setChecked(True)
    assert picker.grid.rowCount() == 0
    assert shop[1].documents() == []


def test_sorted_multicheck_and_scope_change_never_applies_hidden_other_supplier(shop, monkeypatch):
    dialog = make_dialog(shop)
    picker = ProductPicker(dialog)
    picker.supplier_only.setChecked(False)
    picker.grid.sortItems(2, Qt.SortOrder.DescendingOrder)
    picker.check_all(True)
    assert set(picker.checked) == {shop[5], shop[6], shop[7]}
    picker.search.setText("500g")
    assert len(picker.checked) == 3
    picker.supplier_only.setChecked(True)
    assert set(picker.checked) == {shop[5]}
    picker.apply_checked()
    assert picker.result() == QDialog.DialogCode.Accepted
    assert [record["id"] for record, _ in picker.selections] == [shop[5]]
    def choose_all(other):
        other.supplier_only.setChecked(False)
        other.check_all(True)
        other.apply_checked()
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(ProductPicker, "exec", choose_all)
    dialog.pick_product()
    assert {row["product"].currentData() for row in dialog.line_rows} == {shop[5], shop[6], shop[7]}
    assert not shop[1].documents()


def test_enter_applies_checked_items_without_saving_or_posting(shop):
    picker = ProductPicker(make_dialog(shop))
    picker.show()
    picker.check_all(True)
    picker.search.setFocus()
    QTest.keyClick(picker.search, Qt.Key.Key_Return)
    shop[0].processEvents()
    assert picker.result() == QDialog.DialogCode.Accepted
    assert len(picker.selections) == 1
    assert not shop[1].documents()


def test_purchase_grid_reference_fields_pack_conversion_and_partial_payment(shop):
    dialog = make_dialog(shop)
    assert dialog.table.columnCount() == 15
    assert "123-45-67890" in dialog.partner_info.text()
    dialog.scan_barcode("000098765")
    row = dialog.line_rows[0]
    row["qty"].setText("2.500")
    assert row["spec"].text() == "500g 냉장"
    assert row["barcode"].text() == "000098765"
    assert row["factor"].text() == "5"
    assert row["base_qty"].text() == "12.5 kg"
    assert row["total"].text() == "120,000.00"
    assert "미지급잔액  120,000.00원" in dialog.balance_label.text()
    assert dialog.payment_status.text() == "미결제"
    dialog.paid.setText("20,000")
    assert "100,000.00원" in dialog.balance_label.text()
    assert dialog.payment_status.text() == "부분결제"
    dialog.paid.setText("120000")
    assert "0.00원" in dialog.balance_label.text()
    assert "결제완료" in dialog.payment_status.text() and "확정 전" in dialog.payment_status.text()
    dialog.paid.setText("120001")
    assert "입력" in dialog.balance_label.text()
    assert not shop[1].documents()


def test_posted_balance_includes_later_payment_and_return_credits(shop):
    _, store, window, supplier, _, product, *_ = shop
    original = store.post_document({"kind": "purchase", "date": date.today().isoformat(), "partner_id": supplier, "lines": [{"product_id": product, "qty": "5", "unit_price": 10000}], "paid": 10000})
    returned = store.post_document({"kind": "purchase_return", "date": date.today().isoformat(), "partner_id": supplier, "source_id": original, "lines": [{"product_id": product, "source_line_id": store.document(original)["lines"][0]["id"], "qty": "2"}], "paid": 0})
    dialog = TradeDialog(window, "purchase", original)
    assert dialog.readonly
    assert dialog.line_rows[0]["total"].text() == "50,000.00"
    assert "20,000.00원" in dialog.balance_label.text()
    assert dialog.payment_status.text() == "부분결제"
    assert store.document(returned)["balance"] == 0


def test_mixed_units_quantity_not_added_and_integer_won_rounding_matches_post(shop):
    dialog = make_dialog(shop)
    dialog.scan_barcode("000012345")
    row = dialog.line_rows[0]
    row["qty"].setText("0.125")
    row["price"].setText("10000.6")
    other = shop[1].save_product({"name": "양념", "base_unit": "개", "purchase_price": 500})
    dialog.products = shop[1].products()
    dialog.product_map = {p["id"]: p for p in dialog.products}
    dialog.add_line(other, quantity="2")
    assert row["total"].text() == "1,250.08"
    assert "0.125 kg" in dialog.quantity_label.text() and "2 개" in dialog.quantity_label.text()
    preview = shop[1].save_draft(dialog.payload())
    assert shop[1].document(preview)["total"] == Decimal("2250.08")


def test_purchase_excel_uses_numeric_values_and_saved_balances_not_catalog_prices(shop, monkeypatch):
    dialog = make_dialog(shop)
    dialog.scan_barcode("000098765")
    captured = []
    monkeypatch.setattr("pos2.widgets.export_rows", lambda *args: captured.append(args))
    dialog.export_document()
    assert captured[0][3][0][0] == "미확정 입력"
    assert captured[0][3][0][-3:] == [Decimal("1"), 48000, 48000]
    assert not shop[1].documents()
