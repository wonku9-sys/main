"""Mouse feedback is preloaded, press-timed and never queued after loading."""
from array import array
from pathlib import Path
from types import SimpleNamespace
import sys
import wave

import pytest
from PySide6.QtCore import QEvent, QPointF, QSettings, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from pos2.audio_defaults import MOUSE_PCM, default_source, mouse_pcm_source
from pos2.lucky_audio import DrawSound


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def sound_at(tmp_path, kind):
    return DrawSound(settings=QSettings(str(tmp_path/(kind+'.ini')), QSettings.Format.IniFormat), root=tmp_path/kind, kind=kind)


@pytest.mark.parametrize('kind', ['click', 'context'])
def test_verified_pcm_starts_promptly_and_preserves_original_file(app, tmp_path, kind):
    original = default_source(kind); source = mouse_pcm_source(kind, original)
    assert source is not None and source.name == MOUSE_PCM[kind][0]
    with wave.open(str(source), 'rb') as clip:
        assert clip.getsampwidth() == 2 and clip.getnchannels() == 2
        assert 0 < clip.getnframes()/clip.getframerate() < .3
        samples = array('h', clip.readframes(clip.getnframes()))
        if sys.byteorder != 'little': samples.byteswap()
        onset = next(i for i, value in enumerate(samples) if abs(value) > 200)
        assert onset/clip.getnchannels()/clip.getframerate() < .015
    sound = sound_at(tmp_path, kind); copy = sound.register(original)
    assert copy.read_bytes() == original.read_bytes() and mouse_pcm_source(kind, copy) == source
    assert mouse_pcm_source(kind, default_source('login')) is None


@pytest.mark.parametrize('kind', ['click', 'context'])
def test_mouse_effect_loads_once_for_rapid_replay_and_respects_settings(app, tmp_path, monkeypatch, kind):
    from PySide6 import QtMultimedia
    effect_status = QtMultimedia.QSoundEffect.Status
    class Effect:
        Status = effect_status
        def __init__(self, *_): self.sources=[]; self.plays=0; self.stops=0; self.state=effect_status.Ready
        def setLoopCount(self, count): assert count == 1
        def setSource(self, url): self.sources.append(Path(url.toLocalFile()))
        def setVolume(self, volume): self.volume=volume
        def status(self): return self.state
        def play(self): self.plays+=1
        def stop(self): self.stops+=1
    monkeypatch.setattr(QtMultimedia, 'QSoundEffect', Effect)
    monkeypatch.setattr(QtMultimedia, 'QMediaPlayer', lambda *_: pytest.fail('Default mouse sound used MP3 playback'))
    monkeypatch.setattr(QtMultimedia.QMediaDevices, 'audioOutputs', lambda: [object()])
    monkeypatch.setattr(QApplication, 'platformName', lambda *_: 'windows')
    monkeypatch.setattr(QApplication, 'topLevelWidgets', lambda: [])
    sound = sound_at(tmp_path, kind)
    assert sound.prepare_mouse() and sound.effect.plays == 0
    assert all(sound.play() for _ in range(20))
    assert len(sound.effect.sources) == 1 and sound.effect.sources[0].suffix == '.wav'
    assert sound.effect.plays == 20
    sound.set_volume(41); assert sound.effect.volume == .41
    sound.effect.state=effect_status.Loading
    assert not sound.play() and sound.effect.plays == 20
    sound.effect.state=effect_status.Ready
    sound.set_enabled(False); assert sound.effect.stops and not sound.play()
    sound.set_enabled(True); assert sound.play() and len(sound.effect.sources) == 1
    sound.set_volume(0); assert not sound.play()


