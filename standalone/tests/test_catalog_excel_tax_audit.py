"""Synthetic Excel only: no uploaded catalogue, supplier or price bytes shipped."""
from decimal import Decimal
import json
import struct
import pytest
from openpyxl import Workbook
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from pos2.catalog_import import read_excel,plan_excel,suggest_tax
from pos2.catalog_defaults import suggest_category
from pos2.store import Store


@pytest.fixture
def shop(tmp_path):
    store=Store(tmp_path/'catalog.db');store.setup_admin('owner','관리자','Owner-Password-2026!')
    yield store
    store.close()


@pytest.fixture
def app():return QApplication.instance() or QApplication([])


def row(name='청양고추',barcode='00001234',**extra):
    return dict(name=name,barcode=barcode,supplier_name='테스트 공급사',category='야채',category_mid='야채',category_small='고추류',base_unit='g',price_basis=100,purchase_price='300.25',sale_price='500.50',tax_mode='exempt',source_row=2,**extra)


def test_raw_biff2_cp949_and_nonstandard_large_row_supported(tmp_path):
    def record(kind,data):return struct.pack('<HH',kind,len(data))+data
    def label(r,c,value):
        encoded=value.encode('cp949');return record(4,struct.pack('<HH3sB',r,c,bytes(3),len(encoded))+encoded)
    payload=record(9,struct.pack('<HH',2,16))
    for c,name in enumerate(['번호','상품명','규격','바코드','매입가','판매가']):payload+=label(0,c,name)
    payload+=label(20000,1,'생삼겹살')+label(20000,3,'00009999')+label(20000,4,'100.25')+label(20000,5,'200.50')+record(10,b'')
    source=tmp_path/'synthetic.xls';source.write_bytes(payload);rows=read_excel(source)
    assert len(rows)==20001 and rows[20000][3]=='00009999'
    plan=plan_excel(source);assert len(plan['rows'])==1 and plan['rows'][0]['tax_mode']=='exempt'
    source.write_bytes(payload[:-2])
    with pytest.raises(ValueError):read_excel(source)


def test_xlsx_recommendations_stats_exclusion_and_explicit_tax_override(tmp_path):
    book=Workbook();sheet=book.active;sheet.append(['번호','상품명','바코드','매입가','판매가','과면세'])
    sheet.append([1,'밀가루','00000001',10.25,20.50,'']);sheet.append([2,'양념갈비','00000002',100,200,''])
    sheet.append([3,'특수 품목','00000003',0,0,'면세']);sheet.append(['','합계','',100,200,''])
    source=tmp_path/'test.xlsx';book.save(source);plan=plan_excel(source);assert len(plan['rows'])==3 and plan['skipped']==1
    assert [r['tax_mode'] for r in plan['rows']]==['exempt','taxable','exempt']
    assert plan['rows'][0]['barcode']=='00000001' and plan['rows'][2]['tax_source']=='원본'
    assert suggest_tax('냉동 고등어',suggest_category('냉동 고등어'))=='exempt'
    assert suggest_tax('볶은 참깨',suggest_category('볶은 참깨'))=='taxable'
    assert suggest_tax('확인 어려운 상품',suggest_category('확인 어려운 상품')) is None


def test_catalog_import_create_only_backup_decimal_idempotence_and_no_stock(shop):
    existing=shop.save_product(dict(name='기존 상품',barcode='00009999',purchase_price='10.99',sale_price='20.99'))
    before=shop.products()[0].copy();records=[row(),row(name='중복 기존',barcode='00009999')]
    result=shop.import_catalog(records);assert result['created']==1 and result['skipped']==1 and result['backup']
    assert shop.inspect_backup(result['backup'])['counts']['products']==1
    products=shop.products();saved=next(p for p in products if p['barcode']=='00001234')
    assert saved['purchase_price']==Decimal('300.25') and saved['stock_qty']=='0.000'
    assert next(p for p in products if p['id']==existing)==before
    assert shop.import_catalog(records)['created']==0 and not shop.documents()
    assert any(c['path']==['야채','야채','고추류'] for c in shop.categories())


def test_failed_batch_rolls_back_every_product_supplier_and_audit(shop):
    before=(len(shop.products()),len(shop.partners('supplier')),len(shop.audit_log()))
    good=row();bad=row(name='잘못된 단가',barcode='00009998');bad['sale_price']='-1'
    with pytest.raises(ValueError):shop.import_catalog([good,bad])
    assert (len(shop.products()),len(shop.partners('supplier')),len(shop.audit_log()))==before
    unknown=row();unknown['tax_mode']=None
    with pytest.raises(ValueError,match='과세'):shop.import_catalog([unknown])


