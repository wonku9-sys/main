"""Catalogue, counterparties and pack units, written for the standalone edition."""

from datetime import date
import json

from .common import day, money, now, qtext, qty, rounded, text

PRODUCT_TEXT = ("code", "barcode", "name", "receipt_name", "category", "category_mid", "category_small", "specification", "base_unit", "origin", "warehouse", "shelf", "keywords", "memo")
PARTNER_TEXT = ("code", "name", "business_no", "contact", "phone", "bank", "account", "account_holder", "memo")


class CatalogMixin:
    def _next_code(self, table, prefix, kind=None):
        number = 1
        while self.db.execute(f"SELECT 1 FROM {table} WHERE code=?" + (" AND kind=?" if kind else ""), ((f"{prefix}{number:05d}", kind) if kind else (f"{prefix}{number:05d}",))).fetchone():
            number += 1
        return f"{prefix}{number:05d}"

    def _partner_balance(self, identifier):
        opening = self.db.execute("SELECT opening_balance FROM partners WHERE id=?", (identifier,)).fetchone()[0]
        charge = self.db.execute("SELECT COALESCE(SUM(CASE WHEN kind IN ('purchase_return','sale_return') THEN -(total-points_used) ELSE total-points_used END),0) FROM documents WHERE partner_id=? AND status='posted'", (identifier,)).fetchone()[0]
        paid = self.db.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE partner_id=? AND voided=0", (identifier,)).fetchone()[0]
        return opening + charge - paid

    def partners(self, kind, search=""):
        self._require("catalog", "trade", "reports")
        if kind not in {"supplier", "customer"}:
            raise ValueError("거래처 유형을 확인하세요.")
        term = f"%{text(search)}%"
        result = []
        for row in self.db.execute("SELECT * FROM partners WHERE kind=? AND (name LIKE ? OR code LIKE ? OR phone LIKE ? OR business_no LIKE ?) ORDER BY code", (kind, term, term, term, term)):
            item = dict(row)
            item["balance"] = self._partner_balance(row["id"])
            result.append(item)
        return result

    def save_partner(self, data, id=None):
        with self._tx():
            self._require("catalog")
            old = self.db.execute("SELECT * FROM partners WHERE id=?", (id,)).fetchone() if id else None
            if id and not old:
                raise ValueError("거래처를 찾을 수 없습니다.")
            values = dict(old) if old else {key: "" for key in PARTNER_TEXT}
            values.update({key: text(data.get(key, values[key]), key, key == "name", 2000 if key == "memo" else 200) for key in PARTNER_TEXT})
            values["kind"] = data.get("kind", old["kind"] if old else "supplier")
            if values["kind"] not in {"supplier", "customer"}:
                raise ValueError("거래처 유형을 확인하세요.")
            if old and old["kind"] != values["kind"]:
                raise ValueError("공급사와 판매처 유형은 변경할 수 없습니다.")
            values["code"] = values["code"] or self._next_code("partners", "S" if values["kind"] == "supplier" else "C", values["kind"])
            values["active"] = int(bool(data.get("active", old["active"] if old else True)))
            values["opening_balance"] = rounded(data.get("opening_balance", old["opening_balance"] if old else 0))
            values["opening_date"] = day(data.get("opening_date", old["opening_date"] if old else date.today().isoformat()))
            values["supplier_mode"] = data.get("supplier_mode", old["supplier_mode"] if old else "direct")
            if values["supplier_mode"] not in {"direct", "commission"}:
                raise ValueError("공급사 거래 유형을 확인하세요.")
            raw_bps = str(data.get("commission_bps", old["commission_bps"] if old else 0))
            try:
                values["commission_bps"] = int(raw_bps)
            except ValueError:
                raise ValueError("수수료율은 정수 기준점으로 입력하세요.") from None
            if not 0 <= values["commission_bps"] <= 10000:
                raise ValueError("수수료율은 0~100% 범위여야 합니다.")
            if old and (values["opening_balance"] != old["opening_balance"] or values["opening_date"] != old["opening_date"]):
                if self.db.execute("SELECT 1 FROM documents WHERE partner_id=? UNION ALL SELECT 1 FROM payments WHERE partner_id=? LIMIT 1", (id, id)).fetchone():
                    raise ValueError("거래 이력이 있는 거래처의 초기 외상과 기준일은 변경할 수 없습니다.")
            columns = PARTNER_TEXT + ("kind", "active", "opening_balance", "opening_date", "supplier_mode", "commission_bps")
            if old:
                self.db.execute("UPDATE partners SET " + ",".join(f"{key}=?" for key in columns) + " WHERE id=?", tuple(values[key] for key in columns) + (id,))
            else:
                id = self.db.execute("INSERT INTO partners(" + ",".join(columns) + ") VALUES(" + ",".join("?" for _ in columns) + ")", tuple(values[key] for key in columns)).lastrowid
            self._audit("update" if old else "create", "partner", id, {"name": values["name"], "kind": values["kind"]})
        return id

    def delete_partner(self, id):
        with self._tx():
            self._require("catalog")
            row = self.db.execute("SELECT * FROM partners WHERE id=?", (id,)).fetchone()
            if not row:
                raise ValueError("거래처를 찾을 수 없습니다.")
            if row["opening_balance"]:
                raise ValueError("초기 외상이 있는 거래처는 삭제하지 말고 비활성화하세요.")
            self.db.execute("DELETE FROM partners WHERE id=?", (id,))
            self._audit("delete", "partner", id, {"name": row["name"]})

    def _public_product(self, row):
        result = dict(row)
        result["stock_qty"], result["min_qty"] = qtext(row["stock_qty"]), qtext(row["min_qty"])
        return result

    def products(self, search="", supplier_id=None, category="", active_only=False):
        self._require("catalog", "trade", "inventory", "reports", "loyalty")
        term = f"%{text(search)}%"
        sql = "SELECT p.*,s.name AS supplier_name FROM products p LEFT JOIN partners s ON s.id=p.supplier_id WHERE (p.name LIKE ? OR p.code LIKE ? OR p.barcode LIKE ? OR p.keywords LIKE ? OR p.receipt_name LIKE ? OR EXISTS(SELECT 1 FROM product_units u WHERE u.product_id=p.id AND u.barcode LIKE ?))"
        params = [term] * 6
        if supplier_id is not None:
            sql += " AND p.supplier_id=?"
            params.append(supplier_id)
        if category:
            sql += " AND p.category=?"
            params.append(category)
        if active_only:
            sql += " AND p.active=1"
        return [self._public_product(row) for row in self.db.execute(sql + " ORDER BY p.code", params)]

    def trade_products(self, search="", supplier_id=None):
        self._require("trade")
        return self.products(search=search, supplier_id=supplier_id, active_only=True)

    def _product_used(self, identifier):
        return bool(self.db.execute("SELECT 1 FROM document_lines WHERE product_id=? UNION ALL SELECT 1 FROM stock_events WHERE product_id=? UNION ALL SELECT 1 FROM inventory_count_lines WHERE product_id=? UNION ALL SELECT 1 FROM inventory_close_lines WHERE product_id=? LIMIT 1", (identifier, identifier, identifier, identifier)).fetchone())

    def save_product(self, data, id=None):
        with self._tx():
            self._require("catalog")
            old = self.db.execute("SELECT * FROM products WHERE id=?", (id,)).fetchone() if id else None
            if id and not old:
                raise ValueError("상품을 찾을 수 없습니다.")
            values = dict(old) if old else {key: "" for key in PRODUCT_TEXT}
            values.update({key: text(data.get(key, values[key]), key, key == "name", 4000 if key == "memo" else 300) for key in PRODUCT_TEXT})
            values["code"] = values["code"] or self._next_code("products", "P")
            values["category"] = values["category"] or "미분류"
            values["base_unit"] = values["base_unit"] or "kg"
            values["supplier_id"] = data.get("supplier_id", old["supplier_id"] if old else None) or None
            if values["supplier_id"]:
                supplier = self.db.execute("SELECT * FROM partners WHERE id=?", (values["supplier_id"],)).fetchone()
                if not supplier or supplier["kind"] != "supplier":
                    raise ValueError("상품의 공급사를 확인하세요.")
            values["tax_mode"] = data.get("tax_mode", old["tax_mode"] if old else "exempt")
            if values["tax_mode"] not in {"exempt", "taxable"}:
                raise ValueError("과세·면세 구분을 확인하세요.")
            for key in ("tracked", "active"):
                values[key] = int(bool(data.get(key, old[key] if old else True)))
            for key in ("purchase_price", "sale_price"):
                values[key] = money(data.get(key, old[key] if old else 0))
            values["min_qty"] = qty(data["min_qty"], allow_zero=True) if "min_qty" in data else old["min_qty"] if old else 0
            if old:
                used = self._product_used(id)
                if values["base_unit"] != old["base_unit"] and (used or self.db.execute("SELECT 1 FROM product_units WHERE product_id=?", (id,)).fetchone()):
                    raise ValueError("이력 또는 확장단위가 있는 상품의 기본단위는 변경할 수 없습니다.")
                if values["tracked"] != old["tracked"] and (used or old["stock_qty"] or old["stock_cost"]):
                    raise ValueError("재고 또는 이력이 있는 상품의 재고관리 설정은 변경할 수 없습니다.")
            values["updated_at"] = now()
            columns = PRODUCT_TEXT + ("supplier_id", "tax_mode", "tracked", "active", "purchase_price", "sale_price", "min_qty", "updated_at")
            if old:
                self.db.execute("UPDATE products SET " + ",".join(f"{key}=?" for key in columns) + " WHERE id=?", tuple(values[key] for key in columns) + (id,))
            else:
                columns += ("created_at",)
                values["created_at"] = values["updated_at"]
                id = self.db.execute("INSERT INTO products(" + ",".join(columns) + ") VALUES(" + ",".join("?" for _ in columns) + ")", tuple(values[key] for key in columns)).lastrowid
            changes = {key: {"old": old[key] if old else None, "new": values[key]} for key in columns if not old or old[key] != values[key]}
            self._audit("update" if old else "create", "product", id, {"changes": changes})
        return id

    def delete_product(self, id):
        with self._tx():
            self._require("catalog")
            row = self.db.execute("SELECT * FROM products WHERE id=?", (id,)).fetchone()
            if not row:
                raise ValueError("상품을 찾을 수 없습니다.")
            if self._product_used(id) or row["stock_qty"] or row["stock_cost"]:
                raise ValueError("거래·재고 이력이 있는 상품은 삭제하지 말고 비활성화하세요.")
            self.db.execute("DELETE FROM product_units WHERE product_id=?", (id,))
            self.db.execute("DELETE FROM products WHERE id=?", (id,))
            self._audit("delete", "product", id, {"name": row["name"]})

    def units(self, product_id):
        self._require("catalog", "trade", "inventory", "reports", "loyalty")
        return [{**dict(row), "factor": qtext(row["factor"])} for row in self.db.execute("SELECT * FROM product_units WHERE product_id=? ORDER BY id", (product_id,))]

    def trade_units(self, product_id):
        self._require("trade")
        return [item for item in self.units(product_id) if item["active"]]

    def save_unit(self, data, id=None):
        with self._tx():
            self._require("catalog")
            old = self.db.execute("SELECT * FROM product_units WHERE id=?", (id,)).fetchone() if id else None
            if id and not old:
                raise ValueError("확장단위를 찾을 수 없습니다.")
            product_id = data.get("product_id", old["product_id"] if old else None)
            if not self.db.execute("SELECT 1 FROM products WHERE id=?", (product_id,)).fetchone():
                raise ValueError("상품을 먼저 저장하세요.")
            if old and product_id != old["product_id"]:
                raise ValueError("확장단위의 상품은 변경할 수 없습니다.")
            factor = qty(data["factor"]) if "factor" in data else old["factor"] if old else 1000
            if old and factor != old["factor"] and self.db.execute("SELECT 1 FROM document_lines WHERE unit_id=?", (id,)).fetchone():
                raise ValueError("거래에 사용된 확장단위의 환산량은 변경할 수 없습니다.")
            values = (product_id, text(data.get("name", old["name"] if old else ""), "단위명", True, 80), text(data.get("barcode", old["barcode"] if old else ""), "바코드", maximum=100), factor, money(data.get("purchase_price", old["purchase_price"] if old else 0)), money(data.get("sale_price", old["sale_price"] if old else 0)), int(bool(data.get("active", old["active"] if old else True))))
            if old:
                self.db.execute("UPDATE product_units SET product_id=?,name=?,barcode=?,factor=?,purchase_price=?,sale_price=?,active=? WHERE id=?", values + (id,))
            else:
                id = self.db.execute("INSERT INTO product_units(product_id,name,barcode,factor,purchase_price,sale_price,active) VALUES(?,?,?,?,?,?,?)", values).lastrowid
            self._audit("update_unit" if old else "create_unit", "product", product_id, {"unit_id": id, "name": values[1], "barcode": values[2], "factor": qtext(factor), "purchase_price": values[4], "sale_price": values[5]})
        return id

    def delete_unit(self, id):
        with self._tx():
            self._require("catalog")
            row = self.db.execute("SELECT * FROM product_units WHERE id=?", (id,)).fetchone()
            if not row:
                raise ValueError("확장단위를 찾을 수 없습니다.")
            self.db.execute("DELETE FROM product_units WHERE id=?", (id,))
            self._audit("delete_unit", "product", row["product_id"], {"unit_id": id, "name": row["name"]})

    def lookup_barcode(self, barcode):
        self._require("catalog", "trade", "inventory")
        barcode = text(barcode)
        if not barcode:
            return None
        row = self.db.execute("SELECT * FROM products WHERE barcode=? AND active=1", (barcode,)).fetchone()
        if row:
            return {"product": self._public_product(row), "unit": None}
        unit = self.db.execute("SELECT u.* FROM product_units u JOIN products p ON p.id=u.product_id WHERE u.barcode=? AND u.active=1 AND p.active=1", (barcode,)).fetchone()
        if not unit:
            return None
        product = self.db.execute("SELECT * FROM products WHERE id=?", (unit["product_id"],)).fetchone()
        return {"product": self._public_product(product), "unit": {**dict(unit), "factor": qtext(unit["factor"])}}

    def bulk_category(self, ids, category):
        category = text(category, "분류", True, 300)
        unique = list(dict.fromkeys(ids))
        if not unique:
            raise ValueError("상품을 선택하세요.")
        with self._tx():
            self._require("catalog")
            for identifier in unique:
                row = self.db.execute("SELECT category FROM products WHERE id=?", (identifier,)).fetchone()
                if not row:
                    raise ValueError("선택한 상품 중 존재하지 않는 상품이 있습니다.")
                self.db.execute("UPDATE products SET category=?,updated_at=? WHERE id=?", (category, now(), identifier))
                self._audit("bulk_category", "product", identifier, {"changes": {"category": {"old": row[0], "new": category}}})

    def product_history(self, product_id):
        self._require("catalog", "reports")
        if not self.db.execute("SELECT 1 FROM products WHERE id=?", (product_id,)).fetchone():
            raise ValueError("상품을 찾을 수 없습니다.")
        result = {"purchases": [], "sales": [], "stock": []}
        for row in self.db.execute("SELECT d.id AS document_id,d.number,d.date,d.kind,d.status,p.name AS partner_name,l.input_qty,l.base_qty,l.unit_name,l.unit_price,l.total FROM document_lines l JOIN documents d ON d.id=l.document_id JOIN partners p ON p.id=d.partner_id WHERE l.product_id=? ORDER BY d.date DESC,d.id DESC", (product_id,)):
            item = dict(row)
            item["qty"], item["base_qty"] = qtext(item.pop("input_qty")), qtext(item["base_qty"])
            result["purchases" if item["kind"].startswith("purchase") else "sales"].append(item)
        result["stock"] = [{**dict(row), "qty_delta": qtext(row["qty_delta"]), "balance_qty": qtext(row["balance_qty"])} for row in self.db.execute("SELECT * FROM stock_events WHERE product_id=? ORDER BY id DESC", (product_id,))]
        return result

    def product_audit(self, product_id):
        self._require("catalog", "reports")
        return [dict(row) for row in self.db.execute("SELECT a.id,a.at,a.action,a.detail,u.name AS user_name FROM audit a LEFT JOIN users u ON u.id=a.user_id WHERE a.entity='product' AND a.entity_id=? ORDER BY a.id DESC", (product_id,))]
