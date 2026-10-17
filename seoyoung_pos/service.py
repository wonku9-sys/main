"""Offline POS business rules and durable SQLite storage.

Quantities use integer thousandths, and money uses integer KRW. Each line is
rounded half up to the nearest won. Moving-average inventory costs are saved
with sale lines so cancellation restores the original cost, not today's price.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date as Date, datetime
from decimal import Decimal, DecimalException, ROUND_HALF_UP
import json
from pathlib import Path
import sqlite3
from typing import Any

from .security import hash_password, verify_password


PERMISSIONS = frozenset({"products", "partners", "purchases", "sales", "inventory", "reports", "users", "settings"})
MAX_INTEGER = 9_000_000_000_000


def _integer(value: Any, label: str = "금액", *, positive: bool = False) -> int:
    try:
        decimal = Decimal(str(value))
        if not decimal.is_finite() or decimal < (1 if positive else 0) or decimal > MAX_INTEGER or decimal != decimal.to_integral_value():
            raise ValueError
        result = int(decimal)
        if result < (1 if positive else 0) or result > MAX_INTEGER:
            raise ValueError
        return result
    except (ValueError, DecimalException, TypeError, OverflowError):
        raise ValueError(f"{label}은(는) {'1 이상의' if positive else '0 이상의'} 정수로 입력해 주세요.") from None


def _quantity(value: Any, *, signed: bool = False, zero: bool = False) -> int:
    try:
        decimal = Decimal(str(value))
        if not decimal.is_finite() or abs(decimal) > Decimal(MAX_INTEGER) / 1000:
            raise ValueError
        scaled = decimal * 1000
        if scaled != scaled.to_integral_value():
            raise ValueError
        result = int(scaled)
        if abs(result) > MAX_INTEGER or (not signed and result < 0) or (not zero and result == 0):
            raise ValueError
        return result
    except (ValueError, TypeError, DecimalException, OverflowError):
        raise ValueError("수량은 소수점 셋째 자리까지 입력해 주세요. 거래 수량은 0보다 커야 합니다.") from None


def _qty_text(value: int) -> str:
    return format(Decimal(value) / 1000, ".3f")


def _rounded(value: Decimal) -> int:
    result = int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if abs(result) > MAX_INTEGER:
        raise ValueError("거래 금액이 허용 범위를 초과했습니다.")
    return result


def _day(value: str) -> str:
    try:
        parsed = Date.fromisoformat(str(value))
        if parsed.isoformat() != str(value):
            raise ValueError
        return parsed.isoformat()
    except (ValueError, TypeError):
        raise ValueError("날짜는 YYYY-MM-DD 형식으로 입력해 주세요.") from None


class POSService:
    def __init__(self, path: str | Path):
        self.path = Path(path) if str(path) != ":memory:" else None
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), timeout=10, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA busy_timeout=10000")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.user: dict | None = None
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
              id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
              name TEXT NOT NULL, password_hash TEXT NOT NULL,
              role TEXT NOT NULL CHECK(role IN ('admin','staff')), permissions TEXT NOT NULL DEFAULT '[]');
            CREATE TABLE IF NOT EXISTS partners (
              id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('supplier','customer')),
              code TEXT NOT NULL, name TEXT NOT NULL, business_no TEXT NOT NULL DEFAULT '',
              contact TEXT NOT NULL DEFAULT '', phone TEXT NOT NULL DEFAULT '', bank TEXT NOT NULL DEFAULT '',
              account TEXT NOT NULL DEFAULT '', account_holder TEXT NOT NULL DEFAULT '', memo TEXT NOT NULL DEFAULT '',
              UNIQUE(kind,code));
            CREATE TABLE IF NOT EXISTS products (
              id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, barcode TEXT NOT NULL DEFAULT '',
              name TEXT NOT NULL, category TEXT NOT NULL DEFAULT '', specification TEXT NOT NULL DEFAULT '',
              unit TEXT NOT NULL DEFAULT 'kg', origin TEXT NOT NULL DEFAULT '', supplier_id INTEGER REFERENCES partners(id),
              purchase_price INTEGER NOT NULL DEFAULT 0 CHECK(purchase_price>=0),
              sale_price INTEGER NOT NULL DEFAULT 0 CHECK(sale_price>=0),
              min_stock INTEGER NOT NULL DEFAULT 0 CHECK(min_stock>=0),
              stock_qty INTEGER NOT NULL DEFAULT 0 CHECK(stock_qty>=0),
              stock_cost INTEGER NOT NULL DEFAULT 0 CHECK(stock_cost>=0),
              memo TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1 CHECK(active IN(0,1)));
            CREATE UNIQUE INDEX IF NOT EXISTS product_barcode_unique ON products(barcode) WHERE barcode<>'';
            CREATE TABLE IF NOT EXISTS documents (
              id INTEGER PRIMARY KEY, number TEXT NOT NULL UNIQUE,
              kind TEXT NOT NULL CHECK(kind IN ('purchase','sale')), date TEXT NOT NULL,
              partner_id INTEGER NOT NULL REFERENCES partners(id), total INTEGER NOT NULL CHECK(total>=0),
              paid INTEGER NOT NULL DEFAULT 0 CHECK(paid>=0 AND paid<=total), memo TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT 'posted' CHECK(status IN('posted','cancelled')),
              user_id INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
              cancelled_reason TEXT NOT NULL DEFAULT '');
            CREATE TABLE IF NOT EXISTS document_items (
              id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL REFERENCES documents(id),
              product_id INTEGER NOT NULL REFERENCES products(id), product_name TEXT NOT NULL,
              unit TEXT NOT NULL, qty INTEGER NOT NULL CHECK(qty>0),
              unit_price INTEGER NOT NULL CHECK(unit_price>=0), total INTEGER NOT NULL CHECK(total>=0),
              cost INTEGER NOT NULL DEFAULT 0 CHECK(cost>=0));
            CREATE TABLE IF NOT EXISTS payments (
              id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL REFERENCES documents(id),
              amount INTEGER NOT NULL CHECK(amount>0), date TEXT NOT NULL,
              memo TEXT NOT NULL DEFAULT '', user_id INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS stock_movements (
              id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id),
              date TEXT NOT NULL, kind TEXT NOT NULL, qty INTEGER NOT NULL, balance_qty INTEGER NOT NULL CHECK(balance_qty>=0),
              reason TEXT NOT NULL, document_id INTEGER REFERENCES documents(id),
              user_id INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS audit (
              id INTEGER PRIMARY KEY, at TEXT NOT NULL, user_id INTEGER,
              username TEXT NOT NULL, action TEXT NOT NULL, entity TEXT NOT NULL,
              entity_id INTEGER, detail TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS document_date_kind ON documents(kind,date);
            CREATE INDEX IF NOT EXISTS document_partner ON documents(partner_id);
            CREATE INDEX IF NOT EXISTS item_document ON document_items(document_id);
            CREATE INDEX IF NOT EXISTS stock_product ON stock_movements(product_id,id);
            PRAGMA user_version=1;
        """)

    @contextmanager
    def _transaction(self):
        try:
            self.db.execute("BEGIN IMMEDIATE")
            yield
            self.db.execute("COMMIT")
        except sqlite3.IntegrityError:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise ValueError("중복된 코드·바코드·사용자이거나 다른 자료에서 사용 중인 항목입니다.") from None
        except sqlite3.Error as exc:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise ValueError("자료를 저장하지 못했습니다. 저장 공간과 데이터 파일 접근 권한을 확인해 주세요.") from exc
        except Exception:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise

    def _current(self) -> dict:
        if not self.user:
            raise PermissionError("로그인 후 이용해 주세요.")
        row = self.db.execute("SELECT * FROM users WHERE id=?", (self.user["id"],)).fetchone()
        if not row:
            self.user = None
            raise PermissionError("계정이 삭제되었습니다. 다시 로그인해 주세요.")
        self.user = self._public_user(row)
        return self.user

    @staticmethod
    def _public_user(row) -> dict:
        return {"id": row["id"], "username": row["username"], "name": row["name"],
                "role": row["role"], "permissions": json.loads(row["permissions"])}

    def has_permission(self, permission: str) -> bool:
        if not self.user or permission not in PERMISSIONS:
            return False
        user = self._current()
        return user["role"] == "admin" or (permission not in {"users", "settings"} and permission in user["permissions"])

    def _require(self, *permissions: str):
        self._current()
        if not any(self.has_permission(item) for item in permissions):
            raise PermissionError("이 기능에 접근할 권한이 없습니다. 관리자에게 문의해 주세요.")

    def _audit(self, action, entity, entity_id, detail):
        user = self.user or {"id": None, "username": "system"}
        self.db.execute("INSERT INTO audit(at,user_id,username,action,entity,entity_id,detail) VALUES(?,?,?,?,?,?,?)",
                        (datetime.now().astimezone().isoformat(timespec="seconds"), user["id"], user["username"],
                         action, entity, entity_id, json.dumps(detail, ensure_ascii=False)))

    def users_count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def create_initial_admin(self, username, name, password) -> dict:
        encoded = hash_password(password)
        username, name = str(username).strip(), str(name).strip()
        if not username or not name:
            raise ValueError("사용자 코드와 이름을 입력해 주세요.")
        with self._transaction():
            if self.users_count():
                raise ValueError("초기 관리자가 이미 등록되어 있습니다.")
            user_id = self.db.execute("INSERT INTO users(username,name,password_hash,role,permissions) VALUES(?,?,?,'admin','[]')",
                                      (username, name, encoded)).lastrowid
            self._audit("create_initial_admin", "user", user_id, {"username": username})
        return self._public_user(self.db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())

    def login(self, username, password) -> dict:
        self.user = None
        row = self.db.execute("SELECT * FROM users WHERE username=?", (str(username).strip(),)).fetchone()
        # Use an equally expensive derivation for unknown accounts as for known accounts.
        if not row:
            hash_password(str(password) if 8 <= len(str(password)) <= 1024 else "invalid-login-placeholder")
            raise ValueError("사용자 코드 또는 비밀번호가 올바르지 않습니다.")
        if not verify_password(password, row["password_hash"]):
            raise ValueError("사용자 코드 또는 비밀번호가 올바르지 않습니다.")
        with self._transaction():
            current = self.db.execute("SELECT * FROM users WHERE id=?", (row["id"],)).fetchone()
            if not current or current["password_hash"] != row["password_hash"]:
                raise ValueError("계정 정보가 변경되었습니다. 다시 로그인해 주세요.")
            self.user = self._public_user(current)
            self._audit("login", "user", row["id"], {})
        return dict(self.user)

    def logout(self):
        self.user = None

    def list_users(self) -> list[dict]:
        self._require("users")
        return [self._public_user(row) for row in self.db.execute("SELECT * FROM users ORDER BY username")]

    def save_user(self, data: dict, user_id=None) -> int:
        self._require("users")
        username, name = str(data.get("username", "")).strip(), str(data.get("name", "")).strip()
        role = data.get("role", "staff")
        permissions = data.get("permissions", [])
        if not username or not name or role not in {"admin", "staff"}:
            raise ValueError("사용자 코드, 이름, 올바른 역할을 입력해 주세요.")
        if not isinstance(permissions, (list, tuple, set)) or set(permissions) - PERMISSIONS:
            raise ValueError("올바른 접근 권한을 선택해 주세요.")
        if role == "staff" and set(permissions) & {"users", "settings"}:
            raise ValueError("사용자 관리와 환경 설정은 관리자만 사용할 수 있습니다.")
        password = data.get("password", "")
        encoded = hash_password(password) if password else None
        encoded_permissions = json.dumps(sorted(set(permissions)))
        with self._transaction():
            self._require("users")
            if user_id is None:
                if not encoded:
                    raise ValueError("신규 사용자의 비밀번호를 입력해 주세요.")
                user_id = self.db.execute("INSERT INTO users(username,name,password_hash,role,permissions) VALUES(?,?,?,?,?)",
                                         (username, name, encoded, role, encoded_permissions)).lastrowid
                action = "create"
            else:
                old = self.db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
                if not old:
                    raise ValueError("사용자를 찾을 수 없습니다.")
                if old["role"] == "admin" and role != "admin" and self.db.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0] <= 1:
                    raise ValueError("마지막 관리자 계정의 권한을 변경할 수 없습니다.")
                self.db.execute("UPDATE users SET username=?,name=?,role=?,permissions=?,password_hash=? WHERE id=?",
                                (username, name, role, encoded_permissions, encoded or old["password_hash"], user_id))
                action = "update"
            self._audit(action, "user", user_id, {"username": username, "role": role, "permissions": sorted(set(permissions))})
        return user_id

    def delete_user(self, user_id):
        self._require("users")
        with self._transaction():
            self._require("users")
            row = self.db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            if not row:
                raise ValueError("사용자를 찾을 수 없습니다.")
            if row["id"] == self.user["id"]:
                raise ValueError("현재 로그인 중인 계정은 삭제할 수 없습니다.")
            if row["role"] == "admin" and self.db.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0] <= 1:
                raise ValueError("마지막 관리자 계정은 삭제할 수 없습니다.")
            if self.db.execute("SELECT 1 FROM documents WHERE user_id=? UNION ALL SELECT 1 FROM payments WHERE user_id=? UNION ALL SELECT 1 FROM stock_movements WHERE user_id=? LIMIT 1", (user_id, user_id, user_id)).fetchone():
                raise ValueError("거래 이력이 있는 계정은 감사 추적을 위해 삭제할 수 없습니다. 접근 권한을 해제해 주세요.")
            self.db.execute("DELETE FROM users WHERE id=?", (user_id,))
            self._audit("delete", "user", user_id, {"username": row["username"]})

    def change_password(self, old, new):
        self._current()
        encoded = hash_password(new)
        with self._transaction():
            self._current()
            row = self.db.execute("SELECT password_hash FROM users WHERE id=?", (self.user["id"],)).fetchone()
            if not verify_password(old, row[0]):
                raise ValueError("현재 비밀번호가 올바르지 않습니다.")
            self.db.execute("UPDATE users SET password_hash=? WHERE id=?", (encoded, self.user["id"]))
            self._audit("change_password", "user", self.user["id"], {})

    def list_partners(self, kind, search="") -> list[dict]:
        self._require("partners", "purchases" if kind == "supplier" else "sales", "products", "reports")
        if kind not in {"supplier", "customer"}:
            raise ValueError("거래처 종류가 올바르지 않습니다.")
        rows = self.db.execute("""SELECT p.*, COALESCE((SELECT SUM(d.total-d.paid) FROM documents d
            WHERE d.partner_id=p.id AND d.status='posted'),0) AS balance FROM partners p
            WHERE p.kind=? AND (p.name LIKE ? OR p.code LIKE ? OR p.phone LIKE ? OR p.contact LIKE ?) ORDER BY p.name,p.id""",
                               (kind, *([f"%{search}%"] * 4)))
        return [dict(row) for row in rows]

    def save_partner(self, data, partner_id=None) -> int:
        self._require("partners")
        fields = ("kind", "code", "name", "business_no", "contact", "phone", "bank", "account", "account_holder", "memo")
        values = {key: str(data.get(key, "")).strip() for key in fields}
        if values["kind"] not in {"supplier", "customer"} or not values["code"] or not values["name"]:
            raise ValueError("거래처 종류, 코드, 이름을 입력해 주세요.")
        with self._transaction():
            self._require("partners")
            if partner_id is None:
                partner_id = self.db.execute(f"INSERT INTO partners({','.join(fields)}) VALUES({','.join('?' for _ in fields)})",
                                            tuple(values[key] for key in fields)).lastrowid
                action = "create"
            else:
                old = self.db.execute("SELECT kind FROM partners WHERE id=?", (partner_id,)).fetchone()
                if not old:
                    raise ValueError("거래처를 찾을 수 없습니다.")
                if old[0] != values["kind"]:
                    raise ValueError("등록한 거래처의 공급사/고객 종류는 변경할 수 없습니다.")
                self.db.execute(f"UPDATE partners SET {','.join(key+'=?' for key in fields)} WHERE id=?",
                                (*[values[key] for key in fields], partner_id))
                action = "update"
            self._audit(action, "partner", partner_id, {"name": values["name"], "kind": values["kind"]})
        return partner_id

    def delete_partner(self, partner_id):
        self._require("partners")
        with self._transaction():
            self._require("partners")
            if self.db.execute("SELECT 1 FROM documents WHERE partner_id=? UNION ALL SELECT 1 FROM products WHERE supplier_id=? LIMIT 1", (partner_id, partner_id)).fetchone():
                raise ValueError("거래 이력 또는 연결된 상품이 있는 거래처는 삭제할 수 없습니다.")
            if not self.db.execute("DELETE FROM partners WHERE id=?", (partner_id,)).rowcount:
                raise ValueError("거래처를 찾을 수 없습니다.")
            self._audit("delete", "partner", partner_id, {})

    @staticmethod
    def _product(row) -> dict:
        result = dict(row)
        for key in ("min_stock", "stock_qty"):
            result[key] = _qty_text(result[key])
        result["active"] = bool(result["active"])
        return result

    def list_products(self, search="", supplier_id=None, category="", low_stock=False) -> list[dict]:
        self._require("products", "purchases", "sales", "inventory", "reports")
        clauses, params = ["(p.name LIKE ? OR p.code LIKE ? OR p.barcode LIKE ?)"], [f"%{search}%"] * 3
        if supplier_id is not None:
            clauses.append("p.supplier_id=?")
            params.append(supplier_id)
        if category:
            clauses.append("p.category=?")
            params.append(category)
        if low_stock:
            clauses.append("p.active=1 AND p.stock_qty<=p.min_stock")
        rows = self.db.execute("SELECT p.*,COALESCE(s.name,'') AS supplier_name FROM products p LEFT JOIN partners s ON s.id=p.supplier_id WHERE " + " AND ".join(clauses) + " ORDER BY p.name,p.id", params)
        return [self._product(row) for row in rows]

    def save_product(self, data, product_id=None) -> int:
        self._require("products")
        text_fields = ("code", "barcode", "name", "category", "specification", "unit", "origin", "memo")
        values = {key: str(data.get(key, "kg" if key == "unit" else "")).strip() for key in text_fields}
        if not values["code"] or not values["name"] or not values["unit"]:
            raise ValueError("상품 코드, 상품명, 단위를 입력해 주세요.")
        values.update(supplier_id=data.get("supplier_id") or None,
                      purchase_price=_integer(data.get("purchase_price", 0), "매입 단가"),
                      sale_price=_integer(data.get("sale_price", 0), "판매 단가"),
                      min_stock=_quantity(data.get("min_stock", "0"), zero=True),
                      active=1 if data.get("active", True) else 0)
        with self._transaction():
            self._require("products")
            if values["supplier_id"] and not self.db.execute("SELECT 1 FROM partners WHERE id=? AND kind='supplier'", (values["supplier_id"],)).fetchone():
                raise ValueError("올바른 공급사를 선택해 주세요.")
            if product_id is None:
                fields = list(values)
                product_id = self.db.execute(f"INSERT INTO products({','.join(fields)}) VALUES({','.join('?' for _ in fields)})", tuple(values.values())).lastrowid
                action = "create"
            else:
                old = self.db.execute("SELECT unit FROM products WHERE id=?", (product_id,)).fetchone()
                if not old:
                    raise ValueError("상품을 찾을 수 없습니다.")
                if old[0] != values["unit"] and self.db.execute("SELECT 1 FROM stock_movements WHERE product_id=? LIMIT 1", (product_id,)).fetchone():
                    raise ValueError("재고 이력이 있는 상품의 단위는 변경할 수 없습니다. 새 상품으로 등록해 주세요.")
                self.db.execute(f"UPDATE products SET {','.join(key+'=?' for key in values)} WHERE id=?", (*values.values(), product_id))
                action = "update"
            self._audit(action, "product", product_id, {"name": values["name"]})
        return product_id

    def delete_product(self, product_id):
        self._require("products")
        with self._transaction():
            self._require("products")
            if self.db.execute("SELECT 1 FROM document_items WHERE product_id=? UNION ALL SELECT 1 FROM stock_movements WHERE product_id=? LIMIT 1", (product_id, product_id)).fetchone():
                raise ValueError("거래·재고 이력이 있는 상품은 삭제할 수 없습니다. 사용 중지를 선택해 주세요.")
            if not self.db.execute("DELETE FROM products WHERE id=?", (product_id,)).rowcount:
                raise ValueError("상품을 찾을 수 없습니다.")
            self._audit("delete", "product", product_id, {})

    @staticmethod
    def _kind(kind):
        if kind not in {"purchase", "sale"}:
            raise ValueError("전표 종류가 올바르지 않습니다.")
        return "purchases" if kind == "purchase" else "sales"

    def _stock_move(self, product_id, delta, kind, reason, document_id=None, at=None):
        product = self.db.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
        if not product:
            raise ValueError("상품을 찾을 수 없습니다.")
        balance = product["stock_qty"] + delta
        if balance < 0:
            raise ValueError(f"'{product['name']}' 재고가 부족합니다. 현재 재고: {_qty_text(product['stock_qty'])} {product['unit']}")
        if balance > MAX_INTEGER:
            raise ValueError("재고 수량이 허용 범위를 초과했습니다.")
        self.db.execute("UPDATE products SET stock_qty=? WHERE id=?", (balance, product_id))
        self.db.execute("INSERT INTO stock_movements(product_id,date,kind,qty,balance_qty,reason,document_id,user_id,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                        (product_id, at or Date.today().isoformat(), kind, delta, balance, reason, document_id, self.user["id"], datetime.now().astimezone().isoformat(timespec="seconds")))

    def create_document(self, kind, partner_id, date, items, paid=0, memo="") -> int:
        self._require(self._kind(kind))
        date, paid = _day(date), _integer(paid, "결제 금액")
        if not items or not isinstance(items, (list, tuple)):
            raise ValueError("한 개 이상의 상품을 입력해 주세요.")
        prepared = []
        for item in items:
            qty = _quantity(item.get("qty", ""))
            if qty <= 0:
                raise ValueError("거래 수량은 0보다 커야 합니다.")
            price = _integer(item.get("unit_price", ""), "단가")
            total = _rounded(Decimal(qty) * price / 1000)
            prepared.append((item.get("product_id"), qty, price, total))
        total = sum(item[3] for item in prepared)
        if total > MAX_INTEGER or paid > total:
            raise ValueError("결제 금액은 전표 합계를 초과할 수 없습니다.")
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        with self._transaction():
            self._require(self._kind(kind))
            partner = self.db.execute("SELECT * FROM partners WHERE id=?", (partner_id,)).fetchone()
            expected = "supplier" if kind == "purchase" else "customer"
            if not partner or partner["kind"] != expected:
                raise ValueError("매입은 공급사, 매출은 고객 거래처를 선택해 주세요.")
            # The integer sequence and date are committed atomically with the document.
            next_id = self.db.execute("SELECT COALESCE(MAX(id),0)+1 FROM documents").fetchone()[0]
            number = f"{'PI' if kind == 'purchase' else 'SO'}-{date.replace('-', '')}-{next_id:06d}"
            document_id = self.db.execute("INSERT INTO documents(number,kind,date,partner_id,total,paid,memo,user_id,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                                          (number, kind, date, partner_id, total, paid, str(memo).strip(), self.user["id"], now)).lastrowid
            for product_id, qty, price, line_total in prepared:
                product = self.db.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
                if not product or not product["active"]:
                    raise ValueError("사용 가능한 상품을 선택해 주세요.")
                if kind == "purchase":
                    cost = line_total
                    stock_cost = product["stock_cost"] + cost
                else:
                    if product["stock_qty"] < qty:
                        raise ValueError(f"'{product['name']}' 재고가 부족합니다. 현재 재고: {_qty_text(product['stock_qty'])} {product['unit']}")
                    cost = _rounded(Decimal(product["stock_cost"]) * qty / product["stock_qty"])
                    stock_cost = product["stock_cost"] - cost
                if stock_cost > MAX_INTEGER:
                    raise ValueError("재고 금액이 허용 범위를 초과했습니다.")
                self.db.execute("INSERT INTO document_items(document_id,product_id,product_name,unit,qty,unit_price,total,cost) VALUES(?,?,?,?,?,?,?,?)",
                                (document_id, product_id, product["name"], product["unit"], qty, price, line_total, cost))
                self._stock_move(product_id, qty if kind == "purchase" else -qty, kind, str(memo).strip() or number, document_id, date)
                self.db.execute("UPDATE products SET stock_cost=? WHERE id=?", (stock_cost, product_id))
            if paid:
                self.db.execute("INSERT INTO payments(document_id,amount,date,memo,user_id,created_at) VALUES(?,?,?,?,?,?)", (document_id, paid, date, "전표 등록 시 결제", self.user["id"], now))
            self._audit("create", "document", document_id, {"number": number, "total": total, "paid": paid})
        return document_id

    def list_documents(self, kind, start="", end="", partner_id=None, search="", status="") -> list[dict]:
        self._require(self._kind(kind), "reports")
        clauses, params = ["d.kind=?"], [kind]
        if start:
            clauses.append("d.date>=?")
            params.append(_day(start))
        if end:
            clauses.append("d.date<=?")
            params.append(_day(end))
        if start and end and start > end:
            raise ValueError("조회 시작일은 종료일보다 늦을 수 없습니다.")
        if partner_id is not None:
            clauses.append("d.partner_id=?")
            params.append(partner_id)
        if search:
            clauses.append("(d.number LIKE ? OR p.name LIKE ? OR d.memo LIKE ? OR EXISTS (SELECT 1 FROM document_items i WHERE i.document_id=d.id AND i.product_name LIKE ?))")
            params.extend([f"%{search}%"] * 4)
        if status:
            if status not in {"posted", "cancelled"}:
                raise ValueError("전표 상태가 올바르지 않습니다.")
            clauses.append("d.status=?")
            params.append(status)
        rows = self.db.execute("""SELECT d.*,p.name AS partner_name,u.name AS user_name,
            CASE WHEN d.status='posted' THEN d.total-d.paid ELSE 0 END AS balance,
            (SELECT COUNT(*) FROM document_items i WHERE i.document_id=d.id) AS items_count
            FROM documents d JOIN partners p ON p.id=d.partner_id JOIN users u ON u.id=d.user_id
            WHERE """ + " AND ".join(clauses) + " ORDER BY d.date DESC,d.id DESC", params)
        return [dict(row) for row in rows]

    def _document(self, document_id):
        row = self.db.execute("SELECT d.*,p.name AS partner_name,u.name AS user_name,CASE WHEN d.status='posted' THEN d.total-d.paid ELSE 0 END AS balance FROM documents d JOIN partners p ON p.id=d.partner_id JOIN users u ON u.id=d.user_id WHERE d.id=?", (document_id,)).fetchone()
        if not row:
            raise ValueError("전표를 찾을 수 없습니다.")
        return row

    def get_document(self, document_id) -> dict:
        self._current()
        row = self._document(document_id)
        self._require(self._kind(row["kind"]), "reports")
        result = dict(row)
        result["items"] = []
        for item in self.db.execute("SELECT * FROM document_items WHERE document_id=? ORDER BY id", (document_id,)):
            entry = dict(item)
            entry["qty"] = _qty_text(entry["qty"])
            result["items"].append(entry)
        result["payments"] = [dict(item) for item in self.db.execute("SELECT p.*,u.name AS user_name FROM payments p JOIN users u ON u.id=p.user_id WHERE p.document_id=? ORDER BY p.id", (document_id,))]
        return result

    def product_history(self, product_id, kind="") -> list[dict]:
        """A single query for a product's purchase/sale history, including reversals."""
        if kind:
            self._require(self._kind(kind), "products", "inventory", "reports")
        else:
            self._require("products", "inventory", "reports")
        clauses, params = ["i.product_id=?"], [product_id]
        if kind:
            clauses.append("d.kind=?")
            params.append(kind)
        rows = self.db.execute("""SELECT d.*,p.name AS partner_name,u.name AS user_name,
            CASE WHEN d.status='posted' THEN d.total-d.paid ELSE 0 END AS balance,
            i.qty,i.unit_price,i.total AS item_total,i.unit,i.product_name
            FROM document_items i JOIN documents d ON d.id=i.document_id
            JOIN partners p ON p.id=d.partner_id JOIN users u ON u.id=d.user_id
            WHERE """ + " AND ".join(clauses) + " ORDER BY d.date DESC,d.id DESC,i.id", params)
        result = []
        for row in rows:
            item = dict(row)
            item["qty"] = _qty_text(item["qty"])
            result.append(item)
        return result

    def add_payment(self, doc_id, amount, date, memo=""):
        self._current()
        amount, date = _integer(amount, "결제 금액", positive=True), _day(date)
        with self._transaction():
            row = self._document(doc_id)
            self._require(self._kind(row["kind"]))
            if row["status"] != "posted":
                raise ValueError("취소된 전표에는 결제할 수 없습니다.")
            if amount > row["total"] - row["paid"]:
                raise ValueError("결제 금액은 미결제 잔액을 초과할 수 없습니다.")
            if date < row["date"]:
                raise ValueError("결제일은 거래일보다 이전일 수 없습니다.")
            self.db.execute("INSERT INTO payments(document_id,amount,date,memo,user_id,created_at) VALUES(?,?,?,?,?,?)",
                            (doc_id, amount, date, str(memo).strip(), self.user["id"], datetime.now().astimezone().isoformat(timespec="seconds")))
            self.db.execute("UPDATE documents SET paid=paid+? WHERE id=?", (amount, doc_id))
            self._audit("payment", "document", doc_id, {"amount": amount, "date": date})

    def cancel_document(self, doc_id, reason):
        self._current()
        if not str(reason).strip():
            raise ValueError("취소 사유를 입력해 주세요.")
        with self._transaction():
            doc = self._document(doc_id)
            self._require(self._kind(doc["kind"]))
            if doc["status"] != "posted":
                raise ValueError("이미 취소된 전표입니다.")
            if doc["paid"]:
                raise ValueError("결제 이력이 있는 전표는 취소할 수 없습니다. 정산 내역을 확인해 주세요.")
            # Reverse line order so repeated products return to their preceding state.
            for item in self.db.execute("SELECT * FROM document_items WHERE document_id=? ORDER BY id DESC", (doc_id,)).fetchall():
                product = self.db.execute("SELECT * FROM products WHERE id=?", (item["product_id"],)).fetchone()
                if doc["kind"] == "purchase" and self.db.execute("""SELECT 1 FROM stock_movements m
                    LEFT JOIN documents later ON later.id=m.document_id
                    WHERE m.product_id=? AND m.id>(SELECT MAX(id) FROM stock_movements
                        WHERE document_id=? AND product_id=? AND kind='purchase')
                    AND ((m.kind='sale' AND later.status='posted') OR (m.kind='adjustment' AND m.qty<0)) LIMIT 1""",
                    (item["product_id"], doc_id, item["product_id"])).fetchone():
                    raise ValueError("이 매입 이후 유효한 매출 또는 재고 차감이 있어 취소할 수 없습니다. 관련 매출을 먼저 취소해 주세요.")
                delta = -item["qty"] if doc["kind"] == "purchase" else item["qty"]
                cost_delta = -item["cost"] if doc["kind"] == "purchase" else item["cost"]
                resulting_cost = product["stock_cost"] + cost_delta
                if resulting_cost < 0 or (product["stock_qty"] + delta == 0 and resulting_cost != 0):
                    raise ValueError("이후 재고 거래로 원가가 변경되어 취소할 수 없습니다. 관련 매출 취소 후 다시 시도해 주세요.")
                if resulting_cost > MAX_INTEGER:
                    raise ValueError("취소 후 재고 금액이 허용 범위를 초과합니다.")
                self._stock_move(item["product_id"], delta, "cancel_" + doc["kind"], str(reason).strip(), doc_id)
                self.db.execute("UPDATE products SET stock_cost=stock_cost+? WHERE id=?", (cost_delta, item["product_id"]))
            self.db.execute("UPDATE documents SET status='cancelled',cancelled_reason=? WHERE id=?", (str(reason).strip(), doc_id))
            self._audit("cancel", "document", doc_id, {"reason": str(reason).strip()})

    def list_stock(self, search="") -> list[dict]:
        self._require("inventory", "reports")
        return self.list_products(search=search)

    def adjust_stock(self, product_id, delta, reason):
        self._require("inventory")
        delta = _quantity(delta, signed=True)
        if not str(reason).strip():
            raise ValueError("재고 조정 사유를 입력해 주세요.")
        with self._transaction():
            self._require("inventory")
            product = self.db.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
            if not product or not product["active"]:
                raise ValueError("사용 가능한 상품을 선택해 주세요.")
            if delta > 0:
                cost_delta = _rounded(Decimal(delta) * (Decimal(product["stock_cost"]) / product["stock_qty"] if product["stock_qty"] else Decimal(product["purchase_price"]) / 1000))
            else:
                if product["stock_qty"] < -delta:
                    raise ValueError("차감 수량이 현재 재고를 초과합니다.")
                cost_delta = -_rounded(Decimal(product["stock_cost"]) * (-delta) / product["stock_qty"])
            if product["stock_cost"] + cost_delta > MAX_INTEGER:
                raise ValueError("재고 금액이 허용 범위를 초과했습니다.")
            self._stock_move(product_id, delta, "adjustment", str(reason).strip())
            self.db.execute("UPDATE products SET stock_cost=stock_cost+? WHERE id=?", (cost_delta, product_id))
            self._audit("adjust_stock", "product", product_id, {"qty": _qty_text(delta), "reason": str(reason).strip()})

    def list_stock_movements(self, product_id=None) -> list[dict]:
        self._require("inventory", "reports")
        rows = self.db.execute("SELECT m.*,p.name AS product_name,COALESCE(d.number,'') AS document_number FROM stock_movements m JOIN products p ON p.id=m.product_id LEFT JOIN documents d ON d.id=m.document_id" + (" WHERE m.product_id=?" if product_id is not None else "") + " ORDER BY m.id DESC", (product_id,) if product_id is not None else ())
        result = []
        for row in rows:
            item = dict(row)
            item["qty"], item["balance_qty"] = _qty_text(item["qty"]), _qty_text(item["balance_qty"])
            result.append(item)
        return result

    def dashboard(self, start="", end="") -> dict:
        self._require("reports")
        clauses, params = ["status='posted'"], []
        if start:
            clauses.append("date>=?")
            params.append(_day(start))
        if end:
            clauses.append("date<=?")
            params.append(_day(end))
        if start and end and start > end:
            raise ValueError("조회 시작일은 종료일보다 늦을 수 없습니다.")
        totals = self.db.execute("SELECT kind,COALESCE(SUM(total),0) AS total FROM documents WHERE " + " AND ".join(clauses) + " GROUP BY kind", params).fetchall()
        summary = {"purchase_total": 0, "sale_total": 0, "payable": 0, "receivable": 0}
        for row in totals:
            summary[("purchase" if row["kind"] == "purchase" else "sale") + "_total"] = row["total"]
        for row in self.db.execute("SELECT kind,SUM(total-paid) AS balance FROM documents WHERE status='posted' GROUP BY kind"):
            summary["payable" if row["kind"] == "purchase" else "receivable"] = row["balance"]
        inventory = self.db.execute("SELECT COALESCE(SUM(stock_cost),0),COUNT(*),COALESCE(SUM(CASE WHEN active=1 AND stock_qty<=min_stock THEN 1 ELSE 0 END),0) FROM products").fetchone()
        summary.update(stock_value=inventory[0], product_count=inventory[1], low_stock_count=inventory[2])
        summary["profit"] = self.db.execute("SELECT COALESCE(SUM(i.total-i.cost),0) FROM document_items i JOIN documents d ON d.id=i.document_id WHERE d.kind='sale' AND " + " AND ".join("d." + clause for clause in clauses), params).fetchone()[0]
        return summary

    def report(self, start, end) -> dict:
        self._require("reports")
        start, end = _day(start), _day(end)
        summary = self.dashboard(start, end)
        days: dict[str, dict] = {}
        def entry(day):
            return days.setdefault(day, {"date": day, "purchase_total": 0, "sale_total": 0, "paid_purchase": 0, "paid_sale": 0})
        for row in self.db.execute("SELECT date,kind,SUM(total) AS total FROM documents WHERE status='posted' AND date BETWEEN ? AND ? GROUP BY date,kind", (start, end)):
            entry(row["date"])["purchase_total" if row["kind"] == "purchase" else "sale_total"] = row["total"]
        for row in self.db.execute("SELECT p.date,d.kind,SUM(p.amount) AS amount FROM payments p JOIN documents d ON d.id=p.document_id WHERE d.status='posted' AND p.date BETWEEN ? AND ? GROUP BY p.date,d.kind", (start, end)):
            entry(row["date"])["paid_purchase" if row["kind"] == "purchase" else "paid_sale"] = row["amount"]
        return {"summary": summary, "daily": [days[key] for key in sorted(days)]}

    def audit_log(self, entity=None, entity_id=None) -> list[dict]:
        self._require("settings")
        clauses, params = [], []
        if entity:
            clauses.append("entity=?")
            params.append(entity)
        if entity_id is not None:
            clauses.append("entity_id=?")
            params.append(entity_id)
        rows = self.db.execute("SELECT * FROM audit" + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY id DESC", params)
        return [dict(row) for row in rows]

    def backup(self, path):
        self._require("settings")
        target = Path(path)
        if self.path and target.resolve() == self.path.resolve():
            raise ValueError("사용 중인 데이터 파일과 다른 백업 경로를 선택해 주세요.")
        if target.exists():
            raise ValueError("백업 파일이 이미 있습니다. 새 파일 이름을 선택해 주세요.")
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            destination = sqlite3.connect(str(target))
            try:
                self.db.backup(destination)
                if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("백업 파일의 무결성 검증에 실패했습니다.")
            finally:
                destination.close()
        except (sqlite3.Error, OSError) as exc:
            raise ValueError("백업 파일을 만들 수 없습니다. 경로와 저장 공간을 확인해 주세요.") from exc
        with self._transaction():
            self._audit("backup", "database", None, {"filename": target.name})

    def close(self):
        self.user = None
        self.db.close()
