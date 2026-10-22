import pytest
from PySide6.QtCore import QPoint, Qt, QCoreApplication, QEvent
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMainWindow
from test_purchase_price_history import shop
from pos2.workflow_ui import TradeDialog
from pos2.purchase_context_menu import build_menu
from pos2.popup_policy import install_popup_policy
from pos2.localization import install_korean_ui


@pytest.fixture
def desktop(shop):
    app=QApplication.instance() or QApplication([]);install_korean_ui(app);install_popup_policy(app)
    store,_,product=shop;other=store.save_product(dict(name='두 번째 상품',base_unit='개'))
    host=QMainWindow();host.store=store;host.notify=lambda *_:None
    trade=TradeDialog(host,'purchase');trade.apply_picked_products([(trade.product_map[product],None),(trade.product_map[other],None)])
    trade.show();trade.activateWindow();app.processEvents()
    yield app,store,trade
    trade.reject();trade.deleteLater();host.close();host.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents()


def test_left_zone_selects_row_right_zone_selects_and_edits_one_cell(desktop):
    app,store,trade=desktop;first=trade.line_rows[0]
    QTest.mouseClick(first['spec'],Qt.MouseButton.LeftButton);app.processEvents()
    assert trade.table.selection_scope=='row' and trade.table.currentRow()==0
    assert '#EEEFCF' in first['product'].styleSheet() and '#EEEFCF' in first['spec'].styleSheet()
    assert all('#087FD3' in first[key].styleSheet() for key in ('barcode','qty','price','sale_price'))
    QTest.mouseClick(first['qty'],Qt.MouseButton.LeftButton);app.processEvents()
    assert trade.table.selection_scope=='cell' and trade.table.currentColumn()==3
    assert '#087FD3' in first['qty'].styleSheet() and '#087FD3' not in first['price'].styleSheet()
    first['qty'].selectAll();QTest.keyClicks(first['qty'],'12');app.processEvents()
    assert first['qty'].text()=='12' and not store.documents()
    trade.table.choose_row(1);assert '#087FD3' not in first['qty'].styleSheet()


def test_real_product_context_menu_compact_expand_and_routes(desktop,monkeypatch):
    app,store,trade=desktop;called=[]
    monkeypatch.setattr(trade,'product_info',lambda:called.append('info'))
    field=trade.line_rows[0]['product'];position=QPoint(8,8)
    event=QContextMenuEvent(QContextMenuEvent.Reason.Mouse,position,field.mapToGlobal(position))
    QApplication.sendEvent(field,event);app.processEvents()
    menu=trade.table._product_menu
    commands={a.text():a for a in menu.actions() if not a.isSeparator()}
    assert menu.isVisible() and trade.table.currentRow()==0
    assert {'줄여보기','펼쳐보기','인쇄(그리드)','인쇄(출력양식)','엑셀저장','상품 순서이동'}<=commands.keys()
    before=trade.payload();commands['줄여보기'].trigger()
    from pos2.purchase_worksheet_view import BASIC_COLUMNS,DETAIL_KEYS
    assert not any(trade.table.isColumnHidden(trade.line_columns.index(k)) for k in BASIC_COLUMNS)
    assert all(trade.table.isColumnHidden(trade.line_columns.index(k)) for k in DETAIL_KEYS)
    assert not trade.table.isColumnHidden(trade.line_columns.index('price'))
    commands['펼쳐보기'].trigger()
    assert not any(trade.table.isColumnHidden(c) for c in range(trade.table.columnCount()))
    commands['상품 등록정보 (F8)'].trigger();assert called==['info']
    assert trade.payload()==before and not store.documents()
    menu.close()


def test_context_mutations_respect_readonly_and_move_the_selected_row(desktop):
    app,store,trade=desktop;trade.table.choose_row(1)
    before=trade.line_rows[1]['product'].currentData()
    menu=build_menu(trade);move=next(a.menu() for a in menu.actions() if a.text()=='상품 순서이동')
    next(a for a in move.actions() if a.text()=='위로').trigger()
    assert trade.line_rows[0]['product'].currentData()==before and trade.table.currentRow()==0
    trade.readonly=True;readonly=build_menu(trade)
    states={a.text():a.isEnabled() for a in readonly.actions()}
    assert not states['매입수정 (F6)'] and not states['선택행 삭제 (F7)']
    assert states['인쇄(그리드)'] and states['상품 등록정보 (F8)']
    assert not store.documents();readonly.deleteLater();menu.deleteLater()


