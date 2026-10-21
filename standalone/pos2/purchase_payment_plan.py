"""Serializable purchase settlement instructions; never an external payment API."""
from datetime import datetime
from decimal import Decimal

from .common import day, text
from .currency import public_input

PAYMENT_METHODS = ('cash', 'transfer', 'card', 'bill', 'dc', 'rebate', 'coupon', 'other_discount')


def normalize_plan(plan):
    if not isinstance(plan, dict) or set(plan) != {'partner_id', 'target', 'components', 'datetime', 'account', 'memo', 'bill'}:
        raise ValueError('상세 결제 입력정보를 다시 확인하세요.')
    if type(plan['partner_id']) is not int or plan['partner_id'] <= 0:
        raise ValueError('결제 공급사를 선택하세요.')
    values = plan['components']
    if not isinstance(values, dict) or set(values) - set(PAYMENT_METHODS):
        raise ValueError('결제 수단을 확인하세요.')
    values = {key: public_input(values.get(key, 0)) for key in PAYMENT_METHODS}
    target = public_input(plan['target'], positive=True)
    if sum(values.values(), Decimal(0)) != target:
        raise ValueError('실지급금액과 할인 소계의 합계가 결제대상액과 일치해야 합니다.')
    try:
        stamp = datetime.strptime(plan['datetime'], '%Y-%m-%d %H:%M:%S').strftime('%Y-%m-%d %H:%M:%S')
    except (ValueError, TypeError):
        raise ValueError('결제일시를 확인하세요.') from None
    bill = plan['bill']
    if values['bill']:
        if not isinstance(bill, dict) or set(bill) != {'number', 'due_date', 'bank'}:
            raise ValueError('어음번호·만기일·은행을 입력하세요.')
        bill = dict(number=text(bill['number'], '어음번호', True, 80),
                    due_date=day(bill['due_date']), bank=text(bill['bank'], '어음 은행', maximum=100))
        if bill['due_date'] < stamp[:10]:
            raise ValueError('어음 만기일은 발행일보다 빠를 수 없습니다.')
    elif bill:
        raise ValueError('어음금액이 없는 발행 정보입니다.')
    return dict(partner_id=plan['partner_id'], target=str(target),
                components={key: str(value) for key, value in values.items()}, datetime=stamp,
                account=text(plan['account'], '인출금계좌', maximum=200),
                memo=text(plan['memo'], '결제 메모', maximum=300), bill=bill)
