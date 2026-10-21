from datetime import date
from decimal import Decimal
import pytest
from test_shared_network import network, crypto
from test_purchase_amendments import payload


def test_shared_revision_visible_without_reposting_payment_and_stale_peer_is_rejected(network):
    owner, _, (second, third), _, supplier, _, product = network
    today = date.today().isoformat()
    identifier = second.post_document(dict(kind='purchase', date=today, partner_id=supplier,
                                           lines=[dict(product_id=product, qty=100, unit_price='20.25')]))
    second.add_payment(identifier, 5, today, 'card')
    context = second.purchase_edit_context(identifier); stale = third.purchase_edit_context(identifier)
    data = payload(second, identifier); data['lines'][0]['qty'] = '200'
    second.revise_purchase(identifier, data, context['state'], '공유 입고 수량 확인')
    assert third.document(identifier)['total'] == Decimal('40.50')
    assert owner.document(identifier)['balance'] == Decimal('35.50')
    assert len(third.document(identifier)['payments']) == 1
    assert third.purchase_revisions(identifier)[0]['before']['document']['total'] == Decimal('20.25')
    with pytest.raises(ValueError, match='다른 작업'):
        third.revise_purchase(identifier, data, stale['state'], '동시 수정')
    assert len(second.purchase_revisions(identifier)) == 1
