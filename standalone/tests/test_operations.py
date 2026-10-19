"""Evidence for physical stock, month locking, cashier and reporting boundaries."""

from datetime import date
from decimal import Decimal
import sqlite3

import pytest

from pos2.store import Store


@pytest.fixture
def shop(tmp_path):
    store = Store(tmp_path / "operations.db")
    store.setup_admin("owner", "점주", "Owner-Password-2026!")
    supplier = store.save_partner({"kind": "supplier", "name": "축산 공급사", "code": "SUP",
                                   "opening_date": "2024-01-01"})
    customer = store.save_partner({"kind": "customer", "name": "판매처", "code": "CUS",
                                   "opening_date": "2024-01-01"})
    product = store.save_product({"name": "삼겹살", "code": "P1", "base_unit": "kg",
                                  "supplier_id": supplier, "purchase_price": 100,
                                  "sale_price": 200, "category": "돈육"})
    yield store, supplier, customer, product
    store.close()


def trade(shop, kind="purchase", quantity="10", price=100, paid=0, **extra):
    store, supplier, customer, product = shop
    data = {"kind": kind, "date": "2025-01-10", "partner_id": supplier if kind.startswith("purchase") else customer,
            "lines": [{"product_id": product, "qty": quantity, "unit_price": price}],
            "paid": paid, "method": "transfer"}
    data.update(extra)
    return store.post_document(data)


def returned(shop, original_id, quantity, paid=0, **extra):
    store = shop[0]
    original = store.document(original_id)
    line = original["lines"][0]
    data = {"kind": original["kind"] + "_return", "date": "2025-01-11",
            "partner_id": original["partner_id"], "source_id": original_id,
            "lines": [{"product_id": line["product_id"], "unit_id": line["unit_id"],
                       "source_line_id": line["id"], "qty": quantity}], "paid": paid, "method": "transfer"}
    data.update(extra)
    return store.post_document(data)


def physical(shop, expected="10", counted="8", **extra):
    data = {"title": "월말 냉장창고 조사", "date": "2025-01-15",
            "items": [{"product_id": shop[3], "expected_qty": expected, "counted_qty": counted}]}
    data.update(extra)
    return shop[0].create_count(data)


def balance(shop):
    row = shop[0].db.execute("SELECT stock_qty,stock_cost FROM products WHERE id=?", (shop[3],)).fetchone()
    return row[0], Decimal(row[1]) / 100


def test_count_is_frozen_preview_then_persistent_once_only_application(shop):
    store = shop[0]
    trade(shop)
    count_id = physical(shop)
    assert balance(shop) == (10000, 1000)
    preview = store.count(count_id)
    assert preview["status"] == "draft"
    assert preview["items"][0]["difference"] == "-2.000"
    assert preview["items"][0]["cost_difference"] == -200
    assert store.counts()[0]["item_count"] == 1
    store.apply_count(count_id)
    assert balance(shop) == (8000, 800)
    assert store.count(count_id)["status"] == "applied"
    assert store.stock_events(shop[3])[0]["qty_delta"] == "-2.000"
    reopened = Store(store.path)
    try:
        reopened.login("owner", "Owner-Password-2026!")
        assert reopened.count(count_id)["items"][0]["counted_qty"] == "8.000"
        with pytest.raises(ValueError):
            reopened.apply_count(count_id)
        with pytest.raises(ValueError):
            reopened.delete_count(count_id)
    finally:
        reopened.close()


def test_count_stale_qty_even_other_row_rolls_back_every_product(shop):
    store = shop[0]
    trade(shop)
    second = store.save_product({"name": "목살", "base_unit": "kg", "purchase_price": 200})
    trade(shop, lines=[{"product_id": second, "qty": "3", "unit_price": 200}])
    count_id = physical(shop, items=[{"product_id": shop[3], "expected_qty": "10", "counted_qty": "8"},
                                   {"product_id": second, "expected_qty": "3", "counted_qty": "2"}])
    trade(shop, "sale", lines=[{"product_id": second, "qty": "1", "unit_price": 300}])
    before_events = store.db.execute("SELECT COUNT(*) FROM stock_events").fetchone()[0]
    with pytest.raises(ValueError, match="변경"):
        store.apply_count(count_id)
    assert balance(shop) == (10000, 1000)
    assert store.db.execute("SELECT stock_qty FROM products WHERE id=?", (second,)).fetchone()[0] == 2000
    assert store.count(count_id)["status"] == "draft"
    assert store.db.execute("SELECT COUNT(*) FROM stock_events").fetchone()[0] == before_events


