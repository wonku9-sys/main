"""The same settlement plan and correction travel through real TLS RPC."""
from datetime import date
from decimal import Decimal
import pytest
from test_shared_network import network, crypto
from pos2.purchase_payment_plan import normalize_plan


def test_plan_post_and_correct_are_atomic_and_visible_on_both_pcs(network):
    owner,_,(second,third),_,supplier,_,product=network
    today=date.today().isoformat()
    plan=normalize_plan(dict(partner_id=supplier,target='100.25',components={'cash':'50.25','card':40,'dc':10},
        datetime=today+' 16:12:00',account='공유 시험계좌',memo='공유 상세결제',bill=None))
    payload=dict(kind='purchase',date=today,partner_id=supplier,paid=0,
        lines=[dict(product_id=product,qty=100,unit_price='100.25')],payment_plan=plan)
    draft=second.save_draft(payload)
    assert third.document(draft)['entry']['payment_plan']==plan and third.document(draft)['cash_paid']==0
    payload['_expected_token']=second.document(draft)['_edit_token']
    second.post_document(payload,draft)
    posted=third.document(draft);assert posted['balance']==0 and len(posted['payments'])==3
    identifier=posted['payments'][0]['id'];batch=third.purchase_payment_batch(identifier)
    assert batch['plan']==plan and batch['cap']==Decimal('100.25')
    plan=normalize_plan(dict(plan,target='50.25',components={'card':'40.25','dc':10}))
    result=third.replace_purchase_payment_batch(identifier,plan,batch['state'],'공유 정정')
    assert second.document(draft)['balance']==50 and owner.document(draft)['balance']==50
    with pytest.raises(ValueError,match='유효한|취소|바뀌었'):
        second.replace_purchase_payment_batch(identifier,plan,batch['state'],'중복 정정 방지')
    latest=second.purchase_payment_batch(result['records'][0]['id'])
    second.void_purchase_payment_batch(latest['payment_ids'][0],latest['state'],'공유 취소')
    assert third.document(draft)['balance']==Decimal('100.25')
