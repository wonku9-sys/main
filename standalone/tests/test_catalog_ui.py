"""Functional GUI tests for the independent catalogue screens."""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QDate, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QFileDialog, QLineEdit

from pos2.catalog_ui import EntryDialog, PartnersPage, ProductDialog, ProductsPage, SettingsPage, UsersPage
from pos2.store import Store


@pytest.fixture(scope="module")
def app():
    result = QApplication.instance() or QApplication([])
    yield result
    for widget in result.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    result.processEvents()


@pytest.fixture
def shop(tmp_path):
    store = Store(tmp_path / "fresh-ui.db")
    store.setup_admin("manager", "관리자", "FreshAdmin2026!")
    supplier = store.save_partner({"kind": "supplier", "name": "청정축산", "code": "S1"})
    customer = store.save_partner({"kind": "customer", "name": "단골식당", "code": "C1"})
    product = store.save_product({"code": "P1", "name": "국내산 삼겹살", "barcode": "0012345678905", "base_unit": "kg",
                                  "category": "돈육", "supplier_id": supplier, "purchase_price": 10000, "sale_price": 18000,
                                  "min_qty": "1.500"})
    messages, pages = [], []
    window = SimpleNamespace(store=store, notify=messages.append, open_page=pages.append)
    yield store, window, supplier, customer, product, messages
    store.close()


def get_product(store, identifier):
    return next(p for p in store.products() if p["id"] == identifier)


def test_product_dialog_real_tabs_and_internal_save_does_not_duplicate(app, shop):
    store, _, supplier, _, _, _ = shop
    root = store.save_category({"name": "한우"})
    store.save_category({"name": "냉장육", "parent_id": root})
    dialog = ProductDialog(store)
    assert [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())] == ["상품정보", "매입정보", "판매정보", "재고정보", "변경로그", "회원지정가", "확장단위"]
    assert not any(button.isEnabled() for button in dialog.unit_buttons)
    dialog.fields["name"].setText("한우 등심")
    dialog.fields["barcode"].setText("000000001234")
    dialog.fields["category"].setText("한우")
    dialog.fields["category_mid"].setText("냉장육")
    dialog.fields["warehouse"].setText("냉장 1창고")
    dialog.fields["keywords"].setText("구이 스테이크")
    dialog.supplier.setCurrentIndex(dialog.supplier.findData(supplier))
    dialog.purchase_price.setText("30000")
    dialog.sale_price.setText("45000")
    dialog.save(False)
    identifier = dialog.saved_id
    assert identifier and dialog.result() != QDialog.DialogCode.Accepted
    assert "33.33" in dialog.margin.text()
    dialog.fields["shelf"].setText("A-02")
    dialog.save(False)
    assert dialog.saved_id == identifier
    assert len(store.products()) == 2
    saved = get_product(store, identifier)
    assert saved["category_mid"] == "냉장육"
    assert saved["warehouse"] == "냉장 1창고" and saved["shelf"] == "A-02"
    assert saved["barcode"] == "000000001234"
    assert dialog.audit_table.rowCount() == 2
    assert all(button.isEnabled() for button in dialog.unit_buttons)
    dialog.reject()
    assert get_product(store, identifier)["shelf"] == "A-02"


def test_product_barcode_enter_does_not_save_or_close(app, shop):
    store = shop[0]
    dialog = ProductDialog(store)
    dialog.show()
    dialog.fields["name"].setText("스캔만 입력")
    barcode = dialog.fields["barcode"]
    barcode.setFocus()
    QTest.keyClicks(barcode, "0011223344556")
    QTest.keyClick(barcode, Qt.Key.Key_Return)
    app.processEvents()
    assert barcode.text() == "0011223344556"
    assert dialog.saved_id is None
    assert len(store.products()) == 1
    assert dialog.isVisible()
    dialog.close()


def test_save_button_closes_but_apply_remains_open(app, shop):
    dialog = ProductDialog(shop[0])
    dialog.fields["name"].setText("클릭 저장")
    dialog.show()
    QTest.mouseClick(dialog.apply_button, Qt.MouseButton.LeftButton)
    assert dialog.isVisible()
    assert not dialog.fields['name'].text()
    dialog.fields['name'].setText('다음 상품 클릭 저장')
    QTest.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)
    assert not dialog.isVisible()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert len(shop[0].products()) == 3


