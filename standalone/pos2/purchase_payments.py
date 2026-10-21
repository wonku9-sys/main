"""Document-scoped purchasing payments, without duplicating supplier ledgers.

All values are internal integer hundredths. Public boundaries are supplied by
Store's currency decorator; writes share its existing SQLite transaction.
"""
from datetime import date as calendar_date

from .common import day, money, text
from .shared_protocol import fingerprint


def context(store, document_id, payment_date=None):
    store._require('trade')
    store.require_menu('purchases')
    store.require_menu('payments')
    when = day(payment_date or calendar_date.today())
    if when > calendar_date.today().isoformat():
        raise ValueError('미래 날짜에는 결제를 등록할 수 없습니다.')
    document = store.document(document_id)
    if document['kind'] != 'purchase' or document['status'] != 'posted':
        raise ValueError('확정된 매입전표에서 결제를 관리하세요. 초안·반품·취소 전표는 대상이 아닙니다.')
    outstanding = store.supplier_outstanding(document['partner_id'], when)
    cap = min(document['balance'], outstanding['cap'], store._source_settlement(document_id, when)[0]) if document['date'] <= when else 0
    state = fingerprint(dict(document=document, supplier_state=outstanding['state'], date=when, cap=cap))
    return dict(document=document, partner=outstanding['partner'],
                balance=outstanding['balance'], cap=max(0, cap), date=when,
                user_name=store.actor['name'], state=state)


def add(store, document_id, components, payment_date, memo, expected_state):
    with store._tx():
        store._require('trade')
        store._require_capability('payments', 'create')
        if not isinstance(components, dict) or set(components) - {'cash', 'transfer', 'card'}:
            raise ValueError('현금·계좌이체·카드 수기 금액을 확인하세요.')
        amounts = {method: money(components.get(method, 0)) for method in ('cash', 'transfer', 'card')}
        total = sum(amounts.values())
        if not total:
            raise ValueError('지급 합계는 0원보다 커야 합니다.')
        memo = text(memo, '결제 메모')
        snapshot = context(store, document_id, payment_date)
        if not expected_state or expected_state != snapshot['state']:
            raise ValueError('다른 결제·반품·수정으로 잔액이 바뀌었습니다. 다시 조회한 뒤 결제하세요.')
        if total > snapshot['cap']:
            raise ValueError('선택 전표 또는 공급사의 결제 가능 잔액을 초과합니다.')
        ids = [store._insert_trade_payment(document_id, value, snapshot['date'], method, memo)
               for method, value in amounts.items() if value]
        store._audit('purchase_payment_batch', 'document', document_id,
                     dict(payment_ids=ids, amount=total, methods=[m for m, v in amounts.items() if v]))
        return dict(document_id=document_id, payment_ids=ids, amount=total)
