"""MIS month closing, separate from inventory and cashier closeouts.

The reference screenshot closes April in a November run: keep the six completed
months May–October open, and close everything preceding them. Carry balances
are snapshots of the existing ledger, never additional charges/payments.
"""
from datetime import date, timedelta, datetime
import hmac
import json
import re

from .common import LIMIT, day, now
from .shared_protocol import fingerprint


PAYMENT_CLOSE_SCHEMA = """
CREATE TABLE IF NOT EXISTS payment_month_closes (
 id INTEGER PRIMARY KEY, run_month TEXT NOT NULL UNIQUE, through_date TEXT NOT NULL UNIQUE,
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 created_at TEXT NOT NULL, snapshot TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS payment_month_close_immutable_update BEFORE UPDATE ON payment_month_closes
 BEGIN SELECT RAISE(ABORT,'MIS 결제 월마감은 변경할 수 없습니다.'); END;
CREATE TRIGGER IF NOT EXISTS payment_month_close_immutable_delete BEFORE DELETE ON payment_month_closes
 BEGIN SELECT RAISE(ABORT,'MIS 결제 월마감은 삭제할 수 없습니다.'); END;
"""


def payment_close_target(today=None):
    today = today or date.today()
    year, month = divmod(today.year * 12 + today.month - 1 - 6, 12)
    return (date(year, month + 1, 1) - timedelta(days=1)).isoformat()


def validate_payment_closes(db):
    last_date = last_month = ''
    for row in db.execute('SELECT run_month,through_date,created_at,snapshot FROM payment_month_closes ORDER BY run_month'):
        try:
            month, through, stamp, payload = row
            if not re.fullmatch(r'\d{4}-\d{2}', month): raise ValueError()
            parsed = date.fromisoformat(month+'-01')
            if day(through) != payment_close_target(parsed) or month <= last_month or through <= last_date: raise ValueError()
            if datetime.fromisoformat(stamp).date().isoformat()[:7] != month: raise ValueError()
            values = json.loads(payload)
            if not isinstance(values, list): raise ValueError()
            seen = set()
            for item in values:
                if set(item) != {'type','id','code','name','balance'}: raise ValueError()
                if item['type'] not in {'supplier','customer','member'} or type(item['id']) is not int or item['id'] <= 0: raise ValueError()
                if type(item['balance']) is not int or not -LIMIT <= item['balance'] <= LIMIT: raise ValueError()
                if not isinstance(item['code'],str) or not isinstance(item['name'],str): raise ValueError()
                key = item['type'],item['id']
                if key in seen: raise ValueError()
                seen.add(key)
            last_date,last_month = through,month
        except (ValueError,TypeError,KeyError,OverflowError):
            raise ValueError('백업의 MIS 월마감 기간 또는 이월 잔액이 올바르지 않습니다.') from None


