"""Private supplied audio registration and draw/open timing, no audio hardware."""
from pathlib import Path
from types import SimpleNamespace
import pytest
from PySide6.QtCore import QSettings,Qt
from PySide6.QtWidgets import QApplication,QPushButton,QFileDialog
from PySide6.QtTest import QTest
from pos2.lucky_audio import DrawSound


@pytest.fixture
def app():return QApplication.instance() or QApplication([])


def controller(tmp_path,kind='draw'):
    return DrawSound(settings=QSettings(str(tmp_path/(kind+'.ini')),QSettings.Format.IniFormat),root=tmp_path/kind,kind=kind)


def test_audio_private_copy_preserves_original_and_preferences(app,tmp_path):
    source=tmp_path/'내 당첨 소리.mp3';source.write_bytes(b'ID3'+bytes(50));sound=controller(tmp_path)
    target=sound.register(source);assert target!=source and target.read_bytes()==source.read_bytes()
    sound.set_enabled(False);sound.set_volume(36)
    again=controller(tmp_path);assert not again.enabled and again.volume==36 and again.source==target
    assert again.settings.value('display_name')==source.name
    opening=controller(tmp_path,'open');assert opening.enabled and opening.source is None
    assert not sound.play() # Disabled, independent of audio output availability.
    source.write_bytes(b'not mp3 content!'+bytes(20))
    with pytest.raises(ValueError):sound.register(source)
    assert target.exists()


def test_lucky_draw_once_per_visible_result_open_on_show_close_stops(app,tmp_path,monkeypatch):
    import pos2.lucky_audio as audio
    original=audio.DrawSound
    monkeypatch.setattr(audio,'DrawSound',lambda parent=None,kind='draw':original(parent,QSettings(str(tmp_path/(kind+'.ini')),QSettings.Format.IniFormat),tmp_path/kind,kind))
    from pos2.lucky_numbers import LuckyNumbersDialog
    dialog=LuckyNumbersDialog();page=dialog.page;events=[]
    monkeypatch.setattr(page.open_sound,'play',lambda:events.append('open'))
    monkeypatch.setattr(page.open_sound,'stop',lambda:events.append('stop-open'))
    monkeypatch.setattr(page.draw_sound,'play',lambda:events.append('draw'))
    monkeypatch.setattr(page.draw_sound,'stop',lambda:events.append('stop-draw'))
    dialog.show();app.processEvents();QTest.qWait(30);app.processEvents();assert events.count('open')==1
    page.draw();page.finish_draw();assert events.count('draw')==1
    page.finish_draw();assert events.count('draw')==1
    page.draw_five();page.finish_draw();assert len(page.results)==5 and events.count('draw')==2
    source=tmp_path/'private.mp3';source.write_bytes(b'ID3'+bytes(50))
    monkeypatch.setattr(QFileDialog,'getOpenFileName',lambda *_:(str(source),'MP3'))
    button=next(b for b in page.findChildren(QPushButton) if b.text()=='사운드 파일 선택')
    QTest.mouseClick(button,Qt.MouseButton.LeftButton)
    assert page.draw_sound.source is not None and page.open_sound.source is None
    page.choose_sound('open');assert page.open_sound.source is not None
    dialog.close();assert 'stop-draw' in events and 'stop-open' in events
    dialog.deleteLater();app.processEvents()


def test_sound_gates_master_switch_and_keeps_public_packages_clean(app,tmp_path,monkeypatch):
    sound=controller(tmp_path);sound.set_enabled(True)
    fake=SimpleNamespace(isVisible=lambda:True,sounds=SimpleNamespace(store=SimpleNamespace(popup_sound_enabled=lambda:False)))
    monkeypatch.setattr(QApplication,'topLevelWidgets',lambda:[fake]);assert not sound.allowed()
    fake.sounds.store.popup_sound_enabled=lambda:True;assert sound.allowed()
    sound.set_volume(0);assert not sound.allowed()
    import build_portable
    for path in ('SY-POS/lucky-audio/draw/clip.mp3','SY-POS/freesound_community-winning-82808.mp3','SY-POS/u_xmiiqyhi46-gamestart-272829.mp3','SY-POS/game.smc'):
        with pytest.raises(RuntimeError):build_portable.check_entry(Path(path))