def test_count_stale_event_even_net_stock_and_cost_are_unchanged(shop):
    store = shop[0]
    trade(shop)
    count_id = physical(shop)
    sale = trade(shop, "sale", quantity="1", price=200)
    returned(shop, sale, "1")
    assert balance(shop) == (10000, 1000)
    with pytest.raises(ValueError, match="변경"):
        store.apply_count(count_id)


def test_count_application_failure_after_first_move_is_atomic(shop, monkeypatch):
    store = shop[0]
    trade(shop)
    second = store.save_product({"name": "두번째", "base_unit": "개", "purchase_price": 50})
    count_id = physical(shop, items=[{"product_id": shop[3], "expected_qty": "10", "counted_qty": "8"},
                                   {"product_id": second, "expected_qty": "0", "counted_qty": "2"}])
    real_move = store._move
    calls = []

    def fail_after_one(product_id, *args, **kwargs):
        calls.append(product_id)
        if product_id == second:
            raise ValueError("검증용 두번째 이동 실패")
        return real_move(product_id, *args, **kwargs)

    monkeypatch.setattr(store, "_move", fail_after_one)
    before_events = store.db.execute("SELECT COUNT(*) FROM stock_events").fetchone()[0]
    with pytest.raises(ValueError, match="두번째"):
        store.apply_count(count_id)
    assert calls == [shop[3], second]
    assert balance(shop) == (10000, 1000)
    assert store.count(count_id)["status"] == "draft"
    assert store.db.execute("SELECT COUNT(*) FROM stock_events").fetchone()[0] == before_events


@pytest.mark.parametrize("items", [[], [{"product_id": 9999, "expected_qty": "0", "counted_qty": "1"}],
                                     [{"product_id": 1, "expected_qty": "999", "counted_qty": "1"}],
                                     [{"product_id": 1, "expected_qty": "0", "counted_qty": "-1"}]])
def test_count_rejects_invalid_input_without_leaving_partial_draft(shop, items):
    with pytest.raises(ValueError):
        physical(shop, items=items)
    assert shop[0].counts() == []


def test_count_zeroes_stock_and_zero_balance_stock_gain_uses_master_cost(shop):
    store = shop[0]
    trade(shop)
    store.apply_count(physical(shop, counted="0"))
    assert balance(shop) == (0, 0)
    count_id = physical(shop, expected="0", counted="1.333")
    assert store.count(count_id)["items"][0]["counted_cost"] == Decimal("133.30")
    store.apply_count(count_id)
    assert balance(shop) == (1333, Decimal("133.30"))


def test_count_deletion_only_draft_and_backdated_future_count_rejected(shop):
    store = shop[0]
    trade(shop)
    count_id = physical(shop)
    store.delete_count(count_id)
    assert store.counts() == []
    with pytest.raises(ValueError, match="이후"):
        physical(shop, date="2025-01-01")
    with pytest.raises(ValueError, match="미래"):
        physical(shop, date="2999-01-01")


def test_month_snapshot_uses_event_dates_not_latest_live_stock_and_is_immutable(shop):
    store = shop[0]
    trade(shop)
    trade(shop, "sale", quantity="4", price=200, date="2025-02-03")
    assert balance(shop) == (6000, 600)
    close_id = store.inventory_close("2025-01")
    detail = store.inventory_close_detail(close_id)
    assert detail["basis"] == "stock_events_by_date"
    assert (detail["lines"][0]["stock_qty"], detail["stock_cost"]) == ("10.000", 1000)
    store.save_product({"name": "변경된 이름"}, shop[3])
    assert store.inventory_close_detail(close_id)["lines"][0]["product_name"] == "삼겹살"
    assert store.inventory_closes()[0]["month"] == "2025-01"
    for statement in ("UPDATE inventory_closes SET stock_cost=1", "DELETE FROM inventory_closes",
                      "UPDATE inventory_close_lines SET stock_qty=1", "DELETE FROM inventory_close_lines"):
        with pytest.raises(sqlite3.IntegrityError):
            store.db.execute(statement)
    assert store.inventory_close_detail(close_id)["stock_cost"] == 1000


