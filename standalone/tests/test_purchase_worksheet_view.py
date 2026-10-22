from datetime import date
from decimal import Decimal
import json

import pytest
from PySide6.QtCore import QCoreApplication,QEvent,QPoint,Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QMainWindow

from test_purchase_price_history import shop
from pos2.navigation import state
from pos2.purchase_context_menu import build_menu
from pos2.purchase_worksheet_view import BASIC_COLUMNS,DETAIL_KEYS,EXPANDED_COLUMNS,profit_values
from pos2.workflow_ui import TradeDialog


@pytest.fixture
def desktop(shop):
    app=QApplication.instance() or QApplication([])
    store,supplier,product=shop
    host=QMainWindow();host.store=store;host.notify=lambda *_:None
    trade=TradeDialog(host,'purchase');trade.partner.setCurrentIndex(trade.partner.findData(supplier))
    trade.apply_picked_products([(trade.product_map[product],None)])
    trade.show();trade.activateWindow();app.processEvents()
    yield app,store,trade,supplier,product
    for dialog in host.findChildren(TradeDialog):dialog.reject();dialog.deleteLater()
    host.close();host.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents()


def test_presets_show_all_basic_columns_and_real_expanded_order_without_any_write(desktop):
    app,store,trade,_,_=desktop
    assert trade.purchase_view.visible_keys()==set(BASIC_COLUMNS)
    before=trade.payload(),state(trade),store.audit_revision(),store.documents()
    trade.purchase_view.set_view('expanded')
    header=trade.table.horizontalHeader()
    assert tuple(trade.line_columns[header.logicalIndex(i)] for i in range(header.count()))==EXPANDED_COLUMNS
    assert trade.purchase_view.visible_keys()==set(trade.line_columns)
    assert trade.purchase_view.dc_amount.isVisible() and trade.purchase_view.dc_rate.isVisible()
    assert trade.purchase_view.dc_amount.text()=='DC금액: 미기록'
    app.processEvents()
    assert trade.purchase_view.dc_amount.mapTo(trade,QPoint()).y()<trade.table.mapTo(trade,QPoint()).y()
    trade.purchase_view.set_view('compact')
    assert trade.purchase_view.visible_keys()==set(BASIC_COLUMNS)
    assert not trade.purchase_view.dc_amount.isVisible()
    assert (trade.payload(),state(trade),store.audit_revision(),store.documents())==before


def test_real_column_menu_preserves_custom_selection_for_same_store_and_user(desktop):
    app,store,trade,_,_=desktop
    before=trade.payload(),store.audit_revision()
    menu=build_menu(trade)
    columns=next(a.menu() for a in menu.actions() if a.text()=='열 선택')
    options={a.text():a for a in columns.actions()}
    assert not options['상품명'].isEnabled() and not options['규격'].isEnabled()
    options['분류'].trigger();options['판매가액'].trigger()
    assert trade.table.isColumnHidden(trade.line_columns.index('category'))
    assert not trade.table.isColumnHidden(trade.line_columns.index('sale_amount'))
    other=TradeDialog(trade.window,'purchase')
    assert other.purchase_view.mode=='custom'
    assert other.purchase_view.visible_keys()==trade.purchase_view.visible_keys()
    assert (trade.payload(),store.audit_revision())==before
    # Explicit compact/expanded presets override a custom choice, not hide basics.
    other.purchase_view.set_view('compact')
    assert other.purchase_view.visible_keys()==set(BASIC_COLUMNS)
    other.reject();menu.deleteLater()


def test_hiding_current_detail_moves_selection_to_visible_cell_without_losing_row(desktop):
    _,store,trade,_,_=desktop
    trade.purchase_view.set_view('expanded')
    trade.table.choose_cell(0,trade.line_columns.index('estimated_profit'))
    trade.purchase_view.set_view('compact')
    assert trade.table.currentRow()==0 and trade.table.currentColumn()==trade.line_columns.index('price')
    trade.table.choose_row(0);trade.purchase_view.set_view('expanded');trade.purchase_view.set_view('compact')
    assert trade.table.selection_scope=='row' and trade.table.currentRow()==0
    assert not store.documents()


@pytest.mark.parametrize('quantity,factor,purchase,sale,basis,expected',[
    ('2','1','11800','19800',1,'4000.00'),
    ('2','24','48000','72000',1,'500.00'),
    ('200','1','2000','3000',100,'500.00'),
    ('100','0.001','125.55','200.05',1,'745.00'),
    ('3','1','1.00','3.00',1,'0.67'),
    ('2','1','5','3',1,'-1.00'),
])
def test_detail_reference_profit_normalizes_basic_pack_and_weight_units(quantity,factor,purchase,sale,basis,expected):
    values=profit_values(quantity,factor,purchase,sale,basis)
    assert values['unit_profit']==Decimal(expected)
    assert values['estimated_profit']==Decimal(sale)-Decimal(purchase)


def test_exact_override_is_used_not_rounded_price_times_quantity_and_no_unknown_zeroes(desktop):
    _,store,trade,_,_=desktop;row=trade.line_rows[0]
    row['qty'].setText('2');row['price'].setText('5900');row['sale_price'].setText('9900')
    assert row['sale_amount'].text()=='19,800.00'
    assert row['estimated_profit'].text()=='8,000.00' and row['unit_profit'].text()=='4,000.00'
    row['total'].setText('5001.01');trade.line_amount_changed(row)
    assert row['price'].text()=='2,500.51' and row['total'].text()=='5,001.01'
    assert row['estimated_profit'].text()=='14,798.99'
    assert row['unit_profit'].text()=='7,399.50'
    for key in DETAIL_KEYS[:8]+('item_type',):
        assert row[key].text()=='미기록' and '추정하지' in row[key].toolTip()
    assert not store.documents()


