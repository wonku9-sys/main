"""Short compositor-only dialog transitions; never delay done(), hide or locking.

One transient, input-transparent surface scales a single in-memory render. The
real dialog never changes geometry, so complex forms are not relaid out per
frame. Private closing windows use a blank privacy surface, never a snapshot.
"""
import sys
import weakref

from PySide6.QtCore import QObject,QEvent,QPoint,QRect,Qt,QTimer,QPropertyAnimation,QParallelAnimationGroup,QEasingCurve
from PySide6.QtGui import QPainter,QPixmap
from PySide6.QtWidgets import QApplication,QDialog,QWidget
from shiboken6 import isValid

OPEN_MS=180
CLOSE_MS=140
SCALE=.97
MAX_PIXELS=6_000_000
MAX_ACTIVE=2
NATIVE_DIALOGS={'QMessageBox','QInputDialog','QFileDialog','QPrintDialog','QPrintPreviewDialog'}


def system_motion_allowed():
    if sys.platform!='win32':return True
    try:
        import ctypes
        from ctypes import wintypes
        enabled=wintypes.BOOL()
        # Read Windows' accessibility/client-area animation preference only.
        if ctypes.windll.user32.SystemParametersInfoW(0x1042,0,ctypes.byref(enabled),0):
            return bool(enabled.value)
    except (AttributeError,OSError):
        pass
    return False


def private_dialog(dialog):
    while dialog is not None:
        if (callable(getattr(dialog,'wipe',None))
                or isinstance(getattr(dialog,'key',None),(bytes,bytearray,memoryview))
                or getattr(dialog,'menu_key',None) in {'diary','household'}):return True
        dialog=dialog.parentWidget()
    return False


def scaled_rect(rect,factor):
    result=QRect(0,0,max(1,round(rect.width()*factor)),max(1,round(rect.height()*factor)))
    result.moveCenter(rect.center())
    return result


class MotionSurface(QWidget):
    def __init__(self,pixmap):
        flags=(Qt.WindowType.Tool|Qt.WindowType.FramelessWindowHint|
               Qt.WindowType.WindowDoesNotAcceptFocus|Qt.WindowType.WindowTransparentForInput|
               Qt.WindowType.WindowStaysOnTopHint)
        super().__init__(None,flags)
        self.setObjectName('syTransientMotionSurface')
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose,False)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.pixmap=pixmap

    def paintEvent(self,event):
        painter=QPainter(self);painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(self.rect(),self.pixmap)

    def clear(self):
        self.pixmap=QPixmap()
        self.hide();self.deleteLater()