def test_product_history_filters_posted_totals_and_refreshes_real_stock(app, shop):
    store, _, supplier, _, product, _ = shop
    first = store.post_document({"kind": "purchase", "date": "2026-09-10", "partner_id": supplier,
                                  "lines": [{"product_id": product, "qty": "2.500", "unit_price": 10000}]})
    store.cancel_document(first, "잘못 입력한 거래")
    store.post_document({"kind": "purchase", "date": "2026-10-10", "partner_id": supplier,
                         "lines": [{"product_id": product, "qty": "1.000", "unit_price": 12000}]})
    dialog = ProductDialog(store, get_product(store, product))
    assert dialog.history_filters['purchases'][0].isChecked()
    dialog.history_filters['purchases'][0].setChecked(False)
    assert dialog.history_tables["purchases"].rowCount() == 2
    assert "12,000" in dialog.history_summaries["purchases"].text()
    assert "1.000 kg" in dialog.stock_quantity.text()
    enabled, start, end = dialog.history_filters["purchases"]
    start.setDate(QDate(2026, 9, 1))
    end.setDate(QDate(2026, 9, 30))
    enabled.setChecked(True)
    assert dialog.history_tables["purchases"].rowCount() == 1
    assert "0 원" in dialog.history_summaries["purchases"].text()
    assert dialog.stock_table.rowCount() == 3


def test_unit_editor_writes_real_conversion_and_refreshes_audit(app, shop, monkeypatch):
    store, _, _, _, product, _ = shop
    dialog = ProductDialog(store, get_product(store, product))

    def accepted(editor):
        editor.fields["name"].setText("박스")
        editor.fields["barcode"].setText("000011119999")
        editor.fields["factor"].setText("12.500")
        editor.fields["purchase_price"].setText("120000")
        editor.fields["sale_price"].setText("180000")
        editor.buttons.accepted.emit()
        return editor.result()

    monkeypatch.setattr(EntryDialog, "exec", accepted)
    dialog.add_unit()
    units = store.units(product)
    assert len(units) == 1 and units[0]["factor"] == "12.500"
    assert units[0]["sale_price"] == 180000
    assert dialog.unit_table.rowCount() == 1
    assert dialog.audit_table.rowCount() == 2
    assert store.lookup_barcode("000011119999")["product"]["id"] == product


def test_existing_units_prevent_unsafe_base_unit_change_in_dialog(app, shop):
    store, _, _, _, product, _ = shop
    store.save_unit({"product_id": product, "name": "묶음", "factor": "2"})
    dialog = ProductDialog(store, get_product(store, product))
    dialog.unit.setCurrentText("g")
    assert dialog.save(False) is False
    assert "기본단위" in dialog.error_label.text()
    assert get_product(store, product)["base_unit"] == "kg"


def test_products_page_scan_supports_expanded_barcode_and_leading_zeros(app, shop):
    store, window, _, _, product, _ = shop
    store.save_unit({"product_id": product, "name": "500g", "factor": "0.500", "barcode": "000090001234"})
    page = ProductsPage(window)
    page.show()
    page.scan.setFocus()
    QTest.keyClicks(page.scan, "000090001234")
    QTest.keyClick(page.scan, Qt.Key.Key_Return)
    assert page.grid.selected()["id"] == product
    assert page.search.text() == "000090001234"
    assert "500g" in page.scan_result.text() and "0.500 kg" in page.scan_result.text()
    page.scan_barcode("000000000000")
    assert "미등록" in page.scan_result.text()
    page.close()


def test_products_page_filters_summary_numeric_sort_and_page_exports(app, shop):
    store, window, supplier, _, _, _ = shop
    other = store.save_product({"name": "한우 채끝", "base_unit": "g", "category": "우육", "sale_price": 9000, "supplier_id": supplier})
    page = ProductsPage(window)
    assert page.grids == [page.grid]
    page.category.setCurrentIndex(page.category.findData("우육"))
    assert page.grid.rowCount() == 1 and page.grid.selected() is None
    assert page.grid.item(0, 1).text() == "한우 채끝"
    page.category.setCurrentIndex(0)
    page.grid.sortItems(8, Qt.SortOrder.AscendingOrder)
    assert page.grid.item(0, 0).data(Qt.ItemDataRole.UserRole)["id"] == other
    assert "2품목" in page.summary.text()
    assert isinstance(page.grid.export_rows()[0][8], Decimal)


