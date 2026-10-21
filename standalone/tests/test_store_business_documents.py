"""Certificate-like store fields feed all three papers from saved snapshots."""
from datetime import date

import pytest
from openpyxl import load_workbook
from PySide6.QtCore import QPoint,Qt,QCoreApplication,QEvent,QObject,Signal
from PySide6.QtPdf import QPdfDocument
from PySide6.QtWidgets import QApplication,QFileDialog,QLabel,QMessageBox

from pos2.app import MainWindow
from pos2.commercial_paper import paper_document,paper_html,supplier_summary
from pos2.offline_ui import SalesFormDialog
from pos2.paper_output_ui import output_paper
from pos2.store import Store

IDENTITY=dict(store_name='검증 상점',business_no='123-45-67890',representative='테스트 대표',
              business_type='도매,소매',business_category='식료품 판매',phone='041-555-0123',address='가상시 검증로 123 상가 201호')
CHANGED=dict(store_name='새로운 매장',business_no='987-65-43210',representative='변경 담당',
             business_type='서비스',business_category='생활용품',phone='02-777-5678',address='별도시 변경길 456')


@pytest.fixture
def shop(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    from pos2.popup_policy import install_popup_policy
    install_popup_policy(app)
    store=Store(tmp_path/'business-documents.db');store.setup_admin('owner','관리자','Business-Papers-2026!')
    store.save_settings(dict(IDENTITY,bank='검증 은행',account='999-000-123',account_holder='검증 예금주',fax='041-555-9999',store_email='shop@example.invalid'))
    customer=store.save_partner(dict(kind='customer',name='검증 거래처'))
    product=store.save_product(dict(name='검증 상품',base_unit='개',tracked=False,tax_mode='taxable'))
    window=MainWindow(store);window.show();app.processEvents()
    monkeypatch.setattr(window,'notify',lambda *_:None)
    monkeypatch.setattr('pos2.navigation.ask_unsaved',lambda *_:QMessageBox.StandardButton.Discard)
    yield app,store,window,customer,product,tmp_path
    window.navigation.suspended=True;window.navigation.disable()
    for widget in app.topLevelWidgets():widget.close();widget.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents();store.close()


def form_data(shop,kind):
    _,store,_,customer,product,_=shop
    data=dict(date=date.today().isoformat(),partner_id=customer,lines=[dict(product_id=product,qty='2',unit_price='1100')])
    if kind=='statement':
        sale=store.post_document(dict(data,kind='sale'))
        return dict(date=data['date'],source_ids=[sale])
    if kind=='order':data['order']=dict(delivery_date=data['date'])
    return data


def assert_identity(text,values=IDENTITY):
    compact=''.join(text.split())
    for value in values.values():assert ''.join(value.split()) in compact,value


def test_settings_certificate_fields_share_profile_and_keep_optional_accounts(shop):
    app,store,window,_,_,_=shop;window.open_page('settings');page=window.current_page;app.processEvents()
    for key,value in IDENTITY.items():assert page.fields[key].text()==value
    for left,right in [('store_name','business_type'),('business_no','business_category'),('representative','phone')]:
        assert page.fields[left].mapTo(page,QPoint()).y()==page.fields[right].mapTo(page,QPoint()).y()
    assert page.fields['address'].width()>page.fields['store_name'].width()
    assert page.business_registration.findChild(QLabel,'businessLabel_business_category').text()=='업종'
    for key,value in CHANGED.items():page.fields[key].setText(value)
    page.save()
    assert {key:store.store_profile()[key] for key in CHANGED}==CHANGED
    assert store.store_profile()['bank']=='검증 은행' and store.store_profile()['account']=='999-000-123'
    assert store.store_profile()['fax']=='041-555-9999' and store.store_profile()['store_email']=='shop@example.invalid'
    window.open_page('store_profile');profile=window.current_page
    assert profile.title=='점포 등록정보'
    for key,value in CHANGED.items():assert profile.fields[key].text()==value
    profile.fields['business_category'].setText('추가 업종');assert profile.save()
    window.open_page('settings');assert window.current_page.fields['business_category'].text()=='추가 업종'
    other=Store(store.path)
    try:
        other.login('owner','Business-Papers-2026!')
        assert other.store_profile()['representative']==CHANGED['representative']
        assert other.store_profile()['business_category']=='추가 업종'
    finally:other.close()


def test_unsaved_certificate_edits_do_not_reach_new_papers(shop):
    _,store,window,_,_,_=shop;window.open_page('settings');page=window.current_page
    for key,value in CHANGED.items():page.fields[key].setText(value)
    record=store.sales_form(store.save_sales_form('quotation',form_data(shop,'quotation')))
    assert {key:record['seller'][key] for key in IDENTITY}==IDENTITY


@pytest.mark.parametrize('kind,key,title',[('quotation','quotations','견적서'),('statement','statements','거래명세서'),('order','orders','주문서')])
def test_all_seven_fields_in_dialog_real_pdf_png_print_and_excel_keep_issued_snapshot(shop,monkeypatch,kind,key,title):
    app,store,window,_,_,tmp=shop
    window.open_page('settings')
    for field,value in IDENTITY.items():window.current_page.fields[field].setText(value)
    window.current_page.save()
    data=form_data(shop,kind);count=len(store.documents());identifier=store.save_sales_form(kind,data)
    assert len(store.documents())==count
    record=store.sales_form(identifier);assert {field:record['seller'][field] for field in IDENTITY}==IDENTITY
    store.save_settings(CHANGED)
    assert_identity(paper_document(record,title).toPlainText())
    assert '업태 / 업종' in paper_html(record,title)
    editor=SalesFormDialog(window,key,record);assert_identity(editor.supplier_info.text())
    assert editor.supplier_info.textFormat()==Qt.TextFormat.PlainText
    editor.close();editor.deleteLater();app.processEvents()

    pdf=tmp/(key+'.pdf');monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *_:(str(pdf),'PDF'))
    output_paper(store,identifier,title,window,'pdf');assert pdf.read_bytes().startswith(b'%PDF')
    reader=QPdfDocument(app);assert reader.load(str(pdf))==QPdfDocument.Error.None_
    text='\n'.join(reader.getAllText(i).text() for i in range(reader.pageCount()))
    assert_identity(text);reader.close();reader.deleteLater()

    png=tmp/(key+'.png');monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *_:(str(png),'PNG'))
    paths=output_paper(store,identifier,title,window,'image')
    assert len(paths)==1 and png.read_bytes().startswith(b'\x89PNG')

    painted=[]
    class Preview(QObject):
        paintRequested=Signal(object)
        def __init__(self,printer,parent):super().__init__();self.printer=printer
        def setWindowTitle(self,_):pass
        def resize(self,*_):pass
        def exec(self):self.paintRequested.emit(self.printer)
        def reject(self):pass
    monkeypatch.setattr('pos2.paper_output_ui.QPrintPreviewDialog',Preview)
    monkeypatch.setattr('pos2.commercial_paper.QTextDocument.print_',lambda doc,_:painted.append(doc.toPlainText()))
    output_paper(store,identifier,title,window,'preview');assert len(painted)==1;assert_identity(painted[0])

    window.open_page(key);page=window.current_page;page.grid.selectRow(0)
    selected,info=page.output_data();assert selected['id']==identifier;assert_identity(info)
    xlsx=tmp/(key+'.xlsx');monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *_:(str(xlsx),'XLSX'))
    page.export_paper();book=load_workbook(xlsx)
    try:assert_identity('\n'.join(str(cell.value or '') for row in book.active for cell in row))
    finally:book.close()
    assert {field:store.sales_form(identifier)['seller'][field] for field in IDENTITY}==IDENTITY
    edited=dict(data,memo='메모만 정정',_expected_token=store.sales_form(identifier).get('_edit_token'))
    store.save_sales_form(kind,edited,identifier)
    assert {field:store.sales_form(identifier)['seller'][field] for field in IDENTITY}==IDENTITY
    fresh=store.sales_form(store.save_sales_form(kind,form_data(shop,kind)))
    assert {field:fresh['seller'][field] for field in CHANGED}==CHANGED


