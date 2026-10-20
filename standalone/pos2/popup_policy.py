"""Resizable dialogs, maximize/fullscreen controls and accessible overflow."""
import time
from PySide6.QtCore import QEvent,QObject,Qt
from PySide6.QtGui import QAction,QKeySequence
from PySide6.QtWidgets import QApplication,QDialog,QScrollArea,QVBoxLayout,QWidget,QMenu,QPushButton,QHBoxLayout,QSizeGrip

EXCLUDED={'QMessageBox','QInputDialog','QFileDialog','QPrintDialog','QPrintPreviewDialog'}


def window_controls(dialog):
    if getattr(dialog,'_window_controls',False):return
    dialog._window_controls=True
    # Keep the native Windows frame: every edge and corner remains resizable.
    flags=dialog.windowFlags() & ~Qt.WindowType.MSWindowsFixedSizeDialogHint
    dialog.setWindowFlags(flags|Qt.WindowType.WindowMinMaxButtonsHint|Qt.WindowType.WindowSystemMenuHint)
    dialog.setSizeGripEnabled(True)
    for grip in dialog.findChildren(QSizeGrip):
        grip.setAccessibleName('창 크기 조절')
        grip.setToolTip('모서리나 창 테두리를 드래그해 크기를 조절합니다. 최대화·전체화면에서는 창모드로 복원하세요.')
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
    if not isinstance(existing,QScrollArea) and not getattr(dialog,'_fixed_query_header',False):
        surface=QWidget();surface.setObjectName('popupSurface');surface.setLayout(layout)
        outer=QVBoxLayout(dialog);outer.setContentsMargins(0,0,0,0)
        scroll=QScrollArea(dialog);scroll.setObjectName('popupScroll');scroll.setWidgetResizable(True)
        scroll.setWidget(surface);outer.addWidget(scroll)
    # Keep a separate close control reachable even when the form is scrolled.
    close=next((button for button in dialog.findChildren(QPushButton) if button.text()=='이 창 닫기'),None)
    if close is None:
        close=QPushButton('이 창 닫기',dialog);close.setAutoDefault(False)
        close.clicked.connect(dialog.close)
        footer=QHBoxLayout();footer.addStretch();footer.addWidget(close)
        dialog.layout().addLayout(footer)
    close.setToolTip('현재 팝업만 닫습니다. 저장하지 않은 작업은 먼저 확인합니다.\n단축키: Ctrl+W')
    dialog._popup_close_button=close
    close_action=QAction('이 창 닫기',dialog);close_action.setShortcut(QKeySequence('Ctrl+W'))
    close_action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
    close_action.setAutoRepeat(False);close_action.triggered.connect(dialog.close);dialog.addAction(close_action)
    dialog._popup_close_action=close_action
    dialog.setMinimumSize(380,260)
    screen=dialog.screen()
    if screen and QApplication.platformName()!='offscreen':
        available=screen.availableGeometry()
        dialog.resize(min(dialog.width(),max(380,available.width()-24)),min(dialog.height(),max(260,available.height()-48)))


class PopupPolicy(QObject):
    def eventFilter(self,watched,event):
        if event.type()==QEvent.Type.ContextMenu or event.type()==QEvent.Type.MouseButtonPress and event.button()==Qt.MouseButton.RightButton:
            QApplication.instance()._sy_context_requested_at=time.monotonic()
        if isinstance(watched,QWidget) and event.type()==QEvent.Type.MouseButtonRelease and event.button()==Qt.MouseButton.LeftButton and watched.isEnabled():
            from .ui_sounds import play_global_cue
            play_global_cue('click')
        if isinstance(watched,QDialog) and event.type() in {QEvent.Type.Show,QEvent.Type.Hide}:
            from .ui_sounds import play_dialog_cue
            play_dialog_cue(watched,event)
        if isinstance(watched,QMenu) and event.type()==QEvent.Type.Show:
            app=QApplication.instance();requested=getattr(app,'_sy_context_requested_at',0);app._sy_context_requested_at=0
            if requested>0 and 0<=time.monotonic()-requested<2:
                from .ui_sounds import play_global_cue
                play_global_cue('context')
            from .menu_icons import decorate_menu
            decorate_menu(watched)
        if isinstance(watched,QDialog) and type(watched).__name__ not in EXCLUDED:
            if event.type()==QEvent.Type.Polish:window_controls(watched)
            elif event.type()==QEvent.Type.Show:accessible_content(watched)
        return False


def install_popup_policy(app):
    if not hasattr(app,'_sy_popup_policy'):
        app._sy_popup_policy=PopupPolicy(app);app.installEventFilter(app._sy_popup_policy)
