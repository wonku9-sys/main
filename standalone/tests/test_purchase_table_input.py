"""Synthetic tables only: no uploaded customer data or database fixtures."""
import csv
from copy import deepcopy
from decimal import Decimal
from io import StringIO
import struct

import pytest
from openpyxl import Workbook
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from test_purchase_import import shop
from pos2.catalog_import import read_excel, PURCHASE_FILE_FILTER
from pos2.purchase_import import plan_files, plan_table
from pos2.purchase_clipboard import PurchasePasteDialog, paste_purchase
from pos2.workflow_ui import TradeDialog


HEADERS=['No','상품명','규격','바코드','매입량','단위','입수량','총수량',
         '매입금액','매입단가','판매단가','이익율(%)','분류','공급사','현재고','메모']


def sample_table():
    return [HEADERS, ['1','고기','','0000012345','125','g','1','125','1500','1200','2500','','','상품장 공급사','0','연속 입력'],
            ['2','','','','0','개','','0','0','0','0','','','','','']]


def copied(table):
    stream=StringIO();csv.writer(stream,delimiter='\t').writerows(table)
    return stream.getvalue()


def save_table(path,rows):
    suffix=path.suffix.lower()
    if suffix in {'.xlsx','.xlsm','.xltx','.xltm'}:
        book=Workbook()
        for row in rows:book.active.append(row)
        book.save(path);book.close()
    elif suffix in {'.xls','.xlt'}:
        # A genuine BIFF2 value stream, rather than CSV renamed as XLS.
        records=[b'\x09\x00\x04\x00\x02\x00\x10\x00']
        for r,row in enumerate(rows):
            for c,value in enumerate(row):
                raw=str(value).encode('cp949')
                data=struct.pack('<HH',r,c)+b'\0\0\0'+bytes([len(raw)])+raw
                records.append(struct.pack('<HH',4,len(data))+data)
        path.write_bytes(b''.join(records)+struct.pack('<HH',10,0))
    else:
        delimiter='\t' if suffix in {'.tsv','.txt'} else ','
        with path.open('w',encoding='utf-8-sig',newline='') as stream:
            csv.writer(stream,delimiter=delimiter).writerows(rows)


@pytest.mark.parametrize('extension',['xls','xlsx','xlsm','xlt','xltx','xltm','csv','tsv','txt'])
def test_nine_file_formats_draft_review_preserves_units_prices_and_filename_time(shop,extension):
    _,store,supplier,product,_,host,path=shop
    source=path/f'매입전표_시험 공급사_2020-08-14 11-13(20200901).{extension}'
    save_table(source,sample_table())
    assert '.'+extension in PURCHASE_FILE_FILTER
    file=plan_files([source],store.purchase_import_catalog(),None,'2026-01-01')[0]
    assert not file['error'],file
    assert file['date']=='2020-08-14' and file['entry_datetime']=='2020-08-14 11:13:00'
    assert file['partner_id']==supplier and len(file['lines'])==1
    line=file['lines'][0]
    assert line['gram_input'] and Decimal(line['factor_override'])==Decimal('.001')
    assert Decimal(line['sale_price'].replace(',',''))==2500 and line['line_memo']=='연속 입력'
    result=store.import_purchase_drafts([file]);draft=store.document(result['created'][0])
    assert draft['total']==1500 and draft['status']=='draft' and draft['entry']['datetime']=='2020-08-14 11:13:00'
    assert draft['lines'][0]['entry']['sale_price']=='2500.00'
    assert not store.stock_events() and not draft['payments']
    assert store.import_purchase_drafts([file])==dict(created=[],existing=[draft['id']])
    reopened=TradeDialog(host,'purchase',draft)
    assert reopened.payload()['lines'][0]['gram_input']
    store.post_document(reopened.payload(),draft['id'])
    assert store.products()[0]['stock_qty']=='0.125'


