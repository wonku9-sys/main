"""Real selected-voucher XLSX/PDF, numeric values and output access checks."""
from datetime import date
from decimal import Decimal
from pathlib import Path
import pytest
from openpyxl import load_workbook
from PySide6.QtCore import QObject,Signal,QCoreApplication,QEvent
from PySide6.QtWidgets import QApplication,QMainWindow,QFileDialog,QMessageBox
from pos2.store import Store
from pos2.workflow_ui import TradeDialog
from pos2 import purchase_output as output


@pytest.fixture
def shop(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    store=Store(tmp_path/'purchase-output.db');store.setup_admin('owner','관리자','Owner-Password-2026!')
    store.save_settings(dict(store_name='SY 테스트점',business_no='198-85-00963',representative='점포대표',address='점포 주소',business_type='소매',business_category='슈퍼마켓'))
    supplier=store.save_partner(dict(kind='supplier',name='원물 공급사',business_no='123-45-67890',representative='공급대표',address='공급사 주소',business_type='도매',business_item='농산물',phone='010-0000-0000'))
    product=store.save_product(dict(name='원래 상품 <특품>',barcode='0000012345',specification='500g',base_unit='kg',tax_mode='exempt',purchase_price='123.45'))
    def post(qty='1.25',memo='전표 하나'):
        return store.post_document(dict(kind='purchase',date=date.today().isoformat(),partner_id=supplier,lines=[dict(product_id=product,qty=qty,unit_price='123.45')],memo=memo))
    first=post();second=post('2','다른 전표 비밀')
    window=QMainWindow();window.store=store;window.notify=lambda *_:None
    dialog=TradeDialog(window,'purchase',first)
    monkeypatch.setattr(QMessageBox,'warning',lambda *_:QMessageBox.StandardButton.Ok)
    yield app,store,dialog,product,first,second,tmp_path
    for widget in app.topLevelWidgets():widget.close();widget.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents();store.close()


def test_saved_form_uses_selected_document_and_not_changed_catalog_prices(shop):
    _,store,dialog,product,first,second,_=shop
    store.save_product(dict(name='바뀐 상품',purchase_price='99999',tax_mode='taxable'),product)
    record=output.purchase_record(dialog)
    assert record['id']==first and record['number']!=store.document(second)['number']
    assert record['supplier']['name']=='원물 공급사' and record['recipient']['store_name']=='SY 테스트점'
    line=record['lines'][0]
    assert line['product_name']=='원래 상품 <특품>' and line['tax_mode']=='exempt'
    assert line['unit_price']==Decimal('123.45') and line['qty']==Decimal('1.25') and line['total']==Decimal('154.31')
    html=output.purchase_html(record)
    assert '&lt;특품&gt;' in html and '<특품>' not in html and '다른 전표 비밀' not in html
    assert '공 급 자' in html and '공 급 받 는 자' in html
    assert output.purchase_document(record).pageCount()==1


def test_real_form_xlsx_and_pdf_include_parties_and_numeric_lines(shop,monkeypatch):
    _,store,dialog,_,first,_,tmp=shop
    before=store.audit_revision()
    monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *_:(str(tmp/'매입.xlsx'),''))
    assert dialog.export_document()==tmp/'매입.xlsx'
    book=load_workbook(tmp/'매입.xlsx');sheet=book.active
    assert sheet['A1'].value=='매 입 전 표' and 'A1:J1' in sheet.merged_cells
    assert sheet['B4'].value=='123-45-67890' and sheet['G4'].value=='198-85-00963'
    assert sheet['B5'].value=='원물 공급사' and sheet['G5'].value=='SY 테스트점'
    assert sheet['B12'].value=='0000012345' and sheet['B12'].data_type=='s'
    assert [sheet[c].value for c in ('G12','H12','I12')]==[1.25,123.45,154.31]
    assert sheet['I12'].number_format=='#,##0.00' and sheet['A11'].fill.fgColor.rgb.endswith('E3E3E3')
    assert sheet.print_title_rows=='$1:$11' and str(sheet.page_setup.paperSize)==sheet.PAPERSIZE_A4
    assert sheet.page_setup.fitToWidth==1 and sheet.page_setup.fitToHeight==0
    book.close()
    monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *_:(str(tmp/'매입.pdf'),''))
    assert dialog.purchase_output('pdf')==tmp/'매입.pdf'
    assert (tmp/'매입.pdf').read_bytes().startswith(b'%PDF')
    assert store.audit_revision()==before and store.document(first)['total']==Decimal('154.31')


def test_formula_strings_are_text_and_mixed_quantities_not_summed(shop):
    record=output.purchase_record(shop[2]);record['supplier']['name']='=1+1';record['memo']='=HYPERLINK("bad")'
    record['lines'][0]['product_name']='=1+1'
    record['lines'].append({**record['lines'][0],'unit_name':'개','qty':Decimal('2')})
    sheet=output.purchase_workbook(record).active
    assert sheet['B5'].data_type=='s' and sheet['C12'].data_type=='s'
    assert '1.25 kg' in output.quantity_text(record) and '2 개' in output.quantity_text(record)
    assert not any(c.data_type=='f' for row in sheet for c in row)
    record['lines'][0]['qty']=Decimal('0.125');assert '<td>0.125</td>' in output.purchase_html(record)


def test_long_voucher_repeats_headers_and_cancelled_mark_is_visible(shop):
    record=output.purchase_record(shop[2]);record['lines']=[dict(record['lines'][0]) for _ in range(40)]
    record['status']='cancelled'
    html=output.purchase_html(record)
    assert html.count('공 급 자')==3 and html.count('유효 거래로 사용하지 마세요')==3
    assert output.purchase_document(record).pageCount()==3


def test_both_print_choices_render_and_refresh_during_preview(shop,monkeypatch):
    _,_,dialog,_,_,_,_=shop;printed=[]
    class Preview(QObject):
        paintRequested=Signal(object)
        def __init__(self,printer,parent):super().__init__();self.printer=printer
        def setWindowTitle(self,title):printed.append(title)
        def resize(self,*_):pass
        def reject(self):printed.append('rejected')
        def exec(self):self.paintRequested.emit(self.printer)
    monkeypatch.setattr(output,'QPrintPreviewDialog',Preview)
    monkeypatch.setattr(output.QTextDocument,'print_',lambda *_:printed.append('painted'))
    choices=dialog.print_menu.actions();assert len(choices)==3
    assert choices[2].text()=='PDF 저장'
    choices[0].trigger();choices[1].trigger()
    assert sum(x=='painted' for x in printed)==2
    assert any('인쇄그리드' in x for x in printed) and any('프린터 양식' in x for x in printed)


@pytest.mark.parametrize('mode',('xlsx','pdf'))
def test_revocation_in_save_dialog_does_not_replace_existing_file(shop,monkeypatch,mode):
    _,store,dialog,_,_,_,tmp=shop
    user=store.save_user(dict(code='staff',name='직원',role='staff',password='Staff-Password-2026!',permissions=['trade']))
    staff=Store(store.path);staff.login('staff','Staff-Password-2026!');dialog.store=staff
    target=tmp/('kept.'+mode);target.write_bytes(b'original')
    def choose(*_):store.save_user(dict(permissions=[]),user);return str(target),''
    monkeypatch.setattr(QFileDialog,'getSaveFileName',choose)
    try:assert dialog.purchase_output(mode) is None
    finally:staff.close()
    assert target.read_bytes()==b'original'
