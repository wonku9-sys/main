from decimal import Decimal
from test_shared_network import crypto, network


def test_purchase_price_history_is_read_only_and_same_on_connected_pc(network):
    owner,service,(second,third),config,supplier,customer,product=network
    payload=dict(kind='purchase',date='2026-10-20',partner_id=supplier,
        lines=[dict(product_id=product,qty=100,unit_price='1234.56',sale_price='2345.67')])
    identifier=second.post_document(payload)
    audit=owner.audit_revision(); before=owner.documents()
    local=owner.purchase_price_history(product,'2026-10-20')
    assert third.purchase_price_history(product,'2026-10-20')==local
    assert local['records'][0]['purchase_price']==Decimal('1234.56')
    assert local['records'][0]['sale_price']==Decimal('2345.67')
    assert local['records'][0]['document_id']==identifier
    assert owner.audit_revision()==audit and owner.documents()==before
