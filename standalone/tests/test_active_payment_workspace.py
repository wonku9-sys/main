from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt
from test_menu_shortcuts import desktop


def test_payment_opens_modeless_reuses_window_and_keeps_original_purchase(desktop):
    app,_,window=desktop
    window.open_page('purchases');purchase=window.current_page
    surface=window.stack.currentWidget();title=window.windowTitle()
    window.open_page('payments');popup=window.popup_windows['payments'];app.processEvents()
    assert popup.isVisible() and not popup.isModal() and popup.parent() is None
    assert popup.navigation_bar.close_button is None  # close only with native X
    assert window.stack.currentWidget() is surface and purchase.isVisible()
    assert window.windowTitle()==title and window.toolbar.isVisible() and window.menuBar().isVisible()
    window.open_page('payments')
    assert window.popup_windows['payments'] is popup
    popup.close();assert window.stack.currentWidget() is surface and window.isVisible()


def test_export_and_print_shortcuts_follow_focused_workspace_not_last_opened(desktop,monkeypatch):
    app,_,window=desktop;window.open_page('purchases');purchase=window.current_page
    window.open_page('payments');popup=window.popup_windows['payments'];called=[]
    for page,label in ((purchase,'purchase'),(popup.page,'payment')):
        monkeypatch.setattr(page,'export',lambda label=label:called.append((label,'export')))
        monkeypatch.setattr(page,'print',lambda label=label:called.append((label,'print')))
    for host,field,label in ((window,purchase.grid,'purchase'),(popup,popup.page,'payment')):
        host.activateWindow();field.setFocus();app.processEvents()
        for sequence in ('Ctrl+E','Ctrl+P'):
            QTest.keySequence(field,QKeySequence(sequence));app.processEvents()
        assert called[-2:]==[(label,'export'),(label,'print')]
    assert '단축키:' in popup.common_shortcut_actions['인쇄'].toolTip()
    assert '단축키:' in popup.navigation_bar.home_button.toolTip()
