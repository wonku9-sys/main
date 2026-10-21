"""Supplier dropdown/search share one read-only, cached catalogue filter."""
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt, QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from pos2.catalog_ui import ProductsPage, SupplierFilterDialog
from pos2.store import Store


@pytest.fixture
def shop(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = Store(tmp_path/'supplier-filter.db')
    store.setup_admin('owner', '관리자', 'Owner-Password-2026!')
    first = store.save_partner(dict(kind='supplier', code='S010', name='가나다 유통'))
    second = store.save_partner(dict(kind='supplier', code='S020', name='ABC 공급사'))
    inactive = store.save_partner(dict(kind='supplier', code='S030', name='이전 공급사', active=False))
    store.save_product(dict(name='가나다 상품', supplier_id=first))
    store.save_product(dict(name='ABC 상품', supplier_id=second))
    store.save_product(dict(name='과거 공급 상품', supplier_id=inactive))
    window = SimpleNamespace(store=store, notify=lambda *_: None)
    yield app, store, window, first, second, inactive
    for widget in app.topLevelWidgets():
        widget.close(); widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents(); store.close()


def test_metadata_is_one_supplier_select_without_ledger_queries(shop, monkeypatch):
    _, store, _, first, second, inactive = shop
    monkeypatch.setattr(store, '_partner_balance', lambda *_: pytest.fail('Filter calculated supplier balances'))
    statements = []; store.db.set_trace_callback(statements.append)
    try: rows = store.catalog_suppliers()
    finally: store.db.set_trace_callback(None)
    assert {r['id'] for r in rows} == {first, second, inactive}
    assert set(rows[0]) == {'id', 'name', 'code', 'active', 'supplier_mode'}
    assert sum('FROM partners' in sql for sql in statements) == 1
    assert not any('FROM documents' in sql or 'FROM payments' in sql for sql in statements)


def test_dropdown_opens_from_text_and_filters_inactive_history(shop):
    app, store, window, _, second, inactive = shop
    page = ProductsPage(window); page.show(); app.processEvents()
    combo = page.supplier
    assert combo.itemText(0) == '전체 공급사' and combo.itemData(0) is None
    assert not combo.isEditable() and not page.supplier_search_button.icon().isNull()
    assert 'step-down.svg' in combo.styleSheet()
    assert page.supplier_search_button.accessibleName() == '공급사 검색'
    QTest.mouseClick(combo, Qt.MouseButton.LeftButton, pos=combo.rect().center())
    app.processEvents(); assert combo.view().isVisible(); combo.hidePopup()
    combo.setCurrentIndex(combo.findData(second))
    assert len(page._catalog_matches) == 1 and page._catalog_matches[0]['supplier_id'] == second
    combo.setCurrentIndex(combo.findData(inactive))
    assert '무효' in combo.currentText() and page._catalog_matches[0]['supplier_id'] == inactive
    combo.setCurrentIndex(0); assert len(page._catalog_matches) == 3
    assert not store.documents()


def test_popup_search_name_code_keyboard_and_double_click(shop, monkeypatch):
    app, store, _, first, second, _ = shop
    dialog = SupplierFilterDialog(store, selected_id=first)
    assert dialog.grid.selected()['id'] == first
    original = store.catalog_suppliers
    monkeypatch.setattr(store, 'catalog_suppliers', lambda: pytest.fail('Typing reloaded supplier metadata'))
    dialog.search.setText('abc'); assert dialog.grid.rowCount() == 1
    assert dialog.grid.selected()['id'] == second
    dialog.search.setText('s010'); assert dialog.grid.selected()['id'] == first
    dialog.search.setText('없는 공급사'); assert dialog.grid.rowCount() == 0 and not dialog.choose_button.isEnabled()
    dialog.choose(); assert dialog.record is None
    monkeypatch.setattr(store, 'catalog_suppliers', original)
    dialog.search.setText('S020'); dialog.show(); app.processEvents()
    QTest.keyClick(dialog.search, Qt.Key.Key_Down); assert dialog.grid.hasFocus()
    QTest.keyClick(dialog.grid, Qt.Key.Key_Return); app.processEvents()
    assert dialog.result() == QDialog.DialogCode.Accepted and dialog.record['id'] == second
    other = SupplierFilterDialog(store); other.search.setText('가나다'); other.show(); app.processEvents()
    other.grid.cellDoubleClicked.emit(0, 0)
    assert other.result() == QDialog.DialogCode.Accepted and other.record['id'] == first


def test_magnifier_apply_cancel_and_all_preserve_other_filters(shop, monkeypatch):
    _, store, window, first, second, _ = shop
    page = ProductsPage(window); page.search.setText('상품'); page.refresh()
    page.supplier.setCurrentIndex(page.supplier.findData(first))
    revision = store.audit_revision()
    def select_second(dialog):
        assert dialog.grid.selected()['id'] == first
        dialog.search.setText('S020'); dialog.choose(); return dialog.result()
    monkeypatch.setattr(SupplierFilterDialog, 'exec', select_second)
    page.supplier_search_button.click()
    assert page.supplier.currentData() == second and page.search.text() == '상품'
    assert len(page._catalog_matches) == 1
    def cancel(dialog):
        dialog.search.setText('S010'); dialog.reject(); return dialog.result()
    monkeypatch.setattr(SupplierFilterDialog, 'exec', cancel)
    page.supplier_search_button.click(); assert page.supplier.currentData() == second
    def select_all(dialog):
        dialog.grid.setCurrentCell(0, 0); dialog.choose(); return dialog.result()
    monkeypatch.setattr(SupplierFilterDialog, 'exec', select_all)
    page.supplier_search_button.click()
    assert page.supplier.currentData() is None and len(page._catalog_matches) == 3
    assert store.audit_revision() == revision and not store.documents()


def test_refresh_reuses_dropdown_until_metadata_changes(shop, monkeypatch):
    _, store, window, first, _, _ = shop
    page = ProductsPage(window); page.supplier.setCurrentIndex(page.supplier.findData(first))
    original = page.supplier.clear
    monkeypatch.setattr(page.supplier, 'clear', lambda: pytest.fail('Search rebuilt the supplier dropdown'))
    page.search.setText('가나다'); page.refresh()
    page.search.clear(); page.refresh()
    monkeypatch.setattr(page.supplier, 'clear', original)
    store.save_partner(dict(name='변경된 공급사'), first); page.refresh()
    assert page.supplier.currentData() == first and page.supplier.currentText() == '변경된 공급사'


def test_large_popup_pages_debounces_and_stops_timer_on_close(shop, monkeypatch):
    _, store, _, _, _, _ = shop
    with store._tx():
        store.db.executemany("INSERT INTO partners(kind,code,name,opening_date) VALUES('supplier',?,?,'2026-10-20')",
                             [(f'L{i:04d}', f'대량 공급사 {i:04d}') for i in range(1201)])
    dialog = SupplierFilterDialog(store)
    assert dialog.grid.rowCount() == 500 and len(dialog.matches) == 1205
    dialog.move_page(2); assert dialog.grid.rowCount() == 205
    assert dialog.grid.verticalHeaderItem(0).text() == '1001'
    monkeypatch.setattr(store, 'catalog_suppliers', lambda: pytest.fail('Search reloaded metadata'))
    dialog.search.setText('L1200'); assert dialog.timer.isActive()
    dialog.refresh(); assert dialog.grid.rowCount() == 1 and dialog.grid.item(0, 1).text() == 'L1200'
    dialog.search.setText('대량'); assert dialog.timer.isActive()
    dialog.reject(); assert not dialog.timer.isActive()


def test_deleted_supplier_and_revoked_account_cannot_be_applied(shop):
    _, store, _, _, _, _ = shop
    identifier = store.save_partner(dict(kind='supplier', name='삭제할 임시 공급사'))
    dialog = SupplierFilterDialog(store, selected_id=identifier)
    store.delete_partner(identifier); dialog.choose()
    assert dialog.record is None and dialog.result() != QDialog.DialogCode.Accepted
    assert '다시 선택' in dialog.notice.text()
    dialog.reject()
    identifier = store.save_user(dict(code='catalog-only', name='상품 담당자', role='staff',
                                     password='Catalog-Password-2026!', permissions=['catalog']))
    staff = Store(store.path)
    try:
        staff.login('catalog-only', 'Catalog-Password-2026!')
        restricted = SupplierFilterDialog(staff)
        assert restricted.grid.rowCount() > 0
        store.save_user(dict(permissions=['catalog','deny:products']), identifier)
        restricted.refresh(); assert restricted.grid.rowCount() == 0
        with pytest.raises(PermissionError): staff.catalog_suppliers()
        store.save_user(dict(permissions=['catalog']), identifier)
        restricted.refresh(); assert restricted.grid.rowCount() > 0
        store.save_user(dict(active=False), identifier)
        restricted.choose()
        assert restricted.record is None and restricted.grid.rowCount() == 0
        with pytest.raises(PermissionError): staff.catalog_suppliers()
        restricted.reject()
    finally:
        staff.close()
