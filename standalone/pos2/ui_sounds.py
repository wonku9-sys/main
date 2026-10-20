"""Quiet, original local cues. No network, media downloads or system beep."""
from array import array
import math
import sys
import time
import wave
from PySide6.QtCore import QObject,QEvent,QTimer,QUrl,Qt
from PySide6.QtWidgets import QApplication,QAbstractButton,QDialog,QMenu

TONES={'menu':(660,.07),'open':(520,.13),'close':(440,.12),'save':(784,.15),'edit':(698,.14),'delete':(349,.16)}

def write_cue(path,kind):
    frequency,duration=TONES[kind];rate=16000;samples=array('h')
    for n in range(int(rate*duration)):
        t=n/rate;envelope=math.sin(math.pi*t/duration)**2
        samples.append(int(3500*envelope*(math.sin(2*math.pi*frequency*t)+.18*math.sin(2*math.pi*frequency*1.5*t))))
    if sys.byteorder!='little':samples.byteswap()
    with wave.open(str(path),'wb') as output:
        output.setnchannels(1);output.setsampwidth(2);output.setframerate(rate);output.writeframes(samples.tobytes())

class SoundController(QObject):
    def __init__(self,desktop):
        super().__init__(desktop);self.desktop=desktop;self.player=None;self.last=0
        self.store=desktop.store;self.store._ui_sound_controller=self
        self.store._ui_sound_callback=self.committed
        private=getattr(self.store,'private',None)
        if private is not None:private._ui_sound_callback=self.committed;private._ui_sound_controller=self
        QApplication.instance().installEventFilter(self)

    def committed(self,kind):QTimer.singleShot(0,lambda:self.play(kind))

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
        except (ValueError,PermissionError,OSError,RuntimeError,AttributeError):return False

    def eventFilter(self,widget,event):
        # Paint/layout/mouse-move events are frequent. Never walk ownership or
        # read preferences for events that cannot produce a sound.
        kind=event.type()
        if kind not in {QEvent.Type.Show,QEvent.Type.Hide,QEvent.Type.MouseButtonRelease}:return False
        if kind in {QEvent.Type.Show,QEvent.Type.Hide} and not isinstance(widget,QDialog):return False
        if not hasattr(widget,'parentWidget') or not self.belongs(widget):return False
        if isinstance(widget,QDialog) and event.type() in {QEvent.Type.Show,QEvent.Type.Hide} and not event.spontaneous():
            self.play('open' if event.type()==QEvent.Type.Show else 'close')
        elif isinstance(widget,(QAbstractButton,QMenu)) and event.type()==QEvent.Type.MouseButtonRelease and event.button()==Qt.MouseButton.LeftButton:
            if widget.isEnabled():self.play('menu')
        return False

    def stop(self):
        QApplication.instance().removeEventFilter(self)
        if self.player:self.player.stop()
