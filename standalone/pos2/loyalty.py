"""Local member, promotion, price and immutable point books for the new POS.

Prices are resolved for the transaction date, without clocks, services or changing
the product master.  A point is one won; gift stock is an integer item count.
"""

import json
import sqlite3
from decimal import Decimal

from .common import LIMIT, day, decimal, money, now, rounded, text
from .currency import amount as currency_amount


LOYALTY_SCHEMA = """
CREATE TABLE IF NOT EXISTS members (
 id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
 phone TEXT NOT NULL DEFAULT '', birthday TEXT NOT NULL DEFAULT '', memo TEXT NOT NULL DEFAULT '',
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
 points INTEGER NOT NULL DEFAULT 0 CHECK(points BETWEEN 0 AND 9000000000000),
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS member_prices (
 id INTEGER PRIMARY KEY, member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
 product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
 price INTEGER NOT NULL CHECK(price BETWEEN 0 AND 9000000000000),
 UNIQUE(member_id,product_id)
);
CREATE TABLE IF NOT EXISTS member_contact_types (
 member_id INTEGER PRIMARY KEY REFERENCES members(id) ON DELETE CASCADE,
 phone_type TEXT NOT NULL CHECK(length(phone_type) BETWEEN 1 AND 50)
);
CREATE TABLE IF NOT EXISTS promotions (
 id INTEGER PRIMARY KEY, title TEXT NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL,
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)), created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS promotion_items (
 id INTEGER PRIMARY KEY, promotion_id INTEGER NOT NULL REFERENCES promotions(id) ON DELETE RESTRICT,
 product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
 purchase_price INTEGER CHECK(purchase_price BETWEEN 0 AND 9000000000000),
 sale_price INTEGER CHECK(sale_price BETWEEN 0 AND 9000000000000),
 UNIQUE(promotion_id,product_id), CHECK(purchase_price IS NOT NULL OR sale_price IS NOT NULL)
);
CREATE TABLE IF NOT EXISTS price_schedules (
 id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
 date TEXT NOT NULL, title TEXT NOT NULL DEFAULT '',
 purchase_price INTEGER CHECK(purchase_price BETWEEN 0 AND 9000000000000),
 sale_price INTEGER CHECK(sale_price BETWEEN 0 AND 9000000000000),
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)), created_at TEXT NOT NULL,
 CHECK(purchase_price IS NOT NULL OR sale_price IS NOT NULL)
);
CREATE UNIQUE INDEX IF NOT EXISTS schedule_product_day ON price_schedules(product_id,date) WHERE active=1;
CREATE TABLE IF NOT EXISTS point_entries (
 id INTEGER PRIMARY KEY, member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
 date TEXT NOT NULL, kind TEXT NOT NULL, delta INTEGER NOT NULL CHECK(ABS(delta)<=9000000000000),
 balance INTEGER NOT NULL CHECK(balance BETWEEN 0 AND 9000000000000), reason TEXT NOT NULL,
 document_id INTEGER REFERENCES documents(id) ON DELETE RESTRICT,
 source_id INTEGER REFERENCES documents(id) ON DELETE RESTRICT,
 gift_redemption_id INTEGER REFERENCES gift_redemptions(id) ON DELETE RESTRICT,
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT, created_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS point_entries_immutable_update BEFORE UPDATE ON point_entries
 BEGIN SELECT RAISE(ABORT,'포인트 원장은 수정할 수 없습니다. 조정 전표를 등록하세요.'); END;
CREATE TRIGGER IF NOT EXISTS point_entries_immutable_delete BEFORE DELETE ON point_entries
 BEGIN SELECT RAISE(ABORT,'포인트 원장은 삭제할 수 없습니다. 조정 전표를 등록하세요.'); END;
CREATE TABLE IF NOT EXISTS loyalty_sale_actions (
 document_id INTEGER PRIMARY KEY REFERENCES documents(id) ON DELETE RESTRICT,
 member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
 points_used INTEGER NOT NULL, points_earned INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS loyalty_return_actions (
 document_id INTEGER PRIMARY KEY REFERENCES documents(id) ON DELETE RESTRICT,
 source_document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE RESTRICT,
 return_total INTEGER NOT NULL, restored_used INTEGER NOT NULL, reversed_earned INTEGER NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('return','cancel'))
);
CREATE TABLE IF NOT EXISTS gifts (
 id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
 points INTEGER NOT NULL CHECK(points BETWEEN 1 AND 9000000000000),
 stock INTEGER NOT NULL DEFAULT 0 CHECK(stock BETWEEN 0 AND 9000000000000),
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)), created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gift_redemptions (
 id INTEGER PRIMARY KEY, member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
 gift_id INTEGER NOT NULL REFERENCES gifts(id) ON DELETE RESTRICT, gift_name TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('redeem','return')),
 source_id INTEGER REFERENCES gift_redemptions(id) ON DELETE RESTRICT,
 qty INTEGER NOT NULL CHECK(qty>0), points INTEGER NOT NULL CHECK(points>0),
 reason TEXT NOT NULL, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 created_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS gift_redemptions_immutable_update BEFORE UPDATE ON gift_redemptions
 BEGIN SELECT RAISE(ABORT,'사은품 지급 원장은 수정할 수 없습니다. 반품으로 처리하세요.'); END;
CREATE TRIGGER IF NOT EXISTS gift_redemptions_immutable_delete BEFORE DELETE ON gift_redemptions
 BEGIN SELECT RAISE(ABORT,'사은품 지급 원장은 삭제할 수 없습니다. 반품으로 처리하세요.'); END;
CREATE INDEX IF NOT EXISTS points_member_date ON point_entries(member_id,date,id);
CREATE INDEX IF NOT EXISTS gifts_member ON gift_redemptions(member_id,id);
"""


