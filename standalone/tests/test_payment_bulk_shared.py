from datetime import date
from decimal import Decimal
from uuid import uuid4
import pytest
from test_shared_network import crypto, network


def test_bulk_confirmation_and_ledger_check_visible_to_peer_without_local_copies(network):
    owner,service,(second,third),config,supplier,_,product=network
    today=date.today().isoformat()
    rows=[dict(partner_id=supplier,target='10.25',components=dict(cash='8',dc='2.25'),
               datetime=today+' 12:00:00',account='공유 계좌',memo='일괄 지급',bill=None)]
    before=owner.audit_revision();preview=second.preview_supplier_payments(rows)
    assert owner.audit_revision()==before
    token=str(uuid4());result=second.confirm_supplier_payments(rows,preview['state'],token)
    assert third.confirm_supplier_payments(rows,preview['state'],token)==result
    assert result['amount']==Decimal('10.25')
    ledger=third.supplier_ledger(supplier)
    payment=next(r for r in ledger['entries'] if r.get('payment_id'))
    third.set_supplier_ledger_checked(supplier,payment['source_type'],payment['source_id'],True,payment['confirmation_state'])
    assert any(r.get('checked') for r in second.supplier_ledger(supplier)['entries'])
    assert not second.private.db.execute('SELECT 1 FROM payments').fetchone()
    found=second.purchase_clipboard_products(['00001234','00001234','MISSING'])
    assert len(found)==2 and found[0]['found']['product']['id']==product and found[1]['found'] is None
    assert found[0]['found']['product']['purchase_price']==Decimal('1880.25')


def test_other_pc_payment_invalidates_bulk_preview_and_permissions_rechecked(network):
    owner,service,(second,third),config,supplier,_,_=network
    today=date.today().isoformat()
    rows=[dict(partner_id=supplier,target='10',components=dict(cash='10'),datetime=today+' 12:00:00',account='',memo='',bill=None)]
    preview=second.preview_supplier_payments(rows)
    third.settle_supplier(supplier,'1',today,'transfer')
    with pytest.raises(ValueError,match='바뀌었'):second.confirm_supplier_payments(rows,preview['state'],str(uuid4()))


def test_lost_bulk_response_retries_same_network_request_once(network,monkeypatch):
    owner,service,(second,third),config,supplier,_,_=network
    today=date.today().isoformat()
    rows=[dict(partner_id=supplier,target='10',components=dict(cash='10'),datetime=today+' 12:00:00',account='',memo='',bill=None)]
    preview=second.preview_supplier_payments(rows);token=str(uuid4());original=second.transport.request
    def drop(message):
        result=original(message)
        if message.get('method')=='confirm_supplier_payments':raise ConnectionError('응답 유실')
        return result
    monkeypatch.setattr(second.transport,'request',drop)
    before=owner.supplier_outstanding(supplier)['balance']
    with pytest.raises(ConnectionError):second.confirm_supplier_payments(rows,preview['state'],token)
    assert second.pending and third.supplier_outstanding(supplier)['balance']==before-10
    revision=owner.audit_revision();monkeypatch.setattr(second.transport,'request',original)
    assert second.confirm_supplier_payments(rows,preview['state'],token)['amount']==10
    assert not second.pending and owner.audit_revision()==revision
