"""Detailed purchase payment and the continuous worksheet are real entry paths."""
from copy import deepcopy
from datetime import date
from decimal import Decimal
import json
import os
from pathlib import Path

import pytest
from PySide6.QtCore import Qt, QDate
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QInputDialog

from test_payment_finance import shop, TODAY, note
from pos2.purchase_payment_ui import PurchasePaymentDialog
from pos2.purchase_payment_plan import normalize_plan
from pos2.workflow_ui import TradeDialog
from pos2.navigation import state
from pos2.recovery import _validate_database
from pos2.unsaved_work import capture_values, apply_values


def plan(supplier, **values):
    return normalize_plan(dict(partner_id=supplier,target=str(sum(Decimal(str(v)) for v in values.values())),
        components=values,datetime=TODAY+' 16:12:00',account='시험은행 · 123-456 · 매장',
        memo='실제 송금 없는 수기 기록',bill=note() if values.get('bill') else None))


def purchase(shop, settlement):
    return dict(kind='purchase',date=TODAY,partner_id=shop[3],paid=0,
        lines=[dict(product_id=shop[4],qty=10,unit_price='10.25')],payment_plan=settlement)


def test_draft_plan_survives_reopen_and_posts_all_methods_atomically(shop):
    app,s,w,supplier,product,_=shop
    original=s.audit_revision();payments=s.db.execute('SELECT COUNT(*) FROM payments').fetchone()[0]
    settlement=plan(supplier,cash=50,transfer=20,card=10,bill=10,dc=5,rebate=3,coupon=2,other_discount='2.50')
    draft=s.save_draft(purchase(shop,settlement))
    assert s.db.execute('SELECT COUNT(*) FROM payments').fetchone()[0]==payments
    assert s.document(draft)['status']=='draft' and s.document(draft)['entry']['payment_plan']==settlement
    loaded=TradeDialog(w,'purchase',draft)
    assert loaded.payment_plan==settlement and loaded.payload()['paid']=='0'
    s.post_document(loaded.payload(),draft)
    posted=s.document(draft);assert posted['balance']==0 and len(posted['payments'])==8
    batch=s.purchase_payment_batch(posted['payments'][0]['id'])
    assert batch['plan']==settlement and len(batch['payment_ids'])==8 and batch['editable']
    assert len(s.payable_bills(TODAY,TODAY))==1
    _validate_database(s.db)


def test_failed_post_rolls_back_document_stock_payments_and_audit(shop,monkeypatch):
    _,s,_,supplier,_,_=shop
    product=s.save_product(dict(name='원자적 재고 상품',tracked=True,purchase_price=100,supplier_id=supplier))
    payload=purchase(shop,plan(supplier,cash=60,card=40));payload['lines']=[dict(product_id=product,qty=1,unit_price=100)]
    before=s.audit_revision();count=len(s.documents());original=s._insert_trade_payment
    def fail(*args):
        if args[3]=='card':raise ValueError('카드 기록 실패 주입')
        return original(*args)
    monkeypatch.setattr(s,'_insert_trade_payment',fail)
    with pytest.raises(ValueError,match='실패 주입'):s.post_document(payload)
    assert s.audit_revision()==before and len(s.documents())==count
    assert s.catalog_product(product)['stock_qty']=='0.000'
    assert not s.db.execute('SELECT 1 FROM payments WHERE method=?',('cash',)).fetchone()


@pytest.mark.parametrize('change',[
    lambda p:p.update(target='99'),lambda p:p['components'].update(cash='-1'),
    lambda p:p.update(partner_id=1),lambda p:p.update(datetime='2099-01-01 12:00:00'),
    lambda p:p.update(datetime='not a date'),lambda p:p.update(account='a'*201),
])
def test_invalid_or_future_plan_never_partially_posts(shop,change):
    _,s,_,supplier,_,_=shop
    settlement=plan(supplier,cash=100);change(settlement)
    before=s.audit_revision();count=len(s.documents())
    with pytest.raises(ValueError):s.post_document(purchase(shop,settlement))
    assert s.audit_revision()==before and len(s.documents())==count


