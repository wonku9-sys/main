"""Upgrade real v1-shaped stores without changing existing accounting data."""

from datetime import datetime
import json
import sqlite3

import pytest

from seoyoung_pos.security import hash_password
from seoyoung_pos.service import POSService


LEGACY_SCHEMA = """
CREATE TABLE users (
    id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name TEXT NOT NULL, password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('admin','staff')), permissions TEXT NOT NULL DEFAULT '[]');
CREATE TABLE partners (
    id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('supplier','customer')),
    code TEXT NOT NULL, name TEXT NOT NULL, business_no TEXT NOT NULL DEFAULT '',
    contact TEXT NOT NULL DEFAULT '', phone TEXT NOT NULL DEFAULT '', bank TEXT NOT NULL DEFAULT '',
    account TEXT NOT NULL DEFAULT '', account_holder TEXT NOT NULL DEFAULT '', memo TEXT NOT NULL DEFAULT '',
    UNIQUE(kind,code));
CREATE TABLE products (
    id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, barcode TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL, category TEXT NOT NULL DEFAULT '', specification TEXT NOT NULL DEFAULT '',
    unit TEXT NOT NULL DEFAULT 'kg', origin TEXT NOT NULL DEFAULT '', supplier_id INTEGER REFERENCES partners(id),
    purchase_price INTEGER NOT NULL DEFAULT 0 CHECK(purchase_price>=0),
    sale_price INTEGER NOT NULL DEFAULT 0 CHECK(sale_price>=0),
    min_stock INTEGER NOT NULL DEFAULT 0 CHECK(min_stock>=0),
    stock_qty INTEGER NOT NULL DEFAULT 0 CHECK(stock_qty>=0),
    stock_cost INTEGER NOT NULL DEFAULT 0 CHECK(stock_cost>=0),
    memo TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1 CHECK(active IN(0,1)));
CREATE TABLE documents (
    id INTEGER PRIMARY KEY, number TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL CHECK(kind IN ('purchase','sale')), date TEXT NOT NULL,
    partner_id INTEGER NOT NULL REFERENCES partners(id), total INTEGER NOT NULL CHECK(total>=0),
    paid INTEGER NOT NULL DEFAULT 0 CHECK(paid>=0 AND paid<=total), memo TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'posted' CHECK(status IN('posted','cancelled')),
    user_id INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
    cancelled_reason TEXT NOT NULL DEFAULT '');
CREATE TABLE document_items (
    id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL REFERENCES documents(id),
    product_id INTEGER NOT NULL REFERENCES products(id), product_name TEXT NOT NULL,
    unit TEXT NOT NULL, qty INTEGER NOT NULL CHECK(qty>0),
    unit_price INTEGER NOT NULL CHECK(unit_price>=0), total INTEGER NOT NULL CHECK(total>=0),
    cost INTEGER NOT NULL DEFAULT 0 CHECK(cost>=0));
CREATE TABLE payments (
    id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL REFERENCES documents(id),
    amount INTEGER NOT NULL CHECK(amount>0), date TEXT NOT NULL,
    memo TEXT NOT NULL DEFAULT '', user_id INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL);
CREATE TABLE stock_movements (
    id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id),
    date TEXT NOT NULL, kind TEXT NOT NULL, qty INTEGER NOT NULL, balance_qty INTEGER NOT NULL CHECK(balance_qty>=0),
    reason TEXT NOT NULL, document_id INTEGER REFERENCES documents(id),
    user_id INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL);
CREATE TABLE audit (
    id INTEGER PRIMARY KEY, at TEXT NOT NULL, user_id INTEGER,
    username TEXT NOT NULL, action TEXT NOT NULL, entity TEXT NOT NULL,
    entity_id INTEGER, detail TEXT NOT NULL);
PRAGMA user_version=1;
"""