def test_missing_historical_sale_price_never_uses_current_catalog_to_invent_profit(desktop):
    _,store,trade,supplier,product=desktop
    identifier=store.post_document(dict(kind='purchase',date=date.today().isoformat(),partner_id=supplier,
        lines=[dict(product_id=product,qty=2,unit_price=5900,sale_price=9900)]))
    store.db.execute('DELETE FROM document_entry WHERE document_id=?',(identifier,));store.db.commit()
    store.save_product(dict(sale_price=50000),product)
    old=TradeDialog(trade.window,'purchase',store.document(identifier));row=old.line_rows[0]
    for key in ('sale_amount','estimated_profit','unit_profit'):
        assert row[key].text()=='미기록' and '당시 판매단가 기록' in row[key].toolTip()
    # A deliberate user entry is distinguishable from programmatic fallback.
    row['sale_price'].setFocus();row['sale_price'].selectAll();QTest.keyClicks(row['sale_price'],'10000')
    assert row['sale_price_reentered'] and row['sale_amount'].text()=='20,000.00'
    old.reject()


def test_recorded_sale_price_and_partial_return_rounding_remain_historical(desktop):
    _,store,trade,supplier,product=desktop
    identifier=store.post_document(dict(kind='purchase',date=date.today().isoformat(),partner_id=supplier,
        lines=[dict(product_id=product,qty=3,unit_price='0.33',amount_override='1.00',sale_price='1.00')]))
    source=store.document(identifier);line=source['lines'][0]
    store.post_document(dict(kind='purchase_return',date=date.today().isoformat(),partner_id=supplier,source_id=identifier,
        lines=[dict(product_id=product,source_line_id=line['id'],qty=1)]))
    store.save_product(dict(sale_price=99999),product)
    returned=TradeDialog(trade.window,'purchase_return',source=store.document(identifier));row=returned.line_rows[0]
    row['qty'].setText('1')
    assert row['sale_price'].text()=='1.00' and row['total'].text()=='0.34'
    assert row['sale_amount'].text()=='1.00' and row['estimated_profit'].text()=='0.66'
    returned.reject()


def test_invalid_or_empty_row_does_not_keep_previous_derived_amounts(desktop):
    _,_,trade,_,_=desktop;row=trade.line_rows[0]
    assert row['sale_amount'].text()!='—'
    row['factor'].setText('0')
    assert all(row[key].text()=='입력 확인' for key in DETAIL_KEYS)
    row['product'].setCurrentIndex(0)
    assert all(row[key].text()=='—' for key in DETAIL_KEYS)


def test_large_detail_numbers_widen_columns_instead_of_clipping(desktop):
    _,_,trade,_,_=desktop;row=trade.line_rows[0]
    trade.purchase_view.set_view('expanded')
    row['qty'].setText('250');row['price'].setText('10000000');row['sale_price'].setText('20000000')
    assert row['sale_amount'].text()=='5,000,000,000.00'
    for key in ('sale_amount','estimated_profit','unit_profit'):
        column=trade.line_columns.index(key)
        assert trade.table.columnWidth(column)>=row[key].fontMetrics().horizontalAdvance(row[key].text())+14


@pytest.mark.parametrize('raw',['not-json','[]','{"mode":"expanded","visible":7}',
    '{"mode":"custom","visible":["product","spec","unknown"]}'])
def test_invalid_saved_column_preferences_fall_back_to_complete_basic_view(desktop,raw):
    _,_,trade,_,_=desktop
    trade.purchase_view.settings.setValue(trade.purchase_view.preference_key,raw)
    other=TradeDialog(trade.window,'purchase')
    assert other.purchase_view.visible_keys()==set(BASIC_COLUMNS)
    other.reject()


def test_purchase_view_does_not_add_detail_columns_to_sale_entry(desktop):
    _,_,trade,_,_=desktop
    sale=TradeDialog(trade.window,'sale')
    assert sale.table.columnCount()==15 and not hasattr(sale,'purchase_view')
    sale.reject()


def test_column_preferences_are_separate_for_each_user(desktop):
    _,store,trade,_,_=desktop
    trade.purchase_view.set_view('expanded');original_key=trade.purchase_view.preference_key
    store.save_user(dict(code='second',name='다른 관리자',role='admin',password='Second-View-2026!'))
    store.login('second','Second-View-2026!')
    other=TradeDialog(trade.window,'purchase')
    assert other.purchase_view.preference_key!=original_key
    assert other.purchase_view.visible_keys()==set(BASIC_COLUMNS)
    other.reject()
    store.login('owner','Owner-Price-2026!')


def test_view_snapshots_and_horizontal_scroll_use_real_popup(desktop):
    import os
    from pathlib import Path
    app,store,trade,_,_=desktop
    before=trade.payload(),store.audit_revision()
    capture=os.environ.get('SY_TEST_CAPTURE_DIR')
    row=trade.line_rows[0];row['qty'].setText('2');trade.table.choose_row(0)
    before=trade.payload(),store.audit_revision()
    for mode in ('compact','expanded'):
        trade.purchase_view.set_view(mode);app.processEvents()
        scroll=trade.table.horizontalScrollBar();scroll.setValue(0)
        if capture:
            target=Path(capture);target.mkdir(parents=True,exist_ok=True)
            trade.grab().save(str(target/('purchase-'+mode+'-left.png')))
        scroll.setValue(scroll.maximum());app.processEvents()
        assert not trade.table.isColumnHidden(trade.line_columns.index('line_memo'))
        if capture:trade.grab().save(str(target/('purchase-'+mode+'-right.png')))
    assert (trade.payload(),store.audit_revision())==before
