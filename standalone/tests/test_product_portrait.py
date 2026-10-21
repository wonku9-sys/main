"""User's compact product form: three actions, fresh records and category arrows."""
from pathlib import Path
import os
import pytest
from PySide6.QtCore import Qt, QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QPushButton
from pos2.app import MainWindow
from pos2.catalog_ui import ProductDialog
from pos2.store import Store
from pos2.workflow_ui import TradeDialog


@pytest.fixture
def desktop(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    store = Store(tmp_path/'portrait.db')
    store.setup_admin('owner', '관리자', 'Portrait-Strong-2026!')
    window = MainWindow(store); window.show(); window.navigation.enable(); app.processEvents()
    monkeypatch.setattr('pos2.navigation.ask_unsaved', lambda *_: QMessageBox.StandardButton.Cancel)
    yield app, store, window
    window.navigation.suspended = True; window.navigation.disable()
    for widget in app.topLevelWidgets(): widget.close(); widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete); app.processEvents(); store.close()


def test_apply_saves_clears_and_never_overwrites_previous_product(desktop):
    app, store, window = desktop
    supplier = store.save_partner(dict(kind='supplier', name='연속 공급사'))
    d = ProductDialog(store, parent=window); d.show(); app.processEvents()
    d.supplier.setCurrentIndex(d.supplier.findData(supplier))
    path = [d.fields[k].text() for k in d.category_displays]
    seen = []; d.saved.connect(seen.append)
    for i in range(3):
        d.fields['name'].setText(f'연속 상품 {i}')
        d.fields['barcode'].setText(f'000{i}')
        d.fields['purchase_price'].setText('1234567.50')
        d.fields['sale_price'].setText('2000000')
        d.fields['warehouse'].setText('비워질 창고'); d.memo.setPlainText('비워질 메모')
        d.apply_button.click(); app.processEvents()
        assert d.isVisible() and len(store.products()) == i+1 and len(seen) == i+1
        assert not d.record and d.saved_id is None and d.last_saved_id == seen[-1]
        assert all(not d.fields[k].text() for k in ('name', 'barcode', 'code', 'warehouse', 'shelf', 'keywords'))
        assert d.fields['purchase_price'].text() == '0' and not d.memo.toPlainText()
        assert d.supplier.currentData() == supplier
        assert [d.fields[k].text() for k in d.category_displays] == path
        assert d.fields['name'].hasFocus() and not window.navigation.changed(d)
        assert not d.unit_table.rowCount() and not d.audit_table.rowCount()
    assert len(set(seen)) == 3 and len({p['code'] for p in store.products()}) == 3
    assert all(p['purchase_price'] == 1234567.50 for p in store.products())
    d.fields['name'].setText('저장하지 않을 다음 상품'); d.cancel_button.click()
    assert not d.isVisible() and len(store.products()) == 3


def test_cancel_discards_without_prompt_and_save_closes(desktop):
    app, store, window = desktop
    d = ProductDialog(store, parent=window); d.show(); app.processEvents()
    d.fields['name'].setText('취소할 상품'); d.cancel_button.click()
    assert not d.isVisible() and not store.products() and d.result() == QDialog.DialogCode.Rejected
    d = ProductDialog(store, parent=window); d.show(); app.processEvents()
    d.fields['name'].setText('저장할 상품'); d.save_button.click()
    assert not d.isVisible() and len(store.products()) == 1 and d.result() == QDialog.DialogCode.Accepted


def test_invalid_apply_preserves_inputs_and_duplicate_barcode_never_clears(desktop):
    app, store, window = desktop
    d = ProductDialog(store, parent=window); d.show(); app.processEvents()
    d.fields['barcode'].setText('00012'); d.apply_button.click()
    assert d.error_label.text() and d.fields['barcode'].text() == '00012' and not store.products()
    d.fields['name'].setText('첫 상품'); d.apply_button.click()
    assert len(store.products()) == 1
    d.fields['name'].setText('중복 상품'); d.fields['barcode'].setText('00012'); d.apply_button.click()
    assert d.fields['name'].text() == '중복 상품' and d.fields['barcode'].text() == '00012'
    assert d.error_label.text() and len(store.products()) == 1