def test_tax_tree_member_tab_modeless_and_structured_change_columns(shop,app):
    from types import SimpleNamespace
    from pos2.catalog_ui import ProductsPage,ProductDialog
    shop.seed_catalog_categories();assert shop.seed_catalog_categories()==0
    product=shop.save_product(dict(name='시험 상품',barcode='00000001',base_unit='개',purchase_price='100.25',sale_price='200.50',tax_mode='exempt',category='야채',category_mid='야채',category_small='고추류'))
    page=ProductsPage(SimpleNamespace(store=shop));page.show();app.processEvents();page.set_tree_path(('야채','야채','고추류'));assert page.grid.rowCount()==1
    assert page.grid.item(0,14).text()=='면 · 면세' and not page.grid.item(0,1).icon().isNull()
    assert not page.grid.verticalHeader().isHidden();page.grid.selectRow(0);page.grid.setCurrentCell(0,0)
    dialog=page.edit();assert dialog and not dialog.isModal();assert page.edit() is dialog
    assert [dialog.tabs.tabText(i) for i in range(6)]==['상품정보','매입정보','판매정보','재고정보','변경로그','회원지정가']
    dialog.tax_mode.setCurrentIndex(dialog.tax_mode.findData('taxable'));assert dialog.tax_badge.text()=='과 · 과세'
    assert dialog.tax_badge.styleSheet()!=page.grid.item(0,14).background().color().name()
    dialog.tax_mode.setCurrentIndex(dialog.tax_mode.findData('exempt'))
    dialog.sale_price.setText('250.75');dialog.save(False)
    assert [dialog.audit_table.horizontalHeaderItem(i).text() for i in range(7)]==['변경내용','변경전','변경후','변경차','비율(%)','변경일시','변경사용자']
    index=next(i for i in range(dialog.audit_table.rowCount()) if dialog.audit_table.item(i,0).text()=='판매단가')
    assert dialog.audit_table.item(index,3).data(Qt.ItemDataRole.UserRole+1)==Decimal('50.25')
    assert dialog.audit_table.item(index,6).text()=='관리자'
    page.set_tree_path(('비식품','제지류','기저귀'));assert page.grid.rowCount()==0 and page.category_path_label.text()=='비식품 / 제지류 / 기저귀'
    dialog.close();page.close()


def test_audit_zero_baseline_and_text_no_fabricated_ratio():
    from pos2.catalog_audit import audit_rows
    records=[dict(action='update',at='2026-10-20',user_name='담당자',detail=json.dumps(dict(changes=dict(sale_price=dict(old='0.00',new='10.25'),tax_mode=dict(old='exempt',new='taxable')))))]
    rows=audit_rows(records,{})
    assert rows[0][3]==Decimal('10.25') and rows[0][4]=='— (기준 0)'
    assert rows[1][1:5]==['면 · 면세','과 · 과세','—','—']


def test_background_import_uses_separate_connection_and_member_price_scope(shop,app):
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QWidget
    from pos2.catalog_import_ui import CatalogWorker
    parent=QWidget();context=(shop.path,dict(shop.actor),shop._session_password_hash,shop._restore_token)
    worker=CatalogWorker(parent,context=context,rows=[row()]);results=[];errors=[];worker.result.connect(results.append);worker.failed.connect(errors.append);worker.start()
    for _ in range(300):
        app.processEvents()
        if not worker.isRunning():break
        QTest.qWait(10)
    assert worker.wait(1000);app.processEvents();assert not errors and results[0]['created']==1
    product=shop.products()[0]['id'];member=shop.save_member(dict(name='테스트 회원',code='M001'))
    shop.save_member_price(dict(member_id=member,product_id=product,price='123.45'))
    assert shop.product_member_prices(product)[0]['price']==Decimal('123.45')
    shop.save_user(dict(code='catalog',name='상품 담당',password='Catalog-Password-2026!',role='staff',permissions=['catalog','deny:products.create']))
    shop.login('catalog','Catalog-Password-2026!')
    with pytest.raises(PermissionError):shop.product_member_prices(product)
    with pytest.raises(PermissionError):shop.import_catalog([row()])


def test_preview_selected_tax_updates_original_plan_not_qt_copy(shop,app):
    from pos2.catalog_import_ui import CatalogImportDialog
    record=row(name='확인 필요 품목');record.update(specification='',tax_mode=None,tax_source='확인 필요',category_source='추천',error='')
    dialog=CatalogImportDialog(shop);dialog.loaded(dict(rows=[record],skipped=0));dialog.grid.selectRow(0);dialog.tax.setCurrentIndex(dialog.tax.findData('taxable'));dialog.apply_tax(False)
    assert record['tax_mode']=='taxable' and record['tax_source']=='직접 확인'
    assert dialog.commit_button.isEnabled();dialog.close()
