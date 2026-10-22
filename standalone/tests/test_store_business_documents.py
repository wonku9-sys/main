"""Certificate-like store fields feed all three papers from saved snapshots."""
from datetime import date

import pytest
from openpyxl import load_workbook
from PySide6.QtCore import QPoint,Qt,QCoreApplication,QEvent,QObject,Signal
from PySide6.QtPdf import QPdfDocument
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QFileDialog,QLabel,QMessageBox

from pos2.app import MainWindow
from pos2.commercial_paper import paper_document,paper_html,supplier_summary
from pos2.offline_ui import SalesFormDialog
from pos2.paper_output_ui import output_paper
from pos2.store import Store

IDENTITY=dict(store_name='검증 상점',business_no='123-45-67890',representative='테스트 대표',
              business_type='도매,소매',business_category='식료품 판매',phone='041-555-0123',address='가상시 검증로 123 상가 201호',
              account='999-000-123',store_memo='방문해 주셔서 감사합니다.')
CHANGED=dict(store_name='새로운 매장',business_no='987-65-43210',representative='변경 담당',
             business_type='서비스',business_category='생활용품',phone='02-777-5678',address='별도시 변경길 456',
             account='111-222-333',store_memo='변경된 매장 안내')


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
    for left,right in [('business_no','representative'),('business_type','business_category'),('account','phone')]:
        assert page.fields[left].mapTo(page,QPoint()).y()==page.fields[right].mapTo(page,QPoint()).y()
    assert page.fields['address'].width()==page.fields['store_name'].width()>page.fields['business_no'].width()
    assert page.business_registration.findChild(QLabel,'businessLabel_business_category').text()=='종목'
    for key,value in CHANGED.items():page.fields[key].setText(value)
    page.save()
    assert {key:store.store_profile()[key] for key in CHANGED}==CHANGED
    assert store.store_profile()['bank']=='검증 은행' and store.store_profile()['account']==CHANGED['account']
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
    assert '업태 / 종목' in paper_html(record,title)
    editor=SalesFormDialog(window,key,record);assert_identity(editor.supplier_info.text())
    assert editor.supplier_info.textFormat()==Qt.TextFormat.PlainText
    editor.close();editor.deleteLater();app.processEvents()

    pdf=tmp/(key+'.pdf');monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *_:(str(pdf),'PDF'))
    output_paper(store,identifier,title,window,'pdf');assert pdf.read_bytes().startswith(b'%PDF')
    reader=QPdfDocument(app);assert reader.load(str(pdf))==QPdfDocument.Error.None_
    # Loading may complete asynchronously on the native Windows PDF backend.
    for _ in range(200):
        if reader.status() in (QPdfDocument.Status.Ready,QPdfDocument.Status.Error):break
        QTest.qWait(10)
    assert reader.status()==QPdfDocument.Status.Ready and reader.pageCount()>0,(reader.status(),reader.error(),reader.pageCount())
    text='\n'.join(reader.getAllText(i).text() for i in range(reader.pageCount()))
    import os,shutil
    from pathlib import Path
    if os.environ.get('SY_TEST_CAPTURE_DIR'):
        captures=Path(os.environ['SY_TEST_CAPTURE_DIR']);captures.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(pdf,captures/pdf.name)
        reader.render(0,__import__('PySide6.QtCore',fromlist=['QSize']).QSize(794,1123)).save(str(captures/(key+'-render.png')))
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
    assert '대표자명:' in supplier_summary(record['seller']) and '종목:' in supplier_summary(record['seller'])
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


@pytest.mark.parametrize('key',['settings','store_profile'])
def test_requested_registration_rows_labels_and_tab_order(shop,key):
    app,store,window,_,_,_=shop;window.open_page(key);page=window.current_page;app.processEvents()
    panel=page.business_registration if key=='settings' else page.registration
    grid=panel.layout()
    expected=(('store_name','상호',0,0,3),('business_no','사업자등록번호',1,0,1),
              ('representative','대표자명',1,2,1),('address','주소',2,0,3),
              ('business_type','업태',3,0,1),('business_category','종목',3,2,1),
              ('account','입금하실 계좌',4,0,1),('phone','연락처',4,2,1),('store_memo','메모',5,0,3))
    for field,label,row,column,span in expected:
        entry=page.fields[field]
        caption=panel.findChild(QLabel,'businessLabel_'+field)
        assert caption.text()==label and caption.buddy() is entry
        assert grid.getItemPosition(grid.indexOf(entry))==(row,column+1,1,span)
        assert entry.accessibleName()==label
    order=[item[0] for item in expected]
    for first,second in zip(order,order[1:]):
        page.fields[first].setFocus()
        QTest.keyClick(page.fields[first],Qt.Key.Key_Tab)
        assert app.focusWidget() is page.fields[second]
    # The requested account input occurs once, not again in a duplicate bank section.
    assert len(panel.findChildren(type(page.fields['account']),'',Qt.FindChildOption.FindDirectChildrenOnly))>=9
    assert sum(1 for entry in page.findChildren(type(page.fields['account'])) if entry.accessibleName()=='입금하실 계좌')==1
    import os
    from pathlib import Path
    if os.environ.get('SY_TEST_CAPTURE_DIR'):
        captures=Path(os.environ['SY_TEST_CAPTURE_DIR']);captures.mkdir(parents=True,exist_ok=True)
        panel.grab().save(str(captures/(key+'-registration.png')))


def test_store_memo_roundtrip_backup_and_legacy_paper_fallback(shop):
    _,store,_,_,_,tmp=shop
    memo='<안내> & 문의 "환영"'
    store.save_settings({'store_memo':memo})
    record=store.sales_form(store.save_sales_form('quotation',form_data(shop,'quotation')))
    assert record['seller']['store_memo']==memo
    assert '&lt;안내&gt; &amp; 문의 &quot;환영&quot;' in paper_html(record,'견적서')
    before=store.audit_revision()
    with pytest.raises(ValueError):store.save_settings({'store_memo':'가'*501})
    assert store.store_profile()['store_memo']==memo and store.audit_revision()==before
    backup=store.backup(tmp/'profile-backup.db')
    copy=Store(backup)
    try:
        copy.login('owner','Business-Papers-2026!')
        assert copy.store_profile()['store_memo']==memo
    finally:copy.close()
    # Existing issued records have no new memo key and must remain printable.
    record['seller'].pop('store_memo')
    assert '매장 메모' in paper_html(record,'견적서')
    assert memo not in paper_document(record,'견적서').toPlainText()
