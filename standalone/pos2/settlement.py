"""Local supplier payment management based on manual pages 146–153.

One user payment is atomically allocated to opening debt and then the oldest
eligible purchase documents. It is a bookkeeping record, never a bank transfer.
"""
from datetime import date as calendar_date

from .common import day, money, now, text


class SettlementMixin:
    def _supplier(self, identifier):
        row = self.db.execute("SELECT * FROM partners WHERE id=? AND kind='supplier'", (identifier,)).fetchone()
        if not row:
            raise ValueError("공급사를 선택하세요.")
        return dict(row)

    def supplier_summary(self, start, end, search="", only_purchases=False, partner_id=None):
        self._require("trade")
        first, last = day(start), day(end)
        if first > last:
            raise ValueError("조회 시작일이 종료일보다 늦습니다.")
        result = []
        for party in self.partners("supplier", search):
            if partner_id is not None and party["id"] != partner_id:
                continue
            docs = self.documents(start=first, end=last, partner_id=party["id"], status="posted")
            purchases = [row for row in docs if row["kind"] == "purchase"]
            if only_purchases and not purchases:
                continue
            ledger = self.ledger(party["id"], first, last)
            result.append({**party, "opening": ledger["opening"], "purchase": sum(row["total"] for row in purchases),
                           "returns": sum(row["total"] for row in docs if row["kind"] == "purchase_return"),
                           "payment": ledger["payment"], "closing": ledger["closing"], "count": len(purchases)})
        return result

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
            self._require("trade")
            self._require_capability("payments", "create")
            when = day(date)
            if when > calendar_date.today().isoformat():
                raise ValueError("미래 날짜에는 결제를 등록할 수 없습니다.")
            if method not in {"cash", "transfer"}:
                raise ValueError("현금 또는 계좌이체를 선택하세요.")
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
            self._require("trade")
            self._require_capability("payments", "delete")
            group = self.supplier_settlement_detail(identifier)
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
