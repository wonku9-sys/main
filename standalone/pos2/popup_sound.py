"""Short original low-volume opening/closing cues, generated locally."""
from array import array
import math
import sys
import wave
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication,QCheckBox


def sound_checkbox(store):
    box=QCheckBox('팝업 효과음');box.setChecked(store.popup_sound_enabled())
    box.setToolTip('가계부·일기장 열기/닫기 소리. 배경 음악과 별도로 설정합니다.')
    box.toggled.connect(store.save_popup_sound_enabled)
    return box


def play_popup(store,opening):
    try:
        if not store.popup_sound_enabled() or not store.path:return
        app=QApplication.instance()
        # Headless verification has no audio session; opening a device there can
        # block in the multimedia backend. Real desktop playback is unchanged.
        if app.platformName() in {'offscreen','minimal'}:return
        from PySide6.QtMultimedia import QSoundEffect,QMediaDevices
        if not QMediaDevices.audioOutputs():return
        player=getattr(app,'_personal_cue',None)
        if player is None:player=QSoundEffect(app);app._personal_cue=player
        directory=store.path.parent/'music-cache';directory.mkdir(exist_ok=True)
        if directory.is_symlink():return
        path=directory/('popup-open-v1.wav' if opening else 'popup-close-v1.wav')
        if path.is_symlink():return
        if not path.exists():
            rate=16000;duration=.18;samples=array('h')
            for n in range(int(rate*duration)):
                t=n/rate;f=520 if opening else 440
                amplitude=math.sin(math.pi*t/duration)**2
                samples.append(int(4000*amplitude*(math.sin(2*math.pi*f*t)+.25*math.sin(2*math.pi*1.5*f*t))))
            if sys.byteorder!='little':samples.byteswap()
            with wave.open(str(path),'wb') as output:output.setnchannels(1);output.setsampwidth(2);output.setframerate(rate);output.writeframes(samples.tobytes())
        player.stop();player.setSource(QUrl.fromLocalFile(str(path)));player.setVolume(.08);player.play()
    except (ValueError,PermissionError,OSError,RuntimeError):pass
