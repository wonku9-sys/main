from copy import deepcopy
from decimal import Decimal
from uuid import uuid4

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from test_payment_finance import shop, TODAY
from pos2.payment_bulk_ui import BulkPaymentDialog, parse_supplier_clipboard
from pos2.recovery import _validate_database


def plan(supplier, amount='10', method='cash', discount='0', number=None):
    return dict(partner_id=supplier, target=str(Decimal(amount)+Decimal(discount)),
                components={method: amount, 'dc': discount}, datetime=TODAY+' 12:30:00',
                account='시험계좌', memo='일괄 입력',
                bill=dict(number=number, due_date=TODAY, bank='시험은행') if method=='bill' else None)


def test_preview_is_readonly_confirm_is_exact_and_retries_are_idempotent(shop):
    _,s,_,supplier,_,_=shop
    other=s.save_partner(dict(kind='supplier',name='다른 공급사',opening_balance=50,opening_date=TODAY))
    rows=[plan(supplier,'20.25',discount='2.25'),plan(other,'30','bill',number='BULK-001')]
    before=s.audit_revision(); balance=s.supplier_outstanding(supplier)['balance']
    preview=s.preview_supplier_payments(rows)
    assert preview['amount']==Decimal('52.50') and s.audit_revision()==before
    token=str(uuid4()); result=s.confirm_supplier_payments(rows,preview['state'],token)
    assert result['count']==2 and result['amount']==Decimal('52.50')
    assert s.supplier_outstanding(supplier)['balance']==balance-Decimal('22.50')
    assert s.supplier_outstanding(other)['balance']==20
    revision=s.audit_revision()
    assert s.confirm_supplier_payments(rows,'lost response retry',token)==result
    assert s.audit_revision()==revision and len(s.payable_bills(TODAY,TODAY))==1
    changed=deepcopy(rows);changed[0]=plan(supplier,'1')
    with pytest.raises(ValueError,match='이미 사용된'):s.confirm_supplier_payments(changed,preview['state'],token)
    _validate_database(s.db)


def test_repeated_supplier_checks_cumulative_cap_and_stale_balance(shop):
    _,s,_,supplier,_,_=shop
    with pytest.raises(ValueError,match='2행.*누적'):
        s.preview_supplier_payments([plan(supplier,'100'),plan(supplier,'30')])
    rows=[plan(supplier,'10'),plan(supplier,'20')];preview=s.preview_supplier_payments(rows)
    snap=s.payment_context(supplier,TODAY)
    s.register_supplier_payment(supplier,{'cash':'1'},TODAY,'다른 PC',snap['state'])
    before=s.audit_revision()
    with pytest.raises(ValueError,match='바뀌었'):s.confirm_supplier_payments(rows,preview['state'],str(uuid4()))
    assert s.audit_revision()==before
    preview=s.preview_supplier_payments(rows);s.confirm_supplier_payments(rows,preview['state'],str(uuid4()))
    assert s.supplier_outstanding(supplier)['balance']==Decimal('91.75')


def test_mid_batch_failure_rolls_back_all_suppliers_bills_and_audit(shop,monkeypatch):
    _,s,_,supplier,_,_=shop
    other=s.save_partner(dict(kind='supplier',name='실패 공급사',opening_balance=50,opening_date=TODAY))
    rows=[plan(supplier,'10'),plan(other,'20','bill',number='FAIL-001')]
    preview=s.preview_supplier_payments(rows);before=s.audit_revision();initial=s.supplier_outstanding(supplier)
    original=s._register_supplier_payment_in_tx
    def fail(partner,*args):
        if partner==other: raise ValueError('실패 주입')
        return original(partner,*args)
    monkeypatch.setattr(s,'_register_supplier_payment_in_tx',fail)
    with pytest.raises(ValueError,match='실패 주입'):s.confirm_supplier_payments(rows,preview['state'],str(uuid4()))
    assert s.audit_revision()==before and s.supplier_outstanding(supplier)==initial
    assert not s.payable_bills(TODAY,TODAY)
    _validate_database(s.db)


