"""Fixed query controls and native resizable desktop/dialog frames."""
import pytest
from PySide6.QtCore import Qt,QCoreApplication,QEvent,QSize,QRect,QPoint
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QDialog,QMessageBox,QSizeGrip
from pos2.app import MainWindow,menu_caption
from pos2.catalog_ui import ProductDialog
from pos2.popup_policy import install_popup_policy
from pos2.store import Store


@pytest.fixture
def desktop(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([]);install_popup_policy(app)
    store=Store(tmp_path/'resize.db');store.setup_admin('owner','관리자','Owner-Password-2026!')
    window=MainWindow(store);window.show();window.navigation.enable();app.processEvents()
    monkeypatch.setattr('pos2.navigation.ask_unsaved',lambda *_:QMessageBox.StandardButton.Cancel)
    yield app,store,window
    window.navigation.suspended=True;window.navigation.disable()
    for widget in app.topLevelWidgets():widget.close();widget.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents();store.close()


def test_query_stays_at_top_across_menus_and_scrolls(desktop):
    app,_,window=desktop
    origin=None
    for key in ('products','purchases','inventory_categories','settings'):
        assert window.open_page(key);app.processEvents()
        bar=window.query_bar;point=bar.query_button.mapTo(window,bar.query_button.rect().topRight())
        assert abs(bar.query_button.mapTo(bar,bar.query_button.rect().center()).x()-bar.rect().center().x())<=1
        if origin is None:origin=point
        assert point==origin and bar.context.text()==menu_caption(key)
        assert bar is window.current_page.header
        nav=window.navigation_bar
        assert bar.mapTo(window,QPoint()).y()>=nav.mapTo(window,QPoint(0,nav.height())).y()
        assert not nav.findChildren(type(bar.query_button)) or all('조회' not in b.text() for b in nav.findChildren(type(bar.query_button)))
        for button in window.current_page.findChildren(type(bar.query_button)):
            reference=getattr(button,'_sy_query_handler',None)
            handler=reference() if reference else None
            if getattr(handler,'__self__',None) is window.current_page and '조회' in button.text():assert not button.isVisible()
        scroller=window.scrollers[key];scroller.verticalScrollBar().setValue(scroller.verticalScrollBar().maximum())
        app.processEvents();assert bar.query_button.mapTo(window,bar.query_button.rect().topRight())==origin
    assert 'F5' in bar.query_button.toolTip() and '#F6CE63' in bar.styleSheet()
    assert not any(action.text()=='조회' for action in window.toolbar.actions())


def test_button_and_f5_query_same_page_and_respect_unsaved_cancel(desktop,monkeypatch):
    app,_,window=desktop;window.open_page('products');page=window.current_page;called=[]
    monkeypatch.setattr(page,'refresh',lambda:called.append('query'))
    window.query_bar.query_button.click();assert called==['query']
    window.activateWindow();window.setFocus();app.processEvents()
    QTest.keySequence(window,QKeySequence('F5'));app.processEvents();assert called==['query','query']
    window.open_page('settings');page=window.current_page
    page.fields['store_name'].setText('저장하지 않은 이름')
    monkeypatch.setattr(page,'refresh',lambda:called.append('discarded'))
    window.query_bar.query_button.click();assert called==['query','query']
    assert page.fields['store_name'].text()=='저장하지 않은 이름'


def test_popup_fixed_query_native_frame_resize_and_fullscreen_restore(desktop):
    app,_,window=desktop;window.popup_menus=True;window.open_page('worklog');app.processEvents()
    popup=window.popup_windows['worklog'];bar=popup.query_bar
    assert bar is popup.page.header
    assert bar.mapTo(popup,QPoint()).y()>=popup.navigation_bar.height()
    assert popup.isSizeGripEnabled() and popup.findChildren(QSizeGrip)
    assert not popup.windowFlags() & Qt.WindowType.MSWindowsFixedSizeDialogHint
    assert not popup.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert popup.windowFlags() & Qt.WindowType.WindowMaximizeButtonHint
    # Stay inside the small Windows CI desktop; the OS legitimately clamps
    # client sizes larger than its available screen (including native borders).
    for size in (QSize(700,500),QSize(900,650),QSize(760,540)):
        popup.resize(size);app.processEvents();assert popup.size()==size
        pos=bar.pos();scroll=window.scrollers['worklog']
        scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum());app.processEvents()
        assert bar.pos()==pos and bar.query_button.isVisible() and not hasattr(popup,'_popup_close_button')
        assert abs(bar.query_button.mapTo(bar,bar.query_button.rect().center()).x()-bar.rect().center().x())<=1
    popup.showFullScreen();app.processEvents();assert popup.isFullScreen()
    popup.showNormal();app.processEvents();assert not popup.isFullScreen()


def test_main_and_product_dialog_resize_keep_overflow_accessible(desktop):
    app,store,window=desktop
    window.resize(940,640);app.processEvents();assert window.size()==QSize(940,640)
    assert window.statusBar().isSizeGripEnabled()
    assert window.query_bar.query_button.isVisible()
    dialog=ProductDialog(store,parent=window);dialog.show();app.processEvents()
    assert dialog.isSizeGripEnabled()
    dialog.resize(600,440);app.processEvents();assert dialog.size()==QSize(600,440)
    assert dialog.findChild(QDialog) is None
    from PySide6.QtWidgets import QScrollArea
    scroll=dialog.findChild(QScrollArea,'popupScroll')
    assert scroll is not None and scroll.verticalScrollBar().maximum()>0
    assert not hasattr(dialog,'_popup_close_button')
    dialog.close()