def test_blank_gray_area_and_header_use_same_menu_without_losing_selection(desktop):
    app,store,trade=desktop;trade.table.choose_row(1)
    viewport=trade.table.viewport();point=QPoint(20,viewport.height()-5)
    event=QContextMenuEvent(QContextMenuEvent.Reason.Mouse,point,viewport.mapToGlobal(point))
    QApplication.sendEvent(viewport,event);app.processEvents()
    assert trade.table.currentRow()==1 and trade.table._product_menu.isVisible()
    labels={a.text() for a in trade.table._product_menu.actions()}
    assert {'줄여보기','펼쳐보기','엑셀저장'}<=labels
    trade.table._product_menu.close()
    trade.table.horizontalHeader().customContextMenuRequested.emit(QPoint(12,12));app.processEvents()
    assert trade.table._product_menu.isVisible() and trade.table.currentRow()==1
    trade.table._product_menu.close();assert not store.documents()


@pytest.mark.parametrize('key',['barcode','qty','price','sale_price','line_memo'])
@pytest.mark.parametrize('same_row',[True,False])
@pytest.mark.parametrize('event_path',['mouse','native'])
def test_right_click_targets_the_actual_cell_not_the_previous_selection(desktop,key,same_row,event_path):
    app,store,trade=desktop
    target_row=0 if same_row else 1
    trade.table.choose_cell(0,trade.line_columns.index('price'))
    field=trade.line_rows[target_row][key]
    field.setText('우클릭 메모' if key=='line_memo' else '123')
    field.selectAll()
    if event_path=='mouse':QTest.mouseClick(field,Qt.MouseButton.RightButton)
    else:
        point=QPoint(8,8)
        QApplication.sendEvent(field,QContextMenuEvent(QContextMenuEvent.Reason.Mouse,point,field.mapToGlobal(point)))
    app.processEvents()
    assert trade.table.currentRow()==target_row
    assert trade.table.currentColumn()==trade.line_columns.index(key)
    assert trade.table.selection_scope=='cell'
    menu=trade.table._product_menu
    editor=next(a.menu() for a in menu.actions() if a.text()=='셀 편집')
    copy=next(a for a in editor.actions() if '복사' in a.text())
    copy.trigger()
    assert QApplication.clipboard().text()==field.text()
    menu.close();assert not store.documents()


@pytest.mark.parametrize('event_path',['signal','mouse'])
def test_right_click_row_number_selects_that_row_and_keeps_it_on_gray_area(desktop,event_path):
    app,store,trade=desktop;trade.table.choose_row(0)
    header=trade.table.verticalHeader()
    point=QPoint(8,header.sectionViewportPosition(1)+8)
    if event_path=='signal':header.customContextMenuRequested.emit(point)
    else:QTest.mouseClick(header.viewport(),Qt.MouseButton.RightButton,pos=point)
    app.processEvents()
    assert trade.table.currentRow()==1 and trade.table.selection_scope=='row'
    trade.table._product_menu.close()
    viewport=trade.table.viewport();point=QPoint(12,viewport.height()-6)
    QTest.mouseClick(viewport,Qt.MouseButton.RightButton,pos=point);app.processEvents()
    assert trade.table.currentRow()==1 and trade.table.selection_scope=='row'
    trade.table._product_menu.close();assert not store.documents()


def test_all_business_context_actions_offer_korean_hover_help(desktop):
    _,_,trade=desktop;menu=build_menu(trade)
    assert menu.toolTipsVisible()
    for command in menu.actions():
        if command.isSeparator():continue
        assert command.toolTip()!=command.text(),command.text()
        if command.menu():assert command.menu().toolTipsVisible()
    menu.deleteLater()
