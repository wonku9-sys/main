from copy import deepcopy
from datetime import date
from decimal import Decimal
import time
import pytest
from openpyxl import Workbook
from PySide6.QtCore import QCoreApplication,QEvent
from PySide6.QtWidgets import QApplication,QMainWindow,QMessageBox
from pos2.store import Store
from pos2.purchase_import import plan_files
from pos2.purchase_import_ui import PurchaseImportDialog
from pos2.purchase_output import purchase_record,purchase_workbook
from pos2.workflow_ui import TradeDialog


@pytest.fixture
def shop(tmp_path):
    app=QApplication.instance() or QApplication([])
    store=Store(tmp_path/'purchase-import.db');store.setup_admin('owner','관리자','Owner-Password-2026!')
    supplier=store.save_partner(dict(kind='supplier',name='시험 공급사',business_no='123-45-67890'))
    product=store.save_product(dict(name='고기',barcode='0000012345',supplier_id=supplier,base_unit='kg',purchase_price=12000,tax_mode='exempt'))
    unit=store.save_unit(dict(product_id=product,name='박스',barcode='0000099999',factor='5',purchase_price=60000))
    window=QMainWindow();window.store=store;window.notify=lambda *_:None
    yield app,store,supplier,product,unit,window,tmp_path
    for worker in list(getattr(app,'_sy_catalog_workers',[])):worker.wait(10000)
    app.processEvents()
    for widget in app.topLevelWidgets():widget.close();widget.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents();store.close()


def excel(shop,name='one.xlsx',rows=None):
    path=shop[-1]/name;book=Workbook();sheet=book.active
    for row in rows or [['바코드','상품명','수량','매입단가','금액','단위','과면세'],['0000012345','고기','1.250','12000','15000','kg','면']]:sheet.append(row)
    book.save(path);book.close();return path


def plans(shop,paths):
    return plan_files(paths,shop[1].purchase_import_catalog(),shop[2],date.today().isoformat())


def test_multi_file_import_drafts_only_atomic_and_duplicate_retry(shop):
    _,s,_,_,_,_,_=shop
    first=excel(shop);second=excel(shop,'two.xlsx',[['상품명','수량','매입가'],['고기',2,11111.25]])
    files=plans(shop,[first,second]);assert not any(f['error'] for f in files)
    result=s.import_purchase_drafts(files);assert len(result['created'])==2
    assert {d['status'] for d in s.documents()}=={'draft'}
    assert sorted(d['total'] for d in s.documents())==[Decimal('15000'),Decimal('22222.50')]
    assert s.products()[0]['stock_qty']=='0.000' and not s.stock_events()
    assert all(not s.document(i)['payments'] for i in result['created'])
    retry=s.import_purchase_drafts(files);assert not retry['created'] and len(retry['existing'])==2
    assert len(s.documents())==2


def test_own_formatted_xlsx_roundtrip_parties_decimal_and_grams(shop):
    _,s,supplier,product,unit,window,path=shop
    identifier=s.post_document(dict(kind='purchase',partner_id=supplier,date=date.today().isoformat(),lines=[
        dict(product_id=product,qty='125',unit_price='1200',gram_input=True),
        dict(product_id=product,unit_id=unit,qty='2',unit_price='60000')]))
    dialog=TradeDialog(window,'purchase',s.document(identifier));target=path/'formatted.xlsx'
    purchase_workbook(purchase_record(dialog)).save(target)
    files=plans(shop,[target]);assert files[0]['error']=='',files
    assert files[0]['partner_id']==supplier and files[0]['lines'][0]['gram_input']
    assert files[0]['lines'][1]['unit_id']==unit
    result=s.import_purchase_drafts(files);draft=s.document(result['created'][0])
    assert draft['total']==s.document(identifier)['total']
    assert [(l['input_qty'],l['price_basis'],l['unit_name']) for l in draft['lines']]==[('125.000',100,'g'),('2.000',1,'박스')]


@pytest.mark.parametrize('values',[
    ['999','고기',1,12000,12000,'kg','면'],
    ['0000012345','고기',1,12000,12000,'kg','과'],
    ['0000012345','고기',1,12000,11999,'kg','면'],
    ['0000012345','고기',1,12000,12000,'없는단위','면'],
    ['0000012345','고기',-1,12000,12000,'kg','면'],
])
def test_ambiguous_invalid_rows_report_errors_without_writes(shop,values):
    path=excel(shop,rows=[['바코드','상품명','수량','단가','금액','단위','과면세'],values])
    files=plans(shop,[path]);assert files[0]['error']
    with pytest.raises(ValueError):shop[1].import_purchase_drafts(files)
    assert not shop[1].documents()