@pytest.mark.parametrize('encoding,delimiter',[('cp949',','),('utf-16','\t'),('utf-8-sig',';')])
def test_text_encodings_quoted_commas_and_multiline_memo(shop,encoding,delimiter):
    _,store,supplier,_,_,_,path=shop
    table=sample_table();table[1][-1]='메모, 따옴표 "확인"\n두 번째 줄'
    table[1][8]='1,500'
    source=path/'표.csv'
    with source.open('w',encoding=encoding,newline='') as stream:csv.writer(stream,delimiter=delimiter).writerows(table)
    file=plan_files([source],store.purchase_import_catalog(),supplier,'2026-01-01')[0]
    assert not file['error'],file
    assert file['lines'][0]['line_memo']==table[1][-1]


def test_full_table_ctrl_v_and_context_paste_share_preview_without_posting(shop,monkeypatch):
    app,store,supplier,product,_,host,_=shop
    trade=TradeDialog(host,'purchase');trade.partner.setCurrentIndex(trade.partner.findData(supplier))
    trade.show();app.processEvents()
    previews=[]
    def review(dialog):
        previews.append(dialog);return QDialog.DialogCode.Accepted
    monkeypatch.setattr(PurchasePasteDialog,'exec',review)
    QApplication.clipboard().setText(copied(sample_table()))
    before=store.audit_revision()
    QTest.keyClick(trade.line_rows[0]['barcode'],Qt.Key.Key_V,Qt.KeyboardModifier.ControlModifier)
    assert len(trade.line_rows)==1 and len(previews)==1
    line=trade.payload()['lines'][0]
    assert line['product_id']==product and line['gram_input'] and Decimal(line['factor_override'])==Decimal('.001')
    assert Decimal(line['sale_price'].replace(',',''))==2500 and line['line_memo']=='연속 입력'
    assert trade.purchase_summary['total'].text()=='1,500.00'
    QTest.mouseClick(trade.table.viewport(),Qt.MouseButton.RightButton,pos=QPoint(10,trade.table.viewport().height()-8))
    app.processEvents();menu=trade.table._product_menu
    assert menu.isVisible()
    command=next(a for a in menu.actions() if a.text()=='엑셀 붙여넣기 (Ctrl+V)')
    command.trigger();menu.close()
    assert len(trade.payload()['lines'])==2 and len(previews)==2
    assert store.audit_revision()==before and not store.documents() and not store.stock_events()


@pytest.mark.parametrize('target',['product','qty','barcode','gray'])
def test_real_right_mouse_on_new_empty_voucher_opens_working_korean_menu(shop,monkeypatch,target):
    app,store,supplier,_,_,host,_=shop
    trade=TradeDialog(host,'purchase');trade.partner.setCurrentIndex(trade.partner.findData(supplier))
    trade.show();app.processEvents()
    field=trade.table.viewport() if target=='gray' else trade.line_rows[0][target]
    point=QPoint(10,field.height()-8)
    QTest.mouseClick(field,Qt.MouseButton.RightButton,pos=point);app.processEvents()
    menu=trade.table._product_menu;assert menu.isVisible()
    commands={a.text():a for a in menu.actions()}
    assert commands['상품검색 (F5)'].isEnabled() and commands['엑셀 붙여넣기 (Ctrl+V)'].isEnabled()
    assert not commands['매입수정 (F6)'].isEnabled()
    menu.close();assert not store.documents()


def test_product_cell_does_not_open_or_cycle_catalogue_but_search_still_applies(shop):
    app,store,_,product,_,host,_=shop
    trade=TradeDialog(host,'purchase');trade.show();app.processEvents()
    field=trade.line_rows[0]['product']
    QTest.mouseClick(field,Qt.MouseButton.LeftButton);app.processEvents()
    assert not field.view().isVisible() and field.currentData() is None
    for key in (Qt.Key.Key_Down,Qt.Key.Key_Up,Qt.Key.Key_Space,Qt.Key.Key_A):QTest.keyClick(field,key)
    assert field.currentData() is None
    trade.apply_picked_products([(trade.product_map[product],None)])
    assert trade.line_rows[0]['product'].currentData()==product
    sales=TradeDialog(host,'sale');assert not sales.line_rows[0]['product'].picker_only


