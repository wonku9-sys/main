"""Bounded cache and idle work without timing-dependent performance assertions."""
from types import SimpleNamespace
import pytest
from PySide6.QtCore import QCoreApplication,QEvent
from PySide6.QtWidgets import QApplication,QMessageBox
from pos2.app import MainWindow
from pos2.store import Store


@pytest.fixture
def desktop(tmp_path):
    app=QApplication.instance() or QApplication([])
    store=Store(tmp_path/'runtime.db');store.setup_admin('owner','시험 관리자','Owner-Test-Password!')
    window=MainWindow(store);window.show();app.processEvents()
    yield app,store,window
    window.navigation.suspended=True;window.navigation.disable();window.close();window.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents();store.close()


def test_hidden_home_clock_stops_and_resumes_without_duplicated_timer(desktop):
    app,_,window=desktop;home=window.pages['home'];timer=home.clock_timer
    assert timer.isActive() and not window.popup_timer.isActive()
    for _ in range(4):
        window.open_page('products');app.processEvents();assert not timer.isActive()
        window.go_home();app.processEvents();assert home.clock_timer is timer and timer.isActive()
    window.hide();app.processEvents();assert not timer.isActive()
    window.show();app.processEvents();assert timer.isActive()


def test_invisible_popup_poll_does_not_query_database(desktop,monkeypatch):
    _,store,window=desktop
    window.popup_windows['hidden']=SimpleNamespace(isVisible=lambda:False)
    monkeypatch.setattr(store,'audit_revision',lambda:pytest.fail('Hidden popup polled SQLite'))
    window.refresh_popups()
    window.popup_windows.clear()


def test_icon_family_reuses_one_bounded_pixmap_for_different_captions(desktop):
    from pos2.menu_icons import menu_icon,_family_icon
    keys={menu_icon(text).cacheKey() for text in ('products','상품장','상품 검색','상품 등록')}
    assert len(keys)==1
    assert menu_icon('이전').cacheKey()!=menu_icon('다음').cacheKey()
    for i in range(1000):menu_icon(f'상품 이름 {i}')
    assert _family_icon.cache_info().currsize<=32


def test_paint_events_skip_popup_navigation_and_journal_handlers(desktop,monkeypatch):
    from pos2.popup_policy import PopupPolicy
    from pos2.unsaved_work import CrashJournal
    _,_,window=desktop;window.navigation.enable();dialog=QMessageBox(window)
    monkeypatch.setattr(window.navigation,'belongs',lambda *_:pytest.fail('Paint traversed widget parents'))
    event=QEvent(QEvent.Type.Paint)
    assert not PopupPolicy().eventFilter(dialog,event)
    assert not window.navigation.eventFilter(dialog,event)
    journal=CrashJournal(window)
    assert not journal.eventFilter(dialog,event)
    journal.stop();dialog.deleteLater()


def test_skin_switch_changes_palette_without_repolishing_every_cached_screen(desktop,monkeypatch):
    from pos2.appearance import apply_theme
    from PySide6.QtGui import QPalette
    app,store,window=desktop
    for key in ('members','purchase_suppliers','purchase_categories','payments'):window.open_page(key)
    apply_theme('default');revision=store.audit_revision();original=app.palette().color(QPalette.ColorRole.Window)
    monkeypatch.setattr(app,'setStyleSheet',lambda *_:pytest.fail('Skin switch rebuilt the entire cached UI stylesheet'))
    monkeypatch.setattr(app,'allWidgets',lambda:pytest.fail('Skin switch traversed every cached widget'))
    apply_theme('summer');assert app.palette().color(QPalette.ColorRole.Window)!=original
    apply_theme('default');assert app.palette().color(QPalette.ColorRole.Window)==original
    assert store.audit_revision()==revision