def test_popup_router_independent_open_close_and_distinct_warning(app,monkeypatch):
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QDialog,QMessageBox
    from pos2.ui_sounds import play_dialog_cue
    from pos2 import lucky_audio
    events=[];fake=SimpleNamespace(isVisible=lambda:True,sounds=SimpleNamespace(stopped=False,play=lambda kind:events.append(kind)))
    monkeypatch.setattr(QApplication,'topLevelWidgets',lambda:[fake])
    monkeypatch.setattr(lucky_audio,'warning_sound',lambda:SimpleNamespace(enabled=True,volume=20,source=None,stop=lambda:events.append('stop-warning')))
    dialog=QDialog();shown=QEvent(QEvent.Type.Show);hidden=QEvent(QEvent.Type.Hide)
    play_dialog_cue(dialog,shown);play_dialog_cue(dialog,shown);play_dialog_cue(dialog,hidden)
    assert events==['open','close']
    warning=QMessageBox();warning.setIcon(QMessageBox.Icon.Warning);play_dialog_cue(warning,shown);play_dialog_cue(warning,hidden)
    assert events[-3:]==['warning','stop-warning','close']


def test_login_audio_only_after_success_and_master_enabled(app,tmp_path,monkeypatch):
    from pos2.store import Store
    from pos2.app import LoginDialog
    from pos2 import lucky_audio
    events=[];monkeypatch.setattr(lucky_audio,'login_sound',lambda:SimpleNamespace(play=lambda:events.append('success')))
    store=Store(tmp_path/'login.db');store.setup_admin('owner','관리자','Owner-Password-2026!')
    try:
        dialog=LoginDialog(store);dialog.code.setText('owner');dialog.password.setText('WRONG')
        monkeypatch.setattr(dialog,'error',lambda *_:None);dialog.submit();assert not events
        dialog.password.setText('Owner-Password-2026!');dialog.submit();assert events==['success']
        store.save_popup_sound_enabled(False);store.logout()
        another=LoginDialog(store);another.code.setText('owner');another.password.setText('Owner-Password-2026!');another.submit()
        assert events==['success']
    finally:store.close()


def test_login_warning_settings_build_and_keep_their_sources_separate(app,tmp_path,monkeypatch):
    from PySide6.QtWidgets import QDialog
    from pos2 import lucky_audio
    login=controller(tmp_path,'login');warning=controller(tmp_path,'warning')
    monkeypatch.setattr(lucky_audio,'login_sound',lambda:login);monkeypatch.setattr(lucky_audio,'warning_sound',lambda:warning)
    source=tmp_path/'private warning.mp3';source.write_bytes(b'ID3'+bytes(50))
    monkeypatch.setattr(QFileDialog,'getOpenFileName',lambda *_:(str(source),'MP3'))
    def inspect(dialog):
        buttons={button.text():button for button in dialog.findChildren(QPushButton)}
        assert {'로그인 사운드 파일 선택','경고 사운드 파일 선택'}<=buttons.keys()
        buttons['경고 사운드 파일 선택'].click();assert warning.source is not None and login.source is None
        buttons['로그인 사운드 파일 선택'].click();assert login.source is not None and login.source!=warning.source
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(QDialog,'exec',inspect);lucky_audio.login_sound_settings()


def test_mouse_cues_are_separate_toggleable_and_right_click_requires_menu(app,tmp_path,monkeypatch):
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QWidget,QMenu
    from pos2 import lucky_audio,ui_sounds
    from pos2.popup_policy import PopupPolicy
    click=controller(tmp_path,'click');context=controller(tmp_path,'context')
    monkeypatch.setattr(lucky_audio,'mouse_sound',lambda kind:click if kind=='click' else context)
    click.set_enabled(False);context.set_enabled(True)
    assert not ui_sounds.play_global_cue('click') and context.enabled
    events=[];monkeypatch.setattr(ui_sounds,'play_global_cue',lambda kind:events.append(kind))
    policy=PopupPolicy();widget=QWidget();menu=QMenu();app._sy_context_requested_at=0
    policy.eventFilter(menu,QEvent(QEvent.Type.Show));assert not events
    policy.eventFilter(widget,QEvent(QEvent.Type.ContextMenu));assert not events
    policy.eventFilter(menu,QEvent(QEvent.Type.Show));assert events==['context']
    policy.eventFilter(menu,QEvent(QEvent.Type.Show));assert events==['context']