def test_month_lock_prevents_backdated_documents_count_application_and_cancel(shop):
    store = shop[0]
    original = trade(shop)
    count_id = physical(shop)
    store.inventory_close("2025-01")
    for change in (lambda: trade(shop), lambda: store.apply_count(count_id),
                   lambda: store.cancel_document(original, "월마감 이후 취소"), lambda: physical(shop)):
        with pytest.raises(ValueError, match="마감"):
            change()
    assert balance(shop) == (10000, 1000)
    assert store.count(count_id)["status"] == "draft"
    trade(shop, quantity="1", date="2025-02-01")
    assert balance(shop) == (11000, 1100)


def test_month_negative_historical_snapshot_is_rejected_atomically(shop):
    store = shop[0]
    trade(shop, date="2025-02-01")
    trade(shop, "sale", quantity="1", price=200, date="2025-01-10")
    assert balance(shop) == (9000, 900)
    with pytest.raises(ValueError, match="음수"):
        store.inventory_close("2025-01")
    assert store.inventory_closes() == []
    assert store.db.execute("SELECT COUNT(*) FROM inventory_close_lines").fetchone()[0] == 0


@pytest.mark.parametrize("month", ["2025-1", "2025-13", "abcd-ef", "2999-01", None])
def test_month_closing_rejects_invalid_or_future_month(shop, month):
    with pytest.raises(ValueError):
        shop[0].inventory_close(month)


def test_cash_close_uses_actual_payment_operator_not_document_owner_or_purchases(shop):
    store = shop[0]
    trade(shop, paid=1000, method="cash")  # Supplier payout is NOT cashier sales.
    sale = trade(shop, "sale", quantity="2", price=200, paid=100, method="cash")
    store.save_user({"code": "cashier", "name": "계산원", "password": "Cashier-Password!", "permissions": ["trade"]})
    store.login("cashier", "Cashier-Password!")
    store.add_payment(sale, 300, "2025-01-10", "cash")
    expected = store.cash_expected("2025-01-10")
    assert (expected["cash_receipts"], expected["cash_refunds"], expected["cash_net"]) == (300, 0, 300)
    close_id = store.cash_close({"date": "2025-01-10", "opening_cash": 500, "counted_cash": 790, "memo": "10원 부족"})
    close = store.cash_closes()[0]
    assert (close["id"], close["expected_cash"], close["difference"]) == (close_id, 800, -10)
    with pytest.raises(ValueError, match="마감"):
        store.cash_close({"date": "2025-01-10", "opening_cash": 0, "counted_cash": 0})
    store.login("owner", "Owner-Password-2026!")
    assert store.cash_expected("2025-01-10")["cash_net"] == 100
    payment_id = next(row["id"] for row in store.document(sale)["payments"] if row["amount"] == 300)
    with pytest.raises(ValueError, match="현금마감"):
        store.void_payment(payment_id, "점주여도 마감된 계산원 현금 변경 금지")


def test_cash_refunds_count_negative_and_transfer_does_not_change_cash(shop):
    store = shop[0]
    trade(shop)
    sale = trade(shop, "sale", quantity="3", price=200, paid=600, method="cash")
    returned(shop, sale, "1", paid=200, method="cash", date="2025-01-10")
    trade(shop, "sale", quantity="1", price=200, paid=200, method="transfer")
    expected = store.cash_expected("2025-01-10")
    assert (expected["cash_receipts"], expected["cash_refunds"], expected["cash_net"]) == (600, 200, 400)
    store.cash_close({"date": "2025-01-10", "opening_cash": 100, "counted_cash": 500})
    with pytest.raises(ValueError, match="현금마감"):
        trade(shop, "sale", quantity="1", paid=100, method="cash")
    assert store.cash_closes()[0]["difference"] == 0


