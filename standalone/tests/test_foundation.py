"""Business boundaries for the clean independent store, not the former program."""

from decimal import Decimal
import json
import sqlite3

import pytest

from pos2.common import LIMIT, day, money, qty, qtext, rounded
from pos2.store import Store


@pytest.fixture
def store(tmp_path):
    instance = Store(tmp_path / "fresh.db")
    instance.setup_admin("owner", "관리자", "Owner-Strong-2026!")
    yield instance
    instance.close()


def product(store, **extra):
    return store.save_product({"name": "한돈 삼겹살", "base_unit": "kg", "purchase_price": 10000, "sale_price": 18000, **extra})


def supplier(store, **extra):
    return store.save_partner({"name": "정육 공급사", "kind": "supplier", **extra})


def purchase(store, product_id, supplier_id, unit_id=None):
    return store.post_document({"kind": "purchase", "date": "2026-10-19", "partner_id": supplier_id, "lines": [{"product_id": product_id, "unit_id": unit_id, "qty": "2.5", "unit_price": 10000}], "paid": 0})


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "abc", ""])
def test_invalid_numbers(value):
    with pytest.raises(ValueError):
        qty(value)
    with pytest.raises(ValueError):
        money(value)


def test_exact_quantities_money_and_bounds():
    assert qty("1.001") == 1001
    assert qty("-0.001", signed=True) == -1
    assert qty("0", allow_zero=True) == 0
    assert qtext(1250) == "1.250"
    assert rounded(Decimal("-1.5")) == -2
    assert money("1,234.5") == 1235
    for value in ("0.0001", "-1", "0", str(LIMIT)):
        with pytest.raises(ValueError):
            qty(value)
    with pytest.raises(ValueError):
        money(str(LIMIT + 1))
    with pytest.raises(ValueError):
        money("-0.1")
    with pytest.raises(ValueError):
        day("2026-02-30")


def test_empty_database_has_no_default_admin_or_demo(tmp_path):
    instance = Store(tmp_path / "empty.db")
    try:
        assert instance.users_count() == 0
        assert instance.actor is None
        assert instance.db.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0
        assert instance.db.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0
        with pytest.raises(ValueError):
            instance.setup_admin("admin", "관리자", "1234")
        with pytest.raises(ValueError):
            instance.login("admin", "admin")
    finally:
        instance.close()


def test_hash_salts_password_changes_and_audit_secrets(store):
    second = store.save_user({"code": "other", "name": "직원", "password": "Owner-Strong-2026!", "permissions": ["catalog"]})
    rows = list(store.db.execute("SELECT password_hash FROM users ORDER BY id"))
    assert rows[0][0].startswith("scrypt$") and rows[0][0] != rows[1][0]
    assert "Owner-Strong-2026!" not in json.dumps(store.audit_log(), ensure_ascii=False)
    store.change_password("Owner-Strong-2026!", "Changed-Pass-2026!")
    store.logout()
    with pytest.raises(ValueError):
        store.login("owner", "Owner-Strong-2026!")
    store.login("owner", "Changed-Pass-2026!")
    with pytest.raises(ValueError):
        store.setup_admin("new", "새 관리자", "New-Strong-2026!")
    assert second > 1


def test_user_protection_permissions_and_deletion(store):
    with pytest.raises(ValueError):
        store.delete_user(store.actor["id"])
    with pytest.raises(ValueError):
        store.save_user({"role": "staff", "permissions": []}, store.actor["id"])
    staff = store.save_user({"code": "staff", "name": "직원", "password": "Staff-Strong-2026!", "permissions": ["catalog"]})
    with pytest.raises(ValueError):
        store.save_user({"role": "staff", "permissions": ["admin"]}, staff)
    store.logout()
    store.login("staff", "Staff-Strong-2026!")
    with pytest.raises(PermissionError):
        store.save_user({"code": "bad"})
    with pytest.raises(PermissionError):
        store.settings()
    assert store.products() == []
    store.logout()
    store.login("owner", "Owner-Strong-2026!")
    store.delete_user(staff)
    assert len(store.list_users()) == 1


