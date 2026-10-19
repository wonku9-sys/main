"""Real popup mode must show contents and no extra personal landing window."""
import pytest
from PySide6.QtCore import QCoreApplication,QEvent
from PySide6.QtWidgets import QApplication,QDialog,QMessageBox,QPushButton
from pos2.app import MainWindow
from pos2.store import Store
from pos2.popup_policy import install_popup_policy
from pos2.private_session import remember_key,cached_key
from pos2.widgets import FormDialog

@pytest.fixture
def desktop(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([]);install_popup_policy(app)
    store=Store(tmp_path/'popup.db');store.setup_admin('owner','관리자','Owner-Password-2026!')
    store.save_popup_sound_enabled(False);store.save_diary_music_preferences(False,0)
    window=MainWindow(store,popup_menus=True);window.show();window.navigation.enable();app.processEvents()
    monkeypatch.setattr(QMessageBox,'warning',lambda *_:QMessageBox.StandardButton.Ok)
    yield app,store,window
    monkeypatch.setattr('pos2.navigation.ask_unsaved',lambda *_:QMessageBox.StandardButton.Discard)
    window.close();window.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents();store.close()

def prepare(store,kind):
    if kind=='diary':store.setup_diary('Private-2026!','Private-2026!');key=store.unlock_diary('Private-2026!')
    else:store.setup_household('Private-2026!','Private-2026!');key=store.unlock_household('Private-2026!')
    remember_key(store,kind,key);key[:]=bytes(len(key))

@pytest.mark.parametrize('kind',['diary','household'])
def test_private_popup_opens_once_reuses_and_reopens_without_shell(desktop,monkeypatch,kind):
    app,store,window=desktop;prepare(store,kind)
    def unexpected(*_):raise AssertionError('A cached private session must not ask for a password again.')
    monkeypatch.setattr(FormDialog,'exec',unexpected)
    assert window.open_page('worklog');assert window.open_page(kind);app.processEvents()
    editor=window.personal_windows[kind]
    assert editor.isVisible() and not editor.isModal()
    assert kind not in window.popup_windows and not window.pages[kind].isVisible()
    assert window.pages['worklog'].grid.isVisible()
    assert window.open_page(kind);app.processEvents();assert window.personal_windows[kind] is editor
    editor.close();app.processEvents();assert kind not in window.personal_windows and cached_key(store,kind)
    assert window.open_page(kind);app.processEvents();assert window.personal_windows[kind].isVisible()
    assert kind not in window.popup_windows

@pytest.mark.parametrize('kind',['diary','household'])
def test_cancel_unlock_leaves_no_empty_window_and_keeps_recovery_access(desktop,monkeypatch,kind):
    app,store,window=desktop;prepare(store,kind)
    (store.lock_diary if kind=='diary' else store.lock_household)();seen=[]
    def cancel(dialog):
        seen.extend(button.text() for button in dialog.findChildren(QPushButton));return QDialog.DialogCode.Rejected
    monkeypatch.setattr(FormDialog,'exec',cancel)
    assert window.open_page(kind);app.processEvents()
    assert any('암호 찾기' in text and '이메일' in text for text in seen)
    assert kind not in window.popup_windows and kind not in window.personal_windows
    assert not window.pages[kind].isVisible() and window.isVisible()

def test_diary_password_settings_cancel_does_not_lock_open_diary(desktop,monkeypatch):
    app,store,window=desktop;prepare(store,'diary');window.open_page('diary');app.processEvents()
    editor=window.personal_windows['diary'];editor.security_settings();app.processEvents()
    options=editor._security_menu.actions();assert len(options)==3
    monkeypatch.setattr(FormDialog,'exec',lambda *_:QDialog.DialogCode.Rejected)
    editor._security_menu.hide();options[0].trigger();app.processEvents()
    assert editor.isVisible() and not editor.closed_securely and cached_key(store,'diary')