def test_whole_table_cancel_bad_later_row_and_stale_product_are_atomic(shop,monkeypatch):
    _,store,supplier,product,_,host,_=shop
    trade=TradeDialog(host,'purchase');trade.partner.setCurrentIndex(trade.partner.findData(supplier))
    before=trade.payload();warnings=[]
    monkeypatch.setattr('pos2.workflow_ui._warn',lambda _,exc:warnings.append(str(exc)))
    monkeypatch.setattr(PurchasePasteDialog,'exec',lambda _:QDialog.DialogCode.Rejected)
    QApplication.clipboard().setText(copied(sample_table()));paste_purchase(trade)
    assert trade.payload()==before
    bad=sample_table();bad.insert(2,list(bad[1]));bad[2][3]='UNKNOWN'
    QApplication.clipboard().setText(copied(bad));paste_purchase(trade)
    assert trade.payload()==before and '3행' in warnings[-1]
    def change(_):
        store.save_product(dict(name='변경 상품'),product);return QDialog.DialogCode.Accepted
    monkeypatch.setattr(PurchasePasteDialog,'exec',change)
    QApplication.clipboard().setText(copied(sample_table()));paste_purchase(trade)
    assert trade.payload()==before and '변경' in warnings[-1]
    assert not store.documents()


def test_import_and_paste_preserve_exact_total_when_unit_price_was_rounded(shop,monkeypatch):
    _,store,supplier,_,_,host,_=shop
    table=[['상품명','바코드','수량','매입단가','판매단가','매입금액'],['고기','0000012345','3','.33','2','1']]
    file=plan_table(table,store.purchase_import_catalog(),supplier,'2026-01-01')
    assert not file['error'] and Decimal(file['lines'][0]['amount_override'])==1
    trade=TradeDialog(host,'purchase');trade.partner.setCurrentIndex(trade.partner.findData(supplier))
    monkeypatch.setattr(PurchasePasteDialog,'exec',lambda _:QDialog.DialogCode.Accepted)
    QApplication.clipboard().setText(copied(table));paste_purchase(trade)
    assert trade.purchase_summary['total'].text()=='1.00'
    assert Decimal(trade.payload()['lines'][0]['amount_override'])==1
    identifier=store.post_document(trade.payload())
    assert store.document(identifier)['total']==1


def test_factor_override_and_total_quantity_are_validated(shop):
    _,store,supplier,_,unit,_,_=shop
    table=[['상품명','바코드','수량','단위','입수량','총수량','매입단가'],['고기','0000099999','2','박스','4','8','60000']]
    result=plan_table(table,store.purchase_import_catalog(),supplier,'2026-01-01')
    assert not result['error'] and result['lines'][0]['unit_id']==unit and Decimal(result['lines'][0]['factor_override'])==4
    table[1][5]='10'
    assert '총수량' in plan_table(table,store.purchase_import_catalog(),supplier,'2026-01-01')['error']


def test_unknown_format_invalid_numbers_and_uncached_formula_are_not_imported(shop):
    _,store,supplier,_,_,_,path=shop
    bad=path/'unsupported.xlsb';bad.write_bytes(b'not an Excel file')
    assert 'XLSB' in plan_files([bad],store.purchase_import_catalog(),supplier,'2026-01-01')[0]['error']
    for field,value in [(4,'NaN'),(6,'NaN'),(7,'Infinity'),(8,'-1'),(10,'=1+1')]:
        table=deepcopy(sample_table());table[1][field]=value
        assert plan_table(table,store.purchase_import_catalog(),supplier,'2026-01-01')['error']
    table=sample_table();table[1][9]='=1200'
    source=path/'formula.xlsx';save_table(source,table)
    assert read_excel(source)[1][9]==''
    assert plan_files([source],store.purchase_import_catalog(),supplier,'2026-01-01')[0]['error']
    assert not store.documents()