class PaymentClosingMixin:
    def _visible_payment_carries(self, rows):
        from .permissions import has_menu
        return rows if has_menu(self.actor,'members') else [r for r in rows if r['type']!='member']

    def _payment_close_state(self):
        row = self.db.execute('SELECT id,run_month,through_date FROM payment_month_closes ORDER BY through_date DESC LIMIT 1').fetchone()
        return dict(row) if row else None

    def _assert_payment_open(self, when):
        when = day(when)
        closed = self._payment_close_state()
        if closed and when <= closed['through_date']:
            raise ValueError(f"{closed['through_date']}까지 MIS 결제 월마감되었습니다. 해당 기간의 거래·결제는 작성·수정·취소할 수 없습니다.")
        return when

    def _payment_edit_reason(self, rows, bill=None):
        try:
            if bill and bill.get('paid_date'): raise ValueError('지급 완료 어음은 변경할 수 없습니다.')
            for row in rows:
                self._assert_payment_open(row['date']); self._assert_open(row['date'])
                if row['method']=='cash': self._assert_cash_open(row['date'],row['user_id'])
            return ''
        except ValueError as exc: return str(exc)

    def _payment_carry_snapshot(self, through):
        # The same event definitions as ledger()/finance_member_ledger().
        rows = []
        query = """WITH events AS (
            SELECT id partner_id,opening_balance delta FROM partners WHERE opening_date<=?
            UNION ALL SELECT partner_id,CASE WHEN source_id IS NULL THEN total-points_used ELSE -(total-points_used) END
                FROM documents WHERE status='posted' AND date<=?
            UNION ALL SELECT p.partner_id,-p.amount FROM payments p JOIN documents d ON d.id=p.document_id
                WHERE p.voided=0 AND d.status='posted' AND p.date<=?
            UNION ALL SELECT partner_id,-opening_amount FROM supplier_settlements WHERE voided=0 AND date<=?
            ) SELECT s.id,s.kind type,s.code,s.name,SUM(e.delta) balance FROM events e JOIN partners s ON s.id=e.partner_id
            GROUP BY s.id HAVING SUM(e.delta)<>0 ORDER BY s.kind,s.id"""
        rows.extend(dict(r) for r in self.db.execute(query,(through,)*4))
        query = """WITH events AS (
            SELECT member_id,CASE WHEN source_id IS NULL THEN total-points_used ELSE -(total-points_used) END delta
                FROM documents WHERE status='posted' AND member_id IS NOT NULL AND date<=?
            UNION ALL SELECT d.member_id,-p.amount FROM payments p JOIN documents d ON d.id=p.document_id
                WHERE p.voided=0 AND d.status='posted' AND d.member_id IS NOT NULL AND p.date<=?
            ) SELECT m.id,'member' type,m.code,m.name,SUM(e.delta) balance FROM events e JOIN members m ON m.id=e.member_id
            GROUP BY m.id HAVING SUM(e.delta)<>0 ORDER BY m.id"""
        rows.extend(dict(r) for r in self.db.execute(query,(through,)*2))
        if any(abs(r['balance'])>LIMIT for r in rows): raise ValueError('이월 잔액 허용 범위를 초과했습니다.')
        return rows

    def payment_close_context(self):
        self._require('trade'); self.require_menu('payments')
        month = date.today().isoformat()[:7]; target = payment_close_target()
        last = self._payment_close_state()
        history = [dict(r) for r in self.db.execute('SELECT c.id,c.run_month,c.through_date,c.created_at,u.name user_name FROM payment_month_closes c JOIN users u ON u.id=c.user_id ORDER BY c.run_month DESC')]
        carries = self._visible_payment_carries(self._payment_carry_snapshot(target))
        done = bool(last and (last['run_month'] >= month or last['through_date'] >= target))
        return dict(run_month=month,through_date=target,last_close=last,history=history,rows=carries,can_close=not done,
            state=fingerprint(dict(month=month,target=target,last=last,rows=carries,revision=self.audit_revision())))

    def close_payment_month(self, expected_state):
        with self._tx():
            self._require('admin'); self.require_menu('payments')
            current = self.payment_close_context()
            if not current['can_close']: raise ValueError('이번 달 MIS 결제 월마감은 이미 실행했습니다. 월 1회만 가능합니다.')
            if not isinstance(expected_state,str) or not hmac.compare_digest(expected_state,current['state']):
                raise ValueError('월마감 준비 이후 거래·결제·설정이 바뀌었습니다. 다시 조회한 후 잔액을 확인하세요.')
            identifier = self.db.execute('INSERT INTO payment_month_closes(run_month,through_date,user_id,created_at,snapshot) VALUES(?,?,?,?,?)',
                (current['run_month'],current['through_date'],self.actor['id'],now(),json.dumps(current['rows'],ensure_ascii=False))).lastrowid
            self._audit('payment_month_close','payment_month_close',identifier,
                        dict(run_month=current['run_month'],through_date=current['through_date'],parties=len(current['rows'])))
            return identifier

    def payment_close_detail(self, identifier):
        self._require('trade'); self.require_menu('payments')
        row=self.db.execute('SELECT c.*,u.name user_name FROM payment_month_closes c JOIN users u ON u.id=c.user_id WHERE c.id=?',(identifier,)).fetchone()
        if not row: raise ValueError('월마감 이력을 선택하세요.')
        result=dict(row); result['rows']=self._visible_payment_carries(json.loads(result.pop('snapshot'))); return result