def test_category_arrows_filter_parent_and_revalidate_inactive_category(desktop):
    app, store, window = desktop
    root = store.save_category(dict(name='식품'))
    mid = store.save_category(dict(name='정육', parent_id=root))
    leaf = store.save_category(dict(name='한우', parent_id=mid))
    other = store.save_category(dict(name='생활'))
    store.save_category(dict(name='세제', parent_id=other))
    d = ProductDialog(store, parent=window)
    for key, identifier in (('category', root), ('category_mid', mid), ('category_small', leaf)):
        menu = d.category_menu(key)
        target = next(a for a in menu.actions() if a.data() == identifier)
        if key == 'category_mid': assert '세제' not in [a.text() for a in menu.actions()]
        target.trigger(); menu.deleteLater()
    assert [v.text() for v in d.category_displays.values()] == ['식품', '정육', '한우']
    stale = d.category_menu('category_small')
    store.save_category(dict(name='한우', parent_id=mid, active=False), leaf)
    next(a for a in stale.actions() if a.data() == leaf).trigger()
    assert '무효' in d.error_label.text() and not store.products()
    d.apply_category_id(other)
    assert [v.text() for v in d.category_displays.values()] == ['생활', '선택 없음', '선택 없음']


def test_three_buttons_portrait_footer_visible_and_no_home(desktop):
    app, store, window = desktop
    d = ProductDialog(store, parent=window); d.show(); app.processEvents()
    buttons = d.footer.findChildren(QPushButton)
    assert [b.text() for b in buttons] == ['저장(S)', '취소', '적용(A)']
    assert all(not b.icon().isNull() and not b.autoDefault() for b in buttons)
    assert not hasattr(d, 'next_button') and not hasattr(d, '_home_button')
    assert d.width() <= 720 and d.height() > d.width()
    for size in ((700, 740), (620, 580)):
        d.resize(*size); app.processEvents()
        for b in buttons:
            assert b.isVisible() and d.rect().contains(b.mapTo(d, b.rect().bottomRight()))
        assert all(b.isVisible() and '▸' in b.text() for b in d.category_buttons.values())
    d.resize(700, 800); app.processEvents()
    captures = os.environ.get('SY_TEST_CAPTURE_DIR')
    if captures:
        target = Path(captures); target.mkdir(parents=True, exist_ok=True)
        d.grab().save(str(target/'rc34-product-portrait.png'))


def test_edit_apply_commits_original_then_creates_new_and_purchase_receives_each(desktop):
    app, store, window = desktop
    original = store.save_product(dict(name='기존 상품', base_unit='개'))
    d = ProductDialog(store, store.catalog_product(original), window)
    d.fields['name'].setText('기존 상품 수정'); assert d.apply_changes()
    assert store.catalog_product(original)['name'] == '기존 상품 수정' and not d.record
    d.fields['name'].setText('새 상품'); assert d.save(False)
    assert d.saved_id != original and len(store.products()) == 2
    trade = TradeDialog(window, 'purchase'); editor = ProductDialog(store, parent=trade)
    editor.saved.connect(trade.apply_master_product)
    added = []; editor.saved.connect(added.append)
    for name in ('전표 상품1', '전표 상품2'):
        editor.fields['name'].setText(name); assert editor.apply_changes()
    ids = [r['product'].currentData() for r in trade.line_rows]
    assert len(added) == 2 and all(ids.count(identifier) == 1 for identifier in added)
    assert len(store.documents()) == 0  # Product registration does not post a purchase.


def test_edit_after_apply_does_not_reuse_the_cleared_form(desktop):
    app, store, window = desktop
    identifier = store.save_product(dict(name='다시 열 상품'))
    window.open_page('products'); page = window.current_page
    first = page.show_product_dialog(store.catalog_product(identifier))
    first.fields['name'].setText('다시 열 상품 수정'); first.apply_button.click()
    second = page.show_product_dialog(store.catalog_product(identifier))
    assert second is not first and second.record['id'] == identifier
    assert not first.record and not first.fields['name'].text()


def test_keyboard_shortcuts_save_and_continuous_apply(desktop):
    app, store, window = desktop
    d = ProductDialog(store, parent=window); d.show(); d.activateWindow(); app.processEvents()
    d.fields['name'].setText('단축키 적용'); d.fields['name'].setFocus()
    QTest.keyClick(d.fields['name'], Qt.Key.Key_A, Qt.KeyboardModifier.AltModifier); app.processEvents()
    assert len(store.products()) == 1 and d.isVisible() and not d.fields['name'].text()
    d.fields['name'].setText('단축키 저장')
    QTest.keyClick(d.fields['name'], Qt.Key.Key_S, Qt.KeyboardModifier.AltModifier); app.processEvents()
    assert len(store.products()) == 2 and not d.isVisible()
