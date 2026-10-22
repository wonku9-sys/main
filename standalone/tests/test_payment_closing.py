from copy import deepcopy
from datetime import date,timedelta
from decimal import Decimal
import json
from pathlib import Path
import sqlite3

import pytest
from PySide6.QtCore import Qt,QDate
from PySide6.QtWidgets import QDialog
from test_payment_finance import shop,TODAY,PASSWORD
from pos2.store import Store
from pos2.payment_closing import payment_close_target
from pos2.payment_closing_ui import PaymentMonthCloseDialog
from pos2.purchase_payment_ui import PurchasePaymentDialog
from pos2.recovery import _validate_database,SCHEMA_VERSION


def plan(supplier,when,cash='10',dc='0'):
    return dict(partner_id=supplier,target=str(Decimal(cash)+Decimal(dc)),components=dict(cash=cash,dc=dc),
                datetime=when+' 12:13:00',account='시험계좌',memo='미마감 정정',bill=None)


def register(s,supplier,when,document=None):
    return s.register_supplier_payment(supplier,dict(cash='10',dc='5'),when,'과거 결제',s.payment_context(supplier,when,document)['state'],document)


def old_purchase(s,supplier,product,when,amount=100):
    return s.post_document(dict(kind='purchase',date=when,partner_id=supplier,lines=[dict(product_id=product,qty=10,unit_price=str(Decimal(amount)/10))]))


@pytest.mark.parametrize('when,expected',[(date(2020,11,1),'2020-04-30'),(date(2020,6,1),'2019-11-30'),
    (date(2024,9,30),'2024-02-29'),(date(2026,1,31),'2025-06-30')])
def test_reference_month_boundary(when,expected):assert payment_close_target(when)==expected


def test_month_close_snapshots_actual_carry_without_duplicating_debt_and_only_once(shop):
    _,s,_,supplier,product,_=shop;through=payment_close_target()
    doc=old_purchase(s,supplier,product,through)
    result=register(s,supplier,through,doc);balance=s.ledger(supplier)['closing'];documents=s.documents();payments=s.document(doc)['payments']
    first=s.payment_close_context();assert first['can_close']
    identifier=s.close_payment_month(first['state']);detail=s.payment_close_detail(identifier)
    assert detail['through_date']==through
    supplier_row=next(r for r in detail['rows'] if r['id']==supplier and r['type']=='supplier')
    assert supplier_row['balance']==s.ledger(supplier,end=through)['closing']==85
    assert s.ledger(supplier)['closing']==balance and s.documents()==documents and s.document(doc)['payments']==payments
    assert not s.inventory_closes() and not s.payment_close_context()['can_close']
    with pytest.raises(ValueError,match='월 1회'):s.close_payment_month(first['state'])
    with pytest.raises(sqlite3.IntegrityError):s.db.execute('DELETE FROM payment_month_closes')
    _validate_database(s.db)


def test_closed_period_rejects_every_payment_and_charge_write_without_partial_changes(shop):
    _,s,_,supplier,product,_=shop;through=payment_close_target()
    doc=old_purchase(s,supplier,product,through);unpaid=old_purchase(s,supplier,product,through)
    paid=register(s,supplier,through,doc);payment=paid['records'][0]['id']
    grouped=register(s,supplier,through);group=grouped['records'][0]['id']
    direct=s.purchase_payment_batch(payment);batch=s.purchase_payment_batch(group,'settlement')
    stale=s.payment_context(supplier,through);s.close_payment_month(s.payment_close_context()['state'])
    assert not s.purchase_payment_batch(payment)['editable']
    assert 'MIS' in s.purchase_payment_batch(group,'settlement')['edit_reason']
    revision=s.audit_revision();before=s.supplier_outstanding(supplier)['balance']
    calls=[lambda:s.add_payment(doc,1,through,'cash'),
        lambda:s.settle_supplier(supplier,1,through,'transfer'),
        lambda:s.register_supplier_payment(supplier,dict(cash=1),through,'',stale['state']),
        lambda:s.add_purchase_payments(doc,dict(cash=1),through,'',s.purchase_payment_context(doc,through)['state']),
        lambda:s.preview_supplier_payments([plan(supplier,through)]),
        lambda:s.void_payment(payment,'마감'),lambda:s.void_supplier_settlement(group,'마감'),
        lambda:s.void_purchase_payment_batch(payment,direct['state'],'마감'),
        lambda:s.void_purchase_payment_batch(group,batch['state'],'마감','settlement'),
        lambda:old_purchase(s,supplier,product,through),lambda:s.cancel_document(unpaid,'마감'),
        lambda:s.save_partner(dict(kind='supplier',name='과거 기초',opening_date=through,opening_balance=1))]
    for operation in calls:
        with pytest.raises(ValueError,match='MIS|바뀌었'):operation()
        assert s.audit_revision()==revision and s.supplier_outstanding(supplier)['balance']==before
    _validate_database(s.db)