def legacy_database(path):
    """Keep the previous schema fixture independent of the new migration code."""
    with sqlite3.connect(path) as db:
        db.executescript(LEGACY_SCHEMA)
        db.execute("INSERT INTO users VALUES(1,'admin','기존 관리자',?,'admin','[]')",
                   (hash_password("legacy-password"),))
        db.executemany("INSERT INTO partners(id,kind,code,name,memo) VALUES(?,?,?,?,?)", [
            (1, "supplier", "S1", "기존 공급사", "공급사 보존"),
            (2, "customer", "C1", "기존 고객", "고객 보존"),
        ])
        db.execute("""INSERT INTO products VALUES(
            1,'P1','880000000001','기존 삼겹살','정육','냉장','kg','국내산',1,
            3000,5000,1500,8000,24000,'원래 상품 메모',1)""")
        db.executemany("INSERT INTO documents VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", [
            (1, "PI-20261001-000001", "purchase", "2026-10-01", 1, 30000, 6000,
             "원래 매입", "posted", 1, "2026-10-01T10:00:00+09:00", ""),
            (2, "SO-20261002-000002", "sale", "2026-10-02", 2, 10000, 0,
             "원래 매출", "posted", 1, "2026-10-02T10:00:00+09:00", ""),
        ])
        db.executemany("INSERT INTO document_items VALUES(?,?,?,?,?,?,?,?,?)", [
            (1, 1, 1, "기존 삼겹살", "kg", 10000, 3000, 30000, 30000),
            (2, 2, 1, "기존 삼겹살", "kg", 2000, 5000, 10000, 6000),
        ])
        db.execute("INSERT INTO payments VALUES(1,1,6000,'2026-10-01','원래 결제',1,'2026-10-01T10:00:00+09:00')")
        db.executemany("INSERT INTO stock_movements VALUES(?,?,?,?,?,?,?,?,?,?)", [
            (1, 1, "2026-10-01", "purchase", 10000, 10000, "원래 매입", 1, 1, "2026-10-01T10:00:00+09:00"),
            (2, 1, "2026-10-02", "sale", -2000, 8000, "원래 매출", 2, 1, "2026-10-02T10:00:00+09:00"),
        ])
        db.execute("INSERT INTO audit VALUES(1,'2026-10-01T10:00:00+09:00',1,'admin','create','product',1,?)",
                   (json.dumps({"name": "기존 삼겹살"}, ensure_ascii=False),))
        tables = ("users", "partners", "products", "documents", "document_items", "payments", "stock_movements", "audit")
        return {name: (tuple(row[1] for row in db.execute(f"PRAGMA table_info({name})")),
                       db.execute(f"SELECT * FROM {name} ORDER BY id").fetchall()) for name in tables}


@pytest.fixture
def service(tmp_path):
    instance = POSService(tmp_path / "metadata.db")
    instance.create_initial_admin("admin", "관리자", "metadata-password")
    instance.login("admin", "metadata-password")
    yield instance
    instance.close()


def product_data(**overrides):
    return {"code": "P1", "name": "국내산 삼겹살", "unit": "kg", "purchase_price": 18800,
            "sale_price": 28000, "min_stock": "1.250", **overrides}


def test_v1_migration_preserves_all_original_rows_and_accounting(tmp_path):
    path = tmp_path / "legacy.db"
    original = legacy_database(path)
    service = POSService(path)
    try:
        for table, (columns, rows) in original.items():
            after = service.db.execute(f"SELECT {','.join(columns)} FROM {table} ORDER BY id").fetchall()
            assert [tuple(row) for row in after] == rows
        assert service.db.execute("PRAGMA user_version").fetchone()[0] == 2
        assert service.db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        service.login("admin", "legacy-password")
        product = service.list_products()[0]
        assert product["stock_qty"] == "8.000"
        assert product["stock_cost"] == 24000
        assert product["tax_type"] == "exempt"
        assert product["box_quantity"] == "0.000"
        assert product["created_at"] == product["updated_at"] == ""
        assert service.get_document(1)["paid"] == 6000
        assert service.get_document(2)["items"][0]["cost"] == 6000
        summary = service.dashboard()
        assert (summary["payable"], summary["receivable"], summary["profit"]) == (24000, 10000, 4000)
        assert json.loads(service.product_changes(1)[0]["detail"]) == {"name": "기존 삼겹살"}
    finally:
        service.close()
    # A restart must neither reapply defaults nor duplicate the original data.
    service = POSService(path)
    try:
        service.login("admin", "legacy-password")
        assert service.list_products()[0]["stock_cost"] == 24000
        assert len(service.get_document(1)["payments"]) == 1
    finally:
        service.close()


def test_migration_never_downgrades_a_future_schema_version(tmp_path):
    path = tmp_path / "future.db"
    legacy_database(path)
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version=41")
        db.execute("ALTER TABLE products ADD COLUMN future_note TEXT DEFAULT '보존'")
    service = POSService(path)
    try:
        assert service.db.execute("PRAGMA user_version").fetchone()[0] == 41
        assert service.db.execute("SELECT future_note FROM products").fetchone()[0] == "보존"
    finally:
        service.close()


def test_metadata_round_trip_partial_old_client_update_and_timestamps(service):
    metadata = {"tax_type": "taxable", "category_mid": "돈육", "category_small": "삼겹살",
                "receipt_name": "냉장 삼겹살", "capacity": "2.5", "unit_capacity": "100g",
                "keywords": "구이 냉장", "warehouse": "냉장 A", "shelf": "3열",
                "box_quantity": "12.345"}
    product_id = service.save_product(product_data(**metadata))
    created = service.list_products()[0]
    for key, value in metadata.items():
        assert created[key] == value
    assert datetime.fromisoformat(created["created_at"])
    assert datetime.fromisoformat(created["updated_at"])
    assert service.db.execute("SELECT box_quantity FROM products").fetchone()[0] == 12345
    service.db.execute("UPDATE products SET updated_at='2000-01-01T00:00:00+09:00' WHERE id=?", (product_id,))
    # Previous application versions do not send any of the added keys.
    service.save_product(product_data(name="이름 수정"), product_id)
    updated = service.list_products()[0]
    for key, value in metadata.items():
        assert updated[key] == value
    assert updated["created_at"] == created["created_at"]
    assert updated["updated_at"] != "2000-01-01T00:00:00+09:00"
    assert (updated["stock_qty"], updated["stock_cost"]) == ("0.000", 0)
    assert json.loads(service.product_changes(product_id)[0]["detail"]) == {
        "changes": {"name": {"old": "국내산 삼겹살", "new": "이름 수정"}}}
    service.save_product(product_data(**{**metadata, "box_quantity": "0", "category_mid": ""}), product_id)
    assert service.list_products()[0]["box_quantity"] == "0.000"
    assert service.list_products()[0]["category_mid"] == ""


