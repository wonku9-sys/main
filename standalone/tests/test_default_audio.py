"""The six explicitly approved uploads are automatic defaults, not private data."""
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication,QDialog,QGroupBox,QPushButton,QLabel
from pos2.audio_defaults import SOUNDS,default_source,approved_sound_file
from pos2.lucky_audio import DrawSound


@pytest.fixture
def app():return QApplication.instance() or QApplication([])


def sound_at(tmp_path,kind):
    return DrawSound(settings=QSettings(str(tmp_path/(kind+'.ini')),QSettings.Format.IniFormat),root=tmp_path/kind,kind=kind)


@pytest.mark.parametrize('kind',SOUNDS)
def test_six_original_files_are_automatic_without_preferences(app,tmp_path,kind):
    source=default_source(kind);assert source is not None and source.name==SOUNDS[kind][0]
    assert sha256(source.read_bytes()).hexdigest()==SOUNDS[kind][1] and approved_sound_file(source)
    sound=sound_at(tmp_path,kind)
    assert sound.custom_source is None and sound.source==source and sound.enabled and sound.volume>0
    assert not sound.settings.contains('source') and '기본음 자동 적용' in sound.description()
    assert sound_at(tmp_path,kind).source==source


def test_custom_override_missing_path_and_reset_preserve_off_and_volume(app,tmp_path):
    sound=sound_at(tmp_path,'login');source=default_source('login');target=sound.register(source)
    assert sound.source==target and target!=source
    sound.set_enabled(False);sound.set_volume(47);sound.use_default()
    assert sound.source==source and sound.custom_source is None and target.exists()
    assert not sound.enabled and sound.volume==47
    sound.settings.setValue('source',str(tmp_path/'previous-pc'/'missing.mp3'))
    assert sound.source==source and sound.custom_source is not None
    assert '선택한 파일이 없어 기본음 사용' in sound.description()


def test_altered_missing_symlink_and_unapproved_audio_rejected(tmp_path,monkeypatch):
    from pos2 import audio_defaults
    monkeypatch.setattr(audio_defaults,'SOUND_DIRECTORY',tmp_path)
    assert default_source('login') is None
    path=tmp_path/SOUNDS['login'][0];path.write_bytes(b'ID3'+bytes(30))
    assert default_source('login') is None and not approved_sound_file(path)
    import build_portable
    build_portable.check_entry(Path('_internal/pos2/assets/sounds')/SOUNDS['login'][0])
    for candidate in ('_internal/pos2/assets/sounds/private.mp3','lucky-audio/login/private.mp3',SOUNDS['login'][0]):
        with pytest.raises(RuntimeError):build_portable.check_entry(Path(candidate))


def test_all_six_original_mp3_decode_without_an_audio_device(app):
    from pos2.audio_smoke import verify_default_audio
    result=verify_default_audio()
    assert set(result)==set(SOUNDS) and all(value>0 for value in result.values())


def test_login_plays_actual_default_through_media_pipeline_only_after_success(app,tmp_path,monkeypatch):
    from PySide6 import QtMultimedia
    from pos2 import lucky_audio
    from pos2.app import LoginDialog
    from pos2.store import Store
    events=[]
    class Player:
        def __init__(self,*_):self.errorOccurred=SimpleNamespace(connect=lambda _:None)
        def setAudioOutput(self,output):pass
        def stop(self):events.append('stop')
        def setSource(self,url):events.append(('source',Path(url.toLocalFile())))
        def play(self):events.append('play')
    class Output:
        def __init__(self,*_):pass
        def setVolume(self,value):events.append(('volume',value))
    monkeypatch.setattr(QtMultimedia,'QMediaPlayer',Player);monkeypatch.setattr(QtMultimedia,'QAudioOutput',Output)
    monkeypatch.setattr(QtMultimedia.QMediaDevices,'audioOutputs',lambda:[object()])
    monkeypatch.setattr(QApplication,'platformName',lambda *_:'windows')
    monkeypatch.setattr(QApplication,'topLevelWidgets',lambda:[])
    sound=sound_at(tmp_path,'login');monkeypatch.setattr(lucky_audio,'login_sound',lambda:sound)
    store=Store(tmp_path/'login.db');store.setup_admin('owner','관리자','Owner-Password-2026!')
    try:
        dialog=LoginDialog(store);dialog.code.setText('owner');dialog.password.setText('incorrect');monkeypatch.setattr(dialog,'error',lambda *_:None)
        dialog.submit();assert not events
        dialog.password.setText('Owner-Password-2026!');dialog.submit()
        assert ('source',default_source('login')) in events and events.count('play')==1
        sound.set_enabled(False);assert not sound.play() and events.count('play')==1
    finally:store.close()


def test_settings_show_six_defaults_errors_and_restore(app,tmp_path,monkeypatch):
    from pos2 import lucky_audio
    login=sound_at(tmp_path,'login');monkeypatch.setattr(lucky_audio,'login_sound',lambda:login)
    def inspect(dialog):
        groups=dialog.findChildren(QGroupBox);assert len(groups)==6
        group=next(g for g in groups if g.title()=='로그인 성공 사운드')
        label=group.findChildren(QLabel)[-1]
        assert 'lovelyboot1-103697.mp3' in label.text()
        login.problem.emit('테스트 오디오 오류');assert label.text()=='테스트 오디오 오류'
        login.register(default_source('login'));login.set_enabled(False);login.set_volume(42)
        next(b for b in group.findChildren(QPushButton) if b.text()=='기본음으로 복원').click()
        assert login.custom_source is None and not login.enabled and login.volume==42
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(QDialog,'exec',inspect);lucky_audio.login_sound_settings()
