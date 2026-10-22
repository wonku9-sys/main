from datetime import date,timedelta
from decimal import Decimal
import hashlib
import sqlite3
import pytest
from PySide6.QtCore import Qt,QCoreApplication,QEvent,QSize
from PySide6.QtWidgets import QApplication,QMessageBox,QDialog
from pos2.store import Store
from pos2.app import MainWindow
from pos2.purchase_payment_ui import PurchasePaymentDialog
from pos2.recovery import _validate_database

TODAY=date.today().isoformat()
PASSWORD='Finance-Test-2026!'

@pytest.fixture
def shop(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    store=Store(tmp_path/'finance.db');store.setup_admin('owner','시험 관리자',PASSWORD)
    supplier=store.save_partner(dict(kind='supplier',name='시험 공급사',opening_balance='20.25',opening_date=TODAY,bank='시험은행'))
    product=store.save_product(dict(name='시험 상품',supplier_id=supplier,tracked=False,purchase_price='10.25'))
    document=store.post_document(dict(kind='purchase',date=TODAY,partner_id=supplier,lines=[dict(product_id=product,qty='10',unit_price='10.25')]))
    window=MainWindow(store);window.resize(1400,900);window.show();app.processEvents()
    monkeypatch.setattr(QMessageBox,'warning',lambda parent,title,txt:pytest.fail(str(txt)))
    monkeypatch.setattr('pos2.navigation.ask_unsaved',lambda *_:QMessageBox.StandardButton.Discard)
    yield app,store,window,supplier,product,document
    window.navigation.suspended=True;window.navigation.disable()
    for w in app.topLevelWidgets():w.close();w.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents();store.close()

def register(s,supplier,values,document=None,bill=None,snapshot=None):
    snap=snapshot or s.payment_context(supplier,TODAY,document)
    return s.register_supplier_payment(supplier,values,TODAY,'수기 정산',snap['state'],document,bill)

def note(number='TEST-001'):
    return dict(number=number,due_date=TODAY,bank='시험은행')

def test_mixed_payment_discount_and_bill_are_exact_and_supplier_ledger_agrees(shop):
    _,s,_,supplier,_,doc=shop
    before=s.cash_expected(TODAY)['expected_cash']
    result=register(s,supplier,dict(cash='10.25',transfer=20,card=30,bill=25,dc=5,rebate=4,coupon=3,other_discount=5.25),doc,note())
    assert result['amount']==Decimal('102.50') and result['discount_total']==Decimal('17.25')
    assert s.document(doc)['balance']==0 and s.supplier_outstanding(supplier)['balance']==Decimal('20.25')
    row=s.payment_summary(TODAY,TODAY,partner_id=supplier)[0]
    assert row['paid_total']==Decimal('85.25') and row['discount_payment']==Decimal('17.25')
    assert row['closing']==s.ledger(supplier,TODAY,TODAY)['closing']
    assert s.cash_expected(TODAY)['expected_cash']==before
    _validate_database(s.db)

def test_opening_then_oldest_allocation_and_atomic_failure(shop,monkeypatch):
    _,s,_,supplier,_,doc=shop
    register(s,supplier,dict(dc='20.25',cash=10))
    assert s.supplier_outstanding(supplier)['opening']==0 and s.document(doc)['cash_paid']==10
    before=s.supplier_outstanding(supplier)['balance'];audit=s.audit_revision()
    original=s._insert_trade_payment
    def fail(*args):
        if args[3]=='bill':raise ValueError('injected bill failure')
        return original(*args)
    monkeypatch.setattr(s,'_insert_trade_payment',fail)
    with pytest.raises(ValueError,match='injected'):register(s,supplier,dict(cash=10,bill=20),bill=note())
    assert s.supplier_outstanding(supplier)['balance']==before and s.audit_revision()==audit
    assert not s.payable_bills(TODAY,TODAY)

@pytest.mark.parametrize('values,bill',[({'dc':-1},None),({'rebate':'0.001'},None),({'bad':1},None),({},None),({'bill':20},None),({'bill':20},{'number':'','due_date':TODAY,'bank':''}),({'cash':1000},None)])
def test_invalid_financial_records_do_not_write(shop,values,bill):
    _,s,_,supplier,_,_=shop;before=s.audit_revision()
    with pytest.raises(ValueError):register(s,supplier,values,bill=bill)
    assert s.audit_revision()==before and not s.supplier_payment_history(TODAY,TODAY,supplier)

def test_stale_token_duplicate_bill_and_bill_payment_not_double_deducted(shop):
    _,s,_,supplier,_,doc=shop;snap=s.payment_context(supplier,TODAY)
    result=register(s,supplier,{'bill':40},bill=note(),snapshot=snap)
    with pytest.raises(ValueError,match='바뀌었'):register(s,supplier,{'cash':1},snapshot=snap)
    with pytest.raises(ValueError,match='어음번호'):register(s,supplier,{'bill':10},bill=note())
    bill=s.payable_bills(TODAY,TODAY)[0];before=s.supplier_outstanding(supplier)['balance']
    s.pay_bill(bill['id'],TODAY,'transfer','만기 지급')
    assert s.supplier_outstanding(supplier)['balance']==before and s.payable_bills(TODAY,TODAY)[0]['status']=='지급완료'
    with pytest.raises(ValueError,match='이미 지급'):s.pay_bill(bill['id'],TODAY,'transfer')
    with pytest.raises(ValueError,match='지급한 어음'):s.void_supplier_settlement(result['records'][0]['id'],'취소 불가')
    _validate_database(s.db)

def test_discount_cannot_be_cashed_out_on_full_purchase_return(shop):
    _,s,_,supplier,product,doc=shop
    register(s,supplier,dict(cash='52.50',dc=50),doc)
    line=s.document(doc)['lines'][0]
    returned=s.post_document(dict(kind='purchase_return',source_id=doc,partner_id=supplier,date=TODAY,lines=[dict(product_id=product,source_line_id=line['id'],qty=10)]))
    assert s.document(returned)['refundable']==Decimal('52.50')
    with pytest.raises(ValueError):s.add_payment(returned,'52.51',TODAY,'cash')
    s.add_payment(returned,'52.50',TODAY,'cash')
    assert s.document(returned)['refundable']==0

def test_backup_restore_preserves_bill_discount_and_business_entries(shop):
    _,s,_,supplier,_,doc=shop
    register(s,supplier,dict(bill=10,dc=5),doc,note())
    entry=s.add_business_entry(TODAY,'expense','임차료','7.25','transfer','업무 비용')
    backup=s.create_backup();s.void_business_entry(entry,'입력 정정')
    s.restore_backup(backup,PASSWORD);s.login('owner',PASSWORD)
    assert not s.business_entries(TODAY,TODAY)[0]['voided'] and len(s.payable_bills(TODAY,TODAY))==1
    _validate_database(s.db)

def test_profit_exact_matches_sale_cost_expense_and_discount_income(shop):
    _,s,_,supplier,product,doc=shop
    s.post_document(dict(kind='sale',date=TODAY,partner_id=1,paid='30.25',lines=[dict(product_id=product,qty=1,unit_price='30.25')]))
    register(s,supplier,dict(dc='2.25'),doc)
    s.add_business_entry(TODAY,'expense','업무 비용','3.25','transfer')
    report=s.finance_profit(TODAY,TODAY)
    assert report['current']['profit']==20 and report['current']['other_income']==Decimal('2.25')
    assert report['current']['net_profit']==19 and len(report['monthly'])==1
    statements=[];s.db.set_trace_callback(statements.append)
    s.finance_profit(str(date.today().year)+'-01-01',TODAY);s.db.set_trace_callback(None)
    assert sum(q.lstrip().upper().startswith(('SELECT','WITH')) for q in statements)<12

def test_top_menus_grouping_real_icons_navigation_and_no_duplicated_toolbar(shop):
    app,s,window,supplier,_,doc=shop
    assert window.open_page('payments');page=window.current_page;app.processEvents()
    assert [a.text() for a in page.payment_menubar.actions()]==['1.외상매입','2.외상매출','3.간편장부','4.레포트출력','5.마감관리','6.기타']
    assert window.toolbar.isVisible() and window.menuBar().isVisible()
    assert window.popup_windows['payments'].isVisible() and not window.popup_windows['payments'].isModal()
    assert page.payment_toolbar.isVisible() and page.payment_toolbar.toolButtonStyle()==Qt.ToolButtonStyle.ToolButtonTextUnderIcon
    assert page.header.context.text().startswith('1-01.') and page.payment_back.isEnabled()
    assert page.payment_toolbar.iconSize()==QSize(38,38)
    assert sum(a.isSeparator() for a in page.payment_toolbar.actions())>=4
    before=s.audit_revision()
    for index in (1,2,4,5,6,7,8,9):
        page.payment_views[index].trigger();app.processEvents();assert page.tabs.currentIndex()==index
    assert s.audit_revision()==before
    page.payment_back.trigger();assert page.tabs.currentIndex()==8
    page.payment_forward.trigger();assert page.tabs.currentIndex()==9
    window.previous_menu();assert page.tabs.currentIndex()==8
    assert window.history_actions['다음'].isEnabled()
    window.next_menu();assert page.tabs.currentIndex()==9
    window.open_page('purchases');app.processEvents();assert window.toolbar.isVisible() and window.menuBar().isVisible()
    from pos2.menu_icons import payment_icon,PAYMENT_ATLAS,PAYMENT_KEYS
    assert hashlib.sha256(PAYMENT_ATLAS.read_bytes()).hexdigest()=='f40148bdb1e37131de9e0346e553c521dbd801ecb1382c93fc739862fb9b90c9'
    for kind in PAYMENT_KEYS:assert not payment_icon(kind).pixmap(QSize(76,76)).isNull()
    for size in (28,38,76):
        for kind in ('back','forward','printer','excel'):
            picture=payment_icon(kind).pixmap(QSize(size,size)).toImage()
            assert all(picture.pixelColor(x,y).alpha()==0 for x in range(size) for y in (0,size-1))
            assert all(picture.pixelColor(x,y).alpha()==0 for y in range(size) for x in (0,size-1))

def test_supplier_modal_split_discounts_bill_records_once_and_zero_warns(shop,monkeypatch):
    app,s,window,supplier,_,doc=shop;dialog=PurchasePaymentDialog(window,partner_id=supplier)
    monkeypatch.setattr('pos2.purchase_payment_ui._confirm',lambda *_:True)
    for f in dialog.components.values():f.setText('0')
    dialog.save();assert not dialog.saved_id and '입력' in dialog.error.text()
    dialog.components['card'].setText('10.25');dialog.discounts['dc'].setText('2.25')
    dialog.save();dialog.save()
    assert dialog.result()==QDialog.DialogCode.Accepted and s.supplier_outstanding(supplier)['balance']==Decimal('110.25')
    assert len(s.supplier_payment_history(TODAY,TODAY,supplier))==2

def test_permissions_are_rechecked_and_no_bill_records_via_legacy_api(shop):
    _,s,_,supplier,_,doc=shop
    with pytest.raises(ValueError):s.add_payment(doc,1,TODAY,'bill')
    snap=s.payment_context(supplier,TODAY)
    staff=s.save_user(dict(code='STAFF',name='직원',role='staff',password=PASSWORD,permissions=['trade','deny:payments.create']))
    s.login('STAFF',PASSWORD)
    with pytest.raises(PermissionError):register(s,supplier,{'dc':1},snapshot=snap)
    assert not s.supplier_payment_history(TODAY,TODAY,supplier)


def test_real_214_schema_upgrade_retains_data_and_protection_backup(shop,tmp_path):
    _,s,_,supplier,_,doc=shop
    s.add_payment(doc,'1.25',TODAY,'card')
    from pos2.recovery import APPLICATION_ID
    old=tmp_path/'old-214.db';db=sqlite3.connect(old,isolation_level=None)
    objects={(r['type'],r['name']):r['sql'] for r in s.db.execute("SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'")}
    for (kind,name),sql in objects.items():
        if kind=='table' and name not in {'payable_bills','business_entries'}:
            sql=sql.replace("'cash','transfer','card','bill','dc','rebate','coupon','other_discount'","'cash','transfer','card'")
            db.execute(sql)
            rows=s.db.execute('SELECT * FROM "'+name+'"').fetchall()
            if rows:db.executemany('INSERT INTO "'+name+'" VALUES('+','.join('?' for _ in rows[0])+')',rows)
    for (kind,name),sql in objects.items():
        if kind in {'index','trigger'}:db.execute(sql)
    db.execute(f'PRAGMA application_id={APPLICATION_ID}');db.execute('PRAGMA user_version=214')
    _validate_database(db);db.close()
    migrated=Store(old)
    try:
        migrated.login('owner',PASSWORD)
        assert migrated.document(doc)['cash_paid']==Decimal('1.25')
        assert migrated.migration_backup_path
        from pathlib import Path
        assert Path(migrated.migration_backup_path).is_file()
        _validate_database(migrated.db)
        backup=migrated.migration_backup_path
        migrated.restore_backup(backup,PASSWORD);migrated.login('owner',PASSWORD)
        assert migrated.document(doc)['cash_paid']==Decimal('1.25')
        from pos2.recovery import SCHEMA_VERSION
        assert migrated.db.execute('PRAGMA user_version').fetchone()[0]==SCHEMA_VERSION
    finally:migrated.close()


def test_backups_reject_missing_bill_metadata_and_paid_void_conflict(shop):
    _,s,_,supplier,_,doc=shop
    result=register(s,supplier,{'bill':10},doc,note())
    bill=s.payable_bills(TODAY,TODAY)[0]
    s.db.execute('BEGIN')
    try:
        s.db.execute('DELETE FROM payable_bills WHERE id=?',(bill['id'],))
        with pytest.raises(ValueError,match='누락'):_validate_database(s.db)
    finally:s.db.rollback()
    s.pay_bill(bill['id'],TODAY,'transfer')
    s.db.execute('BEGIN')
    try:
        s.db.execute('UPDATE payments SET voided=1 WHERE id=?',(result['records'][0]['id'],))
        with pytest.raises(ValueError,match='어음'):_validate_database(s.db)
    finally:s.db.rollback()


def test_financial_business_reset_clears_notes_and_costs_but_keeps_identity(shop):
    _,s,_,supplier,_,doc=shop
    register(s,supplier,dict(bill=10,dc=5),doc,note())
    s.add_business_entry(TODAY,'expense','업무 비용','7.25','transfer')
    from pos2.factory_reset import private_digest
    before=private_digest(s.db)
    s.configure_reset_authority(PASSWORD,'wonku9',PASSWORD,PASSWORD)
    result=s.reset_business_data(PASSWORD,'wonku9',PASSWORD,'업무자료 초기화')
    s.login('owner',PASSWORD)
    assert private_digest(s.db)==before
    assert not s.payable_bills('0001-01-01','9999-12-31') and not s.business_entries(TODAY,TODAY)
    assert not s.documents()
    assert len(s.backup_files())>=1