def test_current_account_protection_handles_numeric_text_identifier(store):
    store.save_user({"code": "other-admin", "name": "다른 관리자", "role": "admin", "password": "Other-Admin-2026!"})
    with pytest.raises(ValueError, match="현재 로그인"):
        store.delete_user(str(store.actor["id"]))


def test_permission_revoked_on_another_connection_is_immediate(store):
    staff = store.save_user({"code": "staff", "name": "직원", "password": "Staff-Strong-2026!", "permissions": ["catalog"]})
    another = Store(store.path)
    try:
        another.login("staff", "Staff-Strong-2026!")
        assert another.products() == []
        store.save_user({"permissions": ["trade"]}, staff)
        with pytest.raises(PermissionError):
            another.save_product({"name": "권한 없는 입력"})
        assert another.trade_products() == []
        store.save_user({"active": False}, staff)
        with pytest.raises(PermissionError):
            another.trade_products()
        assert another.actor is None
    finally:
        another.close()


def test_catalog_all_metadata_and_persistence(store):
    partner = supplier(store, business_no="123-45-67890", contact="김담당", phone="010-1111-2222", bank="은행", account="123", account_holder="서영", supplier_mode="commission", commission_bps=500)
    identifier = product(store, code="M001", barcode="8800000000001", receipt_name="삼겹", category="돈육", category_mid="냉장", category_small="삼겹", specification="무항생제", tax_mode="taxable", supplier_id=partner, min_qty="1.125", origin="국산", warehouse="냉장1", shelf="A03", keywords="구이", memo="상품 설명")
    row = store.products(search="구이")[0]
    assert row["id"] == identifier and row["min_qty"] == "1.125"
    assert row["stock_qty"] == "0.000" and row["stock_cost"] == 0
    assert row["receipt_name"] == "삼겹" and row["supplier_name"] == "정육 공급사"
    assert row["origin"] == "국산" and row["warehouse"] == "냉장1"
    store.save_product({"sale_price": 19000}, identifier)
    assert store.products()[0]["keywords"] == "구이"
    again = Store(store.path)
    try:
        again.login("owner", "Owner-Strong-2026!")
        assert again.products()[0]["sale_price"] == 19000
        assert again.partners("supplier")[0]["commission_bps"] == 500
    finally:
        again.close()


def test_barcode_uniqueness_across_products_and_units_rolls_back(store):
    one = product(store, barcode="BASE-A")
    two = product(store, name="목살", barcode="BASE-B")
    unit = store.save_unit({"product_id": one, "name": "박스", "barcode": "PACK-A", "factor": "12", "sale_price": 180000})
    audit_count = store.db.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
    for fn in (
        lambda: product(store, barcode="PACK-A"),
        lambda: store.save_product({"barcode": "PACK-A"}, two),
        lambda: store.save_unit({"product_id": two, "name": "팩", "barcode": "BASE-A", "factor": "0.5"}),
        lambda: store.save_unit({"barcode": "BASE-B"}, unit),
    ):
        with pytest.raises(ValueError):
            fn()
    assert store.db.execute("SELECT COUNT(*) FROM audit").fetchone()[0] == audit_count
    assert store.lookup_barcode("PACK-A")["unit"]["factor"] == "12.000"
    assert store.lookup_barcode("BASE-A")["product"]["id"] == one
    assert store.lookup_barcode("") is None
    assert store.lookup_barcode("missing") is None


def test_base_units_factor_history_and_delete_guards(store):
    partner = supplier(store)
    identifier = product(store)
    unit = store.save_unit({"product_id": identifier, "name": "500g팩", "factor": ".5", "barcode": "FIVE"})
    with pytest.raises(ValueError):
        store.save_product({"base_unit": "g"}, identifier)
    document = purchase(store, identifier, partner, unit)
    assert store.products()[0]["stock_qty"] == "1.250"
    assert store.document(document)["lines"][0]["base_qty"] == "1.250"
    for fn in (
        lambda: store.save_unit({"factor": "1"}, unit),
        lambda: store.delete_unit(unit),
        lambda: store.delete_product(identifier),
        lambda: store.delete_partner(partner),
        lambda: store.save_product({"tracked": False}, identifier),
    ):
        with pytest.raises(ValueError):
            fn()
    store.save_unit({"sale_price": 12000}, unit)
    assert store.units(identifier)[0]["factor"] == "0.500"