def test_missing_optional_identity_stays_compatible_and_html_is_escaped(shop):
    _,store,window,_,_,_=shop
    store.save_settings({key:'' for key in IDENTITY if key!='store_name'})
    store.save_settings({'store_name':'<b>검증 & 상점</b>'})
    record=store.sales_form(store.save_sales_form('quotation',form_data(shop,'quotation')))
    html=paper_html(record,'견적서');assert '&lt;b&gt;검증 &amp; 상점&lt;/b&gt;' in html
    editor=SalesFormDialog(window,'quotations',record)
    assert editor.supplier_info.textFormat()==Qt.TextFormat.PlainText
    assert '<b>검증 & 상점</b>' in editor.supplier_info.text()
    assert '대표자명:' in supplier_summary(record['seller']) and '업종:' in supplier_summary(record['seller'])
    editor.close();editor.deleteLater()


def test_new_editor_refreshes_supplier_from_the_snapshot_actually_saved(shop):
    _,store,window,_,product,_=shop
    editor=SalesFormDialog(window,'quotations');assert_identity(editor.supplier_info.text())
    store.save_settings(CHANGED)
    editor.rows[0]['product'].setCurrentIndex(editor.rows[0]['product'].findData(product))
    editor.rows[0]['qty'].setText('1');editor.rows[0]['price'].setText('1100')
    assert editor.save(False)
    assert_identity(editor.supplier_info.text(),CHANGED)
    assert {field:editor.record['seller'][field] for field in CHANGED}==CHANGED
    editor.close();editor.deleteLater()
