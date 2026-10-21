"""Quiet, original local cues. No network, media downloads or system beep."""
from array import array
import math
import sqlite3
import sys
import time
import wave
from PySide6.QtCore import QObject,QEvent,QTimer,QUrl,Qt,QSettings,QStandardPaths
from PySide6.QtWidgets import QApplication,QAbstractButton,QDialog,QMenu,QMessageBox
from pathlib import Path

TONES={'menu':(660,.07),'open':(520,.13),'close':(440,.12),'save':(784,.15),'edit':(698,.14),'delete':(349,.16),'warning':(330,.18)}

def write_cue(path,kind):
    frequency,duration=TONES[kind];rate=16000;samples=array('h')
    for n in range(int(rate*duration)):
        t=n/rate;envelope=math.sin(math.pi*t/duration)**2
        if kind=='warning':frequency=330 if t<duration/2 else 495
        samples.append(int(3500*envelope*(math.sin(2*math.pi*frequency*t)+.18*math.sin(2*math.pi*frequency*1.5*t))))
    if sys.byteorder!='little':samples.byteswap()
    with wave.open(str(path),'wb') as output:
        output.setnchannels(1);output.setsampwidth(2);output.setframerate(rate);output.writeframes(samples.tobytes())

class SoundController(QObject):
    def __init__(self,desktop):
        super().__init__(desktop);self.desktop=desktop;self.player=None;self.last=0;self.stopped=False
        self.store=desktop.store;self.store._ui_sound_controller=self
        self.store._ui_sound_callback=self.committed
        private=getattr(self.store,'private',None)
        if private is not None:private._ui_sound_callback=self.committed;private._ui_sound_controller=self
        QApplication.instance().installEventFilter(self)

    def committed(self,kind):QTimer.singleShot(0,self,lambda:self.play(kind))

    def belongs(self,widget):
        while widget is not None:
            if widget is self.desktop or getattr(widget,'_desktop_owner',None) is self.desktop:return True
            widget=widget.parentWidget()
        return False

    def play(self,kind):
        try:
            app=QApplication.instance()
            if kind not in TONES or not self.store.popup_sound_enabled():return False
            if app.platformName() in {'offscreen','minimal'} or not self.store.path:return False
            from PySide6.QtMultimedia import QSoundEffect,QMediaDevices
            if not QMediaDevices.audioOutputs():return False
            now=time.monotonic()
            if kind in {'menu','open','close'} and now-self.last<.09:return False
            directory=self.store.path.parent/'music-cache'
            if directory.is_symlink():return False
            directory.mkdir(exist_ok=True);path=directory/f'ui-{kind}-v1.wav'
            if path.is_symlink():return False
            if not path.exists():write_cue(path,kind)
            if self.player is None:self.player=QSoundEffect(self)
            self.player.stop();self.player.setSource(QUrl.fromLocalFile(str(path)));self.player.setVolume(.08);self.player.play();self.last=now
            return True
        except (ValueError,PermissionError,OSError,RuntimeError,AttributeError,sqlite3.Error):return False

    def eventFilter(self,widget,event):
        # Paint/layout/mouse-move events are frequent. Never walk ownership or
        # read preferences for events that cannot produce a sound.
        kind=event.type()
        if kind not in {QEvent.Type.Show,QEvent.Type.Hide,QEvent.Type.MouseButtonRelease}:return False
        if kind in {QEvent.Type.Show,QEvent.Type.Hide} and not isinstance(widget,QDialog):return False
        if not hasattr(widget,'parentWidget') or not self.belongs(widget):return False
        if isinstance(widget,QDialog) and event.type() in {QEvent.Type.Show,QEvent.Type.Hide} and not event.spontaneous():
            if hasattr(QApplication.instance(),'_sy_popup_policy'):return False # One global router, no double cue.
            warning=event.type()==QEvent.Type.Show and isinstance(widget,QMessageBox) and widget.icon() in {QMessageBox.Icon.Warning,QMessageBox.Icon.Critical}
            self.play('warning' if warning else 'open' if event.type()==QEvent.Type.Show else 'close')
        elif isinstance(widget,(QAbstractButton,QMenu)) and event.type()==QEvent.Type.MouseButtonRelease and event.button()==Qt.MouseButton.LeftButton:
            if hasattr(QApplication.instance(),'_sy_popup_policy'):return False
            if widget.isEnabled():self.play('menu')
        return False

    def stop(self):
        self.stopped=True
        QApplication.instance().removeEventFilter(self)
        if self.player:self.player.stop()


def public_sound_settings():return QSettings('SY-POS','PublicPopupSounds')


def play_dialog_cue(dialog,event):
    """Route independent/login dialogs too; Qt native minimize events are silent."""
    if event.spontaneous():return False
    if event.type()==QEvent.Type.Show:
        if getattr(dialog,'_sy_sound_visible',False):return False
        dialog._sy_sound_visible=True
        warning=bool(getattr(dialog,'_sy_warning_popup',False)) or isinstance(dialog,QMessageBox) and dialog.icon() in {QMessageBox.Icon.Warning,QMessageBox.Icon.Critical}
        dialog._sy_warning_sound_used=warning
        kind='warning' if warning else 'open'
    elif event.type()==QEvent.Type.Hide:
        if not getattr(dialog,'_sy_sound_visible',False):return False
        dialog._sy_sound_visible=False;kind='close'
        if getattr(dialog,'_sy_warning_sound_used',False):
            from .lucky_audio import warning_sound
            warning_sound().stop()
    else:return False
    return play_global_cue(kind)


def play_global_cue(kind):
    app=QApplication.instance()
    from .lucky_audio import warning_sound
    if kind in {'click','context'}:
        from .lucky_audio import mouse_sound
        sound=mouse_sound(kind)
    elif kind=='warning':
        sound=warning_sound()
    if kind in {'warning','click','context'}:
        if not sound.enabled or not sound.volume:return False
    fallback='menu' if kind in {'click','context'} else kind
    if kind in {'click','context'}:
        now=time.monotonic();previous=getattr(app,'_sy_mouse_cue_times',{})
        if now-previous.get(kind,0)<.035:return False
        previous[kind]=now;app._sy_mouse_cue_times=previous
    for widget in QApplication.topLevelWidgets():
        controller=getattr(widget,'sounds',None)
        if widget.isVisible() and controller is not None and not getattr(controller,'stopped',False):
            if kind in {'click','context'} and sound.source is not None:return sound.play()
            if kind=='warning' and sound.source is not None and sound.play():return True
            return controller.play(fallback)
    if not public_sound_settings().value('enabled',True,type=bool) or app.platformName() in {'offscreen','minimal'}:return False
    if kind in {'click','context'} and sound.source is not None:return sound.play()
    if kind=='warning' and sound.source is not None and sound.play():return True
    try:
        from PySide6.QtMultimedia import QSoundEffect,QMediaDevices
        if not QMediaDevices.audioOutputs():return False
        directory=Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))/'ui-cues'
        if directory.is_symlink():return False
        directory.mkdir(parents=True,exist_ok=True);path=directory/(fallback+'-v1.wav')
        if path.is_symlink():return False
        if not path.exists():write_cue(path,fallback)
        player=getattr(app,'_sy_public_cue',None)
        if player is None:player=QSoundEffect(app);app._sy_public_cue=player
        player.stop();player.setSource(QUrl.fromLocalFile(str(path)));player.setVolume(.08);player.play();return True
    except (ValueError,OSError,RuntimeError):return False
