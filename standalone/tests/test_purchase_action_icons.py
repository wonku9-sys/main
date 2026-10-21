from hashlib import sha256
import pytest
from PySide6.QtCore import QSize,QCoreApplication,QEvent,QPointF
from PySide6.QtGui import QImage,QEnterEvent
from PySide6.QtWidgets import QApplication,QWidget,QHBoxLayout
from pos2.menu_icons import PURCHASE_ACTION_ATLAS,PURCHASE_ACTION_KEYS,PURCHASE_ACTION_SHA256,family,menu_icon
from pos2.hover_effects import _originals,install_widget_hover
from pos2.widgets import action


def test_dedicated_transparent_3d_arrow_and_batch_assets_are_complete():
    app=QApplication.instance() or QApplication([])
    assert sha256(PURCHASE_ACTION_ATLAS.read_bytes()).hexdigest()==PURCHASE_ACTION_SHA256
    original=QImage(str(PURCHASE_ACTION_ATLAS));assert original.hasAlphaChannel() and original.width()==3*original.height()
    assert [family(label) for label in ('위로','아래로','일괄입력')]==list(PURCHASE_ACTION_KEYS)
    digests=[]
    for kind in PURCHASE_ACTION_KEYS:
        icon=menu_icon(kind);assert not icon.isNull() and icon.cacheKey() in _originals
        image=icon.pixmap(QSize(128,128)).toImage();digests.append(sha256(image.constBits()).hexdigest())
        assert all(image.pixelColor(x,y).alpha()==0 for x,y in ((0,0),(127,0),(0,127),(127,127)))
        assert sum(image.pixelColor(x,y).alpha()>30 for x in range(128) for y in range(128))>2500
    assert len(set(digests))==3


@pytest.mark.parametrize('label',('위로','아래로','일괄입력'))
def test_labels_remain_visible_and_icon_hover_does_not_move_button(label):
    app=QApplication.instance() or QApplication([]);window=QWidget();layout=QHBoxLayout(window)
    clicked=[];button=action(label,lambda:clicked.append(True));button.setIconSize(QSize(28,28))
    install_widget_hover(button);layout.addWidget(button);window.show();app.processEvents()
    try:
        normal=button.icon().cacheKey();geometry=button.geometry()
        QCoreApplication.sendEvent(button,QEvent(QEvent.Type.Leave))
        normal=button.icon().cacheKey();point=QPointF(button.rect().center())
        QCoreApplication.sendEvent(button,QEnterEvent(point,point,QPointF(button.mapToGlobal(button.rect().center()))))
        assert button.icon().cacheKey()!=normal and button.geometry()==geometry and button.text()==label
        button.click();assert clicked==[True]
    finally:window.close();window.deleteLater();app.processEvents()
