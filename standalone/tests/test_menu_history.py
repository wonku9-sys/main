"""Browser-style visits never bypass permissions or the unsaved-work guard."""
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from pos2.app import MainWindow, STYLE
from pos2.menu_history import MenuHistory
from pos2.menu_icons import menu_icon
from pos2.store import Store


@pytest.fixture
def desktop(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    previous_style = app.styleSheet()
    app.setStyleSheet(STYLE)
    store = Store(tmp_path / 'history.db')
    store.setup_admin('owner', '관리자', 'Owner-Password-2026!')
    window = MainWindow(store)
    window.show()
    window.navigation.enable()
    app.processEvents()
    monkeypatch.setattr('pos2.navigation.ask_unsaved', lambda *_: QMessageBox.StandardButton.Cancel)
    monkeypatch.setattr(QMessageBox, 'warning', lambda *_: QMessageBox.StandardButton.Ok)
    yield app, store, window
    window.navigation.suspended = True
    window.navigation.disable()
    for widget in app.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    store.close()
    app.setStyleSheet(previous_style)


def test_bounded_history_repeated_visits_and_branching():
    history = MenuHistory(limit=3)
    assert history.target(-1) is None and history.target(1) is None
    for key in ('home', 'products', 'purchases', 'sales', 'sales'):
        history.record(key)
    assert history.entries == ['products', 'purchases', 'sales']
    history.index = 1
    history.record('purchases')
    assert history.label(1) == 'sales'
    history.record('products')
    assert history.entries == ['products', 'purchases', 'products']
    assert history.target(1) is None


def test_real_buttons_replay_order_without_new_entries_or_database_writes(desktop):
    app, store, window = desktop
    baseline = store.audit_revision()
    assert not window.history_actions['이전'].isEnabled()
    assert not window.history_actions['다음'].isEnabled()
    for key in ('products', 'purchases', 'sales'):
        assert window.open_page(key)
    history = window.menu_history
    assert history.entries == ['home', 'products', 'purchases', 'sales']
    assert '매입전표' in window.history_actions['이전'].toolTip()
    for expected in ('purchases', 'products', 'home'):
        window.history_actions['이전'].trigger()
        app.processEvents()
        assert window.current_key == expected
    assert not window.previous_menu()
    assert not window.history_actions['이전'].isEnabled()
    for expected in ('products', 'purchases', 'sales'):
        window.history_actions['다음'].trigger()
        app.processEvents()
        assert window.current_key == expected
    assert history.entries == ['home', 'products', 'purchases', 'sales']
    assert not window.next_menu()
    assert store.audit_revision() == baseline


def test_cancel_failed_menu_and_new_branch_preserve_history(desktop, monkeypatch):
    _, _, window = desktop
    window.open_page('products')
    window.open_page('settings')
    window.current_page.fields['store_name'].setText('아직 저장하지 않은 매장')
    history = window.menu_history
    snapshot = list(history.entries), history.index
    assert not window.previous_menu()
    assert window.current_key == 'settings'
    assert (history.entries, history.index) == snapshot
    monkeypatch.setattr('pos2.navigation.ask_unsaved', lambda *_: QMessageBox.StandardButton.Discard)
    assert window.previous_menu()
    assert history.label(1) == 'settings'
    assert not window.open_page('not-a-menu')
    assert history.label(1) == 'settings'
    assert window.open_page('purchases')
    assert history.entries == ['home', 'products', 'purchases']
    assert not window.history_actions['다음'].isEnabled()


def test_history_rechecks_current_permission(desktop, monkeypatch):
    _, store, window = desktop
    window.open_page('products')
    window.open_page('purchases')
    original = store.require_menu
    def denied(key, *args, **kwargs):
        if key == 'products':raise PermissionError('상품장 권한이 취소되었습니다.')
        return original(key, *args, **kwargs)
    monkeypatch.setattr(store, 'require_menu', denied)
    before = list(window.menu_history.entries), window.menu_history.index
    assert not window.previous_menu()
    assert window.current_key == 'purchases'
    assert (window.menu_history.entries, window.menu_history.index) == before


def test_save_before_history_move_is_explicit_and_preserves_settings(desktop, monkeypatch):
    _, store, window = desktop
    window.open_page('settings')
    window.current_page.fields['store_name'].setText('저장한 매장 이름')
    monkeypatch.setattr('pos2.navigation.ask_unsaved', lambda *_: QMessageBox.StandardButton.Save)
    assert window.previous_menu()
    assert window.current_key == 'home'
    assert store.settings()['store_name'] == '저장한 매장 이름'
    assert window.menu_history.entries == ['home', 'settings']
    assert window.next_menu()
    assert window.current_page.fields['store_name'].text() == '저장한 매장 이름'


def test_popup_history_reuses_windows_reopens_closed_and_keyboard_works(desktop):
    app, _, window = desktop
    window.popup_menus = True
    window.open_page('products')
    products = window.popup_windows['products']
    window.open_page('purchases')
    purchases = window.popup_windows['purchases']
    app.processEvents()
    assert purchases.common_shortcut_actions['이전'].isEnabled()
    assert not purchases.common_shortcut_actions['다음'].isEnabled()
    assert window.previous_menu()
    app.processEvents()
    assert window.current_key == 'products'
    assert window.popup_windows['products'] is products
    assert products.common_shortcut_actions['다음'].isEnabled()
    assert purchases.close()
    products.activateWindow()
    products.setFocus()
    app.processEvents()
    QTest.keySequence(products, QKeySequence('Alt+Right'))
    app.processEvents()
    assert purchases.isVisible() and window.current_key == 'purchases'
    assert window.menu_history.entries == ['home', 'products', 'purchases']
    assert window.tree.currentItem() is window.items['purchases']
    assert window.nav_actions['purchases'].isChecked()
    before = list(window.menu_history.entries)
    QCoreApplication.sendEvent(products, QEvent(QEvent.Type.WindowActivate))
    assert window.menu_history.entries == before
    # Explicitly reopening an existing visible window IS a new menu visit.
    assert window.open_page('products')
    assert window.menu_history.entries == ['home', 'products', 'purchases', 'products']


def test_distinct_arrows_and_visible_toolbar_group_boundaries(desktop):
    _, _, window = desktop
    assert menu_icon('이전').pixmap(64, 64).toImage() != menu_icon('다음').pixmap(64, 64).toImage()
    actions = window.toolbar.actions()
    assert [action.text() for action in actions[:2]] == ['이전', '다음']
    assert actions[2].isSeparator()
    assert sum(action.isSeparator() for action in actions) == 2
    assert 'QToolBar::separator' in STYLE
    assert 'border:1px solid #D9E4DE' in STYLE
    assert not window.toolbar.isMovable()
