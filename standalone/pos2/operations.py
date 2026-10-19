"""Physical counts, immutable closeouts and live reports for a local-only store.

Monthly inventory is reconstructed from dated movement deltas, never from today's
product balances. Reports intentionally use the current catalog classifications;
transaction names, quantities, prices and cost come from the saved line snapshots.
"""

import calendar
from datetime import date
from decimal import Decimal

from .common import LIMIT, day, money, now, qtext, qty, rounded, text


OPERATIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS inventory_counts (
 id INTEGER PRIMARY KEY, title TEXT NOT NULL, date TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','applied')),
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 created_at TEXT NOT NULL, applied_at TEXT NOT NULL DEFAULT '',
 applied_user_id INTEGER REFERENCES users(id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS inventory_count_lines (
 id INTEGER PRIMARY KEY, count_id INTEGER NOT NULL REFERENCES inventory_counts(id) ON DELETE CASCADE,
 product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
 product_name TEXT NOT NULL, base_unit TEXT NOT NULL,
 expected_qty INTEGER NOT NULL CHECK(expected_qty>=0),
 counted_qty INTEGER NOT NULL CHECK(counted_qty>=0),
 expected_cost INTEGER NOT NULL CHECK(expected_cost>=0),
 counted_cost INTEGER NOT NULL CHECK(counted_cost>=0),
 last_event_id INTEGER NOT NULL DEFAULT 0,
 UNIQUE(count_id,product_id)
);
CREATE TABLE IF NOT EXISTS inventory_closes (
 id INTEGER PRIMARY KEY, month TEXT NOT NULL UNIQUE, date TEXT NOT NULL,
 stock_cost INTEGER NOT NULL CHECK(stock_cost>=0), item_count INTEGER NOT NULL,
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS inventory_close_lines (
 id INTEGER PRIMARY KEY, close_id INTEGER NOT NULL REFERENCES inventory_closes(id) ON DELETE RESTRICT,
 product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
 product_code TEXT NOT NULL, product_name TEXT NOT NULL, base_unit TEXT NOT NULL,
 category TEXT NOT NULL, supplier_name TEXT NOT NULL,
 stock_qty INTEGER NOT NULL CHECK(stock_qty>=0), stock_cost INTEGER NOT NULL CHECK(stock_cost>=0),
 UNIQUE(close_id,product_id)
);
CREATE TABLE IF NOT EXISTS cash_closes (
 id INTEGER PRIMARY KEY, date TEXT NOT NULL,
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 user_name TEXT NOT NULL, opening_cash INTEGER NOT NULL CHECK(opening_cash>=0),
 cash_receipts INTEGER NOT NULL, cash_refunds INTEGER NOT NULL,
 cash_net INTEGER NOT NULL, expected_cash INTEGER NOT NULL,
 counted_cash INTEGER NOT NULL CHECK(counted_cash>=0), difference INTEGER NOT NULL,
 memo TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(date,user_id)
);
CREATE INDEX IF NOT EXISTS count_status_date ON inventory_counts(status,date);
CREATE INDEX IF NOT EXISTS cash_close_date ON cash_closes(date,user_id);
CREATE TRIGGER IF NOT EXISTS inventory_close_immutable_update BEFORE UPDATE ON inventory_closes
 BEGIN SELECT RAISE(ABORT,'월 재고마감은 변경할 수 없습니다.'); END;
CREATE TRIGGER IF NOT EXISTS inventory_close_immutable_delete BEFORE DELETE ON inventory_closes
 BEGIN SELECT RAISE(ABORT,'월 재고마감은 삭제할 수 없습니다.'); END;
CREATE TRIGGER IF NOT EXISTS inventory_close_line_immutable_update BEFORE UPDATE ON inventory_close_lines
 BEGIN SELECT RAISE(ABORT,'월 재고마감 상세는 변경할 수 없습니다.'); END;
CREATE TRIGGER IF NOT EXISTS inventory_close_line_immutable_delete BEFORE DELETE ON inventory_close_lines
 BEGIN SELECT RAISE(ABORT,'월 재고마감 상세는 삭제할 수 없습니다.'); END;
CREATE TRIGGER IF NOT EXISTS cash_close_immutable_update BEFORE UPDATE ON cash_closes
 BEGIN SELECT RAISE(ABORT,'현금마감은 변경할 수 없습니다.'); END;
CREATE TRIGGER IF NOT EXISTS cash_close_immutable_delete BEFORE DELETE ON cash_closes
 BEGIN SELECT RAISE(ABORT,'현금마감은 삭제할 수 없습니다.'); END;
"""


def _bounded(value, label):
    if abs(value) > LIMIT:
        raise ValueError(f"{label} 허용 범위를 초과했습니다.")
    return value


class OperationsMixin:
    def _init_operations(self):
        self.db.executescript(OPERATIONS_SCHEMA)

    def _operations_read(self, permission):
        try:
            self._require(permission)
        except PermissionError:
            self._require("reports")

    def _assert_open(self, value):
        """Same-transaction hook used by all stock and commerce mutations."""
        value = day(value)
        last = self.db.execute("SELECT MAX(date) FROM inventory_closes").fetchone()[0]
        if last and value <= last:
            raise ValueError(f"{last}까지 월 재고마감되어 거래·재고를 변경할 수 없습니다.")
        return value

    def _assert_cash_open(self, value, user_id=None):
        """Closeout belongs to the actual payment operator, not document author."""
        value = day(value)
        user_id = self.actor["id"] if user_id is None else user_id
        if self.db.execute(
            "SELECT 1 FROM cash_closes WHERE date=? AND user_id=?", (value, user_id)
        ).fetchone():
            raise ValueError("해당 담당자의 현금마감이 완료되어 현금 입출금을 변경할 수 없습니다.")

    @staticmethod
    def _not_future(value, label):
        value = day(value)
        if value > date.today().isoformat():
            raise ValueError(f"미래 날짜의 {label}은(는) 등록할 수 없습니다.")
        return value

    def create_count(self, data):
        self._require("inventory")
        title = text(data.get("title"), "실사명", required=True, maximum=200)
        count_day = self._not_future(data.get("date"), "재고실사")
        items = data.get("items", [])
        if not isinstance(items, (list, tuple)) or not items:
            raise ValueError("실사할 상품을 한 개 이상 선택하세요.")
        with self._tx():
            self._require("inventory")
            self._require_capability("counts", "create")
            self._assert_open(count_day)
            rows, seen = [], set()
            for item in items:
                try:
                    product_id = int(item["product_id"])
                    expected = qty(item["expected_qty"], allow_zero=True)
                    counted = qty(item["counted_qty"], allow_zero=True)
                except (KeyError, TypeError, ValueError):
                    raise ValueError("실사 상품과 장부수량·실사수량을 올바르게 입력하세요.") from None
                if product_id in seen:
                    raise ValueError("동일 상품은 실사에 한 번만 입력할 수 있습니다.")
                seen.add(product_id)
                product = self.db.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
                if not product or not product["active"] or not product["tracked"]:
                    raise ValueError("사용 중인 재고관리 상품만 실사할 수 있습니다.")
                if expected != product["stock_qty"]:
                    raise ValueError(f"{product['name']}: 장부재고가 변경되었습니다. 다시 조회하세요.")
                latest = self.db.execute(
                    "SELECT COALESCE(MAX(id),0), MAX(date) FROM stock_events WHERE product_id=?",
                    (product_id,),
                ).fetchone()
                if latest[1] and latest[1] > count_day:
                    raise ValueError("실사일 이후 재고이동이 있습니다. 현재 날짜로 실사하세요.")
                counted_cost = rounded(
                    Decimal(product["stock_cost"]) * counted / expected
                    if expected else Decimal(product["purchase_price"]) * counted / 1000
                )
                rows.append((product_id, product["name"], product["base_unit"], expected,
                             counted, product["stock_cost"], counted_cost, latest[0]))
            count_id = self.db.execute(
                "INSERT INTO inventory_counts(title,date,user_id,created_at) VALUES(?,?,?,?)",
                (title, count_day, self.actor["id"], now()),
            ).lastrowid
            self.db.executemany(
                "INSERT INTO inventory_count_lines(count_id,product_id,product_name,base_unit,"
                "expected_qty,counted_qty,expected_cost,counted_cost,last_event_id) "
                "VALUES(?,?,?,?,?,?,?,?,?)", [(count_id, *row) for row in rows],
            )
            self._audit("create", "inventory_count", count_id, {"title": title, "items": len(rows)})
        return count_id

    def counts(self):
        self._operations_read("inventory")
        return [dict(row) for row in self.db.execute(
            "SELECT c.*,u.name AS user_name,(SELECT COUNT(*) FROM inventory_count_lines l "
            "WHERE l.count_id=c.id) AS item_count FROM inventory_counts c "
            "JOIN users u ON u.id=c.user_id ORDER BY c.date DESC,c.id DESC"
        )]

    def count(self, count_id):
        self._operations_read("inventory")
        row = self.db.execute(
            "SELECT c.*,u.name AS user_name FROM inventory_counts c JOIN users u ON u.id=c.user_id WHERE c.id=?",
            (count_id,),
        ).fetchone()
        if not row:
            raise ValueError("재고실사 자료를 찾을 수 없습니다.")
        result = dict(row)
        result["items"] = []
        for item in self.db.execute("SELECT * FROM inventory_count_lines WHERE count_id=? ORDER BY id", (count_id,)):
            item = dict(item)
            item["difference"] = qtext(item["counted_qty"] - item["expected_qty"])
            item["cost_difference"] = item["counted_cost"] - item["expected_cost"]
            item["expected_qty"] = qtext(item["expected_qty"])
            item["counted_qty"] = qtext(item["counted_qty"])
            result["items"].append(item)
        return result

    def apply_count(self, count_id):
        self._require("inventory")
        with self._tx():
            self._require("inventory")
            self._require_capability("counts", "edit")
            count = self.db.execute("SELECT * FROM inventory_counts WHERE id=?", (count_id,)).fetchone()
            if not count or count["status"] != "draft":
                raise ValueError("미적용 초안 실사만 재고에 적용할 수 있습니다.")
            self._assert_open(count["date"])
            lines = self.db.execute("SELECT * FROM inventory_count_lines WHERE count_id=? ORDER BY id", (count_id,)).fetchall()
            # Validate EVERY frozen line before making even the first stock move.
            for line in lines:
                product = self.db.execute("SELECT * FROM products WHERE id=?", (line["product_id"],)).fetchone()
                latest = self.db.execute("SELECT COALESCE(MAX(id),0) FROM stock_events WHERE product_id=?", (line["product_id"],)).fetchone()[0]
                if (not product or not product["active"] or not product["tracked"]
                        or product["stock_qty"] != line["expected_qty"]
                        or product["stock_cost"] != line["expected_cost"]
                        or product["base_unit"] != line["base_unit"]
                        or latest != line["last_event_id"]):
                    raise ValueError(f"{line['product_name']}: 실사 후 장부가 변경되었습니다. 초안을 삭제하고 다시 실사하세요.")
            for line in lines:
                self._move(line["product_id"], line["counted_qty"] - line["expected_qty"],
                           line["counted_cost"] - line["expected_cost"], "count",
                           f"재고실사 #{count_id}: {count['title']}", date=count["date"])
            self.db.execute(
                "UPDATE inventory_counts SET status='applied',applied_at=?,applied_user_id=? WHERE id=?",
                (now(), self.actor["id"], count_id),
            )
            self._audit("apply", "inventory_count", count_id, {"items": len(lines)})
        return count_id

    def delete_count(self, count_id):
        self._require("inventory")
        with self._tx():
            self._require("inventory")
            self._require_capability("counts", "delete")
            row = self.db.execute("SELECT status FROM inventory_counts WHERE id=?", (count_id,)).fetchone()
            if not row or row[0] != "draft":
                raise ValueError("미적용 초안 실사만 삭제할 수 있습니다.")
            self.db.execute("DELETE FROM inventory_counts WHERE id=?", (count_id,))
            self._audit("delete", "inventory_count", count_id, {})

    def stock_events(self, product_id=None):
        self._operations_read("inventory")
        query = ("SELECT e.*,p.name AS product_name,p.base_unit,u.name AS user_name FROM stock_events e "
                 "JOIN products p ON p.id=e.product_id JOIN users u ON u.id=e.user_id")
        params = ()
        if product_id is not None:
            query += " WHERE e.product_id=?"
            params = (product_id,)
        result = []
        for row in self.db.execute(query + " ORDER BY e.date DESC,e.id DESC", params):
            row = dict(row)
            row["qty_delta"] = qtext(row["qty_delta"])
            row["balance_qty"] = qtext(row["balance_qty"])
            result.append(row)
        return result

    def inventory_close(self, month):
        self._require_capability("closings", "create")
        self._require("inventory")
        try:
            if len(month) != 7 or month[4] != "-":
                raise ValueError
            year, month_num = (int(part) for part in month.split("-"))
            end = date(year, month_num, calendar.monthrange(year, month_num)[1]).isoformat()
            if end[:7] != month:
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise ValueError("마감월은 YYYY-MM 형식으로 입력하세요.") from None
        self._not_future(end, "월 재고마감")
        with self._tx():
            self._require_capability("closings", "create")
            self._require("inventory")
            self._assert_open(end)
            rows = self.db.execute(
                "SELECT p.id,p.code,p.name,p.base_unit,p.category,COALESCE(s.name,'') AS supplier_name,"
                "COALESCE(SUM(e.qty_delta),0) AS asof_qty,COALESCE(SUM(e.cost_delta),0) AS asof_cost "
                "FROM products p LEFT JOIN partners s ON s.id=p.supplier_id "
                "LEFT JOIN stock_events e ON e.product_id=p.id AND e.date<=? "
                "WHERE p.tracked=1 OR EXISTS(SELECT 1 FROM stock_events h WHERE h.product_id=p.id) "
                "GROUP BY p.id ORDER BY p.code,p.id", (end,),
            ).fetchall()
            for row in rows:
                if row["asof_qty"] < 0 or row["asof_cost"] < 0:
                    raise ValueError(f"{row['name']}: 해당 월말 기준 재고가 음수입니다. 거래일자를 확인하세요.")
                if row["asof_qty"] == 0 and row["asof_cost"] != 0:
                    raise ValueError(f"{row['name']}: 월말 수량은 0인데 원가가 남습니다. 거래일자를 확인하세요.")
                _bounded(row["asof_qty"], "월말 재고수량")
                _bounded(row["asof_cost"], "월말 재고금액")
            stock_cost = _bounded(sum(row["asof_cost"] for row in rows), "월말 재고합계")
            close_id = self.db.execute(
                "INSERT INTO inventory_closes(month,date,stock_cost,item_count,user_id,created_at) VALUES(?,?,?,?,?,?)",
                (month, end, stock_cost, len(rows), self.actor["id"], now()),
            ).lastrowid
            self.db.executemany(
                "INSERT INTO inventory_close_lines(close_id,product_id,product_code,product_name,base_unit,"
                "category,supplier_name,stock_qty,stock_cost) VALUES(?,?,?,?,?,?,?,?,?)",
                [(close_id, row["id"], row["code"], row["name"], row["base_unit"], row["category"],
                  row["supplier_name"], row["asof_qty"], row["asof_cost"]) for row in rows],
            )
            self._audit("close", "inventory_month", close_id,
                        {"month": month, "basis": "stock_events_by_date", "stock_cost": stock_cost})
        return close_id

    def inventory_closes(self):
        self._operations_read("inventory")
        return [dict(row) for row in self.db.execute(
            "SELECT c.*,u.name AS user_name FROM inventory_closes c JOIN users u ON u.id=c.user_id ORDER BY c.month DESC"
        )]

    def inventory_close_detail(self, close_id):
        self._operations_read("inventory")
        row = self.db.execute("SELECT * FROM inventory_closes WHERE id=?", (close_id,)).fetchone()
        if not row:
            raise ValueError("월 재고마감 자료를 찾을 수 없습니다.")
        result = dict(row)
        result["basis"] = "stock_events_by_date"
        result["lines"] = []
        for line in self.db.execute("SELECT * FROM inventory_close_lines WHERE close_id=? ORDER BY product_code,id", (close_id,)):
            line = dict(line)
            line["stock_qty"] = qtext(line["stock_qty"])
            result["lines"].append(line)
        return result

    def _cash_expected(self, value, user_id):
        values = self.db.execute(
            "SELECT COALESCE(SUM(CASE WHEN p.amount>0 THEN p.amount ELSE 0 END),0),"
            "COALESCE(-SUM(CASE WHEN p.amount<0 THEN p.amount ELSE 0 END),0) "
            "FROM payments p JOIN documents d ON d.id=p.document_id "
            "WHERE p.date=? AND p.user_id=? AND p.method='cash' AND p.voided=0 "
            "AND d.status='posted' AND d.kind IN ('sale','sale_return')", (value, user_id),
        ).fetchone()
        receipts, refunds = values
        return {"date": value, "user_id": user_id, "sale_receipts": receipts,
                "cash_receipts": receipts, "refunds": refunds, "cash_refunds": refunds,
                "cash_net": receipts - refunds, "expected_cash": receipts - refunds}

    def cash_expected(self, value):
        self._require("trade")
        result = self._cash_expected(day(value), self.actor["id"])
        result["user_name"] = self.actor["name"]
        result["basis"] = "cash_payments_by_actual_operator"
        return result

    def cash_close(self, data):
        self._require("trade")
        close_day = self._not_future(data.get("date"), "현금마감")
        opening = money(data.get("opening_cash", 0))
        counted = money(data.get("counted_cash", 0))
        memo = text(data.get("memo"), "메모")
        with self._tx():
            self._require("trade")
            self._require_capability("closings", "create")
            self._assert_cash_open(close_day)
            values = self._cash_expected(close_day, self.actor["id"])
            expected = _bounded(opening + values["cash_net"], "예상 현금")
            difference = _bounded(counted - expected, "현금 과부족")
            close_id = self.db.execute(
                "INSERT INTO cash_closes(date,user_id,user_name,opening_cash,cash_receipts,cash_refunds,"
                "cash_net,expected_cash,counted_cash,difference,memo,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (close_day, self.actor["id"], self.actor["name"], opening, values["cash_receipts"],
                 values["cash_refunds"], values["cash_net"], expected, counted, difference, memo, now()),
            ).lastrowid
            self._audit("close", "cash", close_id, {"date": close_day, "expected": expected, "difference": difference})
        return close_id

    def cash_closes(self):
        self._operations_read("trade")
        if self.actor["role"] == "admin":
            rows = self.db.execute("SELECT * FROM cash_closes ORDER BY date DESC,id DESC")
        else:
            rows = self.db.execute("SELECT * FROM cash_closes WHERE user_id=? ORDER BY date DESC,id DESC", (self.actor["id"],))
        return [dict(row) for row in rows]

    def report(self, start, end, group="day"):
        self._require("reports")
        start, end = day(start), day(end)
        if start > end:
            raise ValueError("시작일은 종료일보다 늦을 수 없습니다.")
        if group not in {"day", "month", "product", "category", "supplier", "member"}:
            raise ValueError("지원하지 않는 보고서 구분입니다.")
        records = self.db.execute(
            "SELECT l.*,d.date,d.kind,d.member_id,p.base_unit,p.category,"
            "COALESCE(s.name,'미지정 공급사') AS supplier_name,COALESCE(m.name,'비회원') AS member_name "
            "FROM document_lines l JOIN documents d ON d.id=l.document_id "
            "JOIN products p ON p.id=l.product_id LEFT JOIN partners s ON s.id=l.supplier_id "
            "LEFT JOIN members m ON m.id=d.member_id WHERE d.status='posted' AND d.date BETWEEN ? AND ? "
            "ORDER BY d.date,d.id,l.id", (start, end),
        ).fetchall()
        groups, quantities = {}, {}
        totals = dict.fromkeys(("purchase_total", "sale_total", "cost", "profit", "taxable_sale_total", "exempt_sale_total"), 0)
        for line in records:
            sign = -1 if line["kind"].endswith("_return") else 1
            purchase = line["kind"].startswith("purchase")
            if group == "day":
                identifier, label = line["date"], line["date"]
            elif group == "month":
                identifier, label = line["date"][:7], line["date"][:7]
            elif group == "product":
                identifier, label = line["product_id"], line["product_name"]
            elif group == "category":
                identifier = label = line["category"] or "미분류"
            elif group == "supplier":
                identifier, label = line["supplier_id"], line["supplier_name"]
            else:
                identifier, label = line["member_id"], line["member_name"]
            unit = line["base_unit"]
            key = (identifier, unit)
            row = groups.setdefault(key, {"key": identifier, "label": label, "unit": unit,
                                          "purchase_qty": 0, "sale_qty": 0, "purchase_total": 0,
                                          "sale_total": 0, "cost": 0, "profit": 0})
            quantity = quantities.setdefault(unit, {"purchase_qty": 0, "sale_qty": 0})
            qty_key, total_key = ("purchase_qty", "purchase_total") if purchase else ("sale_qty", "sale_total")
            row[qty_key] += sign * line["base_qty"]
            quantity[qty_key] += sign * line["base_qty"]
            row[total_key] += sign * line["total"]
            totals[total_key] += sign * line["total"]
            if not purchase:
                row["cost"] += sign * line["cost"]
                totals["cost"] += sign * line["cost"]
                tax_key = "taxable_sale_total" if line["tax_mode"] == "taxable" else "exempt_sale_total"
                totals[tax_key] += sign * line["total"]
        rows = sorted(groups.values(), key=lambda row: (str(row["label"]), row["unit"]))
        for row in rows:
            row["profit"] = row["sale_total"] - row["cost"]
            row["purchase_qty"], row["sale_qty"] = qtext(row["purchase_qty"]), qtext(row["sale_qty"])
        totals["profit"] = totals["sale_total"] - totals["cost"]
        totals["quantities"] = {unit: {key: qtext(value) for key, value in values.items()}
                                for unit, values in quantities.items()}
        totals.update(dict.fromkeys(("cash_receipts", "cash_refunds", "cash_net", "transfer_receipts",
                                     "transfer_refunds", "transfer_net", "points_used", "points_earned"), 0))
        for row in self.db.execute(
            "SELECT p.method,p.amount FROM payments p JOIN documents d ON d.id=p.document_id "
            "WHERE d.status='posted' AND d.kind IN ('sale','sale_return') AND p.voided=0 AND p.date BETWEEN ? AND ?",
            (start, end),
        ):
            totals[f"{row['method']}_receipts" if row["amount"] >= 0 else f"{row['method']}_refunds"] += abs(row["amount"])
            totals[f"{row['method']}_net"] += row["amount"]
        points = self.db.execute(
            "SELECT COALESCE(SUM(CASE WHEN kind='sale' THEN points_used ELSE -points_used END),0),"
            "COALESCE(SUM(CASE WHEN kind='sale' THEN points_earned ELSE -points_earned END),0) "
            "FROM documents WHERE status='posted' AND kind IN ('sale','sale_return') AND date BETWEEN ? AND ?", (start, end),
        ).fetchone()
        totals["points_used"], totals["points_earned"] = points
        return {"rows": rows, "totals": totals, "start": start, "end": end, "group": group,
                "classification_basis": "current_product_catalog", "payment_basis": "actual_payment_date"}

    def commission_report(self, start, end):
        """Net source-linked return fees using the immutable transaction rate.

        This is a local sales commission statement, not a bank transfer or VAT
        filing. Supplier names may change; supplier IDs and the stored fee do not.
        Only sales with a saved nonzero commission rate or fee are included.
        """
        self._require("reports")
        start, end = day(start), day(end)
        if start > end:
            raise ValueError("시작일은 종료일보다 늦을 수 없습니다.")
        groups = {}
        for line in self.db.execute(
            "SELECT l.*,d.kind,p.base_unit,s.name AS supplier_name "
            "FROM document_lines l JOIN documents d ON d.id=l.document_id "
            "JOIN products p ON p.id=l.product_id JOIN partners s ON s.id=l.supplier_id "
            "WHERE d.status='posted' AND d.kind IN ('sale','sale_return') "
            "AND d.date BETWEEN ? AND ? AND (l.commission_bps>0 OR l.commission_amount>0) "
            "ORDER BY s.name,l.product_id,d.date,l.id", (start, end),
        ):
            sign = -1 if line["kind"] == "sale_return" else 1
            row = groups.setdefault(line["supplier_id"], {
                "supplier_id": line["supplier_id"], "supplier_name": line["supplier_name"],
                "sale_total": 0, "commission_fee": 0, "payable": 0, "items": {}, "rates": set(),
            })
            row["rates"].add(line["commission_bps"])
            key = (line["product_id"], line["commission_bps"], line["base_unit"])
            item = row["items"].setdefault(key, {
                "product_id": line["product_id"], "product_name": line["product_name"],
                "unit": line["base_unit"], "commission_bps": line["commission_bps"],
                "sale_qty": 0, "sale_total": 0, "commission_fee": 0,
            })
            item["sale_qty"] += sign * line["base_qty"]
            item["sale_total"] += sign * line["total"]
            item["commission_fee"] += sign * line["commission_amount"]
            row["sale_total"] += sign * line["total"]
            row["commission_fee"] += sign * line["commission_amount"]
        totals = {"sale_total": 0, "commission_fee": 0, "payable": 0}
        rows = list(groups.values())
        for row in rows:
            row["payable"] = row["sale_total"] - row["commission_fee"]
            row["commission_bps"] = next(iter(row["rates"])) if len(row["rates"]) == 1 else None
            row["rates"] = sorted(row["rates"])
            row["items"] = list(row["items"].values())
            for item in row["items"]:
                item["sale_qty"] = qtext(item["sale_qty"])
                item["payable"] = item["sale_total"] - item["commission_fee"]
            for key in totals:
                totals[key] += row[key]
        return {"rows": rows, "totals": totals, "start": start, "end": end,
                "basis": "saved_transaction_supplier_rate_and_fee"}
