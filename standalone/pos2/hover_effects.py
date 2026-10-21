"""Cached icon-only hover growth. No iconSize/layout changes or idle timers."""
from functools import lru_cache

from PySide6.QtCore import QObject,QEvent,QRect,Qt
from PySide6.QtGui import QIcon,QPixmap,QPainter
from PySide6.QtWidgets import QAbstractButton,QTreeWidget,QMenu,QTabBar
from shiboken6 import isValid

_originals={}
_handlers=set()


@lru_cache(maxsize=32)
def normal_menu_icon(kind):
    from .menu_icons import _family_icon
    return register_hover_icon(_family_icon(kind))


def register_hover_icon(original):
    """Apply the same two cached sizes to every original artwork family.

    Called by cached icon factories, not per widget or per mouse movement.
    Financial artwork must use this path as well as the common menu atlas.
    """
    pixmap=QPixmap(128,128);pixmap.fill(Qt.GlobalColor.transparent)
    painter=QPainter(pixmap);painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    original.paint(painter,QRect(4,4,120,120));painter.end()
    normal=QIcon(pixmap);_originals[normal.cacheKey()]=original
    return normal


class ButtonHover(QObject):
    def __init__(self,button):
        self.button=button;self.normal=None;self.enlarged=None
        super().__init__(button)
        button.installEventFilter(self)

    def restore(self):
        if getattr(self,'normal',None) is not None and isValid(self.button) and self.button.icon().cacheKey()==self.enlarged.cacheKey():
            self.button.setIcon(self.normal)
        self.normal=self.enlarged=None

    def eventFilter(self,widget,event):
        kind=event.type()
        if kind==QEvent.Type.Enter and widget.isEnabled() and self.normal is None:
            normal=widget.icon();enlarged=_originals.get(normal.cacheKey())
            if enlarged is not None:
                self.normal,self.enlarged=normal,enlarged;widget.setIcon(enlarged)
        elif kind in {QEvent.Type.Leave,QEvent.Type.Hide,QEvent.Type.EnabledChange}:self.restore()
        return False


class TreeHover(QObject):
    def __init__(self,tree):
        super().__init__(tree);self.tree=tree;self.item=None;self.normal=None;self.enlarged=None
        tree.setMouseTracking(True);tree.viewport().setMouseTracking(True)
        tree.viewport().installEventFilter(self)

    def restore(self):
        if self.item is not None and isValid(self.item) and self.item.icon(0).cacheKey()==self.enlarged.cacheKey():
            self.item.setIcon(0,self.normal)
        self.item=self.normal=self.enlarged=None

    def eventFilter(self,widget,event):
        if event.type()==QEvent.Type.MouseMove:
            item=self.tree.itemAt(event.position().toPoint())
            if item is self.item:return False
            self.restore()
            if item is not None and self.tree.isEnabled() and item.flags() & Qt.ItemFlag.ItemIsEnabled:
                normal=item.icon(0);enlarged=_originals.get(normal.cacheKey())
                if enlarged is not None:self.item,self.normal,self.enlarged=item,normal,enlarged;item.setIcon(0,enlarged)
        elif event.type() in {QEvent.Type.Leave,QEvent.Type.Hide,QEvent.Type.EnabledChange}:self.restore()
        return False


class MenuHover(QObject):
    def __init__(self,menu):
        super().__init__(menu);self.action=None;self.normal=None;self.enlarged=None
        menu.hovered.connect(self.hover);menu.aboutToHide.connect(self.restore)

    def restore(self):
        if self.action is not None and isValid(self.action) and self.action.icon().cacheKey()==self.enlarged.cacheKey():
            self.action.setIcon(self.normal)
        self.action=self.normal=self.enlarged=None

    def hover(self,action):
        if action is self.action:return
        self.restore()
        if action is not None and action.isEnabled():
            normal=action.icon();enlarged=_originals.get(normal.cacheKey())
            if enlarged is not None:self.action,self.normal,self.enlarged=action,normal,enlarged;action.setIcon(enlarged)


class TabHover(QObject):
    """Highlight a tab icon without selecting the tab or changing its slot."""
    def __init__(self,bar):
        super().__init__(bar);self.bar=bar;self.index=-1;self.normal=None;self.enlarged=None
        bar.setMouseTracking(True);bar.installEventFilter(self)

    def restore(self):
        if self.normal is not None and isValid(self.bar) and 0<=self.index<self.bar.count() and self.bar.tabIcon(self.index).cacheKey()==self.enlarged.cacheKey():
            self.bar.setTabIcon(self.index,self.normal)
        self.index=-1;self.normal=self.enlarged=None

    def eventFilter(self,widget,event):
        kind=event.type()
        if kind==QEvent.Type.MouseMove:
            index=widget.tabAt(event.position().toPoint())
            if index==self.index:return False
            self.restore()
            if index>=0 and widget.isEnabled() and widget.isTabEnabled(index):
                normal=widget.tabIcon(index);enlarged=_originals.get(normal.cacheKey())
                if enlarged is not None:
                    self.index,self.normal,self.enlarged=index,normal,enlarged;widget.setTabIcon(index,enlarged)
        elif kind in {QEvent.Type.Leave,QEvent.Type.Hide,QEvent.Type.EnabledChange}:self.restore()
        elif kind==QEvent.Type.Paint and self.normal is not None and (not 0<=self.index<widget.count() or not widget.isTabEnabled(self.index)):
            self.restore()
        return False


def install_widget_hover(widget):
    if hasattr(widget,'_sy_menu_hover'):return
    if isinstance(widget,QAbstractButton):widget._sy_menu_hover=ButtonHover(widget)
    elif isinstance(widget,QTreeWidget):widget._sy_menu_hover=TreeHover(widget)
    elif isinstance(widget,QTabBar):widget._sy_menu_hover=TabHover(widget)
    elif isinstance(widget,QMenu):widget._sy_menu_hover=MenuHover(widget)
    else:return
    # QToolBar creates its buttons in C++; pin Python event-filter state until
    # the owning widget is destroyed, even when its temporary wrapper is GC'd.
    handler=widget._sy_menu_hover;_handlers.add(handler)
    widget.destroyed.connect(lambda *_:_handlers.discard(handler))