@pytest.mark.parametrize('source_type',['payment','settlement'])
def test_open_past_payment_date_and_components_can_be_replaced_atomically(shop,source_type):
    _,s,_,supplier,product,_=shop
    when=(date.fromisoformat(payment_close_target())+timedelta(days=1)).isoformat()
    doc=old_purchase(s,supplier,product,when)
    posted=register(s,supplier,when,doc if source_type=='payment' else None);identifier=posted['records'][0]['id']
    current=s.purchase_payment_batch(identifier,source_type);assert current['editable']
    corrected=plan(supplier,(date.fromisoformat(when)+timedelta(days=1)).isoformat(),'8','2')
    result=s.replace_purchase_payment_batch(identifier,corrected,current['state'],'일시·대상액 확인',source_type)
    assert s.purchase_payment_batch(result['records'][0]['id'],source_type)['plan']['datetime']==corrected['datetime']
    table='payments' if source_type=='payment' else 'supplier_settlements'
    assert all(s.db.execute(f'SELECT voided FROM {table} WHERE id=?',(i,)).fetchone()[0] for i in current['payment_ids'])
    _validate_database(s.db)


def test_closed_destination_or_failed_replacement_keeps_original_payment(shop):
    _,s,_,supplier,product,_=shop;through=payment_close_target()
    doc=old_purchase(s,supplier,product,through)
    when=(date.fromisoformat(through)+timedelta(days=1)).isoformat()
    result=register(s,supplier,when,doc);identifier=result['records'][0]['id']
    s.close_payment_month(s.payment_close_context()['state']);current=s.purchase_payment_batch(identifier)
    before=s.document(doc);revision=s.audit_revision()
    with pytest.raises(ValueError,match='MIS'):
        s.replace_purchase_payment_batch(identifier,plan(supplier,through),current['state'],'마감일로 이동 금지')
    assert s.document(doc)==before and s.audit_revision()==revision


def test_stale_close_snapshot_and_staff_denial_do_not_close(shop):
    _,s,_,supplier,_,_=shop;context=s.payment_close_context()
    s.save_partner(dict(kind='supplier',name='다른 작업'))
    with pytest.raises(ValueError,match='바뀌었'):s.close_payment_month(context['state'])
    uid=s.save_user(dict(code='staff',name='직원',role='staff',password='Staff-Close-2026!',permissions=['trade']))
    worker=Store(s.path)
    try:
        worker.login('staff','Staff-Close-2026!');context=worker.payment_close_context()
        with pytest.raises(PermissionError):worker.close_payment_month(context['state'])
    finally:worker.close()
    assert not s.db.execute('SELECT 1 FROM payment_month_closes').fetchone()


def test_schema217_upgrade_protects_old_file_and_new_close_survives_restore(shop,tmp_path):
    _,s,_,_,_,_=shop
    path=tmp_path/'previous217.db'
    with sqlite3.connect(path) as copy:s.db.backup(copy)
    with sqlite3.connect(path) as copy:copy.execute('DROP TABLE payment_month_closes');copy.execute('PRAGMA user_version=217')
    upgraded=Store(path)
    try:
        assert upgraded.migration_backup_path and upgraded.db.execute('PRAGMA user_version').fetchone()[0]==218
        with sqlite3.connect(upgraded.migration_backup_path) as old:
            assert old.execute('PRAGMA user_version').fetchone()[0]==217;_validate_database(old)
        upgraded.login('owner',PASSWORD);identifier=upgraded.close_payment_month(upgraded.payment_close_context()['state'])
        backup=upgraded.create_backup();upgraded.restore_backup(backup,PASSWORD);upgraded.login('owner',PASSWORD)
        assert upgraded.payment_close_detail(identifier)['through_date']==payment_close_target();_validate_database(upgraded.db)
    finally:upgraded.close()


def test_menu_action_executes_one_month_close_window_and_past_payment_uses_detail_dialog(shop,monkeypatch):
    app,s,w,supplier,product,_=shop;when=(date.today()-timedelta(days=2)).isoformat()
    doc=old_purchase(s,supplier,product,when);result=register(s,supplier,when,doc)
    w.open_page('payments');page=w.current_page;seen=[]
    def close_exec(dialog):
        seen.append(dialog.windowTitle());assert dialog.run_button.isEnabled();return QDialog.DialogCode.Rejected
    monkeypatch.setattr(PaymentMonthCloseDialog,'exec',close_exec);page.payment_close_action.trigger()
    assert seen==['MIS · 월마감처리']
    page.start.setDate(QDate.fromString(when,'yyyy-MM-dd'));page.tabs.setCurrentIndex(2);page.refresh()
    for i in range(page.history_grid.rowCount()):
        row=page.history_grid.item(i,0).data(Qt.ItemDataRole.UserRole)
        if row['type']=='payment' and row['id']==result['records'][0]['id']:page.history_grid.selectRow(i);break
    def detail_exec(dialog):
        seen.append(dialog.windowTitle());assert dialog.editing['editable'] and dialog.date.date().toString('yyyy-MM-dd')==when
        assert dialog.save_button.isEnabled();return QDialog.DialogCode.Rejected
    monkeypatch.setattr(PurchasePaymentDialog,'exec',detail_exec);page.payment_edit_button.click();page.detail()
    assert seen==['MIS · 월마감처리','외상매입 결제','외상매입 결제']