def test_batch_correction_and_cancellation_preserve_original_and_restore_debt(shop):
    _,s,_,supplier,_,doc=shop
    initial=plan(supplier,cash=20,card=20)
    result=s.register_supplier_payment(supplier,initial['components'],TODAY,initial['memo'],s.payment_context(supplier,TODAY,doc)['state'],doc,None,initial)
    first=result['records'][0]['id'];batch=s.purchase_payment_batch(first)
    corrected=plan(supplier,cash=10,card=10,dc=5,rebate=5)
    result=s.replace_purchase_payment_batch(first,corrected,batch['state'],'금액 재확인')
    assert s.document(doc)['balance']==Decimal('72.50')
    assert all(r['voided'] for r in s.document(doc)['payments'] if r['id'] in batch['payment_ids'])
    new=s.purchase_payment_batch(result['records'][0]['id'])
    s.void_purchase_payment_batch(new['payment_ids'][0],new['state'],'거래 취소')
    assert s.document(doc)['status']=='posted' and s.document(doc)['balance']==Decimal('102.50')
    assert all(r['voided'] for r in s.document(doc)['payments'])
    _validate_database(s.db)


def test_stale_correction_and_failed_replacement_never_destroy_original(shop,monkeypatch):
    _,s,_,supplier,_,doc=shop
    initial=plan(supplier,cash=40)
    result=s.register_supplier_payment(supplier,initial['components'],TODAY,initial['memo'],s.payment_context(supplier,TODAY,doc)['state'],doc,None,initial)
    first=result['records'][0]['id'];batch=s.purchase_payment_batch(first)
    s.add_purchase_payments(doc,{'card':1},TODAY,'다른 PC',s.purchase_payment_context(doc)['state'])
    with pytest.raises(ValueError,match='바뀌었'):s.replace_purchase_payment_batch(first,plan(supplier,card=30),batch['state'],'정정')
    batch=s.purchase_payment_batch(first);before=s.audit_revision();balance=s.document(doc)['balance']
    monkeypatch.setattr(s,'_insert_trade_payment',lambda *_:(_ for _ in ()).throw(ValueError('저장 실패')))
    with pytest.raises(ValueError,match='저장 실패'):s.replace_purchase_payment_batch(first,plan(supplier,card=30),batch['state'],'정정')
    assert s.audit_revision()==before and s.document(doc)['balance']==balance
    assert not next(r for r in s.document(doc)['payments'] if r['id']==first)['voided']


def test_paid_bill_cannot_be_cancelled_or_changed(shop):
    _,s,_,supplier,_,doc=shop
    initial=plan(supplier,bill=20)
    result=s.register_supplier_payment(supplier,initial['components'],TODAY,initial['memo'],s.payment_context(supplier,TODAY,doc)['state'],doc,initial['bill'],initial)
    bill=s.payable_bills(TODAY,TODAY)[0];s.pay_bill(bill['id'],TODAY,'transfer')
    batch=s.purchase_payment_batch(result['records'][0]['id']);assert not batch['editable']
    with pytest.raises(ValueError,match='지급 완료'):s.void_purchase_payment_batch(batch['payment_ids'][0],batch['state'],'취소 불가')


def test_new_purchase_opens_reference_dialog_without_writing_before_save(shop,monkeypatch):
    app,s,w,supplier,product,_=shop
    trade=TradeDialog(w);trade.partner.setCurrentIndex(trade.partner.findData(supplier))
    trade.add_line(product,quantity=10,price='10.25')
    monkeypatch.setattr(w,'verify_payment_entry',lambda:True)
    before=s.audit_revision();count=len(s.documents())
    def fill(dialog):
        assert dialog.pending is not None and dialog.windowTitle()=='외상매입 결제'
        for f in dialog.components.values():f.setText('0')
        dialog.components['cash'].setText('50');dialog.components['card'].setText('40')
        dialog.discounts['dc'].setText('10');dialog.hour.setCurrentIndex(16);dialog.minute.setCurrentIndex(12)
        dialog.account.setCurrentText('시험 인출계좌');dialog.save()
        return dialog.result()
    monkeypatch.setattr(PurchasePaymentDialog,'exec',fill)
    before_ui=state(trade);trade.payment_button.click()
    assert trade.payment_plan['target']=='100.00' and trade.payment_plan['datetime']==TODAY+' 16:12:00'
    assert s.audit_revision()==before and len(s.documents())==count
    assert state(trade)!=before_ui and trade.paid.isReadOnly()
    restored=TradeDialog(w);apply_values(restored,capture_values(trade))
    assert restored.payment_plan==trade.payment_plan and restored.payload()==trade.payload()
    draft=s.save_draft(trade.payload());assert s.document(draft)['cash_paid']==0
    s.post_document(TradeDialog(w,'purchase',draft).payload(),draft)
    assert s.document(draft)['balance']==Decimal('2.50')


