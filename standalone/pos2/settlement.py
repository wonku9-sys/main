"""Local supplier payment management based on manual pages 146–153.

One user payment is atomically allocated to opening debt and then the oldest
eligible purchase documents. It is a bookkeeping record, never a bank transfer.
"""
from datetime import date as calendar_date

from .common import day, money, now, text
from .currency import money_input


class SettlementMixin:
    def purchase_payment_context(self, document_id, payment_date=None):
        from .purchase_payments import context
        return context(self, document_id, payment_date)

    def add_purchase_payments(self, document_id, components, payment_date, memo='', expected_state=None):
        from .purchase_payments import add
        return add(self, document_id, components, payment_date, memo, expected_state)

    def verify_payment_access(self,password):
        self._require('trade');self.require_menu('payments')
        from .store import password_matches
        row=self.db.execute('SELECT password_hash FROM users WHERE id=?',(self.actor['id'],)).fetchone()
        if not row or not password_matches(password,row[0]):raise ValueError('비밀번호가 올바르지 않습니다.')
        return {'user_id':self.actor['id'],'restore_token':self._current_restore_token()}
    def _supplier(self, identifier):
        row = self.db.execute("SELECT * FROM partners WHERE id=? AND kind='supplier'", (identifier,)).fetchone()
        if not row:
            raise ValueError("공급사를 선택하세요.")
        return {**dict(row), **self._supplier_profile(identifier)}

    def supplier_summary(self, start, end, search="", only_purchases=False, partner_id=None):
        self._require("trade")
        first, last = day(start), day(end)
        if first > last:
            raise ValueError("조회 시작일이 종료일보다 늦습니다.")
        # One ledger scan, rather than rereading every supplier's documents,
        # refunds, profile and groups separately.
        sql="""WITH events AS (
          SELECT id partner_id,opening_date date,opening_balance charge,0 payment FROM partners
          UNION ALL SELECT partner_id,date,CASE WHEN source_id IS NULL THEN total-points_used ELSE -(total-points_used) END,0 FROM documents WHERE status='posted'
          UNION ALL SELECT p.partner_id,p.date,0,p.amount FROM payments p JOIN documents d ON d.id=p.document_id WHERE p.voided=0 AND d.status='posted'
          UNION ALL SELECT partner_id,date,0,opening_amount FROM supplier_settlements WHERE voided=0
        ), balances AS (
          SELECT partner_id,SUM(CASE WHEN date<? THEN charge-payment ELSE 0 END) opening,
            SUM(CASE WHEN date<=? THEN charge-payment ELSE 0 END) closing,
            SUM(charge-payment) balance,SUM(CASE WHEN date BETWEEN ? AND ? THEN payment ELSE 0 END) payment
          FROM events GROUP BY partner_id
        ), docs AS (
          SELECT partner_id,SUM(CASE WHEN kind='purchase' AND date BETWEEN ? AND ? THEN total ELSE 0 END) purchase,
            SUM(CASE WHEN kind='purchase_return' AND date BETWEEN ? AND ? THEN total ELSE 0 END) returns,
            SUM(CASE WHEN kind='purchase' AND date BETWEEN ? AND ? THEN 1 ELSE 0 END) count,
            MAX(CASE WHEN kind='purchase' THEN date END) last_purchase
          FROM documents WHERE status='posted' GROUP BY partner_id
        ), history AS (
          SELECT partner_id,date,method,amount FROM supplier_settlements WHERE voided=0
          UNION ALL SELECT partner_id,date,method,amount FROM payments WHERE voided=0 AND supplier_settlement_id IS NULL
        ), paid AS (
          SELECT partner_id,MAX(date) last_payment,
            SUM(CASE WHEN method='cash' AND date BETWEEN ? AND ? THEN amount ELSE 0 END) cash_payment,
            SUM(CASE WHEN method='transfer' AND date BETWEEN ? AND ? THEN amount ELSE 0 END) transfer_payment,
            SUM(CASE WHEN method='card' AND date BETWEEN ? AND ? THEN amount ELSE 0 END) card_payment
          FROM history GROUP BY partner_id
        ) SELECT s.*,COALESCE(p.settlement_method,'cash') settlement_method,COALESCE(p.settlement_day,0) settlement_day,
          COALESCE(p.address,'') address,COALESCE(p.representative,'') representative,
          COALESCE(b.opening,0) opening,COALESCE(b.closing,0) closing,COALESCE(b.balance,0) balance,COALESCE(b.payment,0) payment,
          COALESCE(d.purchase,0) purchase,COALESCE(d.returns,0) returns,COALESCE(d.count,0) count,d.last_purchase,
          t.last_payment,COALESCE(t.cash_payment,0) cash_payment,COALESCE(t.transfer_payment,0) transfer_payment,COALESCE(t.card_payment,0) card_payment
        FROM partners s LEFT JOIN supplier_profiles p ON p.partner_id=s.id LEFT JOIN balances b ON b.partner_id=s.id
          LEFT JOIN docs d ON d.partner_id=s.id LEFT JOIN paid t ON t.partner_id=s.id
        WHERE s.kind='supplier' AND (s.code LIKE ? OR s.name LIKE ? OR s.phone LIKE ? OR s.business_no LIKE ?)"""
        term='%'+text(search)+'%';params=[first,last,first,last]+[first,last]*6+[term]*4
        if partner_id is not None:sql+=' AND s.id=?';params.append(partner_id)
        if only_purchases:sql+=' AND COALESCE(d.count,0)>0'
        return [dict(row) for row in self.db.execute(sql+' ORDER BY s.code,s.id',params)]

    def payment_filters(self):
        self._require('trade');self.require_menu('payments')
        return dict(suppliers=[dict(r) for r in self.db.execute(
          "SELECT s.id,s.code,s.name,s.active,s.bank,s.account,s.account_holder,COALESCE(p.settlement_day,0) settlement_day FROM partners s LEFT JOIN supplier_profiles p ON p.partner_id=s.id WHERE s.kind='supplier' ORDER BY s.code,s.id")],
          groups=[dict(r) for r in self.db.execute("SELECT * FROM supplier_groups WHERE kind='settlement' ORDER BY sort_order,code,id")],
          memberships=[dict(r) for r in self.db.execute('SELECT * FROM supplier_group_members')])

    def supplier_outstanding(self, partner_id, payment_date=None):
        self._require("trade")
        party = self._supplier(partner_id)
        when = day(payment_date or calendar_date.today())
        opening_paid = self.db.execute("SELECT COALESCE(SUM(opening_amount),0) FROM supplier_settlements WHERE partner_id=? AND voided=0", (partner_id,)).fetchone()[0]
        opening_due = max(0, party["opening_balance"] - opening_paid)
        opening_eligible = opening_due if party["opening_date"] <= when else 0
        documents = []
        states = []
        for row in self.db.execute("SELECT id,date,number FROM documents WHERE partner_id=? AND kind='purchase' AND status='posted' ORDER BY date,id", (partner_id,)):
            current = self._source_settlement(row["id"])[0]
            states.append([row["id"], current])
            eligible = min(current, self._source_settlement(row["id"], when)[0]) if row["date"] <= when else 0
            if eligible:
                documents.append({**dict(row), "balance": eligible})
        balance = self._partner_balance(partner_id)
        as_of = self.ledger(partner_id, end=when)["closing"]
        cap = max(0, min(balance, as_of, opening_eligible + sum(row["balance"] for row in documents)))
        return {"partner": party, "date": when, "balance": balance, "as_of": as_of, "opening": opening_eligible,
                "documents": documents, "cap": cap, "state": [balance, opening_due, states]}

    def settle_supplier(self, partner_id, amount, date, method="cash", memo="", expected_state=None):
        with self._tx():
            return self._settle_supplier_in_tx(partner_id, amount, date, method, memo, expected_state)

    def _settle_supplier_in_tx(self, partner_id, amount, date, method="cash", memo="", expected_state=None):
        self._require("trade")
        self._require_capability("payments", "create")
        when = day(date)
        if when > calendar_date.today().isoformat():
            raise ValueError("미래 날짜에는 결제를 등록할 수 없습니다.")
        from .payment_finance import METHODS
        if method not in (set(METHODS) if getattr(self,'_finance_batch_active',False) else {"cash", "transfer","card"}):
            raise ValueError("현금·계좌이체·카드 수기를 선택하세요.")
        value = money(amount, positive=True)
        memo = text(memo, "결제 메모")
        self._assert_open(when)
        if method == "cash":
            self._assert_cash_open(when, self.actor["id"])
        snapshot = self.supplier_outstanding(partner_id, when)
        if expected_state is not None and snapshot["state"] != expected_state:
            raise ValueError("다른 결제나 반품으로 잔액이 바뀌었습니다. 다시 조회한 뒤 결제하세요.")
        if value > snapshot["cap"]:
            raise ValueError("현재 또는 선택일의 결제 가능 잔액을 초과합니다.")
        opening = min(snapshot["opening"], value)
        identifier = self.db.execute("INSERT INTO supplier_settlements(partner_id,date,amount,opening_amount,method,memo,user_id,created_at) VALUES(?,?,?,?,?,?,?,?)", (partner_id, when, value, opening, method, memo, self.actor["id"], now())).lastrowid
        remaining = value - opening
        for document in snapshot["documents"]:
            if not remaining:
                break
            allocated = min(remaining, document["balance"])
            payment = self._insert_trade_payment(document["id"], allocated, when, method, memo)
            self.db.execute("UPDATE payments SET supplier_settlement_id=? WHERE id=?", (identifier, payment))
            remaining -= allocated
        if remaining:
            raise ValueError("결제 배분 중 잔액이 변경되어 취소했습니다. 다시 조회하세요.")
        self._audit("supplier_settlement", "supplier_settlement", identifier, {"partner_id": partner_id, "amount": value, "opening_amount": opening})
        return identifier

    def supplier_payment_history(self, start, end, partner_id=None, include_voided=True):
        self._require("trade")
        first, last = day(start), day(end)
        if first > last:
            raise ValueError("조회 시작일이 종료일보다 늦습니다.")
        result = []
        for table, kind in (("supplier_settlements", "settlement"), ("payments", "payment")):
            sql = f"SELECT p.*,s.code partner_code,s.name partner_name,u.name user_name FROM {table} p JOIN partners s ON s.id=p.partner_id JOIN users u ON u.id=p.user_id WHERE s.kind='supplier' AND p.date BETWEEN ? AND ?"
            params = [first, last]
            if kind == "payment":
                sql += " AND p.supplier_settlement_id IS NULL"
            if partner_id is not None:
                sql += " AND p.partner_id=?"
                params.append(partner_id)
            if not include_voided:
                sql += " AND p.voided=0"
            for row in self.db.execute(sql, params):
                result.append({**dict(row), "type": kind, "number": ("결제-" if kind == "settlement" else "전표결제-") + f"{row['id']:06d}"})
        return sorted(result, key=lambda row: (row["date"], row["created_at"], row["id"]), reverse=True)

    def supplier_settlement_detail(self, identifier):
        self._require("trade")
        row = self.db.execute("SELECT g.*,p.name partner_name,p.code partner_code,u.name user_name FROM supplier_settlements g JOIN partners p ON p.id=g.partner_id JOIN users u ON u.id=g.user_id WHERE g.id=?", (identifier,)).fetchone()
        if not row:
            raise ValueError("결제내역을 찾을 수 없습니다.")
        result = dict(row)
        result["allocations"] = [dict(item) for item in self.db.execute("SELECT p.*,d.number,d.date document_date FROM payments p JOIN documents d ON d.id=p.document_id WHERE p.supplier_settlement_id=? ORDER BY d.date,d.id,p.id", (identifier,))]
        return result

    def void_supplier_settlement(self, identifier, reason):
        with self._tx():
            return self._void_supplier_settlement_in_tx(identifier, reason)

    def _void_supplier_settlement_in_tx(self, identifier, reason):
        self._require("trade")
        self._require_capability("payments", "delete")
        group = self.supplier_settlement_detail(identifier)
        bill=self.db.execute('SELECT paid_date FROM payable_bills WHERE settlement_id=?',(identifier,)).fetchone()
        if bill and bill['paid_date']:raise ValueError('이미 지급한 어음은 발행 기록을 취소할 수 없습니다.')
        reason = text(reason, "취소 사유", True)
        if group["voided"]:
            raise ValueError("이미 취소한 결제입니다.")
        if group["date"] != calendar_date.today().isoformat():
            raise ValueError("당일 결제만 취소할 수 있습니다. 지난 날짜의 결제는 보존합니다.")
        self._assert_open(group["date"])
        if group["method"] == "cash":
            self._assert_cash_open(group["date"], group["user_id"])
        for payment in group["allocations"]:
            self._void_trade_payment(payment["id"], reason, identifier)
        self.db.execute("UPDATE supplier_settlements SET voided=1 WHERE id=?", (identifier,))
        self._audit("void_supplier_settlement", "supplier_settlement", identifier, {"reason": reason})

    def void_supplier_payment(self, identifier, reason):
        with self._tx():
            self._require("trade")
            self._require_capability("payments", "delete")
            row = self.db.execute("SELECT p.* FROM payments p JOIN partners s ON s.id=p.partner_id WHERE p.id=? AND s.kind='supplier'", (identifier,)).fetchone()
            if not row or row["date"] != calendar_date.today().isoformat():
                raise ValueError("당일 공급사 결제만 취소할 수 있습니다.")
            self._void_trade_payment(identifier, reason)

    def replace_supplier_payment(self, kind, identifier, amount, method, memo, reason, expected):
        """Preserve the original and replace it atomically, for today only."""
        with self._tx():
            self._require('trade')
            self._require_capability('payments', 'create')
            self._require_capability('payments', 'delete')
            reason = text(reason, '정정 사유', required=True)
            if kind not in {'settlement', 'payment'}:
                raise ValueError('정정할 공급사 결제를 선택하세요.')
            table = 'supplier_settlements' if kind == 'settlement' else 'payments'
            row = self.db.execute(f"SELECT p.* FROM {table} p JOIN partners s ON s.id=p.partner_id WHERE p.id=? AND s.kind='supplier'", (identifier,)).fetchone()
            if not row or row['voided'] or row['date'] != calendar_date.today().isoformat():
                raise ValueError('취소되지 않은 당일 공급사 결제만 정정할 수 있습니다.')
            if row['method'] not in {'cash','transfer','card'} or method not in {'cash','transfer','card'}:
                raise ValueError('어음·할인은 당일 원기록을 취소한 뒤 결제처리에서 다시 등록하세요. 이력은 보존됩니다.')
            if not isinstance(expected, dict) or any(expected.get(key) != row[key] for key in ('date', 'method', 'memo')) or money_input(expected.get('amount'), signed=True) != row['amount']:
                raise ValueError('결제내역이 바뀌었습니다. 다시 조회한 뒤 정정하세요.')
            if kind == 'settlement':
                self._void_supplier_settlement_in_tx(identifier, reason)
                new_id = self._settle_supplier_in_tx(row['partner_id'], amount, row['date'], method, memo)
            else:
                self._void_trade_payment(identifier, reason)
                new_id = self._insert_trade_payment(row['document_id'], money(amount, positive=True), row['date'], method, memo)
            self._audit('replace_supplier_payment', table, identifier, {'replacement_id': new_id, 'reason': reason})
            return new_id
