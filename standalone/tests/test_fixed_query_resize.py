"""Fixed query controls and native resizable desktop/dialog frames."""
import pytest
from PySide6.QtCore import Qt,QCoreApplication,QEvent,QSize
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QDialog,QMessageBox,QSizeGrip
from pos2.app import MainWindow
from pos2.catalog_ui import ProductDialog
from pos2.popup_policy import install_popup_policy
from pos2.store import Store


@pytest.fixture
def desktop(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([]);install_popup_policy(app)
    store=Store(tmp_path/'resize.db');store.setup_admin('owner','관리자','Owner-Password-2026!')
    window=MainWindow(store);window.show();window.navigation.enable();app.processEvents()
    monkeypatch.setattr('pos2.navigation.ask_unsaved',lambda *_:QMessageBox.StandardButton.Cancel)
    yield app,store,window
    window.navigation.suspended=True;window.navigation.disable()
    for widget in app.topLevelWidgets():widget.close();widget.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents();store.close()


def test_query_stays_at_top_across_menus_and_scrolls(desktop):
    app,_,window=desktop
    origin=None
    for key in ('products','purchases','inventory_categories','settings'):
        assert window.open_page(key);app.processEvents()
        bar=window.query_bar;point=bar.query_button.mapTo(window,bar.query_button.rect().topRight())
        if origin is None:origin=point
        assert point==origin and bar.context.text()==window.current_page.title
        scroller=window.scrollers[key];scroller.verticalScrollBar().setValue(scroller.verticalScrollBar().maximum())
        app.processEvents();assert bar.query_button.mapTo(window,bar.query_button.rect().topRight())==origin
    assert 'F5' in bar.query_button.toolTip() and '#F6CE63' in bar.styleSheet()
    assert not any(action.text()=='조회' for action in window.toolbar.actions())


def test_button_and_f5_query_same_page_and_respect_unsaved_cancel(desktop,monkeypatch):
    app,_,window=desktop;window.open_page('products');page=window.current_page;called=[]
    monkeypatch.setattr(page,'refresh',lambda:called.append('query'))
    window.query_bar.query_button.click();assert called==['query']
    window.activateWindow();window.setFocus();app.processEvents()
    QTest.keySequence(window,QKeySequence('F5'));app.processEvents();assert called==['query','query']
    window.open_page('settings');page=window.current_page
    page.fields['store_name'].setText('저장하지 않은 이름')
    monkeypatch.setattr(page,'refresh',lambda:called.append('discarded'))
    window.query_bar.query_button.click();assert called==['query','query']
    assert page.fields['store_name'].text()=='저장하지 않은 이름'


def test_popup_fixed_query_native_frame_resize_and_fullscreen_restore(desktop):
    app,_,window=desktop;window.popup_menus=True;window.open_page('worklog');app.processEvents()
    popup=window.popup_windows['worklog'];bar=popup.query_bar
    assert popup.isSizeGripEnabled() and popup.findChildren(QSizeGrip)
    assert not popup.windowFlags() & Qt.WindowType.MSWindowsFixedSizeDialogHint
    assert not popup.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert popup.windowFlags() & Qt.WindowType.WindowMaximizeButtonHint
    for size in (QSize(700,500),QSize(1100,760),QSize(760,540)):
        popup.resize(size);app.processEvents();assert popup.size()==size
        pos=bar.pos();scroll=window.scrollers['worklog']
        scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum());app.processEvents()
        assert bar.pos()==pos and bar.query_button.isVisible() and popup._popup_close_button.isVisible()
    popup.showFullScreen();app.processEvents();assert popup.isFullScreen()
    popup.showNormal();app.processEvents();assert not popup.isFullScreen()


def test_main_and_product_dialog_resize_keep_overflow_accessible(desktop):
    app,store,window=desktop
    window.resize(940,640);app.processEvents();assert window.size()==QSize(940,640)
    assert window.statusBar().isSizeGripEnabled()
    assert window.query_bar.query_button.isVisible()
    dialog=ProductDialog(store,parent=window);dialog.show();app.processEvents()
    assert dialog.isSizeGripEnabled()
    dialog.resize(600,440);app.processEvents();assert dialog.size()==QSize(600,440)
    assert dialog.findChild(QDialog) is None
    from PySide6.QtWidgets import QScrollArea
    scroll=dialog.findChild(QScrollArea,'popupScroll')
    assert scroll is not None and scroll.verticalScrollBar().maximum()>0
    assert dialog._popup_close_button.isVisible()
    dialog.close()