@pytest.mark.parametrize('width',(380,700,1000))
@pytest.mark.parametrize('action_count',(0,4))
def test_query_is_truly_centered_with_asymmetric_controls_and_long_titles(desktop,width,action_count):
    from pos2.query_bar import QueryBar
    from pos2.widgets import action
    app,_,_=desktop;called=[]
    bar=QueryBar('상품장',lambda:called.append('query'),description='검색 조건으로 상품을 확인합니다.')
    for i in range(action_count):bar.actions.addWidget(action('엑셀 저장 '+str(i),lambda:None))
    bar.resize(width,88);bar.show();app.processEvents()
    for title in ('상품장','현재고 · 공급사별 / 대분류 / 중분류 / 소분류 · '+'긴 메뉴 설명 '*20):
        bar.context.setText(title);app.processEvents()
        assert bar.context.text()==title and bar.context.toolTip()==title
        button=bar.query_button;rect=QRect(button.mapTo(bar,QPoint()),button.size())
        assert abs(rect.center().x()-bar.rect().center().x())<=1
        assert bar.rect().contains(rect) and button.isVisible()
        for side in (bar.context,bar.action_scroll):
            side_rect=QRect(side.mapTo(bar,QPoint()),side.size())
            assert not rect.intersects(side_rect)
            assert bar.rect().contains(side_rect)
    if action_count and width==380:assert bar.action_scroll.horizontalScrollBar().maximum()>0
    bar.query_button.click();assert called==['query'];bar.close()


def test_background_header_queries_its_own_page_not_active_popup(desktop,monkeypatch):
    app,_,window=desktop;window.open_page('products');products=window.current_page
    window.popup_menus=True;window.open_page('purchases');app.processEvents()
    purchases=window.pages['purchases'];called=[]
    monkeypatch.setattr(products,'refresh',lambda:called.append('products'))
    monkeypatch.setattr(purchases,'refresh',lambda:called.append('purchases'))
    products.header.query_button.click();assert called==['products']
    window.popup_windows['purchases'].query_bar.query_button.click();assert called==['products','purchases']


def test_table_headers_fit_without_scanning_product_rows(desktop,monkeypatch):
    from pos2.widgets import DataGrid
    app,_,_=desktop
    grid=DataGrid(['상품코드','사업자등록번호','순지급 (환급 차감)'])
    grid.setRowCount(35190)
    for column in range(3):grid.setColumnWidth(column,55)
    def forbidden(*args):pytest.fail('Header layout scanned product cells')
    monkeypatch.setattr(grid,'item',forbidden)
    monkeypatch.setattr(grid,'resizeColumnsToContents',forbidden)
    grid.resize(450,300);grid.show();app.processEvents()
    for column in range(3):
        assert grid.columnWidth(column)>=grid.horizontalHeader().sectionSizeHint(column)
        assert grid.horizontalHeaderItem(column).toolTip()==grid.horizontalHeaderItem(column).text()
    grid.horizontalHeader().setStyleSheet('QHeaderView::section {font-size:20px;padding:9px;}')
    grid.hide();grid.show();app.processEvents()
    for column in range(3):assert grid.columnWidth(column)>=grid.horizontalHeader().sectionSizeHint(column)
    assert grid.horizontalScrollBar().maximum()>0
    grid.close()


def test_purchase_input_and_delete_symbol_are_readable(desktop):
    from pos2.workflow_ui import TradeDialog
    app,store,window=desktop
    dialog=TradeDialog(window,'purchase');dialog.show();dialog.resize(600,500);app.processEvents()
    assert dialog.scan.width()>=210 and 'Ctrl+B' in dialog.scan.toolTip()
    button=dialog.line_rows[0]['delete']
    assert button.icon().isNull() and button.width()>=button.minimumSizeHint().width()
    assert button.accessibleName()=='이 품목 삭제'
    header=dialog.table.horizontalHeader()
    for column in range(dialog.table.columnCount()):assert header.sectionSize(column)>=header.sectionSizeHint(column)
    # Long product names remain available without an all-catalogue sizing pass.
    identifier=store.save_product(dict(name='전체 이름을 툴팁으로 확인하는 아주 긴 시험 상품명',base_unit='kg'))
    assert dialog.apply_master_product(identifier)
    selected=next(row for row in dialog.line_rows if row['product'].currentData()==identifier)
    combo=selected['product']
    assert combo.toolTip()==combo.currentText()
    index=combo.model().index(combo.currentIndex())
    assert combo.currentText() in index.data(Qt.ItemDataRole.ToolTipRole)
    assert selected['product'].currentData()==identifier
    unit=selected['unit'];unit.setCurrentIndex(unit.findData('grams'));app.processEvents()
    assert '100g' in unit.toolTip() and unit.toolTip()==unit.currentText()
    assert unit.width()>=unit.minimumSizeHint().width()
    dialog.close()
