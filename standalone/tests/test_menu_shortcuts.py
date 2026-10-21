import pytest
from PySide6.QtCore import Qt, QCoreApplication, QEvent
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QLineEdit, QVBoxLayout, QStyle
from pos2.app import MainWindow, SECTIONS
from pos2.store import Store
from pos2.menu_shortcuts import menu_keys, COMMON_KEYS, ShortcutGuide
from pos2.menu_help import MenuHelpStyle
from pos2.catalog_ui import CategorySearchDialog


@pytest.fixture
def desktop(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    store = Store(tmp_path/'shortcuts.db'); store.setup_admin('owner','관리자','Owner-Password-2026!')
    window = MainWindow(store); window.show(); window.activateWindow(); app.processEvents()
    window.navigation.enable()
    monkeypatch.setattr('pos2.navigation.ask_unsaved', lambda *_: QMessageBox.StandardButton.Cancel)
    yield app, store, window
    window.navigation.suspended = True; window.navigation.disable()
    for widget in app.topLevelWidgets(): widget.close(); widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete); app.processEvents(); store.close()


def press(app, window, sequence):
    window.activateWindow(); window.setFocus(); app.processEvents(); QTest.keySequence(window, QKeySequence(sequence)); app.processEvents()


def test_all_menus_unique_and_no_prefix_conflicts():
    bindings = menu_keys(SECTIONS)
    keys = [QKeySequence(key).toString() for values in bindings.values() for key in values]
    keys += [QKeySequence(key).toString() for title, values in COMMON_KEYS.items() if title!='새로고침' for key in values]
    assert len(keys)==len(set(keys))
    assert set(bindings)=={key for _,entries in SECTIONS for key,_,_ in entries}
    for first in keys:
        assert not any(second.startswith(first+', ') for second in keys if second!=first)


def test_real_keyboard_navigation_and_searchable_guide(desktop):
    app,_,window = desktop
    press(app,window,'F2'); assert window.current_key=='products'
    press(app,window,'Ctrl+2'); assert window.current_key=='purchases'
    press(app,window,window.menu_keys['purchase_categories'][0]); assert window.current_key=='purchase_categories'
    press(app,window,'F1'); guide = window._shortcut_guide
    assert guide.isVisible() and guide.grid.rowCount()==len(window.items)+9
    guide.search.setText('상품장'); assert guide.grid.rowCount()==1
    assert 'Ctrl+1' in guide.grid.item(0,1).text()
    assert guide.grid.item(0,2).text()!='help'


def test_hover_help_and_menu_display_include_shortcuts(desktop):
    _,_,window = desktop
    for key,item in window.items.items():
        assert '단축키:' in item.toolTip(0)
        assert window.nav_actions[key].toolTip()==item.toolTip(0)
        assert window.nav_actions[key].shortcuts()
    for tool in window.toolbar.actions():
        if tool.isSeparator():continue
        if tool is window.toolbar_brand_action:continue # Informational logo, not a command.
        if tool.text()!='메뉴 독립 창': assert '단축키:' in tool.toolTip() or tool.text()=='판매 등록'
    style = MenuHelpStyle(); assert style.styleHint(QStyle.StyleHint.SH_ToolTip_WakeUpDelay)==700; style.deleteLater()


def test_unsaved_guard_and_permissions_still_apply(desktop):
    app,store,window = desktop
    window.open_page('settings'); window.current_page.fields['store_name'].setText('변경중')
    press(app,window,'Ctrl+1'); assert window.current_key=='settings'
    window.navigation.suspended=True
    store.save_user({'code':'staff','name':'직원','password':'Staff-Password-2026!','permissions':['trade']})
    store.login('staff','Staff-Password-2026!')
    other=MainWindow(store); other.show(); app.processEvents()
    assert 'products' not in other.nav_actions
    press(app,other,'Ctrl+1'); assert other.current_key=='home'
    guide=ShortcutGuide(other); assert not any(row['title']=='상품장' for row in guide.records)


def test_independent_window_shortcuts_and_dialog_function_keys(desktop):
    app,store,window = desktop; window.popup_menus=True
    window.open_page('products'); popup=window.popup_windows['products']; app.processEvents()
    press(app,popup,'Ctrl+2'); assert window.popup_windows['purchases'].isVisible()
    dialog=CategorySearchDialog(store,window); dialog.show(); app.processEvents()
    press(app,dialog,'F6'); assert dialog.filters[1].hasFocus()
    assert window.current_key=='purchases'
    dialog.close()
    modal=QDialog(window); modal.setModal(True); field=QLineEdit(); layout=QVBoxLayout(modal); layout.addWidget(field)
    modal.show(); app.processEvents(); press(app,modal,'F2')
    assert window.current_key=='purchases'