def test_report_partial_returns_net_profit_units_and_actual_payments(shop):
    store = shop[0]
    trade(shop)
    sale = trade(shop, "sale", quantity="3", price=200, paid=600, method="cash")
    returned(shop, sale, "1", paid=200, method="cash")
    eggs = store.save_product({"name": "달걀", "base_unit": "개", "category": "계란", "tracked": False,
                               "sale_price": 20, "tax_mode": "taxable"})
    trade(shop, "sale", lines=[{"product_id": eggs, "qty": "5", "unit_price": 20}], paid=100, method="transfer")
    draft = store.save_draft({"kind": "sale", "date": "2025-01-10", "partner_id": shop[2],
                              "lines": [{"product_id": eggs, "qty": "1", "unit_price": 999}]})
    cancelled = trade(shop, "sale", quantity="1", price=200)
    store.cancel_document(cancelled, "보고서에서 제외 확인")
    result = store.report("2025-01-01", "2025-01-31", "product")
    assert result["totals"]["sale_total"] == 500
    assert result["totals"]["purchase_total"] == 1000
    assert result["totals"]["cost"] == 200
    assert result["totals"]["profit"] == 300
    assert result["totals"]["cash_net"] == 400
    assert result["totals"]["transfer_net"] == 100
    assert result["totals"]["quantities"] == {"kg": {"purchase_qty": "10.000", "sale_qty": "2.000"},
                                                "개": {"purchase_qty": "0.000", "sale_qty": "5.000"}}
    assert result["totals"]["taxable_sale_total"] == 100
    assert result["totals"]["exempt_sale_total"] == 400
    assert len(result["rows"]) == 2
    assert store.document(draft)["status"] == "draft"
    for group in ("day", "month", "category", "supplier", "member"):
        grouped = store.report("2025-01-01", "2025-01-31", group)
        assert grouped["totals"] == result["totals"]
        assert all("unit" in row for row in grouped["rows"])


def test_report_points_are_not_counted_as_cash_and_tax_snapshot_survives_master_edit(shop):
    store = shop[0]
    trade(shop)
    member = store.save_member({"name": "단골", "code": "M1"})
    store.adjust_points(member, 1000, "이관된 시작 포인트")
    trade(shop, "sale", quantity="10", price=200, paid=1000, method="cash", member_id=member, points_used=1000)
    store.save_product({"tax_mode": "taxable"}, shop[3])
    totals = store.report("2025-01-01", "2025-01-31")["totals"]
    assert (totals["sale_total"], totals["cash_net"], totals["points_used"]) == (2000, 1000, 1000)
    assert totals["exempt_sale_total"] == 2000 and totals["taxable_sale_total"] == 0


def test_commission_report_uses_original_rates_supplier_and_exact_partial_return_fees(shop):
    store, supplier, _, product = shop
    store.save_partner({"supplier_mode": "commission", "commission_bps": 1250}, supplier)
    trade(shop)
    sale = trade(shop, "sale", quantity="3", price=101)
    original = store.document(sale)
    assert original["lines"][0]["commission_amount"] == Decimal("37.88")
    store.save_partner({"commission_bps": 9000}, supplier)
    other = store.save_partner({"kind": "supplier", "name": "다른 공급사"})
    store.save_product({"supplier_id": other}, product)
    returned(shop, sale, "1")
    result = store.commission_report("2025-01-01", "2025-01-31")
    row = result["rows"][0]
    assert row["supplier_id"] == supplier and row["commission_bps"] == 1250
    assert row["sale_total"] == 202 and row["commission_fee"] == Decimal("25.25")
    assert row["items"][0]["sale_qty"] == "2.000"
    assert row["payable"] == Decimal("176.75")
    returned(shop, sale, "1")
    returned(shop, sale, "1")
    assert store.commission_report("2025-01-01", "2025-01-31")["totals"] == {
        "sale_total": 0, "commission_fee": 0, "payable": 0}


def test_operations_permissions_are_enforced_and_rechecked(shop):
    store = shop[0]
    staff_id = store.save_user({"code": "viewer", "name": "조회직원", "password": "Viewer-Password!", "permissions": ["reports"]})
    store.login("viewer", "Viewer-Password!")
    assert store.counts() == []
    assert store.report("2025-01-01", "2025-01-31")["rows"] == []
    with pytest.raises(PermissionError):
        physical(shop)
    with pytest.raises(PermissionError):
        store.cash_close({"date": "2025-01-01", "opening_cash": 0, "counted_cash": 0})
    store.db.execute("UPDATE users SET active=0 WHERE id=?", (staff_id,))
    with pytest.raises(PermissionError):
        store.inventory_closes()