@pytest.mark.parametrize("value", ["-1", "-0.001", "0.0001", "NaN", "Infinity", "9000000001", None])
def test_invalid_box_quantity_is_atomic(service, value):
    product_id = service.save_product(product_data(box_quantity="2"))
    before = service.list_products()[0]
    history = service.product_changes(product_id)
    with pytest.raises(ValueError, match="박스 입수"):
        service.save_product(product_data(box_quantity=value), product_id)
    assert service.list_products()[0] == before
    assert service.product_changes(product_id) == history


@pytest.mark.parametrize("value", ["unknown", "", None, [], 1])
def test_invalid_tax_metadata_is_rejected_without_creating_rows(service, value):
    with pytest.raises(ValueError, match="과세 구분"):
        service.save_product(product_data(tax_type=value))
    assert service.list_products() == []


def test_tax_metadata_never_changes_transaction_or_inventory_calculations(service):
    supplier = service.save_partner({"kind": "supplier", "code": "S1", "name": "공급사"})
    customer = service.save_partner({"kind": "customer", "code": "C1", "name": "고객"})
    product_id = service.save_product(product_data(tax_type="taxable", box_quantity="100"))
    purchase = service.create_document("purchase", supplier, "2026-10-17", [
        {"product_id": product_id, "qty": "0.125", "unit_price": 1004}])
    sale = service.create_document("sale", customer, "2026-10-17", [
        {"product_id": product_id, "qty": "0.125", "unit_price": 2000}])
    assert service.get_document(purchase)["total"] == 126
    assert service.get_document(sale)["total"] == 250
    assert service.get_document(sale)["items"][0]["cost"] == 126
    product = service.list_products()[0]
    assert (product["stock_qty"], product["stock_cost"]) == ("0.000", 0)


def test_product_search_matches_keywords_and_receipt_name_with_existing_category_filter(service):
    product_id = service.save_product(product_data(
        category="정육", keywords="캠핑용 바비큐", receipt_name="냉장 돈육"))
    service.save_product(product_data(code="P2", name="목심", category="기타"))
    for search in ("P1", "삼겹살", "바비큐", "냉장 돈육"):
        assert [row["id"] for row in service.list_products(search=search)] == [product_id]
    assert service.list_products(search="바비큐", category="기타") == []
    assert [row["id"] for row in service.list_products(search="바비큐", category="정육")] == [product_id]


def test_product_changes_are_scoped_sanitized_and_include_real_field_diffs(service):
    product_id = service.save_product(product_data(box_quantity="4"))
    created = json.loads(service.product_changes(product_id)[0]["detail"])["changes"]
    assert created["name"] == {"old": None, "new": "국내산 삼겹살"}
    assert created["box_quantity"] == {"old": None, "new": "4.000"}
    service.save_product(product_data(sale_price=29000, warehouse="B"), product_id)
    changed = json.loads(service.product_changes(product_id)[0]["detail"])["changes"]
    assert changed == {"sale_price": {"old": 28000, "new": 29000},
                       "warehouse": {"old": "", "new": "B"}}
    second = service.save_product(product_data(code="P2", name="다른 상품"))
    service._audit("unrelated", "user", product_id, {"password_hash": "never-return-user-secret"})
    service._audit("legacy", "product", product_id, {
        "name": "과거 상품", "password_hash": "never-return-product-secret",
        "changes": {"name": {"old": "전", "new": "후", "password": "never-return-nested-secret"},
                    "password_hash": {"old": "never-return-secret", "new": "never-return-secret"}},
    })
    history = service.product_changes(product_id)
    assert all(set(row) == {"at", "username", "action", "detail"} for row in history)
    assert all(row["action"] != "unrelated" for row in history)
    assert "never-return" not in json.dumps(history)
    assert "다른 상품" not in json.dumps(history, ensure_ascii=False)
    assert len(service.product_changes(second)) == 1


def test_product_history_uses_relevant_permission_and_keeps_global_audit_private(service):
    product_id = service.save_product(product_data())
    for permission in ("products", "reports", "inventory"):
        service.save_user({"username": permission, "name": permission, "password": "staff-password",
                           "role": "staff", "permissions": [permission]})
    for permission in ("products", "reports"):
        service.login(permission, "staff-password")
        assert service.product_changes(product_id)[0]["action"] == "create"
        with pytest.raises(PermissionError):
            service.audit_log()
    service.login("inventory", "staff-password")
    with pytest.raises(PermissionError):
        service.product_changes(product_id)
    service.logout()
    with pytest.raises(PermissionError):
        service.product_changes(product_id)