def test_expanded_barcode_infers_unit_and_fails_if_inactive(shop):
    path=excel(shop,rows=[['바코드','상품명','수량','단가'],['0000099999','고기',2,60000]])
    files=plans(shop,[path]);assert not files[0]['error']
    assert files[0]['lines'][0]['unit_id']==shop[4]
    shop[1].delete_unit(shop[4])
    with pytest.raises(ValueError):shop[1].import_purchase_drafts(files)
    assert not shop[1].documents()


def test_changed_product_or_invalid_second_file_rolls_back_whole_batch(shop):
    _,s,_,product,_,_,_=shop
    files=plans(shop,[excel(shop),excel(shop,'two.xlsx',[['商品','상품명','수량','단가'],['','고기',2,10000]])])
    assert not any(f['error'] for f in files)
    invalid=deepcopy(files);invalid[1]['partner_id']=99999
    with pytest.raises(ValueError):s.import_purchase_drafts(invalid)
    assert not s.documents()
    s.save_product(dict(name='수정된 상품'),product)
    with pytest.raises(ValueError,match='변경'):s.import_purchase_drafts(files)
    assert not s.documents()


def test_live_permission_denial_and_preview_worker_closes_cleanly(shop,monkeypatch):
    app,s,supplier,_,_,window,_=shop
    dialog=PurchaseImportDialog(s,window);dialog.supplier.setCurrentIndex(dialog.supplier.findData(supplier));dialog.show()
    dialog.load_files([excel(shop)])
    assert dialog.worker.isRunning()
    dialog.close();assert dialog.isVisible()
    until=time.monotonic()+10
    while dialog.worker.isRunning() and time.monotonic()<until:app.processEvents();time.sleep(.01)
    app.processEvents();assert dialog.files and not dialog.files[0]['error']
    assert dialog.file_grid.rowCount()==1 and dialog.line_grid.rowCount()==1
    assert not s.documents()
    monkeypatch.setattr(QMessageBox,'question',lambda *_:QMessageBox.StandardButton.Yes)
    dialog.commit()
    while dialog.worker.isRunning() and time.monotonic()<until:app.processEvents();time.sleep(.01)
    app.processEvents();assert len(s.documents())==1
    dialog.close();assert not dialog.isVisible()
    files=plans(shop,[excel(shop,'new.xlsx',[['상품명','수량','단가'],['고기',3,10]])])
    s.save_user(dict(code='staff',name='직원',password='Staff-Password-2026!',role='staff',permissions=['trade','deny:purchases.create']))
    s.login('staff','Staff-Password-2026!')
    with pytest.raises(PermissionError):s.import_purchase_drafts(files)


def test_legacy_blank_unit_header_filename_metadata_and_100g_basis(shop):
    _,s,supplier,product,_,_,_=shop
    path=excel(shop,'매입전표_시험 공급사_2020-08-14 11-13(20200901).xlsx',[
        ['No','상품명','규격','바코드','수량','','매입금액','매입단가','판매단가','이익율','분류','공급사','현재고'],
        [1,'고기','','0000012345',75000,'g',371400,495.2,2390,79.28,'돈육','상품장 현재 공급사',0]])
    file=plans(shop,[path])[0];assert not file['error'],file
    assert file['date']=='2020-08-14' and file['partner_id']==supplier
    assert file['lines'][0]['gram_input'] and file['lines'][0]['total']=='371400.00'
    assert s.document(s.import_purchase_drafts([file])['created'][0])['total']==Decimal('371400')


def test_barcode_quantity_requires_explicit_price_consent_and_summary_rejected(shop):
    _,s,supplier,_,unit,_,_=shop
    path=excel(shop,'매입전표_시험 공급사_2021-11-05 13-39(20211214).xlsx',[
        ['바코드','수량'],['0000099999',2]])
    assert '단가가 없습니다' in plans(shop,[path])[0]['error']
    file=plan_files([path],s.purchase_import_catalog(),supplier,date.today().isoformat(),True)[0]
    assert not file['error'] and file['lines'][0]['unit_id']==unit and file['lines'][0]['unit_price']=='60000.00'
    assert '현재' in file['price_source']
    path=excel(shop,'summary.xlsx',[['No','공급사','입고일시','매입합계'],[1,'시험 공급사','2020-01-01',12000]])
    assert '상품 상세 없음' in plans(shop,[path])[0]['error']
