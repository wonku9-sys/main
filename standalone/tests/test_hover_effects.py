"""Hover changes pixels, never menu geometry, selection or command invocation."""
import pytest
from PySide6.QtCore import QCoreApplication,QEvent,QPoint,QPointF,QSize,Qt
from PySide6.QtGui import QEnterEvent,QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QHBoxLayout,QWidget,QTreeWidget,QTreeWidgetItem,QMenu

from pos2.appearance import apply_theme,COLORS
from pos2.hover_effects import _originals
from pos2.menu_icons import menu_icon
from pos2.popup_policy import install_popup_policy
from pos2.widgets import output_icon,action


@pytest.fixture
def ui():
    app=QApplication.instance() or QApplication([]);install_popup_policy(app)
    old_css=app.styleSheet();old_palette=app.palette()
    apply_theme('default')
    windows=[]
    yield app,windows
    for window in windows:window.close();window.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents()
    app.setPalette(old_palette);app.setStyleSheet(old_css)


def pixels(icon):
    image=icon.pixmap(QSize(64,64)).toImage()
    return sum(image.pixelColor(x,y).alpha()>30 for x in range(64) for y in range(64))


def enter(widget):
    # A Windows CI desktop has one shared native cursor. Dispatch the real Qt
    # event deterministically rather than racing queued global pointer moves.
    point=widget.rect().center()
    QCoreApplication.sendEvent(widget,QEnterEvent(QPointF(point),
        QPointF(widget.mapTo(widget.window(),point)),QPointF(widget.mapToGlobal(point))))


def leave(widget):
    QCoreApplication.sendEvent(widget,QEvent(QEvent.Type.Leave))


def move_over(widget,point):
    QCoreApplication.sendEvent(widget,QMouseEvent(QEvent.Type.MouseMove,QPointF(point),
        QPointF(widget.mapToGlobal(point)),Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier))


@pytest.mark.parametrize('label',('인쇄','엑셀 저장','일기장','가계부'))
def test_button_hover_grows_icon_only_and_restores_on_leave_or_disable(ui,label):
    app,windows=ui;window=QWidget();windows.append(window);row=QHBoxLayout(window);called=[]
    button=output_icon(label,lambda:called.append(True)) if label in ('인쇄','엑셀 저장') else action(label,lambda:called.append(True))
    row.addWidget(button);row.addStretch();window.resize(440,130);window.show();app.processEvents()
    leave(button)
    normal=button.icon();geometry=button.geometry();hint=button.sizeHint();size=button.iconSize()
    assert normal.cacheKey() in _originals
    enter(button)
    assert button.icon().cacheKey()!=normal.cacheKey() and pixels(button.icon())>pixels(normal)
    assert button.geometry()==geometry and button.sizeHint()==hint and button.iconSize()==size
    assert not called
    button.click();assert called==[True]
    button.setEnabled(False);app.processEvents();assert button.icon().cacheKey()==normal.cacheKey()
    button.click();assert called==[True]
    button.setEnabled(True);leave(button)
    assert button.icon().cacheKey()==normal.cacheKey()


def test_tree_hover_preserves_text_row_size_selection_and_click_behavior(ui):
    app,windows=ui;tree=QTreeWidget();windows.append(tree);tree.setObjectName('navTree')
    tree.setHeaderHidden(True);tree.setIconSize(QSize(18,18));tree.resize(320,180)
    first=QTreeWidgetItem(tree,['일기장']);first.setIcon(0,menu_icon('diary'))
    second=QTreeWidgetItem(tree,['가계부']);second.setIcon(0,menu_icon('household'))
    tree.setCurrentItem(second);calls=[];tree.itemClicked.connect(lambda *_:calls.append(True))
    tree.show();app.processEvents();leave(tree.viewport());rect=tree.visualItemRect(first);normal=first.icon(0)
    move_over(tree.viewport(),rect.center())
    assert first.icon(0).cacheKey()!=normal.cacheKey() and pixels(first.icon(0))>pixels(normal)
    assert tree.visualItemRect(first)==rect and tree.currentItem() is second and not calls
    leave(tree.viewport())
    assert first.icon(0).cacheKey()==normal.cacheKey()
    QTest.mouseClick(tree.viewport(),Qt.MouseButton.LeftButton,pos=rect.center())
    assert calls==[True] and tree.currentItem() is first


def test_menu_hover_restores_icon_without_activating_action(ui):
    app,windows=ui;menu=QMenu();windows.append(menu)
    first=menu.addAction(menu_icon('diary'),'일기장');second=menu.addAction(menu_icon('household'),'가계부')
    calls=[];first.triggered.connect(lambda:calls.append(True));normal=first.icon()
    menu.popup(QPoint(40,40));app.processEvents();menu.hovered.emit(first);app.processEvents()
    assert first.icon().cacheKey()!=normal.cacheKey() and not calls
    menu.hovered.emit(second);assert first.icon().cacheKey()==normal.cacheKey()
    menu.hide();assert second.icon().cacheKey()==menu_icon('household').cacheKey() and not calls


def test_cpp_created_toolbar_hover_survives_gc_and_releases_handler_with_owner(ui):
    import gc
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import QToolBar
    from pos2.hover_effects import _handlers
    app,windows=ui;toolbar=QToolBar();windows.append(toolbar)
    item=QAction(menu_icon('products'),'상품장',toolbar);toolbar.addAction(item)
    toolbar.show();app.processEvents()
    button=toolbar.widgetForAction(item)
    leave(button)
    handler=button._sy_menu_hover;normal=button.icon();geometry=button.geometry()
    del button;gc.collect();button=toolbar.widgetForAction(item)
    item.setEnabled(False);item.setEnabled(True);app.processEvents()
    leave(button)
    assert button._sy_menu_hover is handler and handler.normal is None
    enter(button)
    assert button.icon().cacheKey()!=normal.cacheKey() and button.geometry()==geometry
    button.hide();assert button.icon().cacheKey()==normal.cacheKey()
    toolbar.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    assert handler not in _handlers
    windows.remove(toolbar)


@pytest.mark.parametrize('theme',('default','spring','summer','autumn','winter'))
def test_hover_palette_is_subtly_brighter_and_skin_relative(ui,theme):
    from PySide6.QtGui import QPalette,QColor
    app,_=ui;apply_theme(theme);normal=QColor(COLORS[theme][0]);hover=app.palette().color(QPalette.ColorRole.Light)
    assert all(h>n for h,n in zip((hover.red(),hover.green(),hover.blue()),(normal.red(),normal.green(),normal.blue())))
    assert max(hover.red()-normal.red(),hover.green()-normal.green(),hover.blue()-normal.blue())<=12