def test_duplicate_bills_and_changed_preview_are_rejected(shop):
    _,s,_,supplier,_,_=shop
    with pytest.raises(ValueError,match='중복 어음'):
        s.preview_supplier_payments([plan(supplier,'10','bill',number='DUP'),plan(supplier,'20','bill',number='DUP')])
    rows=[plan(supplier)];preview=s.preview_supplier_payments(rows);rows[0]=plan(supplier,'11')
    with pytest.raises(ValueError,match='바뀌었'):s.confirm_supplier_payments(rows,preview['state'],str(uuid4()))


@pytest.mark.parametrize('value',['001\t-1','001\t0.001','001\tNaN','001\t100\t200','\t100'])
def test_bad_paste_rejected_without_coercion(value):
    with pytest.raises(ValueError):parse_supplier_clipboard(value)


def test_real_ui_prepare_confirm_invalidation_keyboard_paste_and_group(shop,monkeypatch):
    app,s,w,supplier,_,_=shop
    monkeypatch.setattr('pos2.workflow_ui._confirm',lambda *_:True)
    dialog=BulkPaymentDialog(w);dialog.show();app.processEvents()
    code=next(r['code'] for r in dialog.suppliers if r['id']==supplier)
    QApplication.clipboard().setText(code+'\t10.25\n'+code+'\t20')
    dialog.table.setFocus();QTest.keyClick(dialog.table,Qt.Key.Key_V,Qt.KeyboardModifier.ControlModifier);app.processEvents()
    assert len(dialog.rows)==2 and not dialog.confirm_button.isEnabled()
    before=s.audit_revision();QTest.keyClick(dialog.table,Qt.Key.Key_F5);app.processEvents()
    assert dialog.confirm_button.isEnabled() and s.audit_revision()==before
    dialog.rows[0]['discount'].setText('2.25');assert not dialog.confirm_button.isEnabled()
    dialog.prepare();assert dialog.preview['amount']==Decimal('32.50')
    dialog.confirm();assert dialog.saved_result['count']==2 and dialog.result()==dialog.DialogCode.Accepted
    assert s.supplier_outstanding(supplier)['balance']==Decimal('90.25')


def test_ui_invalid_code_paste_does_not_add_any_row(shop):
    _,s,w,supplier,_,_=shop;dialog=BulkPaymentDialog(w)
    code=next(r['code'] for r in dialog.suppliers if r['id']==supplier)
    QApplication.clipboard().setText(code+'\t10\nINVALID\t20')
    before=s.audit_revision();dialog.paste()
    assert dialog.rows==[] and s.audit_revision()==before and '2행' in dialog.message.text()


def test_bulk_ui_is_reachable_only_in_purchase_payment_view(shop):
    app,s,w,_,_,_=shop;w.open_page('payments');page=w.current_page
    page.tabs.setCurrentIndex(2);app.processEvents();assert page.bulk_payment_button.isVisible()
    page.tabs.setCurrentIndex(1);assert not page.bulk_payment_button.isVisible()


def test_lost_response_ui_preserves_request_and_retries_without_duplicate_debt(shop,monkeypatch):
    _,s,w,supplier,_,_=shop;dialog=BulkPaymentDialog(w)
    monkeypatch.setattr('pos2.workflow_ui._confirm',lambda *_:True)
    code=next(r['code'] for r in dialog.suppliers if r['id']==supplier)
    dialog.add_row(code,'10');dialog.prepare();token=dialog.request_id
    original=s.confirm_supplier_payments;lost=[True]
    def drop(*args):
        result=original(*args)
        if lost[0]:lost[0]=False;raise ConnectionError('저장 후 응답 유실')
        return result
    monkeypatch.setattr(s,'confirm_supplier_payments',drop)
    balance=s.supplier_outstanding(supplier)['balance'];dialog.confirm()
    assert dialog._outcome_unknown and not dialog.table.isEnabled() and dialog.confirm_button.isEnabled()
    dialog.reject();assert dialog.result()==0 and dialog.request_id==token
    revision=s.audit_revision();dialog.confirm()
    assert dialog.saved_result and s.audit_revision()==revision
    assert s.supplier_outstanding(supplier)['balance']==balance-10