def test_unused_catalog_can_delete_and_bulk_is_atomic(store):
    one, two = product(store), product(store, name="목살")
    store.save_unit({"product_id": one, "name": "팩", "factor": ".5"})
    store.bulk_category([one, two], "돈육")
    assert all(row["category"] == "돈육" for row in store.products())
    with pytest.raises(ValueError):
        store.bulk_category([one, 999999], "실패 분류")
    assert store.products()[0]["category"] == "돈육"
    store.delete_product(one)
    assert [row["id"] for row in store.products()] == [two]


def test_inventory_count_snapshot_locks_product_base_unit(store):
    identifier = product(store)
    store.create_count({"title": "첫 실사", "date": "2026-10-19", "items": [{"product_id": identifier, "expected_qty": "0", "counted_qty": "1"}]})
    with pytest.raises(ValueError):
        store.save_product({"base_unit": "g"}, identifier)


def test_partner_opening_balance_no_double_count_and_history_lock(store):
    partner = supplier(store, opening_balance=12345, opening_date="2026-10-01")
    assert store.partners("supplier")[0]["balance"] == 12345
    store.save_partner({"opening_balance": 20000}, partner)
    identifier = product(store)
    document = purchase(store, identifier, partner)
    assert store.partners("supplier")[0]["balance"] == 45000
    store.add_payment(document, 5000, "2026-10-19")
    assert store.partners("supplier")[0]["balance"] == 40000
    for changes in ({"opening_balance": 0}, {"opening_date": "2026-09-01"}):
        with pytest.raises(ValueError):
            store.save_partner(changes, partner)
    store.save_partner({"memo": "정기 결제"}, partner)


def test_product_scoped_history_does_not_leak_login_audit(store):
    partner = supplier(store)
    identifier = product(store)
    purchase(store, identifier, partner)
    history = store.product_history(identifier)
    assert len(history["purchases"]) == 1 and history["sales"] == []
    assert history["purchases"][0]["qty"] == "2.500"
    assert history["stock"][0]["balance_qty"] == "2.500"
    assert all(item["action"] != "login" for item in store.product_audit(identifier))


def test_settings_validation_backup_and_old_database_rejection(store, tmp_path):
    store.save_settings({"store_name": "서영 정육", "point_enabled": False, "point_step": 10})
    assert store.settings()["store_name"] == "서영 정육"
    for value in ({"point_step": 0}, {"earn_bps": 10001}, {"point_min": "1.5"}, {"point_min": None}, {"point_enabled": "true"}, {"server": "bad"}):
        with pytest.raises(ValueError):
            store.save_settings(value)
    product(store)
    target = tmp_path / "backup.db"
    store.backup(target)
    backup = Store(target)
    try:
        backup.login("owner", "Owner-Strong-2026!")
        assert len(backup.products()) == 1
        assert backup.db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        backup.close()
    with pytest.raises(ValueError):
        store.backup(target)
    with pytest.raises(ValueError):
        store.backup(store.path)
    old = tmp_path / "unrelated.db"
    connection = sqlite3.connect(old)
    connection.execute("CREATE TABLE secret(data TEXT)")
    connection.commit()
    connection.close()
    with pytest.raises(ValueError, match="기존 프로그램"):
        Store(old)
    connection = sqlite3.connect(old)
    assert connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [("secret",)]
    connection.close()


def test_transaction_context_rolls_back_and_forbids_nesting(store):
    with pytest.raises(ValueError):
        with store._tx():
            store.db.execute("INSERT INTO settings VALUES('temporary','1')")
            raise ValueError("의도된 실패")
    assert store.db.execute("SELECT 1 FROM settings WHERE key='temporary'").fetchone() is None
    with pytest.raises(RuntimeError):
        with store._tx():
            with store._tx():
                pass