def integer(value, label, positive=False, signed=False):
    value = decimal(value)
    if value != value.to_integral_value() or abs(value) > LIMIT:
        raise ValueError(f"{label}은(는) 허용 범위 내의 정수로 입력하세요.")
    if (not signed and value < 0) or (positive and value <= 0):
        raise ValueError(f"{label}은(는) {'1 이상' if positive else '0 이상'}이어야 합니다.")
    return int(value)


class LoyaltyMixin:
    def _init_loyalty(self):
        self.db.executescript(LOYALTY_SCHEMA)
        for key, value in {"earn_bps": 100, "point_min": 1000, "point_step": 100,
                           "point_enabled": True}.items():
            self.db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (key, json.dumps(value)))

    def _loyalty_require_any(self, *permissions):
        for permission in permissions:
            try:
                self._require(permission)
                return
            except PermissionError:
                pass
        raise PermissionError("이 작업에 필요한 접근 권한이 없습니다.")

    def _member_row(self, member_id, active=False):
        row = self.db.execute("SELECT * FROM members WHERE id=?", (member_id,)).fetchone()
        if row is None:
            raise ValueError("회원을 찾을 수 없습니다.")
        if active and not row["active"]:
            raise ValueError("사용 중지된 회원입니다.")
        return row

    def _loyalty_product(self, product_id):
        row = self.db.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
        if row is None:
            raise ValueError("상품을 찾을 수 없습니다.")
        return row

    def members(self, search=""):
        self._loyalty_require_any("loyalty", "reports")
        search = f"%{text(search)}%"
        rows = [dict(row) for row in self.db.execute(
            "SELECT m.* FROM members m LEFT JOIN member_profiles p ON p.member_id=m.id WHERE m.code LIKE ? OR m.name LIKE ? OR m.phone LIKE ? OR p.mobile LIKE ? OR p.address LIKE ? OR p.group_name LIKE ? ORDER BY m.name,m.id",
            (search,)*6)]
        for row in rows:
            profile = self.db.execute("SELECT * FROM member_profiles WHERE member_id=?",(row["id"],)).fetchone()
            if profile: row.update({k:profile[k] for k in profile.keys() if k != "member_id"})
            contact=self.db.execute('SELECT phone_type FROM member_contact_types WHERE member_id=?',(row['id'],)).fetchone()
            row['phone_type']=contact[0] if contact else '기타'
        return rows

    def trade_members(self, search=""):
        self._loyalty_require_any("trade", "loyalty", "reports")
        search = f"%{text(search)}%"
        return [dict(row) for row in self.db.execute(
            "SELECT id,code,name,points,active FROM members WHERE code LIKE ? OR name LIKE ? OR phone LIKE ? ORDER BY name,id",
            (search, search, search))]

    def loyalty_products(self):
        self._loyalty_require_any("loyalty", "catalog", "trade")
        return [dict(row) for row in self.db.execute(
            "SELECT id,code,name,base_unit,price_basis,purchase_price,sale_price,active FROM products ORDER BY name,id")]

    def save_member(self, data, id=None):
        with self._tx():
            self._require("loyalty")
            self._require_capability("members", "edit" if id else "create")
            old = self._member_row(id) if id is not None else None
            values = {key: text(data.get(key, old[key] if old else ""), label, required)
                      for key, label, required in (("code", "회원 코드", True), ("name", "회원명", True),
                                                   ("phone", "전화번호", False), ("memo", "메모", False))}
            birthday = data.get("birthday", old["birthday"] if old else "")
            values["birthday"] = day(birthday) if birthday else ""
            values["active"] = int(bool(data.get("active", old["active"] if old else True)))
            stamp = now()
            try:
                if old:
                    self.db.execute("UPDATE members SET code=:code,name=:name,phone=:phone,memo=:memo,birthday=:birthday,active=:active,updated_at=:stamp WHERE id=:id",
                                    dict(values, stamp=stamp, id=id))
                else:
                    id = self.db.execute("INSERT INTO members(code,name,phone,memo,birthday,active,created_at,updated_at) VALUES(:code,:name,:phone,:memo,:birthday,:active,:stamp,:stamp)",
                                         dict(values, stamp=stamp)).lastrowid
            except sqlite3.IntegrityError:
                raise ValueError("이미 사용 중인 회원 코드입니다.") from None
            profile_old = self.db.execute("SELECT * FROM member_profiles WHERE member_id=?",(id,)).fetchone()
            previous_type=self.db.execute('SELECT phone_type FROM member_contact_types WHERE member_id=?',(id,)).fetchone()
            phone_type=text(data.get('phone_type',previous_type[0] if previous_type else '휴대폰'),'연락처 구분',True,50)
            self.db.execute('INSERT INTO member_contact_types(member_id,phone_type) VALUES(?,?) ON CONFLICT(member_id) DO UPDATE SET phone_type=excluded.phone_type',(id,phone_type))
            fields = ("mobile","address","member_type","business_no","company","representative","group_name","anniversary")
            profile = {key:text(data.get(key,profile_old[key] if profile_old else "일반고객" if key=="member_type" else ""),key) for key in fields}
            if profile["anniversary"]: profile["anniversary"] = day(profile["anniversary"])
            columns = ",".join(fields)
            self.db.execute(f"INSERT INTO member_profiles(member_id,{columns}) VALUES(?,{','.join('?' for _ in fields)}) ON CONFLICT(member_id) DO UPDATE SET " + ",".join(f"{key}=excluded.{key}" for key in fields),(id,*profile.values()))
            self._audit("update" if old else "create", "member", id, values)
            return id

    def next_member_code(self):
        self.require_menu("members")
        values = [int(r[0][1:]) for r in self.db.execute("SELECT code FROM members WHERE code LIKE 'M%'") if r[0][1:].isdigit()]
        return f"M{max(values,default=0)+1:07d}"

    def delete_member(self, id):
        """Unused members may be removed; financial history is never orphaned."""
        with self._tx():
            self._require("loyalty")
            self._require_capability("members", "delete")
            row = self._member_row(id)
            if row["points"] or self.db.execute("SELECT 1 FROM point_entries WHERE member_id=? UNION ALL SELECT 1 FROM documents WHERE member_id=? UNION ALL SELECT 1 FROM gift_redemptions WHERE member_id=? LIMIT 1", (id, id, id)).fetchone():
                raise ValueError("포인트 또는 거래 이력이 있는 회원은 삭제할 수 없습니다. 사용 중지로 변경하세요.")
            self.db.execute("DELETE FROM member_prices WHERE member_id=?", (id,))
            self.db.execute("DELETE FROM members WHERE id=?", (id,))
            self._audit("delete", "member", id, {"code": row["code"], "name": row["name"]})

    def member_prices(self, member_id):
        self._require("loyalty")
        self._member_row(member_id)
        return [dict(row) for row in self.db.execute("SELECT m.*,p.name AS product_name,p.code AS product_code FROM member_prices m JOIN products p ON p.id=m.product_id WHERE member_id=? ORDER BY p.name", (member_id,))]

    def save_member_price(self, data):
        with self._tx():
            self._require("loyalty")
            self._require_capability("members", "edit")
            self._member_row(data["member_id"], active=True)
            self._loyalty_product(data["product_id"])
            price = money(data["price"])
            self.db.execute("INSERT INTO member_prices(member_id,product_id,price) VALUES(?,?,?) ON CONFLICT(member_id,product_id) DO UPDATE SET price=excluded.price", (data["member_id"], data["product_id"], price))
            id = self.db.execute("SELECT id FROM member_prices WHERE member_id=? AND product_id=?", (data["member_id"], data["product_id"])).fetchone()[0]
            self._audit("save", "member_price", id, dict(data, price=price))
            return id

    def delete_member_price(self, id):
        with self._tx():
            self._require("loyalty")
            self._require_capability("members", "delete")
            row = self.db.execute("SELECT * FROM member_prices WHERE id=?", (id,)).fetchone()
            if row is None:
                raise ValueError("회원 지정가를 찾을 수 없습니다.")
            self.db.execute("DELETE FROM member_prices WHERE id=?", (id,))
            self._audit("delete", "member_price", id, dict(row))

    def promotions(self):
        self._require("loyalty")
        return [dict(row) for row in self.db.execute("SELECT p.*,COUNT(i.id) AS item_count FROM promotions p LEFT JOIN promotion_items i ON i.promotion_id=p.id GROUP BY p.id ORDER BY p.start DESC,p.id DESC")]

    def promotion(self, id):
        self._require("loyalty")
        row = self.db.execute("SELECT * FROM promotions WHERE id=?", (id,)).fetchone()
        if row is None:
            raise ValueError("특매 그룹을 찾을 수 없습니다.")
        result = dict(row)
        result["items"] = [dict(item) for item in self.db.execute("SELECT i.*,p.name AS product_name,p.code AS product_code FROM promotion_items i JOIN products p ON p.id=i.product_id WHERE promotion_id=? ORDER BY i.id", (id,))]
        return result

    def _save_promotion(self, data, id=None):
        old = self.db.execute("SELECT * FROM promotions WHERE id=?", (id,)).fetchone() if id is not None else None
        if id is not None and old is None:
            raise ValueError("특매 그룹을 찾을 수 없습니다.")
        title = text(data.get("title"), "특매 제목", True)
        start, end = day(data["start"]), day(data["end"])
        if end < start:
            raise ValueError("특매 종료일은 시작일보다 빠를 수 없습니다.")
        active = int(bool(data.get("active", True)))
        items, seen = [], set()
        for item in data.get("items", []):
            product = self._loyalty_product(item["product_id"])
            if product["id"] in seen:
                raise ValueError("특매 그룹에 같은 상품을 두 번 추가할 수 없습니다.")
            seen.add(product["id"])
            purchase = money(item["purchase_price"]) if item.get("purchase_price") is not None else None
            sale = money(item["sale_price"]) if item.get("sale_price") is not None else None
            if purchase is None and sale is None:
                raise ValueError("특매 매입가 또는 판매가를 입력하세요.")
            if active and self.db.execute("SELECT 1 FROM promotion_items i JOIN promotions p ON p.id=i.promotion_id WHERE p.active=1 AND i.product_id=? AND p.start<=? AND p.end>=? AND p.id<>? LIMIT 1", (product["id"], end, start, id or -1)).fetchone():
                raise ValueError("같은 상품의 활성 특매 기간이 겹칩니다. 기존 특매를 종료하거나 사용 중지하세요.")
            items.append({"product_id": product["id"], "purchase_price": purchase, "sale_price": sale})
        if old:
            self.db.execute("UPDATE promotions SET title=?,start=?,end=?,active=? WHERE id=?", (title, start, end, active, id))
            self.db.execute("DELETE FROM promotion_items WHERE promotion_id=?", (id,))
        else:
            id = self.db.execute("INSERT INTO promotions(title,start,end,active,created_at) VALUES(?,?,?,?,?)", (title, start, end, active, now())).lastrowid
        self.db.executemany("INSERT INTO promotion_items(promotion_id,product_id,purchase_price,sale_price) VALUES(?,?,?,?)", [(id, item["product_id"], item["purchase_price"], item["sale_price"]) for item in items])
        self._audit("update" if old else "create", "promotion", id, {"title": title, "start": start, "end": end, "active": active, "items": items})
        return id

    def save_promotion(self, data, id=None):
        with self._tx():
            self._require("loyalty")
            self._require_capability("promotions", "edit" if id else "create")
            return self._save_promotion(data, id)

    def delete_promotion(self, id):
        with self._tx():
            self._require("loyalty")
            self._require_capability("promotions", "delete")
            if not self.db.execute("SELECT 1 FROM promotions WHERE id=?", (id,)).fetchone():
                raise ValueError("특매 그룹을 찾을 수 없습니다.")
            self.db.execute("UPDATE promotions SET active=0 WHERE id=?", (id,))
            self._audit("deactivate", "promotion", id, {"reason": "특매 기록은 보존하고 사용만 중지"})

    def clone_promotion(self, id, new_start, new_end):
        with self._tx():
            self._require("loyalty")
            self._require_capability("promotions", "create")
            data = self.promotion(id)
            for item in data["items"]:
                for key in ("purchase_price", "sale_price"):
                    if item[key] is not None:
                        item[key] = currency_amount(item[key])
            data.update(start=new_start, end=new_end, title=data["title"] + " (복사)", active=True)
            return self._save_promotion(data)

    def extend_promotion(self, id, new_end):
        with self._tx():
            self._require("loyalty")
            self._require_capability("promotions", "edit")
            data = self.promotion(id)
            for item in data["items"]:
                for key in ("purchase_price", "sale_price"):
                    if item[key] is not None:
                        item[key] = currency_amount(item[key])
            if day(new_end) < data["end"]:
                raise ValueError("기간 연장은 현재 종료일 이후로 지정하세요.")
            data["end"] = new_end
            return self._save_promotion(data, id)

    def price_schedules(self):
        self._require("loyalty")
        return [dict(row) for row in self.db.execute("SELECT s.*,p.name AS product_name,p.code AS product_code FROM price_schedules s JOIN products p ON p.id=s.product_id ORDER BY s.date DESC,s.id DESC")]

    def save_price_schedule(self, data, id=None):
        with self._tx():
            self._require("loyalty")
            self._require_capability("prices", "edit" if id else "create")
            if id is not None and not self.db.execute("SELECT 1 FROM price_schedules WHERE id=?", (id,)).fetchone():
                raise ValueError("가격 예약을 찾을 수 없습니다.")
            self._loyalty_product(data["product_id"])
            purchase = money(data["purchase_price"]) if data.get("purchase_price") is not None else None
            sale = money(data["sale_price"]) if data.get("sale_price") is not None else None
            if purchase is None and sale is None:
                raise ValueError("변경할 매입가 또는 판매가를 입력하세요.")
            values = (data["product_id"], day(data["date"]), text(data.get("title", "")), purchase, sale, int(bool(data.get("active", True))))
            try:
                if id is None:
                    id = self.db.execute("INSERT INTO price_schedules(product_id,date,title,purchase_price,sale_price,active,created_at) VALUES(?,?,?,?,?,?,?)", (*values, now())).lastrowid
                else:
                    self.db.execute("UPDATE price_schedules SET product_id=?,date=?,title=?,purchase_price=?,sale_price=?,active=? WHERE id=?", (*values, id))
            except sqlite3.IntegrityError:
                raise ValueError("같은 상품·날짜에 활성 가격 예약이 이미 있습니다.") from None
            self._audit("save", "price_schedule", id, {"product_id": values[0], "date": values[1], "purchase_price": purchase, "sale_price": sale, "active": values[-1]})
            return id

    def delete_price_schedule(self, id):
        with self._tx():
            self._require("loyalty")
            self._require_capability("prices", "delete")
            if not self.db.execute("SELECT 1 FROM price_schedules WHERE id=?", (id,)).fetchone():
                raise ValueError("가격 예약을 찾을 수 없습니다.")
            self.db.execute("UPDATE price_schedules SET active=0 WHERE id=?", (id,))
            self._audit("deactivate", "price_schedule", id, {})

    def quote(self, product_id, date, unit_id=None, member_id=None):
        self._loyalty_require_any("trade", "catalog", "loyalty")
        date = day(date)
        product = self._loyalty_product(product_id)
        if not product["active"]:
            raise ValueError("사용 중지된 상품입니다.")
        if member_id is not None:
            self._member_row(member_id, active=True)
        if unit_id is not None:
            unit = self.db.execute("SELECT * FROM product_units WHERE id=? AND product_id=? AND active=1", (unit_id, product_id)).fetchone()
            if unit is None:
                raise ValueError("사용 가능한 확장단위가 아닙니다.")
            return {"price": unit["sale_price"], "purchase_price": unit["purchase_price"], "source": "확장단위 등록가", "purchase_source": "확장단위 등록가"}
        prices = {"price": product["sale_price"], "purchase_price": product["purchase_price"], "source": "기본가", "purchase_source": "기본가"}
        # Purchase/sale schedules are resolved separately: a sale-only reservation
        # must not accidentally hide an earlier, still-effective purchase change.
        for column, output, source in (("purchase_price", "purchase_price", "purchase_source"), ("sale_price", "price", "source")):
            schedule = self.db.execute(f"SELECT {column},date FROM price_schedules WHERE product_id=? AND active=1 AND date<=? AND {column} IS NOT NULL ORDER BY date DESC,id DESC LIMIT 1", (product_id, date)).fetchone()
            if schedule:
                prices[output], prices[source] = schedule[column], f"예약가 ({schedule['date']})"
        promotion = self.db.execute("SELECT i.*,p.title FROM promotion_items i JOIN promotions p ON p.id=i.promotion_id WHERE i.product_id=? AND p.active=1 AND p.start<=? AND p.end>=? ORDER BY p.id LIMIT 1", (product_id, date, date)).fetchone()
        if promotion:
            if promotion["sale_price"] is not None:
                prices["price"], prices["source"] = promotion["sale_price"], f"특매 · {promotion['title']}"
            if promotion["purchase_price"] is not None:
                prices["purchase_price"], prices["purchase_source"] = promotion["purchase_price"], f"특매 · {promotion['title']}"
        if member_id is not None:
            fixed = self.db.execute("SELECT price FROM member_prices WHERE member_id=? AND product_id=?", (member_id, product_id)).fetchone()
            if fixed:
                prices["price"], prices["source"] = fixed["price"], "회원 지정가"
        return prices

    def point_history(self, member_id):
        self._loyalty_require_any("loyalty", "reports")
        self._member_row(member_id)
        return [dict(row) for row in self.db.execute("SELECT e.*,u.name AS user_name,d.number AS document_number FROM point_entries e JOIN users u ON u.id=e.user_id LEFT JOIN documents d ON d.id=e.document_id WHERE e.member_id=? ORDER BY e.id DESC", (member_id,))]

    def _point_entry(self, member_id, delta, kind, reason, document_id=None, source_id=None, gift_redemption_id=None, date=None):
        member = self._member_row(member_id)
        balance = member["points"] + delta
        if balance < 0:
            raise ValueError("포인트가 부족합니다. 이미 사용된 적립 포인트를 먼저 복원한 뒤 반품/취소하세요.")
        if balance > LIMIT:
            raise ValueError("포인트 허용 범위를 초과했습니다.")
        self.db.execute("UPDATE members SET points=?,updated_at=? WHERE id=?", (balance, now(), member_id))
        return self.db.execute("INSERT INTO point_entries(member_id,date,kind,delta,balance,reason,document_id,source_id,gift_redemption_id,user_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                               (member_id, day(date) if date else now()[:10], kind, delta, balance, reason, document_id, source_id, gift_redemption_id, self.actor["id"], now())).lastrowid

    def adjust_points(self, member_id, delta, reason):
        with self._tx():
            self._require("loyalty")
            self._require_capability("members", "edit")
            self._member_row(member_id, active=True)
            delta = integer(delta, "조정 포인트", signed=True)
            if not delta:
                raise ValueError("조정 포인트는 0일 수 없습니다.")
            reason = text(reason, "포인트 조정 사유", True)
            id = self._point_entry(member_id, delta, "adjust", reason)
            self._audit("adjust", "point", id, {"member_id": member_id, "delta": delta, "reason": reason})
            return id

    def _point_policy(self):
        values = self._settings_values()
        bps = integer(values.get("earn_bps", 100), "포인트 적립률")
        if bps > 10000:
            raise ValueError("포인트 적립률은 100% 이하여야 합니다.")
        minimum = integer(values.get("point_min", 1000), "최소 사용 포인트")
        step = integer(values.get("point_step", 100), "포인트 사용 단위", positive=True)
        enabled = values.get("point_enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError("포인트 사용 여부 설정이 올바르지 않습니다.")
        return bps, minimum, step, enabled

    def _sale_points(self, document_id, member_id, total, points_used):
        if type(total) is not int or type(points_used) is not int or points_used % 100:
            raise ValueError("내부 금액과 포인트 단위를 확인하세요.")
        used = integer(points_used // 100, "사용 포인트")
        if member_id is None:
            if used:
                raise ValueError("포인트를 사용하려면 회원을 지정하세요.")
            return 0
        member = self._member_row(member_id, active=True)
        if self.db.execute("SELECT 1 FROM loyalty_sale_actions WHERE document_id=?", (document_id,)).fetchone():
            raise ValueError("이미 포인트 처리가 완료된 매출입니다.")
        bps, minimum, step, enabled = self._point_policy()
        if used * 100 > total:
            raise ValueError("사용 포인트는 거래 합계를 초과할 수 없습니다.")
        if used and (not enabled or used < minimum or used % step):
            raise ValueError(f"포인트 사용은 허용 상태에서 최소 {minimum:,}점, {step:,}점 단위로 가능합니다.")
        if used > member["points"]:
            raise ValueError("사용 가능한 포인트가 부족합니다.")
        earned = rounded(Decimal(total - used * 100) * bps / 1000000)
        document = self.db.execute("SELECT date FROM documents WHERE id=?", (document_id,)).fetchone()
        if document is None:
            raise ValueError("매출 전표를 찾을 수 없습니다.")
        self.db.execute("INSERT INTO loyalty_sale_actions VALUES(?,?,?,?)", (document_id, member_id, used, earned))
        if used:
            self._point_entry(member_id, -used, "sale_use", "매출 포인트 사용", document_id=document_id, date=document["date"])
        if earned:
            self._point_entry(member_id, earned, "sale_earn", "매출 적립", document_id=document_id, date=document["date"])
        return earned

    def _reverse_sale_points(self, document_id, source_document_id, return_total):
        source = self.db.execute("SELECT * FROM documents WHERE id=? AND kind='sale'", (source_document_id,)).fetchone()
        if source is None:
            raise ValueError("원매출을 찾을 수 없습니다.")
        if source["member_id"] is None:
            return 0, 0
        if self.db.execute("SELECT 1 FROM loyalty_return_actions WHERE document_id=?", (document_id,)).fetchone():
            raise ValueError("이미 포인트 반환 처리가 완료된 전표입니다.")
        returning = return_total
        previous = self.db.execute("SELECT COALESCE(SUM(a.return_total),0),COALESCE(SUM(a.restored_used),0),COALESCE(SUM(a.reversed_earned),0) FROM loyalty_return_actions a JOIN documents d ON d.id=a.document_id WHERE a.source_document_id=? AND a.kind='return' AND d.status='posted'", (source_document_id,)).fetchone()
        cumulative = previous[0] + returning
        if cumulative > source["total"]:
            raise ValueError("반품 합계가 원매출 합계를 초과합니다.")
        if source["total"]:
            ratio = Decimal(cumulative) / source["total"]
            restored = rounded(Decimal(source["points_used"]) / 100 * ratio) - previous[1]
            reversed_earned = rounded(Decimal(source["points_earned"]) * ratio) - previous[2]
        else:
            restored = reversed_earned = 0
        # Check the net reversal before appending either immutable ledger entry.
        if self._member_row(source["member_id"])["points"] + restored - reversed_earned < 0:
            raise ValueError("이미 사용된 적립 포인트가 있어 반품/취소할 수 없습니다. 포인트를 복원한 뒤 다시 처리하세요.")
        current = self.db.execute("SELECT date FROM documents WHERE id=?", (document_id,)).fetchone()
        if current is None:
            raise ValueError("반품/취소 전표를 찾을 수 없습니다.")
        cancel = document_id == source_document_id
        self.db.execute("INSERT INTO loyalty_return_actions VALUES(?,?,?,?,?,?)", (document_id, source_document_id, returning, restored, reversed_earned, "cancel" if cancel else "return"))
        if restored:
            self._point_entry(source["member_id"], restored, "cancel_restore" if cancel else "return_restore", "사용 포인트 반환", document_id, source_document_id, date=current["date"])
        if reversed_earned:
            self._point_entry(source["member_id"], -reversed_earned, "cancel_revoke" if cancel else "return_revoke", "적립 포인트 회수", document_id, source_document_id, date=current["date"])
        return restored * 100, reversed_earned

    def member_history(self, member_id, start="", end=""):
        self._loyalty_require_any("loyalty", "reports")
        self._member_row(member_id)
        clauses, args = ["member_id=?", "kind IN ('sale','sale_return')"], [member_id]
        if start:
            clauses.append("date>=?"); args.append(day(start))
        if end:
            clauses.append("date<=?"); args.append(day(end))
        return [dict(row) for row in self.db.execute("SELECT * FROM documents WHERE " + " AND ".join(clauses) + " ORDER BY date DESC,id DESC", args)]

    def best_members(self, start, end):
        self._loyalty_require_any("loyalty", "reports")
        start, end = day(start), day(end)
        if end < start:
            raise ValueError("조회 종료일은 시작일 이후로 지정하세요.")
        return [dict(row) for row in self.db.execute("SELECT m.id,m.code,m.name,m.points,COUNT(CASE WHEN d.kind='sale' THEN 1 END) AS sale_count,COALESCE(SUM(CASE WHEN d.kind='sale' THEN d.total ELSE -d.total END),0) AS total,MIN(d.date) AS first_purchase,MAX(d.date) AS last_purchase FROM members m JOIN documents d ON d.member_id=m.id WHERE d.status='posted' AND d.kind IN ('sale','sale_return') AND d.date BETWEEN ? AND ? GROUP BY m.id ORDER BY total DESC,sale_count DESC,m.id", (start, end))]

    def gifts(self):
        self._require("loyalty")
        return [dict(row) for row in self.db.execute("SELECT * FROM gifts ORDER BY name,id")]

    def save_gift(self, data, id=None):
        with self._tx():
            self._require("loyalty")
            self._require_capability("gifts", "edit" if id else "create")
            old = self.db.execute("SELECT * FROM gifts WHERE id=?", (id,)).fetchone() if id is not None else None
            if id is not None and old is None:
                raise ValueError("사은품을 찾을 수 없습니다.")
            values = {"code": text(data.get("code", old["code"] if old else ""), "사은품 코드", True),
                      "name": text(data.get("name", old["name"] if old else ""), "사은품명", True),
                      "points": integer(data.get("points", old["points"] if old else 0), "교환 포인트", positive=True),
                      "stock": integer(data.get("stock", old["stock"] if old else 0), "사은품 재고"),
                      "active": int(bool(data.get("active", old["active"] if old else True)))}
            try:
                if old:
                    self.db.execute("UPDATE gifts SET code=:code,name=:name,points=:points,stock=:stock,active=:active WHERE id=:id", dict(values, id=id))
                else:
                    id = self.db.execute("INSERT INTO gifts(code,name,points,stock,active,created_at) VALUES(:code,:name,:points,:stock,:active,:stamp)", dict(values, stamp=now())).lastrowid
            except sqlite3.IntegrityError:
                raise ValueError("이미 사용 중인 사은품 코드입니다.") from None
            self._audit("update" if old else "create", "gift", id, {"new": values, "old_stock": old["stock"] if old else 0})
            return id

    def redeem_gift(self, member_id, gift_id, qty, reason):
        with self._tx():
            self._require("loyalty")
            self._require_capability("gifts", "create")
            member = self._member_row(member_id, active=True)
            gift = self.db.execute("SELECT * FROM gifts WHERE id=? AND active=1", (gift_id,)).fetchone()
            if gift is None:
                raise ValueError("사용 가능한 사은품을 찾을 수 없습니다.")
            count = integer(qty, "사은품 수량", positive=True)
            reason = text(reason, "사은품 지급 사유", True)
            points = count * gift["points"]
            if points > LIMIT or points > member["points"]:
                raise ValueError("사은품을 교환할 포인트가 부족합니다.")
            if count > gift["stock"]:
                raise ValueError("사은품 재고가 부족합니다.")
            self.db.execute("UPDATE gifts SET stock=stock-? WHERE id=?", (count, gift_id))
            id = self.db.execute("INSERT INTO gift_redemptions(member_id,gift_id,gift_name,kind,qty,points,reason,user_id,created_at) VALUES(?,?,?,'redeem',?,?,?,?,?)", (member_id, gift_id, gift["name"], count, points, reason, self.actor["id"], now())).lastrowid
            self._point_entry(member_id, -points, "gift_redeem", reason, gift_redemption_id=id)
            self._audit("redeem", "gift_redemption", id, {"member_id": member_id, "gift_id": gift_id, "qty": count, "points": points, "reason": reason})
            return id

    def return_gift(self, redemption_id, qty, reason):
        with self._tx():
            self._require("loyalty")
            self._require_capability("gifts", "delete")
            source = self.db.execute("SELECT * FROM gift_redemptions WHERE id=? AND kind='redeem'", (redemption_id,)).fetchone()
            if source is None:
                raise ValueError("원래 사은품 지급 기록을 찾을 수 없습니다.")
            count = integer(qty, "사은품 반품 수량", positive=True)
            reason = text(reason, "사은품 반품 사유", True)
            returned = self.db.execute("SELECT COALESCE(SUM(qty),0) FROM gift_redemptions WHERE source_id=? AND kind='return'", (redemption_id,)).fetchone()[0]
            if returned + count > source["qty"]:
                raise ValueError("반품 수량이 원래 지급한 사은품 수량을 초과합니다.")
            points = source["points"] * count // source["qty"]
            gift = self.db.execute("SELECT stock FROM gifts WHERE id=?", (source["gift_id"],)).fetchone()
            if gift["stock"] + count > LIMIT:
                raise ValueError("사은품 재고 허용 범위를 초과합니다.")
            self.db.execute("UPDATE gifts SET stock=stock+? WHERE id=?", (count, source["gift_id"]))
            id = self.db.execute("INSERT INTO gift_redemptions(member_id,gift_id,gift_name,kind,source_id,qty,points,reason,user_id,created_at) VALUES(?,?,?,'return',?,?,?,?,?,?)", (source["member_id"], source["gift_id"], source["gift_name"], redemption_id, count, points, reason, self.actor["id"], now())).lastrowid
            self._point_entry(source["member_id"], points, "gift_return", reason, gift_redemption_id=id)
            self._audit("return", "gift_redemption", id, {"source_id": redemption_id, "qty": count, "points": points, "reason": reason})
            return id

    def gift_history(self, member_id=None):
        self._loyalty_require_any("loyalty", "reports")
        clause, args = (" WHERE r.member_id=?", (member_id,)) if member_id is not None else ("", ())
        return [dict(row) for row in self.db.execute("SELECT r.*,m.name AS member_name,u.name AS user_name FROM gift_redemptions r JOIN members m ON m.id=r.member_id JOIN users u ON u.id=r.user_id" + clause + " ORDER BY r.id DESC", args)]
