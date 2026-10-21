"""Readable reference-sized navigation with original, scalable menu artwork."""
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QSize, Qt
from PySide6.QtWidgets import QApplication, QHeaderView,QPushButton

from pos2.app import MainWindow
from pos2.menu_icons import family, menu_icon
from pos2.store import Store


@pytest.fixture
def desktop(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = Store(tmp_path / 'appearance.db')
    store.setup_admin('owner', '관리자', 'Owner-Password-2026!')
    window = MainWindow(store)
    window.show()
    app.processEvents()
    yield app, window
    window.navigation.suspended = True
    window.navigation.disable()
    for widget in app.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    store.close()


def test_navigation_matches_reference_font_and_keeps_long_labels_accessible(desktop):
    app, window = desktop
    tree = window.tree
    assert tree.font().pixelSize() == 14
    assert tree.textElideMode() == Qt.TextElideMode.ElideNone
    assert tree.header().sectionResizeMode(0) == QHeaderView.ResizeMode.ResizeToContents
    item = window.items['products']
    label = item.text(0)
    item.setText(0, label + ' · 공급사와 분류를 포함한 긴 메뉴 이름')
    tree.expandAll()
    app.processEvents()
    # Only the last expanded group remains open under accordion navigation.
    item.parent().setExpanded(True)
    app.processEvents()
    assert tree.horizontalScrollBar().maximum() > 0
    for width, height in ((940, 640), (1500, 930)):
        window.resize(width, height)
        tree.scrollToItem(item)
        app.processEvents()
        assert tree.font().pixelSize() == 14
        assert tree.visualItemRect(item).height() >= tree.fontMetrics().height() + 6
        assert tree.visualItemRect(item).intersects(tree.viewport().rect())
    item.setText(0, label)


def test_toolbar_uses_large_distinct_original_icons(desktop):
    _, window = desktop
    assert window.toolbar.iconSize() == QSize(38, 38)
    images = []
    for key in ('home', 'products', 'purchases', 'calendar', '인쇄', '엑셀 저장'):
        icon = menu_icon(key)
        assert not icon.isNull()
        pixmap = icon.pixmap(QSize(64, 64))
        assert not pixmap.isNull()
        image = pixmap.toImage()
        assert image.pixelColor(0, 0).alpha() == 0
        assert image.pixelColor(32, 32).alpha() > 0
        images.append(bytes(image.constBits()))
    assert len(set(images)) == len(images)
    assert family('첫화면') == 'home'
    assert family('상품장') == 'product'
    assert family('매입전표') == 'purchase'
    assert not window.toolbar.isMovable()


def test_personal_shortcuts_blend_with_the_skin_instead_of_white_cards(desktop):
    _,window=desktop
    assert 'background:white' not in window.personal_panel.styleSheet()
    assert 'background:transparent' in window.personal_panel.styleSheet()
    assert 'background:palette(window)' in window.personal_dock.styleSheet()


def test_modest_icon_increase_preserves_label_size_and_output_clearance(desktop):
    app,window=desktop
    assert window.tree.iconSize()==QSize(18,18) and window.tree.font().pixelSize()==14
    for button in window.personal_panel.findChildren(QPushButton):
        assert button.iconSize()==QSize(26,26)
        assert button.fontMetrics().horizontalAdvance(button.text())+26+30<=button.width()
    window.open_page('purchases');app.processEvents()
    for name in ('outputPrintIcon','outputSaveIcon'):
        button=window.current_page.findChild(QPushButton,name) or window.current_page.header.findChild(QPushButton,name)
        assert button is not None and button.iconSize()==QSize(28,28)
        assert button.width()>=button.iconSize().width()+4 and button.height()>=button.iconSize().height()+4
    window.open_page('payments');app.processEvents()
    assert window.current_page.payment_toolbar.iconSize()==QSize(38,38)