def test_catalog_only_staff_can_view_scoped_history_without_admin_audit(app, shop):
    store, window, _, _, product, _ = shop
    store.save_user({"code": "catalog", "name": "상품 담당", "password": "Catalog2026!", "role": "staff", "permissions": ["catalog"]})
    store.logout()
    store.login("catalog", "Catalog2026!")
    dialog = ProductDialog(store, get_product(store, product))
    assert dialog.tabs.count() == 7
    assert dialog.member_price_grid.rowCount()==0 and not dialog.member_price_add.isEnabled()
    assert dialog.audit_table.rowCount() == 1
    with pytest.raises(PermissionError):
        store.audit_log()
    ProductsPage(window)
    PartnersPage(window, "supplier")
    with pytest.raises(PermissionError):
        UsersPage(window)
    with pytest.raises(PermissionError):
        SettingsPage(window)


def test_product_label_action_passes_selected_ids(app, shop, monkeypatch):
    from pos2.labels import LabelDialog
    page = ProductsPage(shop[1])
    page.grid.selectRow(0)
    seen = []
    monkeypatch.setattr(LabelDialog, "exec", lambda self: seen.append(self))
    page.print_labels()
    assert len(seen) == 1


def test_partner_editor_preserves_bank_details_and_commission_policy(app, shop, monkeypatch):
    store, window, _, _, _, _ = shop
    page = PartnersPage(window, "supplier")

    def accepted(editor):
        editor.fields["code"].setText("S2")
        editor.fields["name"].setText("수수료 공급사")
        editor.fields["bank"].setText("농협")
        editor.fields["account"].setText("001-000-012345")
        editor.fields["account_holder"].setText("서영")
        editor.fields["commission_bps"].setText("1500")
        combos = editor.findChildren(QComboBox)
        combos[0].setCurrentIndex(1)
        editor.buttons.accepted.emit()
        return editor.result()

    monkeypatch.setattr(EntryDialog, "exec", accepted)
    page.add()
    saved = next(p for p in store.partners("supplier") if p["code"] == "S2")
    assert (saved["supplier_mode"], saved["commission_bps"]) == ("commission", 1500)
    assert saved["account"] == "001-000-012345" and saved["account_holder"] == "서영"
    assert page.grid.rowCount() == 2


def test_users_editor_requires_matching_password_and_persists_access(app, shop, monkeypatch):
    store, window = shop[:2]
    page = UsersPage(window)

    def accepted(editor):
        editor.fields["code"].setText("worker")
        editor.fields["name"].setText("업무 담당")
        editor.fields["password"].setText("Worker2026!")
        password_fields = [f for f in editor.findChildren(QLineEdit) if f.echoMode() == QLineEdit.EchoMode.Password]
        password_fields[-1].setText("다른 비밀번호")
        editor.buttons.accepted.emit()
        assert "일치" in editor.error_label.text()
        assert len(store.list_users()) == 1
        password_fields[-1].setText("Worker2026!")
        editor.buttons.accepted.emit()
        return editor.result()

    monkeypatch.setattr(EntryDialog, "exec", accepted)
    page.add()
    assert len(store.list_users()) == 2
    store.logout()
    actor = store.login("worker", "Worker2026!")
    assert actor["role"] == "staff" and actor["permissions"] == []


def test_settings_save_and_backup_use_supported_named_keys(app, shop, tmp_path, monkeypatch):
    store, window, _, _, _, messages = shop
    page = SettingsPage(window)
    page.fields["store_name"].setText("서영 축산")
    page.fields["earn_bps"].setText("250")
    page.fields["point_min"].setText("500")
    page.fields["point_step"].setText("50")
    page.save()
    assert store.settings()["store_name"] == "서영 축산"
    assert store.settings()["earn_bps"] == 250
    assert messages and "저장" in messages[-1]
    page.backup()
    target = store.backup_files()[0]["path"]
    other = Store(target)
    other.login("manager", "FreshAdmin2026!")
    assert other.settings()["store_name"] == "서영 축산"
    assert len(other.products()) == 1
    other.close()


def test_long_partner_form_keeps_save_outside_scroll_area(app, shop):
    dialog = EntryDialog("거래처 상세정보")
    for i in range(20):
        dialog.field(str(i), "입력항목")
    dialog.finish(lambda: None)
    dialog.resize(580, 440)
    dialog.show()
    app.processEvents()
    assert dialog.buttons.geometry().bottom() < dialog.height()
    assert dialog.buttons.isVisible()
    dialog.close()