class PopupMotion(QObject):
    def __init__(self,app,force=False):
        super().__init__(app)
        self.app=app;self.force=force;self.active={};self.capturing=set();self.stopped=False
        self.system_enabled=system_motion_allowed()
        app.aboutToQuit.connect(self.stop)

    def allowed(self,dialog):
        if self.stopped or self.app.closingDown() or not isValid(dialog):return False
        if self.app.property('_sy_window_motion_enabled') is False:return False
        if not self.force and (not self.system_enabled or self.app.platformName() in {'offscreen','minimal','wayland'}):return False
        if not isinstance(dialog,QDialog) or type(dialog).__name__ in NATIVE_DIALOGS:return False
        if not dialog.isWindow() or dialog.isMinimized():return False
        return 0<dialog.width()*dialog.height()*dialog.devicePixelRatioF()**2<=MAX_PIXELS

    def handle(self,dialog,event_type):
        if id(dialog) in self.capturing:return
        if event_type==QEvent.Type.Show:self.show(dialog)
        elif event_type==QEvent.Type.Hide:self.hide(dialog)

    def _trim(self):
        while len(self.active)>=MAX_ACTIVE:self._clean(next(iter(self.active)))

    def _watch(self,dialog):
        watchers=getattr(dialog,'_sy_motion_watchers',set())
        if id(self) not in watchers:
            key=id(dialog);dialog.destroyed.connect(lambda *_:self._source_destroyed(key))
            watchers.add(id(self));dialog._sy_motion_watchers=watchers

    def _source_destroyed(self,key):
        state=self.active.get(key)
        if state is None:return
        if state['opening']:
            # Never retain an opening/private content snapshot after destruction.
            self._clean(key,state)
        else:
            # An already-closed window may use WA_DeleteOnClose. Its bounded
            # closing decoration owns no source widget (private content is blank).
            state['ref']=lambda:None

    def show(self,dialog):
        key=id(dialog);self._clean(key)
        # Login should be immediately readable; only its disappearance fades.
        if type(dialog).__name__=='LoginDialog' or not self.allowed(dialog):return False
        self._watch(dialog)
        opacity=dialog.windowOpacity()
        if opacity<=0:return False
        self._trim()
        state={'ref':weakref.ref(dialog),'opacity':opacity,'opening':True,'phase':'pending','surface':None,'group':None}
        self.active[key]=state;dialog.setWindowOpacity(0)
        QTimer.singleShot(0,self,lambda:self._open_ready(key,state))
        return True

    def _open_ready(self,key,state):
        if self.active.get(key) is not state:return
        dialog=state['ref']()
        if dialog is None or not isValid(dialog) or not dialog.isVisible() or not self.allowed(dialog):
            self._clean(key,state);return
        try:
            self.capturing.add(key);pixmap=dialog.grab()
            rect=QRect(dialog.mapToGlobal(QPoint()),dialog.size())
            self._animate(key,state,pixmap,rect,SCALE)
        except (RuntimeError,ValueError):
            self._clean(key,state)
        finally:self.capturing.discard(key)

    def hide(self,dialog):
        key=id(dialog);previous=self.active.get(key)
        pending=previous is not None and previous['phase']=='pending'
        self._clean(key)
        if pending or not self.allowed(dialog) or dialog.windowOpacity()<=0:return False
        self._watch(dialog)
        self._trim()
        state={'ref':weakref.ref(dialog),'opacity':dialog.windowOpacity(),'opening':False,'phase':'pending','surface':None,'group':None}
        try:
            self.capturing.add(key)
            if private_dialog(dialog):
                # Lock/wipe is already complete. Do not resurrect private text
                # for even a 140ms decorative closing animation.
                ratio=dialog.devicePixelRatioF()
                pixmap=QPixmap(round(dialog.width()*ratio),round(dialog.height()*ratio))
                pixmap.setDevicePixelRatio(ratio);pixmap.fill(dialog.palette().window().color())
                painter=QPainter(pixmap);painter.setFont(dialog.font())
                painter.setPen(dialog.palette().windowText().color())
                painter.drawText(QRect(QPoint(),dialog.size()),Qt.AlignmentFlag.AlignCenter,'안전하게 닫는 중')
                painter.end()
            else:pixmap=dialog.grab()
            rect=QRect(dialog.mapToGlobal(QPoint()),dialog.size())
            self.active[key]=state
            self._animate(key,state,pixmap,rect,1.0 if type(dialog).__name__=='LoginDialog' else SCALE)
            return True
        except (RuntimeError,ValueError):
            self._clean(key,state);return False
        finally:self.capturing.discard(key)

    def _animate(self,key,state,pixmap,rect,factor):
        if pixmap.isNull():self._clean(key,state);return
        opening=state['opening'];surface=MotionSurface(pixmap)
        group=QParallelAnimationGroup(self)
        state.update(surface=surface,group=group,phase='running')
        smaller=scaled_rect(rect,factor)
        start,end=(smaller,rect) if opening else (rect,smaller)
        surface.setGeometry(start)
        surface.setWindowOpacity(0 if opening else state['opacity'])
        opacity=QPropertyAnimation(surface,b'windowOpacity',group)
        opacity.setStartValue(0 if opening else state['opacity']);opacity.setEndValue(state['opacity'] if opening else 0)
        geometry=QPropertyAnimation(surface,b'geometry',group)
        geometry.setStartValue(start);geometry.setEndValue(end)
        for animation in (opacity,geometry):
            animation.setDuration(OPEN_MS if opening else CLOSE_MS)
            animation.setEasingCurve(QEasingCurve.Type.OutCubic if opening else QEasingCurve.Type.InCubic)
            group.addAnimation(animation)
        group.finished.connect(lambda:self._clean(key,state))
        surface.show();group.start()

    def _clean(self,key,expected=None):
        state=self.active.get(key)
        if state is None or expected is not None and state is not expected:return
        self.active.pop(key,None)
        group=state['group'];surface=state['surface'];dialog=state['ref']()
        if group is not None and isValid(group):group.stop();group.deleteLater()
        if surface is not None and isValid(surface):surface.clear()
        if state['opening'] and dialog is not None and isValid(dialog):dialog.setWindowOpacity(state['opacity'])

    def stop(self):
        self.stopped=True
        for key in list(self.active):self._clean(key)


def install_popup_motion(app):
    if not hasattr(app,'_sy_popup_motion'):app._sy_popup_motion=PopupMotion(app)
    return app._sy_popup_motion
