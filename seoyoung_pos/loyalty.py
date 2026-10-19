"""Local member point ledgers and date-limited product prices.

No card provider, network account, automatic point accrual, or background
service is involved. Corrections to points are new compensating entries;
historical entries are never overwritten.
"""

from __future__ import annotations

from datetime import date as Date, datetime
from decimal import Decimal, DecimalException


def _text(value) -> str:
    return "" if value is None else str(value).strip()


def _active(value) -> int:
    if not isinstance(value, (bool, int)) or value not in (False, True):
        raise ValueError("사용 여부는 사용 또는 중지로 선택해 주세요.")
    return int(value)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class LoyaltyMixin:
    """Additive business functions mixed into :class:`POSService`."""

    def _migrate_loyalty(self):
        """Create local tables atomically without replacing existing data."""
        statements = (
            """CREATE TABLE IF NOT EXISTS members (
                id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE COLLATE NOCASE,
                name TEXT NOT NULL, phone TEXT NOT NULL DEFAULT '',
                memo TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1 CHECK(active IN(0,1)),
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS point_movements (
                id INTEGER PRIMARY KEY, member_id INTEGER NOT NULL REFERENCES members(id),
                date TEXT NOT NULL,
                points INTEGER NOT NULL CHECK(points<>0 AND ABS(points)<=9000000000000),
                balance INTEGER NOT NULL CHECK(balance>=0 AND balance<=9000000000000),
                reason TEXT NOT NULL CHECK(LENGTH(TRIM(reason))>0),
                user_id INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL)""",
            """CREATE INDEX IF NOT EXISTS point_member_history
                ON point_movements(member_id,id)""",
            """CREATE TRIGGER IF NOT EXISTS point_movements_no_update
                BEFORE UPDATE ON point_movements BEGIN
                SELECT RAISE(ABORT,'point history is immutable'); END""",
            """CREATE TRIGGER IF NOT EXISTS point_movements_no_delete
                BEFORE DELETE ON point_movements BEGIN
                SELECT RAISE(ABORT,'point history is immutable'); END""",
            """CREATE TABLE IF NOT EXISTS promotions (
                id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id),
                title TEXT NOT NULL, date_from TEXT NOT NULL, date_to TEXT NOT NULL,
                purchase_price INTEGER CHECK(purchase_price IS NULL OR purchase_price>=0),
                sale_price INTEGER CHECK(sale_price IS NULL OR sale_price>=0),
                active INTEGER NOT NULL DEFAULT 1 CHECK(active IN(0,1)),
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                CHECK(date_from<=date_to),
                CHECK(purchase_price IS NOT NULL OR sale_price IS NOT NULL))""",
            """CREATE INDEX IF NOT EXISTS promotion_product_dates
                ON promotions(product_id,active,date_from,date_to)""",
        )
        with self._transaction():
            for statement in statements:
                self.db.execute(statement)
        # Each table is self-describing and IF NOT EXISTS makes this idempotent.
        # The central schema migration owns user_version; never lower it here.

    def list_members(self, search="", active_only=False) -> list[dict]:
        self._require("members", "reports")
        clauses = ["(m.code LIKE ? OR m.name LIKE ? OR m.phone LIKE ?)"]
        params = [f"%{_text(search)}%"] * 3
        if active_only:
            clauses.append("m.active=1")
        rows = self.db.execute("""SELECT m.*, COALESCE((SELECT SUM(points)
            FROM point_movements pm WHERE pm.member_id=m.id),0) AS points
            FROM members m WHERE """ + " AND ".join(clauses) + " ORDER BY m.name,m.id", params)
        result = []
        for row in rows:
            member = dict(row)
            member["active"] = bool(member["active"])
            result.append(member)
        return result

    def save_member(self, data, member_id=None) -> int:
        self._require("members")
        with self._transaction():
            self._require("members")
            old = self.db.execute("SELECT * FROM members WHERE id=?", (member_id,)).fetchone() if member_id is not None else None
            if member_id is not None and old is None:
                raise ValueError("회원을 찾을 수 없습니다.")
            fields = ("code", "name", "phone", "memo")
            values = {key: _text(data.get(key, old[key] if old else "")) for key in fields}
            if not values["code"] or not values["name"]:
                raise ValueError("회원 코드와 이름을 입력해 주세요.")
            values["active"] = _active(data.get("active", old["active"] if old else True))
            values["updated_at"] = _now()
            if old is None:
                values["created_at"] = values["updated_at"]
                member_id = self.db.execute(
                    f"INSERT INTO members({','.join(values)}) VALUES({','.join('?' for _ in values)})",
                    tuple(values.values()),
                ).lastrowid
                action = "create"
            else:
                self.db.execute(f"UPDATE members SET {','.join(key+'=?' for key in values)} WHERE id=?",
                                (*values.values(), member_id))
                action = "update"
            self._audit(action, "member", member_id, {"code": values["code"], "name": values["name"], "active": bool(values["active"])})
        return member_id

    def delete_member(self, member_id):
        self._require("members")
        with self._transaction():
            self._require("members")
            if self.db.execute("SELECT 1 FROM point_movements WHERE member_id=? LIMIT 1", (member_id,)).fetchone():
                raise ValueError("포인트 이력이 있는 회원은 삭제할 수 없습니다. 사용 중지를 선택해 주세요.")
            if not self.db.execute("DELETE FROM members WHERE id=?", (member_id,)).rowcount:
                raise ValueError("회원을 찾을 수 없습니다.")
            self._audit("delete", "member", member_id, {})

    def _member_balance(self, member_id) -> int:
        if not self.db.execute("SELECT 1 FROM members WHERE id=?", (member_id,)).fetchone():
            raise ValueError("회원을 찾을 수 없습니다.")
        return self.db.execute("SELECT COALESCE(SUM(points),0) FROM point_movements WHERE member_id=?", (member_id,)).fetchone()[0]

    def member_points(self, member_id) -> int:
        self._require("members", "reports")
        return self._member_balance(member_id)

    def member_point_history(self, member_id) -> list[dict]:
        self._require("members", "reports")
        self._member_balance(member_id)
        rows = self.db.execute("""SELECT pm.*, u.username FROM point_movements pm
            JOIN users u ON u.id=pm.user_id WHERE member_id=? ORDER BY pm.id DESC""", (member_id,))
        return [dict(row) for row in rows]

    def adjust_member_points(self, member_id, points, reason, date=None) -> int:
        from .service import MAX_INTEGER, _day

        self._require("members")
        reason = _text(reason)
        if not reason:
            raise ValueError("포인트 변경 사유를 입력해 주세요.")
        try:
            value = Decimal(str(points))
            if not value.is_finite() or value == 0 or abs(value) > MAX_INTEGER or value != value.to_integral_value():
                raise ValueError
            delta = int(value)
        except (ValueError, DecimalException, TypeError, OverflowError):
            raise ValueError("변경 포인트는 0이 아닌 정수로 입력해 주세요.") from None
        day = _day(date if date is not None else Date.today().isoformat())
        with self._transaction():
            self._require("members")
            balance = self._member_balance(member_id) + delta
            member = self.db.execute("SELECT active FROM members WHERE id=?", (member_id,)).fetchone()
            if not member["active"]:
                raise ValueError("사용 중지된 회원의 포인트는 변경할 수 없습니다.")
            if balance < 0:
                raise ValueError("사용할 포인트가 현재 잔액보다 많습니다.")
            if balance > MAX_INTEGER:
                raise ValueError("포인트 잔액이 허용 범위를 초과했습니다.")
            movement_id = self.db.execute("""INSERT INTO point_movements
                (member_id,date,points,balance,reason,user_id,created_at) VALUES(?,?,?,?,?,?,?)""",
                (member_id, day, delta, balance, reason, self.user["id"], _now())).lastrowid
            self._audit("adjust_points", "member", member_id,
                        {"movement_id": movement_id, "points": delta, "balance": balance, "reason": reason, "date": day})
        return movement_id

    def list_promotion_products(self, search="") -> list[dict]:
        """Expose only fields needed by the promotion product selector."""
        self._require("promotions", "reports")
        rows = self.db.execute("""SELECT id,code,name,unit,purchase_price,sale_price
            FROM products WHERE code LIKE ? OR name LIKE ? OR barcode LIKE ? ORDER BY name,id""",
            [f"%{_text(search)}%"] * 3)
        return [dict(row) for row in rows]

    def list_promotions(self, search="", product_id=None, active_only=False, on_date=None) -> list[dict]:
        from .service import _day

        self._require("promotions", "reports")
        clauses = ["(p.title LIKE ? OR pr.name LIKE ? OR pr.code LIKE ?)"]
        params = [f"%{_text(search)}%"] * 3
        if product_id is not None:
            clauses.append("p.product_id=?")
            params.append(product_id)
        if active_only:
            clauses.append("p.active=1")
        if on_date is not None:
            day = _day(on_date)
            clauses.append("p.date_from<=? AND p.date_to>=?")
            params.extend((day, day))
        rows = self.db.execute("""SELECT p.*, pr.name AS product_name, pr.code AS product_code, pr.unit
            FROM promotions p JOIN products pr ON pr.id=p.product_id WHERE """ + " AND ".join(clauses) + " ORDER BY p.date_from DESC,p.id DESC", params)
        result = []
        for row in rows:
            promotion = dict(row)
            promotion["active"] = bool(promotion["active"])
            result.append(promotion)
        return result

    def save_promotion(self, data, promotion_id=None) -> int:
        from .service import _day, _integer

        self._require("promotions")
        with self._transaction():
            self._require("promotions")
            old = self.db.execute("SELECT * FROM promotions WHERE id=?", (promotion_id,)).fetchone() if promotion_id is not None else None
            if promotion_id is not None and old is None:
                raise ValueError("특매 정보를 찾을 수 없습니다.")
            values = {key: data.get(key, old[key] if old else None)
                      for key in ("product_id", "title", "date_from", "date_to", "purchase_price", "sale_price")}
            values["title"] = _text(values["title"])
            if not values["title"]:
                raise ValueError("특매 제목을 입력해 주세요.")
            if not self.db.execute("SELECT 1 FROM products WHERE id=?", (values["product_id"],)).fetchone():
                raise ValueError("특매를 적용할 상품을 선택해 주세요.")
            values["date_from"], values["date_to"] = _day(values["date_from"]), _day(values["date_to"])
            if values["date_from"] > values["date_to"]:
                raise ValueError("특매 시작일은 종료일보다 늦을 수 없습니다.")
            for key, label in (("purchase_price", "특매 매입 단가"), ("sale_price", "특매 판매 단가")):
                raw = values[key]
                values[key] = None if raw is None or isinstance(raw, str) and not raw.strip() else _integer(raw, label)
            if values["purchase_price"] is None and values["sale_price"] is None:
                raise ValueError("특매 매입 단가 또는 판매 단가를 하나 이상 입력해 주세요.")
            values["active"] = _active(data.get("active", old["active"] if old else True))
            if values["active"] and self.db.execute("""SELECT 1 FROM promotions WHERE product_id=?
                AND active=1 AND date_from<=? AND date_to>=? AND id<>? LIMIT 1""",
                (values["product_id"], values["date_to"], values["date_from"], promotion_id if promotion_id is not None else -1)).fetchone():
                raise ValueError("이 상품에는 해당 기간과 겹치는 특매가 있습니다. 기간을 변경하거나 기존 특매를 중지해 주세요.")
            values["updated_at"] = _now()
            if old is None:
                values["created_at"] = values["updated_at"]
                promotion_id = self.db.execute(
                    f"INSERT INTO promotions({','.join(values)}) VALUES({','.join('?' for _ in values)})",
                    tuple(values.values()),
                ).lastrowid
                action = "create"
            else:
                self.db.execute(f"UPDATE promotions SET {','.join(key+'=?' for key in values)} WHERE id=?",
                                (*values.values(), promotion_id))
                action = "update"
            self._audit(action, "promotion", promotion_id,
                        {key: values[key] for key in ("product_id", "title", "date_from", "date_to", "purchase_price", "sale_price", "active")})
        return promotion_id

    def delete_promotion(self, promotion_id):
        self._require("promotions")
        with self._transaction():
            self._require("promotions")
            if not self.db.execute("DELETE FROM promotions WHERE id=?", (promotion_id,)).rowcount:
                raise ValueError("특매 정보를 찾을 수 없습니다.")
            # Posted document items contain their own unit_price snapshots.
            self._audit("delete", "promotion", promotion_id, {})

    def get_effective_price(self, product_id, date, kind="sale") -> int:
        """Return an integer price; never retroactively rewrite a document."""
        from .service import _day

        if kind not in {"purchase", "sale"}:
            raise ValueError("전표 종류가 올바르지 않습니다.")
        self._require("products", "promotions", "reports", "purchases" if kind == "purchase" else "sales")
        day = _day(date)
        column = "purchase_price" if kind == "purchase" else "sale_price"
        product = self.db.execute(f"SELECT {column} FROM products WHERE id=?", (product_id,)).fetchone()
        if not product:
            raise ValueError("상품을 찾을 수 없습니다.")
        promotion = self.db.execute(f"""SELECT {column} FROM promotions WHERE product_id=?
            AND active=1 AND date_from<=? AND date_to>=? ORDER BY date_from DESC,id DESC LIMIT 1""",
            (product_id, day, day)).fetchone()
        return promotion[column] if promotion and promotion[column] is not None else product[column]