def test_target_rates_datetime_account_and_reference_sheet_are_visible(shop,monkeypatch,tmp_path):
    app,s,w,supplier,product,doc=shop
    monkeypatch.setattr('pos2.purchase_payment_ui._confirm',lambda *_:True)
    dialog=PurchasePaymentDialog(w,doc);dialog.show();app.processEvents()
    dialog.payment_rate.setText('50');dialog.rate_button.click()
    assert dialog.target_amount.text()=='51.25'
    dialog.dc_rate.setText('10');dialog.dc_button.click()
    assert dialog.discounts['dc'].text()=='5.13' and dialog.components['cash'].text()=='46.12'
    dialog.hour.setCurrentIndex(16);dialog.minute.setCurrentIndex(12);dialog.account.setCurrentText('별도 인출계좌')
    dialog.save();batch=s.purchase_payment_batch(dialog.saved_id)
    assert batch['plan']['account']=='별도 인출계좌' and batch['plan']['datetime']==TODAY+' 16:12:00'
    editing=PurchasePaymentDialog(w,doc,editing=batch);editing.show();app.processEvents()
    assert editing.save_button.text()=='결제수정' and editing.hour.currentData()==16 and editing.minute.currentData()==12
    assert editing.account.currentText()=='별도 인출계좌'
    trade=TradeDialog(w);trade.partner.setCurrentIndex(trade.partner.findData(supplier))
    trade.add_line(product,price='12345678.90');trade.add_line(product,quantity=3,price='10.25')
    trade.show();trade.activateWindow();app.processEvents()
    assert trade.table.objectName()=='tradeWorksheet' and trade.table.showGrid()
    assert not trade.scanner_strip.isVisible() and trade.purchase_summary['total'].text()
    row=trade.line_rows[-1];row['qty'].setFocus();QTest.keyClick(row['qty'],Qt.Key.Key_Return)
    assert row['factor'].hasFocus() and trade.result()==0
    QTest.keyClick(row['factor'],Qt.Key.Key_Up);assert trade.line_rows[-2]['factor'].hasFocus()
    for field in (editing.target_amount,editing.components['cash'],editing.hour,editing.minute,editing.save_button):
        assert field.isVisible() and field.height()>=field.fontMetrics().height()
    capture=Path(os.environ.get('SY_TEST_CAPTURE_DIR',str(tmp_path)));capture.mkdir(parents=True,exist_ok=True)
    trade.grab().save(str(capture/'rc32-purchase-worksheet.png'))
    editing.grab().save(str(capture/'rc32-detailed-payment.png'))


def test_moving_rows_keeps_exact_amount_factor_sale_price_and_memo(shop):
    _,s,w,supplier,product,_=shop
    trade=TradeDialog(w);trade.partner.setCurrentIndex(trade.partner.findData(supplier))
    a=trade.add_line(product,quantity=3,price='33.33');a['total'].setText('100');trade.line_amount_changed(a)
    a['factor'].setText('2');a['sale_price'].setText('60');a['line_memo'].setText('이동 보존')
    trade.add_line(product,quantity=1,price=10)
    trade.table.setCurrentCell(1,3);trade.move_line(1)
    moved=trade.line_rows[2]
    assert moved['amount_override']==100 and moved['factor'].text()=='2'
    assert moved['sale_price'].text()=='60' and moved['line_memo'].text()=='이동 보존'
