"""Modeless desktop windows with one owner, permission checks and safe shutdown."""
from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QApplication,QDialog, QVBoxLayout, QMessageBox, QToolButton


class PageWindow(QDialog):
    def __init__(self,desktop,key,page,surface):
        super().__init__(None)
        self._desktop_owner=desktop;self.key,self.page=key,page
        self.revision=None
        self.setWindowTitle(page.title+' · SY POS');self.setWindowIcon(desktop.windowIcon())
        self.resize(1180,800);self.setMinimumSize(780,540)
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.setSpacing(0)
        from .query_bar import NavigationBar
        self._fixed_query_header=True
        self.navigation_bar=NavigationBar(page.title,self,home=desktop.go_home,close=self.close)
        self.query_bar=page.header;self.query_bar.set_query(self.refresh)
        layout.addWidget(self.navigation_bar)
        layout.addWidget(surface,1)
        # QStackedWidget hides non-current pages explicitly. Reparenting that
        # page surface into a dialog does not clear its hidden flag by itself.
        surface.show()
        self.setWindowModality(Qt.WindowModality.NonModal)
        from .menu_shortcuts import install_window_shortcuts
        install_window_shortcuts(self, desktop)
        from .menu_icons import menu_icon
        for index,title in enumerate(('이전','다음')):
            tool=self.common_shortcut_actions[title];tool.setIcon(menu_icon(title))
            button=QToolButton(self.navigation_bar);button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.setDefaultAction(tool);self.navigation_bar.layout().insertWidget(index,button)
        desktop._update_history_actions()

    def refresh(self):
        owner=self._desktop_owner
        try:
            owner.store.require_menu(self.key)
            if owner.navigation.allow_leave(self.page):self.page.refresh();owner.navigation.track(self.page)
        except (ValueError,PermissionError) as exc:
            QMessageBox.warning(self,'조회 확인',str(exc))

    def event(self,event):
        if event.type()==QEvent.Type.WindowActivate and hasattr(self,'page'):
            owner=self._desktop_owner
            # Native focus events can be queued by raise/close and are not a
            # menu execution. Never turn history replay into new visits.
            owner._sync_menu_context(self.key,self.page,record=False)
        return super().event(event)

    def closeEvent(self,event):
        owner=self._desktop_owner
        for dialog in reversed(self.findChildren(QDialog)):
            if dialog.isVisible():
                dialog.close()
                if dialog.isVisible():event.ignore();return
        if not owner.navigation.allow_leave(self.page):event.ignore();return
        event.accept()

    def reject(self):self.close()


def active_personal(page,kind):
    owner=page.window
    dialog=getattr(owner,'personal_windows',{}).get(kind)
    if dialog is not None and not getattr(dialog,'closed_securely',False):
        dialog.showNormal();dialog.raise_();dialog.activateWindow();return True
    return False


def show_personal(page,kind,dialog):
    owner=page.window
    if not hasattr(owner,'personal_windows'):owner.personal_windows={}
    dialog.setParent(None);dialog._desktop_owner=owner
    dialog.setWindowModality(Qt.WindowModality.NonModal)
    owner.personal_windows[kind]=dialog
    def finished(*_):
        dialog.wipe()
        if owner.personal_windows.get(kind) is dialog:owner.personal_windows.pop(kind,None)
        dialog.deleteLater()
    dialog.finished.connect(finished)
    dialog.show();dialog.raise_();dialog.activateWindow()


def close_independent_windows(desktop):
    from shiboken6 import isValid
    lucky=getattr(QApplication.instance(),'_sy_lucky_window',None)
    app=QApplication.instance()
    for game in getattr(app,'_sy_arcade_windows',[]):
        if isValid(game):game.close()
    lobby=getattr(app,'_sy_arcade_lobby',None)
    if lobby is not None and isValid(lobby):lobby.close()
    if lucky is not None and isValid(lucky):lucky.close()
    for dialog in list(getattr(desktop,'personal_windows',{}).values())+list(getattr(desktop,'popup_windows',{}).values()):
        if dialog.isVisible():
            dialog.close()
            if dialog.isVisible():return False
    return True