def test_custom_mp3_is_prepared_once_and_loading_does_not_queue_clicks(app, tmp_path, monkeypatch):
    from PySide6 import QtMultimedia
    statuses = QtMultimedia.QMediaPlayer.MediaStatus
    class Player:
        MediaStatus = statuses
        def __init__(self, *_):
            self.sources=[]; self.positions=[]; self.plays=0; self.state=statuses.LoadedMedia
            self.errorOccurred=SimpleNamespace(connect=lambda _: None)
        def setAudioOutput(self, output): pass
        def setSource(self, url): self.sources.append(url.toLocalFile())
        def setPosition(self, value): self.positions.append(value)
        def mediaStatus(self): return self.state
        def stop(self): pass
        def play(self): self.plays+=1
    class Output:
        def __init__(self, *_): pass
        def setVolume(self, value): pass
    monkeypatch.setattr(QtMultimedia, 'QMediaPlayer', Player)
    monkeypatch.setattr(QtMultimedia, 'QAudioOutput', Output)
    monkeypatch.setattr(QtMultimedia.QMediaDevices, 'audioOutputs', lambda: [object()])
    monkeypatch.setattr(QApplication, 'platformName', lambda *_: 'windows')
    monkeypatch.setattr(QApplication, 'topLevelWidgets', lambda: [])
    sound=sound_at(tmp_path, 'click'); selected=sound.register(default_source('login'))
    assert not sound._mouse_effect and sound.player.sources == [str(selected)]
    assert sound.play() and sound.play() and sound.player.positions == [0, 0]
    assert sound.player.sources == [str(selected)]
    sound.player.state=statuses.LoadingMedia
    assert not sound.play() and sound.player.plays == 2


def test_press_not_release_triggers_left_sound_and_right_stays_menu_only(app, monkeypatch):
    from pos2.popup_policy import PopupPolicy
    from pos2 import ui_sounds
    events=[]; monkeypatch.setattr(ui_sounds, 'play_global_cue', lambda kind: events.append(kind))
    monkeypatch.setattr('pos2.popup_policy.time.monotonic', lambda: 100.)
    monkeypatch.setattr(app, '_sy_context_requested_at', 0, raising=False)
    policy=PopupPolicy(); widget=QWidget(); menu=QMenu()
    def mouse(kind, button):
        return QMouseEvent(kind, QPointF(2, 2), QPointF(2, 2), button, button, Qt.KeyboardModifier.NoModifier)
    policy.eventFilter(widget, mouse(QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton))
    assert events == ['click']
    policy.eventFilter(widget, mouse(QEvent.Type.MouseButtonRelease, Qt.MouseButton.LeftButton))
    assert events == ['click']
    policy.eventFilter(widget, mouse(QEvent.Type.MouseButtonDblClick, Qt.MouseButton.LeftButton))
    assert events == ['click', 'click']
    widget.setEnabled(False)
    policy.eventFilter(widget, mouse(QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton))
    assert len(events) == 2
    widget.setEnabled(True)
    policy.eventFilter(widget, mouse(QEvent.Type.MouseButtonPress, Qt.MouseButton.RightButton))
    assert len(events) == 2
    policy.eventFilter(menu, QEvent(QEvent.Type.Show)); assert events[-1] == 'context'
    policy.eventFilter(menu, QEvent(QEvent.Type.Show)); assert len(events) == 3
    widget.deleteLater(); menu.deleteLater()


def test_loading_does_not_fallback_to_delayed_tone_and_buttons_throttle_separately(app, monkeypatch):
    from pos2 import ui_sounds, lucky_audio
    events=[]; ready=[False]; clock=[100.]
    def sound(kind):
        return SimpleNamespace(enabled=True, volume=20, source=Path('selected.mp3'),
                               play=lambda: events.append(kind) or ready[0])
    controller=SimpleNamespace(stopped=False, play=lambda kind: pytest.fail('Mouse click queued a fallback tone'))
    window=SimpleNamespace(sounds=controller, isVisible=lambda: True)
    monkeypatch.setattr(QApplication, 'topLevelWidgets', lambda: [window])
    monkeypatch.setattr(lucky_audio, 'mouse_sound', sound)
    monkeypatch.setattr(ui_sounds.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(app, '_sy_mouse_cue_times', {}, raising=False)
    assert not ui_sounds.play_global_cue('click')
    ready[0]=True
    assert ui_sounds.play_global_cue('context')
    assert not ui_sounds.play_global_cue('click')
    clock[0]+=.04; assert ui_sounds.play_global_cue('click')
    assert events == ['click', 'context', 'click']
