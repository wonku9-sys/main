"""All 46 artwork families use one bounded, command-free hover path."""
import pytest
from PySide6.QtCore import QCoreApplication,QEvent,QPointF,QSize,Qt
from PySide6.QtGui import QAction,QEnterEvent,QMouseEvent
from PySide6.QtWidgets import QApplication,QToolBar,QTabWidget,QWidget,QTreeWidget,QTreeWidgetItem,QDialog,QVBoxLayout,QLabel
from pos2.menu_icons import PAYMENT_KEYS,ATLAS_KEYS,payment_icon,_payment_atlas_image
from pos2.hover_effects import _originals,normal_menu_icon
from pos2.popup_policy import install_popup_policy
from pos2.popup_motion import PopupMotion,OPEN_MS,CLOSE_MS
from pos2.appearance import apply_theme


@pytest.fixture
def ui():
    app=QApplication.instance() or QApplication([]);install_popup_policy(app)
    roots=[];old_css=app.styleSheet();old_palette=app.palette();apply_theme('default')
    yield app,roots
    for root in roots:root.close();root.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents()
    app.setPalette(old_palette);app.setStyleSheet(old_css)


def enter(widget):
    point=widget.rect().center()
    QCoreApplication.sendEvent(widget,QEnterEvent(QPointF(point),QPointF(widget.mapTo(widget.window(),point)),QPointF(widget.mapToGlobal(point))))


def move(widget,point):
    QCoreApplication.sendEvent(widget,QMouseEvent(QEvent.Type.MouseMove,QPointF(point),QPointF(widget.mapToGlobal(point)),Qt.MouseButton.NoButton,Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier))


@pytest.mark.parametrize('key',PAYMENT_KEYS)
def test_every_financial_icon_has_growth_without_relayout_activation_or_clipping(ui,key):
    app,roots=ui;toolbar=QToolBar();roots.append(toolbar);toolbar.setIconSize(QSize(38,38))
    icon=payment_icon(key);item=QAction(icon,key,toolbar);toolbar.addAction(item);calls=[];item.triggered.connect(lambda:calls.append(1))
    toolbar.show();app.processEvents();button=toolbar.widgetForAction(item)
    QCoreApplication.sendEvent(button,QEvent(QEvent.Type.Leave))
    assert icon.cacheKey() in _originals
    rect=button.geometry();hint=button.sizeHint();size=button.iconSize()
    enter(button);assert button.icon().cacheKey()==_originals[icon.cacheKey()].cacheKey()
    assert button.geometry()==rect and button.sizeHint()==hint and button.iconSize()==size and not calls
    for picture in (icon,_originals[icon.cacheKey()]):
        image=picture.pixmap(QSize(76,76)).toImage()
        assert all(image.pixelColor(x,y).alpha()==0 for x in range(76) for y in (0,75))
        assert all(image.pixelColor(x,y).alpha()==0 for y in range(76) for x in (0,75))
    item.setEnabled(False);app.processEvents();assert button.icon().cacheKey()==icon.cacheKey()


def test_common_and_payment_factories_are_cached_without_hover_decode(ui):
    app,roots=ui
    for key in ATLAS_KEYS:assert normal_menu_icon(key).cacheKey() in _originals
    for key in PAYMENT_KEYS:assert payment_icon(key).cacheKey() in _originals
    before=_payment_atlas_image.cache_info()
    for _ in range(20):
        for key in PAYMENT_KEYS:payment_icon(key)
    after=_payment_atlas_image.cache_info();assert before==after


def test_tab_icon_hover_does_not_switch_tab_and_clears_on_disable(ui):
    app,roots=ui;tabs=QTabWidget();roots.append(tabs)
    tabs.addTab(QWidget(),payment_icon('payables'),'외상매입');tabs.addTab(QWidget(),payment_icon('bill'),'어음관리')
    tabs.resize(420,260);tabs.show();app.processEvents();bar=tabs.tabBar();normal=bar.tabIcon(1);rect=bar.tabRect(1);calls=[]
    tabs.currentChanged.connect(lambda *_:calls.append(1))
    move(bar,rect.center());assert bar.tabIcon(1).cacheKey()!=normal.cacheKey()
    assert tabs.currentIndex()==0 and not calls and bar.tabRect(1)==rect
    tabs.setTabEnabled(1,False);bar.repaint();app.processEvents();assert bar.tabIcon(1).cacheKey()==normal.cacheKey()
    tabs.setTabEnabled(1,True);move(bar,rect.center())
    QCoreApplication.sendEvent(bar,QEvent(QEvent.Type.Leave));assert bar.tabIcon(1).cacheKey()==normal.cacheKey()


def test_secondary_tree_menu_uses_same_hover_without_selecting(ui):
    app,roots=ui;tree=QTreeWidget();roots.append(tree);tree.setHeaderHidden(True);tree.setObjectName('secondaryCategoryMenu')
    first=QTreeWidgetItem(tree,['상품']);first.setIcon(0,normal_menu_icon('product'))
    second=QTreeWidgetItem(tree,['공급사']);second.setIcon(0,payment_icon('supplier'));tree.setCurrentItem(first)
    tree.resize(400,250);tree.show();app.processEvents();normal=second.icon(0)
    move(tree.viewport(),tree.visualItemRect(second).center())
    assert second.icon(0).cacheKey()!=normal.cacheKey() and tree.currentItem() is first
    QCoreApplication.sendEvent(tree.viewport(),QEvent(QEvent.Type.Leave));assert second.icon(0).cacheKey()==normal.cacheKey()


@pytest.mark.parametrize('name',('ProductDialog','MemberDialog','SupplierDialog','PurchasePaymentDialog','InspirationDialog','ScheduleDialog','PageWindow','DiaryDialog','HouseholdDialog'))
def test_menu_popup_types_all_share_open_and_close_effect_policy(ui,name):
    app,roots=ui;previous=app._sy_popup_motion;enabled=app.property('_sy_window_motion_enabled')
    controller=PopupMotion(app,force=True);app._sy_popup_motion=controller;app.setProperty('_sy_window_motion_enabled',True)
    dialog=type(name,(QDialog,),{})();roots.append(dialog);dialog.resize(420,280);QVBoxLayout(dialog).addWidget(QLabel('공통 전환 정책 검사'))
    try:
        dialog.show();app.processEvents();state=controller.active[id(dialog)]
        assert state['opening'] and state['group'].duration()==OPEN_MS
        controller._clean(id(dialog));dialog.reject()
        assert dialog.result()==QDialog.DialogCode.Rejected and not dialog.isVisible()
        assert not controller.active[id(dialog)]['opening'] and controller.active[id(dialog)]['group'].duration()==CLOSE_MS
    finally:
        controller.stop();app._sy_popup_motion=previous;app.setProperty('_sy_window_motion_enabled',enabled);controller.deleteLater()
