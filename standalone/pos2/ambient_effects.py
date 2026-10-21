"""Opt-in, bounded edge effects using existing forecasts, never extra HTTP."""
from datetime import date
import math
import time
from PySide6.QtCore import QObject,QEvent,Qt,QTimer,QPointF
from PySide6.QtGui import QColor,QPainter,QPen,QRegion
from PySide6.QtWidgets import QApplication,QDialog,QWidget
from .appearance import apply_theme,special_day

_EVENTS=frozenset((QEvent.Type.Show,QEvent.Type.Hide,QEvent.Type.Resize,QEvent.Type.KeyPress,
                  QEvent.Type.MouseButtonPress,QEvent.Type.Wheel,QEvent.Type.WindowStateChange,QEvent.Type.WindowActivate,QEvent.Type.WindowDeactivate))


def weather_kind(result):
    text=(result or {}).get('weather','').split(' · ',1)[0]
    if '눈' in text:return 'snow'
    if '비' in text or '소나기' in text or '빗방울' in text:return 'rain'
    if '구름' in text or '흐림' in text:return 'cloud'
    if '맑음' in text:return 'sun'
    return ''


class EdgeOverlay(QWidget):
    def __init__(self,parent):
        super().__init__(parent);self.kind='';self.phase=0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground);self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAccessibleName('장식 효과 · 마우스 입력 통과')
    def fit(self):
        self.setGeometry(self.parentWidget().rect());w,h=self.width(),self.height()
        self.setMask(QRegion(0,0,12,h).united(QRegion(max(0,w-12),0,12,h)))
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(110,150,173,85) if self.kind=='rain' else QColor(239,246,249,155),1.2))
        for i in range(18):
            y=(i*53+self.phase*(7 if self.kind=='rain' else 2))%max(1,self.height())
            offset=5+math.sin(self.phase*.06+i)*3
            x=offset if i%2==0 else self.width()-offset
            if self.kind=='rain':p.drawLine(QPointF(x,y),QPointF(x-2,y+7))
            else:
                p.drawLine(QPointF(x-2,y),QPointF(x+2,y));p.drawLine(QPointF(x,y-2),QPointF(x,y+2))
        p.end()


class WeatherBadge(QWidget):
    def __init__(self,parent):
        super().__init__(parent);self.kind='';self.setFixedSize(112,22);self.setToolTip('선택 지역의 기상청 예보기반 장식입니다. 실제 관측이나 위치 추적이 아닙니다.')
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing);p.setPen(QPen(QColor('#7B8E98'),1))
        if self.kind=='sun':
            p.setBrush(QColor('#D6B567'));p.drawEllipse(5,4,12,12)
        elif self.kind in {'rain','snow','cloud'}:
            p.setBrush(QColor('#BDCDD2'));p.drawEllipse(3,6,13,9);p.drawEllipse(9,3,11,12)
            if self.kind in {'rain','snow'}:p.drawLine(7,16,6,19);p.drawLine(15,16,14,19)
        p.setPen(QColor('#526774'));font=p.font();font.setPixelSize(11);p.setFont(font)
        p.drawText(25,15,{'sun':'예보 · 맑음','cloud':'예보 · 구름','rain':'예보 · 비','snow':'예보 · 눈'}.get(self.kind,'장식 · 눈'))


class AmbientEffects(QObject):
    def __init__(self,window,prefs):
        super().__init__(window);self.window=window;self.forecast=None;self.forecast_at=0;self.day=date.today();self.paused_until=0
        self.overlay=EdgeOverlay(window.centralWidget());self.overlay.hide()
        self.badge=WeatherBadge(window);window.statusBar().addPermanentWidget(self.badge);self.badge.hide()
        self.animation=QTimer(self);self.animation.setInterval(100);self.animation.timeout.connect(self.advance)
        self.resume=QTimer(self);self.resume.setSingleShot(True);self.resume.timeout.connect(self.refresh)
        self.clock=QTimer(self);self.clock.setInterval(60000);self.clock.timeout.connect(self.check_day)
        QApplication.instance().installEventFilter(self)
        self.configure(prefs,False)
    def configure(self,prefs,apply=True):
        self.prefs=dict(prefs)
        if apply:apply_theme(prefs['theme'],prefs['holiday'])
        if prefs['holiday'] or prefs['weather']:self.clock.start()
        else:self.clock.stop()
        self.refresh()
    def check_day(self):
        current=date.today()
        if current!=self.day:
            self.day=current
            if self.prefs['holiday']:
                apply_theme(self.prefs['theme'],True,current,resolved=QApplication.instance()._sy_base_skin)
        self.refresh()
    def update_weather(self,result):
        self.forecast=weather_kind(result);self.forecast_at=time.monotonic() if self.forecast else 0;self.refresh()
    def refresh(self):
        kind=self.forecast if self.prefs['weather'] and self.forecast_at and time.monotonic()-self.forecast_at<1800 else ''
        if not kind and self.prefs['snow']:kind='snow'
        self.badge.kind=kind;self.badge.setVisible(bool(kind));self.badge.update()
        allowed=self.window.isVisible() and not self.window.isMinimized() and QApplication.activeModalWidget() is None and time.monotonic()>=self.paused_until
        if allowed and kind in {'snow','rain'}:
            self.overlay.kind=kind;self.overlay.fit();self.overlay.show();self.overlay.raise_();self.animation.start()
        else:self.animation.stop();self.overlay.hide()
    def advance(self):
        if not self.window.isVisible() or self.window.isMinimized() or QApplication.activeModalWidget() is not None:
            self.animation.stop();self.overlay.hide();return
        self.overlay.phase+=1;self.overlay.update()
    def eventFilter(self,watched,event):
        kind=event.type()
        if kind not in _EVENTS:return False
        if kind in {QEvent.Type.KeyPress,QEvent.Type.MouseButtonPress,QEvent.Type.Wheel}:
            if self.prefs['snow'] or self.prefs['weather']:
                self.paused_until=time.monotonic()+2.5;self.animation.stop();self.overlay.hide();self.resume.start(2600)
        elif watched is self.window or isinstance(watched,QDialog):
            if kind in {QEvent.Type.Hide,QEvent.Type.WindowDeactivate}:self.animation.stop();self.overlay.hide()
            elif kind in {QEvent.Type.Show,QEvent.Type.WindowActivate,QEvent.Type.WindowStateChange}:self.resume.start(20)
            if isinstance(watched,QDialog) and kind==QEvent.Type.Hide:self.resume.start(20)
        elif watched is self.window.centralWidget() and kind==QEvent.Type.Resize:self.overlay.fit()
        return False
    def stop(self):
        for timer in (self.animation,self.resume,self.clock):timer.stop()
        self.overlay.hide();self.badge.hide();QApplication.instance().removeEventFilter(self)
