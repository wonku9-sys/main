"""Read-only preview and atomic, retry-safe supplier settlement confirmation."""
from collections import defaultdict
from datetime import date
import hmac
import json
from uuid import UUID

from .common import money
from .purchase_payment_plan import normalize_plan
from .shared_protocol import fingerprint, encode, decode
from .payment_confirmation import PaymentConfirmationMixin


class BulkPaymentMixin(PaymentConfirmationMixin):
    def _bulk_payment_plans(self, rows):
        self._require('trade'); self._require_capability('payments', 'create')
        if not isinstance(rows, list) or not 1 <= len(rows) <= 500:
            raise ValueError('일괄결제는 1~500행을 입력하세요.')
        plans = []
        for index, row in enumerate(rows, 1):
            try:
                plans.append(normalize_plan(row))
            except (ValueError, TypeError) as exc:
                raise ValueError(f'{index}행: {exc}') from None
        return plans

    def _bulk_payment_preview(self, plans):
        used = defaultdict(int); bills = set(); snapshots = [None] * len(plans)
        # Earlier as-of caps must include previous scheduled payments, even
        # when the operator entered the rows in reverse chronological order.
        for index in sorted(range(len(plans)), key=lambda i: (plans[i]['datetime'], i)):
            plan = plans[index]
            try:
                when = plan['datetime'][:10]
                if when > date.today().isoformat():
                    raise ValueError('미래 날짜에는 결제를 등록할 수 없습니다.')
                snap = self.payment_context(plan['partner_id'], when)
                self._assert_open(when)
                self._assert_payment_open(when)
                if money(plan['components']['cash']): self._assert_cash_open(when, self.actor['id'])
                used[plan['partner_id']] += money(plan['target'])
                if used[plan['partner_id']] > snap['cap']:
                    raise ValueError('공급사의 현재/선택일 결제 가능 잔액을 누적 지급액이 초과합니다.')
                if plan['bill']:
                    number = plan['bill']['number']
                    if number in bills or self.db.execute('SELECT 1 FROM payable_bills WHERE number=?', (number,)).fetchone():
                        raise ValueError('중복 어음번호입니다. 취소된 번호도 재사용할 수 없습니다.')
                    bills.add(number)
                snapshots[index] = dict(state=snap['state'], partner_name=snap['partner']['name'], cap=snap['cap'])
            except (ValueError, PermissionError) as exc:
                raise type(exc)(f'{index+1}행: {exc}') from None
        return dict(plans=plans, rows=snapshots,
                    amount=sum(money(p['target']) for p in plans),
                    state=fingerprint(dict(plans=plans, snapshots=snapshots, restore=self._current_restore_token())))

    def preview_supplier_payments(self, rows):
        return self._bulk_payment_preview(self._bulk_payment_plans(rows))

    def confirm_supplier_payments(self, rows, expected_state, request_id):
        with self._tx():
            plans = self._bulk_payment_plans(rows)
            try:
                if str(UUID(request_id)) != request_id: raise ValueError()
            except (ValueError, TypeError, AttributeError):
                raise ValueError('일괄결제 요청번호를 확인하세요.') from None
            payload_hash = fingerprint(plans)
            prior = self.db.execute("SELECT user_id,detail FROM audit WHERE action='confirm_supplier_payments' AND entity='payment_bulk' AND json_extract(detail,'$.request_id')=? ORDER BY id DESC LIMIT 1", (request_id,)).fetchone()
            if prior:
                detail = json.loads(prior['detail'])
                if prior['user_id'] != self.actor['id'] or detail['payload_hash'] != payload_hash:
                    raise ValueError('이미 사용된 요청번호의 사용자 또는 입력 내용이 다릅니다.')
                return decode(detail['result_json'])
            preview = self._bulk_payment_preview(plans)
            if not isinstance(expected_state, str) or not hmac.compare_digest(expected_state, preview['state']):
                raise ValueError('잔액·거래처·입력 내용이 바뀌었습니다. 입력(F5)으로 다시 검토한 뒤 확정하세요.')
            results = [None] * len(plans)
            for index in sorted(range(len(plans)), key=lambda i: (plans[i]['datetime'], i)):
                plan = plans[index]
                snap = self.payment_context(plan['partner_id'], plan['datetime'][:10])
                results[index] = self._register_supplier_payment_in_tx(
                    plan['partner_id'], plan['components'], plan['datetime'][:10],
                    plan['memo'], snap['state'], None, plan['bill'], plan)
            result = dict(rows=results, amount=preview['amount'], count=len(results), request_id=request_id)
            self._audit('confirm_supplier_payments', 'payment_bulk', None,
                        dict(request_id=request_id, payload_hash=payload_hash, result_json=encode(result)))
            return result
