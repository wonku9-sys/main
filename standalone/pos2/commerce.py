"""Offline trade journals: immutable postings, source-linked returns and settlements.

Quantities use exact thousandths, won amounts use explicit half-up rounding.  No
catalog prices are silently rewritten by posting a differently priced purchase.
"""

from collections import defaultdict
from datetime import date as calendar_date
from decimal import Decimal
from uuid import uuid4

from .common import LIMIT, day, money, now, qtext, qty, rounded, text
from .currency import amount as currency_amount


KINDS = {"purchase", "sale", "purchase_return", "sale_return"}


class CommerceMixin:
    def _document_menu(self, kind):
        if kind not in KINDS:
            raise ValueError("전표 유형이 올바르지 않습니다.")
        return "purchases" if kind.startswith("purchase") else "sales"

    def _require_trade_write(self, data, identifier=None):
        menu = self._document_menu(data.get("kind"))
        self._require_capability(menu, "edit" if identifier else "create")
        if str(data.get("kind", "")).endswith("_return"):
            self._require_capability(menu, "delete")
        if identifier:
            original = self._trade_row(identifier)
            self._require_capability(self._document_menu(original["kind"]), "edit")

    def _trade_row(self, identifier):
        row = self.db.execute("SELECT * FROM documents WHERE id=?", (identifier,)).fetchone()
        if not row:
            raise ValueError("전표를 찾을 수 없습니다.")
        return dict(row)

    def trade_partners(self, kind, search=""):
        self._require("trade")
        if kind not in {"supplier", "customer"}:
            raise ValueError("거래처 유형이 올바르지 않습니다.")
        rows = self.db.execute(
            "SELECT id,code,name,business_no,supplier_mode FROM partners WHERE kind=? AND active=1 "
            "AND (name LIKE ? OR code LIKE ?) ORDER BY name,id",
            (kind, f"%{search}%", f"%{search}%"),
        )
        return [dict(row) for row in rows]

    def _trade_payment_sum(self, identifier):
        return self.db.execute(
            "SELECT COALESCE(SUM(amount),0) FROM payments WHERE document_id=? AND voided=0",
            (identifier,),
        ).fetchone()[0]

    def _source_settlement(self, identifier, as_of=None):
        original = self._trade_row(identifier)
        cutoff = day(as_of) if as_of else "9999-12-31"
        paid = self.db.execute(
            "SELECT COALESCE(SUM(amount),0) FROM payments WHERE document_id=? AND voided=0 AND date<=?",
            (identifier, cutoff),
        ).fetchone()[0]
        credits = self.db.execute(
            "SELECT COALESCE(SUM(total-points_used),0) FROM documents "
            "WHERE source_id=? AND status='posted' AND date<=?", (identifier, cutoff),
        ).fetchone()[0]
        refunded = -self.db.execute(
            "SELECT COALESCE(SUM(p.amount),0) FROM payments p JOIN documents d "
            "ON d.id=p.document_id WHERE d.source_id=? AND d.status='posted' AND p.voided=0 AND p.date<=?",
            (identifier, cutoff),
        ).fetchone()[0]
        net_due = original["total"] - original["points_used"] - paid - credits + refunded
        return max(0, net_due), max(0, -net_due)

    def _return_due_allocations(self, source_id):
        """Allocate one shared cash-refund debt without counting it per return.

        Earlier credits extinguish the original unpaid charge first; the latest
        remaining credits are allocated the actual refundable overpayment.  A
        user may settle any linked credit within the shared ``refundable`` cap,
        after which this display allocation is recomputed from actual payments.
        """
        pool = self._source_settlement(source_id)[1]
        result = {}
        rows = self.db.execute(
            "SELECT d.id,d.total-d.points_used+COALESCE(SUM(CASE WHEN p.voided=0 THEN p.amount ELSE 0 END),0) remaining "
            "FROM documents d LEFT JOIN payments p ON p.document_id=d.id "
            "WHERE d.source_id=? AND d.status='posted' GROUP BY d.id ORDER BY d.date DESC,d.id DESC",
            (source_id,),
        )
        for row in rows:
            result[row["id"]] = min(row["remaining"], pool)
            pool -= result[row["id"]]
        return result

    def _public_trade(self, record):
        result = dict(record)
        if result["status"] == "draft":
            result["balance"] = max(0, result["total"] - result["points_used"] - result["cash_paid"])
            result["refundable"] = 0
        elif result["status"] == "cancelled":
            result["balance"] = result["refundable"] = 0
        elif result["source_id"]:
            result["cash_paid"] = -self._trade_payment_sum(result["id"])
            result["unrefunded_credit"] = result["total"] - result["points_used"] - result["cash_paid"]
            result["balance"] = self._return_due_allocations(result["source_id"]).get(result["id"], 0)
            result["credit_applied"] = result["unrefunded_credit"] - result["balance"]
            result["refundable"] = min(result["unrefunded_credit"], self._source_settlement(result["source_id"])[1])
        else:
            result["cash_paid"] = self._trade_payment_sum(result["id"])
            result["balance"] = self._source_settlement(result["id"])[0]
            result["refundable"] = 0
        result["net_balance"] = -result["balance"] if result["source_id"] else result["balance"]
        return result

    def documents(self, kind=None, start="", end="", partner_id=None, status="", search=""):
        self._require("trade")
        where, values = [], []
        for column, value in (("kind", kind), ("partner_id", partner_id), ("status", status)):
            if value:
                if column == "kind" and value not in KINDS:
                    raise ValueError("전표 유형이 올바르지 않습니다.")
                if column == "status" and value not in {"draft", "posted", "cancelled"}:
                    raise ValueError("전표 상태가 올바르지 않습니다.")
                where.append(f"d.{column}=?")
                values.append(value)
        if start:
            where.append("d.date>=?")
            values.append(day(start))
        if end:
            where.append("d.date<=?")
            values.append(day(end))
        if start and end and day(start) > day(end):
            raise ValueError("조회 시작일이 종료일보다 늦습니다.")
        if search:
            where.append("(d.number LIKE ? OR p.name LIKE ? OR d.memo LIKE ?)")
            values.extend([f"%{search}%"] * 3)
        sql = ("SELECT d.*,p.name partner_name,p.code partner_code,u.name user_name "
               "FROM documents d JOIN partners p ON p.id=d.partner_id "
               "JOIN users u ON u.id=d.user_id")
        if where:
            sql += " WHERE " + " AND ".join(where)
        return [self._public_trade(row) for row in self.db.execute(sql + " ORDER BY d.date DESC,d.id DESC", values)]

    def document(self, identifier):
        self._require("trade")
        row = self.db.execute(
            "SELECT d.*,p.name partner_name,p.code partner_code,u.name user_name "
            "FROM documents d JOIN partners p ON p.id=d.partner_id "
            "JOIN users u ON u.id=d.user_id WHERE d.id=?", (identifier,),
        ).fetchone()
        if not row:
            raise ValueError("전표를 찾을 수 없습니다.")
        result = self._public_trade(row)
        result["lines"] = []
        for raw in self.db.execute("SELECT * FROM document_lines WHERE document_id=? ORDER BY id", (identifier,)):
            item = dict(raw)
            returned = self.db.execute(
                "SELECT COALESCE(SUM(l.input_qty),0) FROM document_lines l "
                "JOIN documents d ON d.id=l.document_id WHERE l.source_line_id=? AND d.status='posted'",
                (item["id"],),
            ).fetchone()[0]
            item["returned_qty"] = qtext(returned)
            item["remaining_qty"] = qtext(item["input_qty"] - returned)
            item["qty"] = qtext(item["input_qty"])
            for key in ("input_qty", "base_qty", "factor"):
                item[key] = qtext(item[key])
            result["lines"].append(item)
        result["payments"] = [dict(row) for row in self.db.execute(
            "SELECT p.*,u.name user_name FROM payments p JOIN users u ON u.id=p.user_id "
            "WHERE p.document_id=? ORDER BY p.date,p.id", (identifier,),
        )]
        result['_edit_token']=self._edit_snapshot('documents',identifier)
        return result

    def _prepare_trade(self, data, posting=False):
        kind = data.get("kind")
        if kind not in KINDS:
            raise ValueError("전표 유형이 올바르지 않습니다.")
        result = {"kind": kind, "date": day(data.get("date")), "memo": text(data.get("memo", ""), "메모")}
        result["rounding_mode"] = data.get("rounding_mode", self._settings_values().get("rounding_mode", "decimal"))
        if result["rounding_mode"] not in {"decimal", "won"}:
            raise ValueError("반올림 설정을 확인하세요.")
        partner_id = data.get("partner_id")
        partner = self.db.execute("SELECT * FROM partners WHERE id=?", (partner_id,)).fetchone()
        expected = "supplier" if kind.startswith("purchase") else "customer"
        if not partner or partner["kind"] != expected or not partner["active"]:
            raise ValueError("사용 중인 올바른 거래처를 선택하세요.")
        result.update(partner_id=partner_id, member_id=data.get("member_id") or None,
                      source_id=data.get("source_id") or None)
        if result["member_id"] and not kind.startswith("sale"):
            raise ValueError("회원은 매출 거래에만 지정할 수 있습니다.")
        is_return = kind.endswith("_return")
        source = None
        if is_return:
            source = self._trade_row(result["source_id"])
            result["rounding_mode"] = source["rounding_mode"]
            if source["status"] != "posted" or source["kind"] != kind.removesuffix("_return"):
                raise ValueError("확정된 올바른 원전표를 선택하세요.")
            if source["partner_id"] != partner_id:
                raise ValueError("반품 거래처가 원전표와 다릅니다.")
            if result["date"] < source["date"]:
                raise ValueError("반품일은 원거래일보다 빠를 수 없습니다.")
            if result["member_id"] not in (None, source["member_id"]):
                raise ValueError("반품 회원이 원전표와 다릅니다.")
            result["member_id"] = source["member_id"]
        elif result["source_id"]:
            raise ValueError("원전표 연결은 반품에만 사용합니다.")
        if result["member_id"]:
            member = self.db.execute("SELECT * FROM members WHERE id=?", (result["member_id"],)).fetchone()
            if not member or (not is_return and not member["active"]):
                raise ValueError("사용 중인 회원을 선택하세요.")
        result["paid"] = money(data.get("paid", 0))
        result["points_used"] = money(data.get("points_used", 0))
        if result["points_used"] % 100:
            raise ValueError("사용 포인트는 정수 점수로 입력하세요.")
        result["method"] = data.get("method", "cash")
        if result["method"] not in {"cash", "transfer"}:
            raise ValueError("결제 수단은 현금 또는 계좌이체만 가능합니다.")
        if (kind != "sale" or not result["member_id"]) and result["points_used"]:
            raise ValueError("포인트 사용은 회원 매출에서만 입력하세요.")
        lines, returned_now = [], defaultdict(int)
        raw_lines = data.get("lines", [])
        if not isinstance(raw_lines, (list, tuple)) or len(raw_lines) > 2000:
            raise ValueError("전표는 최대 2,000개 행까지 입력할 수 있습니다.")
        if posting and not raw_lines:
            raise ValueError("상품을 한 개 이상 추가하세요.")
        for raw in raw_lines:
            product = self.db.execute("SELECT * FROM products WHERE id=?", (raw.get("product_id"),)).fetchone()
            if not product or (not is_return and not product["active"]):
                raise ValueError("사용 중인 상품을 선택하세요.")
            item = {"product_id": product["id"], "unit_id": raw.get("unit_id") or None,
                    "input_qty": qty(raw.get("qty")), "source_line_id": raw.get("source_line_id") or None,
                    "product_name": product["name"], "unit_name": product["base_unit"], "factor": 1000,
                    "price_basis": product["price_basis"],
                    "tracked": bool(product["tracked"]), "product": dict(product),
                    "supplier_id": product["supplier_id"], "tax_mode": product["tax_mode"],
                    "commission_bps": 0, "commission_amount": 0}
            if is_return:
                original = self.db.execute("SELECT * FROM document_lines WHERE id=? AND document_id=?",
                                           (item["source_line_id"], source["id"])).fetchone()
                if not original or original["product_id"] != product["id"]:
                    raise ValueError("원전표의 상품 행을 선택하세요.")
                if item["unit_id"] != original["unit_id"]:
                    raise ValueError("반품 단위는 원거래 단위와 같아야 합니다.")
                if "unit_price" in raw and money(raw["unit_price"]) != original["unit_price"]:
                    raise ValueError("반품 가격은 원거래 가격을 변경할 수 없습니다.")
                item.update({key: original[key] for key in ("unit_name", "factor", "unit_price", "product_name", "price_basis")})
                item.update({key: original[key] for key in ("supplier_id", "tax_mode", "commission_bps")})
                prior = self.db.execute(
                    "SELECT COALESCE(SUM(l.input_qty),0) q,COALESCE(SUM(l.total),0) t,"
                    "COALESCE(SUM(l.cost),0) c FROM document_lines l JOIN documents d ON d.id=l.document_id "
                    "WHERE l.source_line_id=? AND d.status='posted'", (original["id"],),
                ).fetchone()
                before = prior["q"] + returned_now[original["id"]]
                after = before + item["input_qty"]
                if after > original["input_qty"]:
                    raise ValueError("이미 반품한 수량을 포함하여 원거래 수량을 초과할 수 없습니다.")
                item["total"] = rounded(Decimal(original["total"]) * after / original["input_qty"]) - rounded(
                    Decimal(original["total"]) * before / original["input_qty"])
                item["cost"] = rounded(Decimal(original["cost"]) * after / original["input_qty"]) - rounded(
                    Decimal(original["cost"]) * before / original["input_qty"])
                item["commission_amount"] = rounded(Decimal(original["commission_amount"]) * after / original["input_qty"]) - rounded(
                    Decimal(original["commission_amount"]) * before / original["input_qty"])
                returned_now[original["id"]] += item["input_qty"]
            else:
                if item["source_line_id"]:
                    raise ValueError("일반 전표에는 원거래 행을 지정할 수 없습니다.")
                if item["unit_id"]:
                    unit = self.db.execute("SELECT * FROM product_units WHERE id=? AND product_id=? AND active=1",
                                           (item["unit_id"], product["id"])).fetchone()
                    if not unit:
                        raise ValueError("사용 중인 올바른 확장단위를 선택하세요.")
                    item.update(unit_name=unit["name"], factor=unit["factor"])
                    item["price_basis"] = 1
                if raw.get("gram_input"):
                    if item["unit_id"] or product["base_unit"] != "kg":
                        raise ValueError("g 입력 환산은 kg 기본상품에서만 가능합니다.")
                    item.update(unit_name="g", factor=1, price_basis=100)
                if "unit_price" not in raw:
                    raise ValueError("확인한 거래 단가를 입력하세요.")
                item["unit_price"] = money(raw["unit_price"])
                calculated = Decimal(item["input_qty"]) * item["unit_price"] / (1000 * item["price_basis"])
                item["total"] = rounded(calculated / 100) * 100 if result["rounding_mode"] == "won" else rounded(calculated)
                item["cost"] = item["total"] if kind == "purchase" else 0
                if kind == "sale" and item["supplier_id"]:
                    supplier = self.db.execute("SELECT supplier_mode,commission_bps FROM partners WHERE id=?",
                                               (item["supplier_id"],)).fetchone()
                    if supplier and supplier["supplier_mode"] == "commission":
                        item["commission_bps"] = supplier["commission_bps"]
                        item["commission_amount"] = rounded(Decimal(item["total"]) * supplier["commission_bps"] / 10000)
            converted = item["input_qty"] * item["factor"]
            if converted % 1000:
                raise ValueError("확장단위 환산 수량이 기본단위 소수점 셋째 자리를 초과합니다.")
            item["base_qty"] = converted // 1000
            if item["base_qty"] <= 0 or item["base_qty"] > LIMIT:
                raise ValueError("환산 수량 허용 범위를 초과했습니다.")
            lines.append(item)
        result["lines"], result["total"] = lines, sum(item["total"] for item in lines)
        if result["total"] > LIMIT:
            raise ValueError("전표 합계 허용 범위를 초과했습니다.")
        if result["points_used"] > result["total"] or result["paid"] > result["total"] - result["points_used"]:
            raise ValueError("결제액과 사용 포인트가 전표 금액을 초과합니다.")
        if posting and kind == "sale" and result["member_id"] and result["paid"] + result["points_used"] != result["total"]:
            raise ValueError("회원 매출은 현금·이체와 포인트로 전액 정산해야 합니다.")
        return result

    def _write_trade(self, prepared, status, identifier=None):
        values = (prepared["kind"], prepared["date"], status, prepared["partner_id"], prepared["member_id"],
                  prepared["source_id"], prepared["total"], prepared["paid"], prepared["points_used"],
                  prepared["memo"], self.actor["id"])
        if identifier is None:
            prefix = {"purchase": "P", "sale": "S", "purchase_return": "PR", "sale_return": "SR"}[prepared["kind"]]
            number = f"{prefix}-{prepared['date'].replace('-', '')}-{uuid4().hex[:10].upper()}"
            cursor = self.db.execute(
                "INSERT INTO documents(number,kind,date,status,partner_id,member_id,source_id,total,"
                "cash_paid,points_used,memo,user_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (number,) + values + (now(),),
            )
            identifier = cursor.lastrowid
        else:
            current = self._trade_row(identifier)
            if current["status"] != "draft":
                raise ValueError("확정된 전표는 수정할 수 없습니다. 취소 또는 원전표 반품을 이용하세요.")
            self.db.execute("DELETE FROM document_lines WHERE document_id=?", (identifier,))
            self.db.execute(
                "UPDATE documents SET kind=?,date=?,status=?,partner_id=?,member_id=?,source_id=?,total=?,"
                "cash_paid=?,points_used=?,memo=?,user_id=?,points_earned=0 WHERE id=?", values + (identifier,),
            )
        for item in prepared["lines"]:
            self.db.execute(
                "INSERT INTO document_lines(document_id,product_id,unit_id,product_name,unit_name,factor,"
                "input_qty,base_qty,unit_price,total,cost,source_line_id,supplier_id,tax_mode,commission_bps,"
                "commission_amount,price_basis) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (identifier,) + tuple(item[key] for key in ("product_id", "unit_id", "product_name", "unit_name",
                 "factor", "input_qty", "base_qty", "unit_price", "total", "cost", "source_line_id",
                 "supplier_id", "tax_mode", "commission_bps", "commission_amount", "price_basis")),
            )
        self.db.execute("UPDATE documents SET rounding_mode=? WHERE id=?", (prepared["rounding_mode"], identifier))
        return identifier

    def save_draft(self, data, id=None):
        with self._tx():
            self._require("trade")
            self._require_trade_write(data, id)
            self._check_edit_snapshot('documents',id,data)
            prepared = self._prepare_trade(data)
            identifier = self._write_trade(prepared, "draft", id)
            self._audit("save_draft", "document", identifier, {"kind": prepared["kind"], "total": prepared["total"]})
            return identifier

    def delete_draft(self, identifier):
        with self._tx():
            self._require("trade")
            self._require_capability(self._document_menu(self._trade_row(identifier)["kind"]), "delete")
            if self._trade_row(identifier)["status"] != "draft":
                raise ValueError("초안만 삭제할 수 있습니다. 확정 이력은 보존합니다.")
            self.db.execute("DELETE FROM documents WHERE id=?", (identifier,))
            self._audit("delete_draft", "document", identifier, {})

    def _assign_sale_costs(self, prepared):
        cumulative = defaultdict(int)
        for item in prepared["lines"]:
            product = item["product"]
            if not item["tracked"]:
                item["cost"] = rounded(Decimal(product["purchase_price"]) * item["base_qty"] / (1000 * product["price_basis"]))
                continue
            before = cumulative[item["product_id"]]
            after = before + item["base_qty"]
            if after > product["stock_qty"]:
                raise ValueError(f"{product['name']} 재고가 부족합니다. 중복 상품 행의 합계도 확인하세요.")
            item["cost"] = rounded(Decimal(product["stock_cost"]) * after / product["stock_qty"]) - rounded(
                Decimal(product["stock_cost"]) * before / product["stock_qty"])
            cumulative[item["product_id"]] = after

    def post_document(self, data, draft_id=None):
        with self._tx():
            self._require("trade")
            self._require_trade_write(data, draft_id)
            self._check_edit_snapshot('documents',draft_id,data)
            prepared = self._prepare_trade(data, posting=True)
            if prepared["date"] > calendar_date.today().isoformat():
                raise ValueError("미래 거래는 확정할 수 없습니다. 예정 거래는 초안으로 보관하세요.")
            self._assert_open(prepared["date"])
            if prepared["kind"] == "sale":
                self._assign_sale_costs(prepared)
            identifier = self._write_trade(prepared, "posted", draft_id)
            points_used, earned = prepared["points_used"], 0
            if prepared["kind"] == "sale" and prepared["member_id"]:
                earned = self._sale_points(identifier, prepared["member_id"], prepared["total"], points_used)
            elif prepared["kind"] == "sale_return" and prepared["member_id"]:
                points_used, earned = self._reverse_sale_points(identifier, prepared["source_id"], prepared["total"])
            self.db.execute("UPDATE documents SET points_used=?,points_earned=?,cash_paid=0 WHERE id=?",
                            (points_used, earned, identifier))
            direction = 1 if prepared["kind"] in {"purchase", "sale_return"} else -1
            for item in prepared["lines"]:
                if item["tracked"]:
                    self._move(item["product_id"], direction * item["base_qty"], direction * item["cost"],
                               prepared["kind"], prepared["memo"], identifier, prepared["date"])
            if prepared["paid"]:
                self._insert_trade_payment(identifier, prepared["paid"], prepared["date"], prepared["method"], "등록 시 정산")
            self._audit("post", "document", identifier,
                        {"kind": prepared["kind"], "total": prepared["total"], "points_used": points_used})
            return identifier

    def _move(self, product_id, qty_delta, cost_delta, kind, reason, document_id=None, date=None):
        if not self.db.in_transaction:
            raise RuntimeError("재고 이동에는 업무 트랜잭션이 필요합니다.")
        event_date = day(date or calendar_date.today())
        self._assert_open(event_date)
        product = self.db.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
        if not product:
            raise ValueError("상품을 찾을 수 없습니다.")
        if not product["tracked"]:
            return
        if not isinstance(qty_delta, int) or not isinstance(cost_delta, int):
            raise ValueError("내부 재고 이동은 정수로 계산해야 합니다.")
        balance_qty, balance_cost = product["stock_qty"] + qty_delta, product["stock_cost"] + cost_delta
        if min(balance_qty, balance_cost) < 0:
            raise ValueError("재고 수량 또는 원가액이 부족하여 처리할 수 없습니다.")
        if max(abs(qty_delta), abs(cost_delta), balance_qty, balance_cost) > LIMIT:
            raise ValueError("재고 허용 범위를 초과했습니다.")
        if balance_qty == 0 and balance_cost != 0:
            raise ValueError("수량 0에 원가 잔액이 남는 이동은 처리할 수 없습니다. 재고 실사를 확인하세요.")
        self.db.execute("UPDATE products SET stock_qty=?,stock_cost=?,updated_at=? WHERE id=?",
                        (balance_qty, balance_cost, now(), product_id))
        self.db.execute(
            "INSERT INTO stock_events(product_id,document_id,date,kind,qty_delta,cost_delta,balance_qty,"
            "balance_cost,reason,user_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (product_id, document_id, event_date, kind, qty_delta, cost_delta, balance_qty, balance_cost,
             text(reason, "재고 사유"), self.actor["id"], now()),
        )

    def _insert_trade_payment(self, document_id, amount, payment_date, method, memo):
        record = self._trade_row(document_id)
        self._require_capability("payments" if record["kind"].startswith("purchase") else "sales", "create")
        if record["status"] != "posted":
            raise ValueError("확정된 전표만 정산할 수 있습니다.")
        payment_date = day(payment_date)
        if payment_date > calendar_date.today().isoformat():
            raise ValueError("미래 날짜에는 정산을 확정할 수 없습니다.")
        if payment_date < record["date"]:
            raise ValueError("정산일은 거래일보다 빠를 수 없습니다.")
        self._assert_open(payment_date)
        if method not in {"cash", "transfer"}:
            raise ValueError("결제 수단은 현금 또는 계좌이체만 가능합니다.")
        if type(amount) is not int or amount <= 0 or amount > LIMIT:
            raise ValueError("정산금액은 0.01원 이상이어야 합니다.")
        if record["source_id"]:
            already = -self._trade_payment_sum(document_id)
            cap = min(record["total"] - record["points_used"] - already,
                      self._source_settlement(record["source_id"])[1],
                      self._source_settlement(record["source_id"], payment_date)[1])
        else:
            cap = self._source_settlement(document_id)[0]
        if amount > cap:
            raise ValueError("정산 가능 잔액을 초과합니다. 반품 외상 차감 및 기존 환불액을 확인하세요.")
        if method == "cash":
            self._assert_cash_open(payment_date, self.actor["id"])
        signed_amount = -amount if record["source_id"] else amount
        identifier = self.db.execute(
            "INSERT INTO payments(partner_id,document_id,date,amount,method,memo,user_id,created_at) "
            "VALUES(?,?,?,?,?,?,?,?)", (record["partner_id"], document_id, payment_date, signed_amount,
                                      method, text(memo, "정산 메모"), self.actor["id"], now()),
        ).lastrowid
        self.db.execute("UPDATE documents SET cash_paid=? WHERE id=?",
                        (abs(self._trade_payment_sum(document_id)), document_id))
        self._audit("payment", "payment", identifier, {"document_id": document_id, "amount": signed_amount})
        return identifier

    def add_payment(self, document_id, amount, date, method="cash", memo=""):
        with self._tx():
            self._require("trade")
            return self._insert_trade_payment(document_id, money(amount, positive=True), date, method, memo)

    def void_payment(self, identifier, reason):
        with self._tx():
            self._require("trade")
            self._void_trade_payment(identifier, reason)

    def _void_trade_payment(self, identifier, reason, settlement_id=None):
        reason = text(reason, "취소 사유", required=True)
        payment = self.db.execute("SELECT * FROM payments WHERE id=?", (identifier,)).fetchone()
        if not payment or payment["voided"]:
            raise ValueError("취소할 수 있는 정산 이력이 아닙니다.")
        if payment["supplier_settlement_id"] and payment["supplier_settlement_id"] != settlement_id:
            raise ValueError("공급사 묶음 결제입니다. 결제관리에서 결제 전체를 취소하세요.")
        record = self._trade_row(payment["document_id"])
        self._require_capability("payments" if record["kind"].startswith("purchase") else "sales", "delete")
        if record["member_id"] and record["kind"] == "sale":
            raise ValueError("회원 매출의 전액 정산을 해제할 수 없습니다. 원전표 반품을 이용하세요.")
        self._assert_open(payment["date"])
        if payment["method"] == "cash":
            self._assert_cash_open(payment["date"], payment["user_id"])
        self.db.execute("UPDATE payments SET voided=1 WHERE id=?", (identifier,))
        if not record["source_id"]:
            refunds = -self.db.execute(
                "SELECT COALESCE(SUM(p.amount),0) FROM payments p JOIN documents d ON d.id=p.document_id "
                "WHERE d.source_id=? AND d.status='posted' AND p.voided=0", (record["id"],),
            ).fetchone()[0]
            if refunds and self._source_settlement(record["id"])[0]:
                raise ValueError("이미 환불한 원전표 정산은 해제할 수 없습니다. 환불 정산을 먼저 확인하세요.")
            if refunds:
                refund_days = self.db.execute(
                    "SELECT DISTINCT p.date FROM payments p JOIN documents d ON d.id=p.document_id "
                    "WHERE d.source_id=? AND d.status='posted' AND p.voided=0 ORDER BY p.date", (record["id"],),
                ).fetchall()
                if any(self._source_settlement(record["id"], row[0])[0] for row in refund_days):
                    raise ValueError("환불 당시의 지급액이 부족해지는 정산 취소는 허용되지 않습니다.")
        self.db.execute("UPDATE documents SET cash_paid=? WHERE id=?", (abs(self._trade_payment_sum(record["id"])), record["id"]))
        self._audit("void_payment", "payment", identifier, {"reason": reason})

    def cancel_document(self, identifier, reason):
        with self._tx():
            self._require("trade")
            reason = text(reason, "취소 사유", required=True)
            record = self._trade_row(identifier)
            self._require_capability(self._document_menu(record["kind"]), "delete")
            if record["status"] != "posted":
                raise ValueError("확정 상태의 전표만 취소할 수 있습니다.")
            self._assert_open(record["date"])
            if self.db.execute("SELECT 1 FROM payments WHERE document_id=? AND voided=0", (identifier,)).fetchone():
                raise ValueError("정산 이력을 먼저 취소하세요. 환불이 필요한 거래는 원전표 반품을 이용하세요.")
            if self.db.execute("SELECT 1 FROM documents WHERE source_id=? AND status='posted'", (identifier,)).fetchone():
                raise ValueError("연결된 반품이 있어 원전표를 취소할 수 없습니다.")
            if record["kind"] == "sale_return" and (record["points_used"] or record["points_earned"]):
                raise ValueError("포인트가 복원된 반품은 취소할 수 없습니다. 회원 포인트 이력을 보존합니다.")
            moves = list(self.db.execute("SELECT * FROM stock_events WHERE document_id=? ORDER BY id DESC", (identifier,)))
            for product_id in {move["product_id"] for move in moves}:
                latest = self.db.execute("SELECT document_id FROM stock_events WHERE product_id=? ORDER BY id DESC LIMIT 1",
                                         (product_id,)).fetchone()
                if latest["document_id"] != identifier:
                    raise ValueError("이후 재고 이동이 있어 단순 취소할 수 없습니다. 원전표 반품을 이용하세요.")
            if record["kind"] == "sale" and record["member_id"] and (record["points_used"] or record["points_earned"]):
                self._reverse_sale_points(identifier, identifier, record["total"])
            for move in moves:
                self._move(move["product_id"], -move["qty_delta"], -move["cost_delta"], "cancel", reason,
                           identifier, record["date"])
            self.db.execute("UPDATE documents SET status='cancelled',cancel_reason=? WHERE id=?", (reason, identifier))
            self._audit("cancel", "document", identifier, {"reason": reason})

    def ledger(self, partner_id, start="", end=""):
        self._require("trade")
        partner = self.db.execute("SELECT * FROM partners WHERE id=?", (partner_id,)).fetchone()
        if not partner:
            raise ValueError("거래처를 찾을 수 없습니다.")
        first, last = day(start) if start else "0001-01-01", day(end) if end else "9999-12-31"
        if first > last:
            raise ValueError("조회 시작일이 종료일보다 늦습니다.")
        entries = []
        if partner["opening_balance"]:
            entries.append({"date": partner["opening_date"], "kind": "opening", "number": "이월잔액",
                            "charge": partner["opening_balance"], "payment": 0, "memo": "초기 외상 잔액", "order": -1})
        for payment in self.db.execute("SELECT * FROM supplier_settlements WHERE partner_id=? AND opening_amount>0 AND voided=0", (partner_id,)):
            entries.append({"date": payment["date"], "kind": "payment", "number": f"결제-{payment['id']:06d}", "charge": 0, "payment": payment["opening_amount"], "memo": payment["memo"], "settlement_id": payment["id"], "order": 0})
        for record in self.db.execute("SELECT * FROM documents WHERE partner_id=? AND status='posted'", (partner_id,)):
            sign = -1 if record["source_id"] else 1
            entries.append({"date": record["date"], "kind": record["kind"], "number": record["number"],
                            "charge": sign * (record["total"] - record["points_used"]), "payment": 0,
                            "memo": record["memo"], "document_id": record["id"], "order": record["id"] * 2})
        for payment in self.db.execute(
            "SELECT p.*,d.number FROM payments p JOIN documents d ON d.id=p.document_id "
            "WHERE p.partner_id=? AND p.voided=0 AND d.status='posted'", (partner_id,),
        ):
            entries.append({"date": payment["date"], "kind": "refund" if payment["amount"] < 0 else "payment",
                            "number": payment["number"], "charge": 0, "payment": payment["amount"],
                            "memo": payment["memo"], "document_id": payment["document_id"],
                            "payment_id": payment["id"], "order": payment["document_id"] * 2 + 1})
        entries.sort(key=lambda item: (item["date"], item["order"], item.get("payment_id", 0)))
        opening = sum(item["charge"] - item["payment"] for item in entries if item["date"] < first)
        visible, balance = [], opening
        for item in entries:
            if first <= item["date"] <= last:
                balance += item["charge"] - item["payment"]
                item.pop("order")
                visible.append({**item, "balance": balance})
        return {"opening": opening, "charge": sum(item["charge"] for item in visible),
                "payment": sum(item["payment"] for item in visible), "closing": balance, "entries": visible}
