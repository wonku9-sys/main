"""Resizable dialogs, maximize/fullscreen controls and accessible overflow."""
from PySide6.QtCore import QEvent,QObject,Qt
from PySide6.QtGui import QAction,QKeySequence
from PySide6.QtWidgets import QApplication,QDialog,QScrollArea,QVBoxLayout,QWidget,QMenu

EXCLUDED={'QMessageBox','QInputDialog','QFileDialog','QPrintDialog','QPrintPreviewDialog'}


def window_controls(dialog):
    if getattr(dialog,'_window_controls',False):return
    dialog._window_controls=True
    dialog.setWindowFlags(dialog.windowFlags()|Qt.WindowType.WindowMinMaxButtonsHint|Qt.WindowType.WindowSystemMenuHint)
    toggle=QAction('전체화면 / 창모드 (F11)',dialog);toggle.setShortcut(QKeySequence('F11'))
    toggle.triggered.connect(lambda:dialog.showNormal() if dialog.isFullScreen() else dialog.showFullScreen())
    dialog.addAction(toggle)


def accessible_content(dialog):
    if getattr(dialog,'_accessible_content',False):return
    dialog._accessible_content=True
    layout=dialog.layout()
    if layout is None:return
    # Already scrollable private cashbooks keep their existing surface/layout.
    existing=layout.itemAt(0).widget() if layout.count() else None
    if not isinstance(existing,QScrollArea):
        surface=QWidget();surface.setObjectName('popupSurface');surface.setLayout(layout)
        outer=QVBoxLayout(dialog);outer.setContentsMargins(0,0,0,0)
        scroll=QScrollArea(dialog);scroll.setObjectName('popupScroll');scroll.setWidgetResizable(True)
        scroll.setWidget(surface);outer.addWidget(scroll)
    dialog.setMinimumSize(380,260)
    screen=dialog.screen()
    if screen and QApplication.platformName()!='offscreen':
        available=screen.availableGeometry()
        dialog.resize(min(dialog.width(),max(380,available.width()-24)),min(dialog.height(),max(260,available.height()-48)))


class PopupPolicy(QObject):
    def eventFilter(self,watched,event):
        if isinstance(watched,QMenu) and event.type()==QEvent.Type.Show:
            from .menu_icons import decorate_menu
            decorate_menu(watched)
        if isinstance(watched,QDialog) and type(watched).__name__ not in EXCLUDED:
            if event.type()==QEvent.Type.Polish:window_controls(watched)
            elif event.type()==QEvent.Type.Show:accessible_content(watched)
        return False


def install_popup_policy(app):
    if not hasattr(app,'_sy_popup_policy'):
        app._sy_popup_policy=PopupPolicy(app);app.installEventFilter(app._sy_popup_policy)
