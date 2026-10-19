"""Offline ledger/report/stocktake correctness, upgrades and concurrent safety."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier

import pytest

from seoyoung_pos.service import POSService


@pytest.fixture
def store(tmp_path):
    service = POSService(tmp_path / "offline.db")
    service.create_initial_admin("admin", "관리자", "offline-test-password")
    service.login("admin", "offline-test-password")
    supplier = service.save_partner({"kind": "supplier", "code": "S1", "name": "정육 공급사"})
    other = service.save_partner({"kind": "supplier", "code": "S2", "name": "포장 공급사"})
    customer = service.save_partner({"kind": "customer", "code": "C1", "name": "식당 고객"})
    meat = service.save_product({"code": "P1", "name": "삼겹살", "unit": "kg", "category": "정육",
                                 "purchase_price": 1000, "supplier_id": supplier})
    packs = service.save_product({"code": "P2", "name": "포장 용기", "unit": "개", "category": "부자재",
                                  "purchase_price": 200, "supplier_id": supplier})
    yield service, supplier, other, customer, meat, packs
    service.close()


def post(service, kind, partner, product, qty, price, day="2026-10-17", paid=0):
    return service.create_document(kind, partner, day,
                                   [{"product_id": product, "qty": qty, "unit_price": price}], paid=paid)


def stock(service):
    return {row["id"]: (row["stock_qty"], row["stock_cost"]) for row in service.list_stock()}


def test_ledger_initial_payment_once_and_true_period_opening(store):
    service, supplier, _, _, meat, _ = store
    original = post(service, "purchase", supplier, meat, "1", 1000, paid=200)
    service.add_payment(original, 300, "2026-10-18", "추가 송금")
    post(service, "purchase", supplier, meat, ".5", 1000, day="2026-10-20")
    service.add_payment(original, 100, "2026-10-22", "조회 기간 후 지급")
    ledger = service.partner_ledger("supplier", supplier, "2026-10-18", "2026-10-20")
    assert ledger["opening_balance"] == 800
    assert ledger["total_charge"] == 500
    assert ledger["total_payment"] == 300
    assert ledger["closing_balance"] == 1000
    assert [(row["event_type"], row["balance"]) for row in ledger["entries"]] == [
        ("payment", 500), ("document", 1000)]
    all_time = service.partner_ledger("purchase", supplier)
    assert all_time["total_charge"] == 1500
    assert all_time["total_payment"] == 600
    assert all_time["closing_balance"] == service.list_partners("supplier")[0]["balance"] == 900
    assert all_time["entries"][0]["event_type"] == "document"
    assert all_time["entries"][1]["payment"] == 200


def test_ledger_empty_window_still_has_opening_and_excludes_cancelled(store):
    service, supplier, _, _, meat, _ = store
    cancelled = post(service, "purchase", supplier, meat, "1", 900)
    service.cancel_document(cancelled, "중복 등록")
    post(service, "purchase", supplier, meat, "1", 1000, paid=250)
    ledger = service.partner_ledger("supplier", supplier, "2026-11-01", "2026-11-30")
    assert ledger["entries"] == []
    assert ledger["opening_balance"] == ledger["closing_balance"] == 750
    assert ledger["total_charge"] == ledger["total_payment"] == 0
    assert service.partner_ledger("supplier", supplier)["total_charge"] == 1000


def test_ledger_sales_and_wrong_kind_are_separate(store):
    service, supplier, _, customer, meat, _ = store
    post(service, "purchase", supplier, meat, "1", 1000)
    sale = post(service, "sale", customer, meat, ".5", 3000, paid=200)
    service.add_payment(sale, 100, "2026-10-18")
    ledger = service.partner_ledger("customer", customer)
    assert (ledger["total_charge"], ledger["total_payment"], ledger["closing_balance"]) == (1500, 300, 1200)
    with pytest.raises(ValueError, match="거래처"):
        service.partner_ledger("supplier", customer)
    with pytest.raises(ValueError):
        service.partner_ledger("other", supplier)


@pytest.mark.parametrize("group_by", ["daily", "monthly", "product", "category", "supplier"])
def test_grouped_report_reconciles_sales_cogs_profit_and_keeps_units_separate(store, group_by):
    service, supplier, other, customer, meat, packs = store
    cancelled = post(service, "purchase", supplier, meat, "1", 900)
    service.cancel_document(cancelled, "중복")
    post(service, "purchase", supplier, meat, "2", 1000)
    post(service, "purchase", other, packs, "4", 200)
    post(service, "sale", customer, meat, ".5", 3000, paid=200)
    post(service, "sale", customer, packs, "2", 500)
    result = service.grouped_report("2026-10-01", "2026-10-31", group_by)
    summary = result["summary"]
    assert (summary["purchase_total"], summary["sale_total"], summary["cost_total"], summary["gross_profit"]) == (2800, 2500, 900, 1600)
    assert summary["quantities_by_unit"] == {
        "kg": {"purchase_qty": "2.000", "sale_qty": "0.500"},
        "개": {"purchase_qty": "4.000", "sale_qty": "2.000"},
    }
    assert sum(row["gross_profit"] for row in result["rows"]) == service.dashboard()["profit"]
    assert {row["unit"] for row in result["rows"]} == {"kg", "개"}
    if group_by == "supplier":
        actual_supplier = next(row for row in result["rows"] if row["group_key"] == str(other))
        assert actual_supplier["purchase_total"] == 800
        assert actual_supplier["sale_total"] == 0  # Sales use the current product supplier, not a fictitious lot.


def test_grouped_monthly_uses_business_date_not_posting_or_payment_date(store):
    service, supplier, _, customer, meat, _ = store
    purchase = post(service, "purchase", supplier, meat, "2", 1000, day="2026-09-30")
    post(service, "sale", customer, meat, "1", 3000, day="2026-10-01")
    service.add_payment(purchase, 500, "2026-10-02")
    rows = service.grouped_report("2026-09-01", "2026-10-31", "monthly")["rows"]
    assert [(row["label"], row["purchase_total"], row["sale_total"]) for row in rows] == [
        ("2026-09", 2000, 0), ("2026-10", 0, 3000)]


def test_date_validation_and_empty_reports(store):
    service, supplier, *_ = store
    for start, end in (("2026-10-20", "2026-10-01"), ("2026-02-30", "2026-10-01")):
        with pytest.raises(ValueError):
            service.grouped_report(start, end)
        with pytest.raises(ValueError):
            service.partner_ledger("supplier", supplier, start, end)
        with pytest.raises(ValueError):
            service.list_stocktakes(start, end)
    with pytest.raises(ValueError):
        service.grouped_report("2026-10-01", "2026-10-31", "unsafe_sql")
    result = service.grouped_report("2026-10-01", "2026-10-31")
    assert result["rows"] == []
    assert result["summary"]["gross_profit"] == 0


def test_stocktake_absolute_counts_increase_decrease_zero_and_persist(store):
    service, supplier, _, _, meat, packs = store
    post(service, "purchase", supplier, meat, "10", 100)
    batch = service.save_stocktake([
        {"product_id": meat, "expected_qty": "10", "counted_qty": "8"},
        {"product_id": packs, "expected_qty": "0", "counted_qty": "2"},
    ], "정기 실사")
    assert stock(service) == {meat: ("8.000", 800), packs: ("2.000", 400)}
    detail = service.get_stocktake(batch)
    assert (detail["items_count"], detail["changed_count"], detail["value_change"]) == (2, 2, 200)
    assert [(row["expected_qty"], row["counted_qty"], row["delta"]) for row in detail["items"]] == [
        ("10.000", "8.000", "-2.000"), ("0.000", "2.000", "2.000")]
    assert service.list_stocktakes()[0]["number"].startswith("ST-")
    assert all(row["kind"] == "stocktake" for row in service.list_stock_movements()[:2])
    zero = service.save_stocktake([{"product_id": meat, "expected_qty": "8", "counted_qty": "0"}], "폐기 후 확인")
    assert stock(service)[meat] == ("0.000", 0)
    assert service.get_stocktake(zero)["value_change"] == -800
    reopened = POSService(service.path)
    try:
        reopened.login("admin", "offline-test-password")
        assert reopened.get_stocktake(batch) == detail
        assert stock(reopened)[packs] == ("2.000", 400)
    finally:
        reopened.close()


def test_stocktake_unchanged_product_retains_trace_and_protects_deletion(store):
    service, _, _, _, meat, _ = store
    batch = service.save_stocktake([{"product_id": meat, "expected_qty": "0", "counted_qty": "0"}], "장부 일치")
    assert service.get_stocktake(batch)["changed_count"] == 0
    assert service.list_stock_movements(meat) == []
    with pytest.raises(ValueError, match="이력"):
        service.delete_product(meat)


@pytest.mark.parametrize("counted", ["-1", "0.0001", "NaN", "Infinity", None])
def test_stocktake_rejects_bad_counts_without_partial_effects(store, counted):
    service, _, _, _, meat, packs = store
    before = stock(service)
    with pytest.raises(ValueError):
        service.save_stocktake([
            {"product_id": meat, "expected_qty": "0", "counted_qty": "1"},
            {"product_id": packs, "expected_qty": "0", "counted_qty": counted},
        ], "검증")
    assert stock(service) == before
    assert service.list_stocktakes() == []


def test_stocktake_stale_expected_qty_and_duplicate_product_reject_whole_batch(store):
    service, _, _, _, meat, packs = store
    before = stock(service)
    with pytest.raises(ValueError, match="변경"):
        service.save_stocktake([
            {"product_id": meat, "expected_qty": "0", "counted_qty": "1"},
            {"product_id": packs, "expected_qty": "1", "counted_qty": "2"},
        ], "오래된 화면")
    assert stock(service) == before
    assert service.list_stocktakes() == []
    with pytest.raises(ValueError, match="한 번"):
        service.save_stocktake([
            {"product_id": meat, "expected_qty": "0", "counted_qty": "1"},
            {"product_id": str(meat), "expected_qty": "0", "counted_qty": "2"},
        ], "중복")


def test_stocktake_database_failure_rolls_back_header_stock_movements_and_audit(store):
    service, _, _, _, meat, packs = store
    before, audit_count = stock(service), len(service.audit_log())
    service.db.execute(f"""CREATE TRIGGER reject_second_count BEFORE INSERT ON stocktake_items
        WHEN NEW.product_id={packs} BEGIN SELECT RAISE(ABORT,'test failure'); END""")
    with pytest.raises(ValueError):
        service.save_stocktake([
            {"product_id": meat, "expected_qty": "0", "counted_qty": "1"},
            {"product_id": packs, "expected_qty": "0", "counted_qty": "1"},
        ], "원자성")
    assert stock(service) == before
    assert service.list_stocktakes() == []
    assert service.list_stock_movements() == []
    assert len(service.audit_log()) == audit_count


def test_negative_stocktake_blocks_historical_purchase_cancellation(store):
    service, supplier, _, _, meat, _ = store
    original = post(service, "purchase", supplier, meat, "10", 100)
    post(service, "purchase", supplier, meat, "10", 200)
    service.save_stocktake([{"product_id": meat, "expected_qty": "20", "counted_qty": "19"}], "감모")
    with pytest.raises(ValueError, match="재고 차감"):
        service.cancel_document(original, "과거 매입 삭제")
    assert stock(service)[meat] == ("19.000", 2850)


def test_concurrent_stocktakes_cannot_overwrite_an_already_changed_count(store):
    service, _, _, _, meat, _ = store
    barrier = Barrier(2)

    def apply(counted):
        other = POSService(service.path)
        try:
            other.login("admin", "offline-test-password")
            barrier.wait(timeout=10)
            try:
                return other.save_stocktake([{"product_id": meat, "expected_qty": "0", "counted_qty": counted}], "동시 실사")
            except ValueError as exc:
                return str(exc)
        finally:
            other.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(apply, ("1", "2")))
    assert len([value for value in outcomes if isinstance(value, int)]) == 1
    assert len(service.list_stocktakes()) == 1
    assert stock(service)[meat][0] in {"1.000", "2.000"}


def test_workflow_permissions_are_distinct_and_rechecked(store):
    service, supplier, _, customer, meat, _ = store
    staff_id = service.save_user({"username": "clerk", "name": "직원", "password": "offline-staff-password",
                                  "role": "staff", "permissions": ["purchases"]})
    service.login("clerk", "offline-staff-password")
    assert service.partner_ledger("supplier", supplier)["entries"] == []
    with pytest.raises(PermissionError):
        service.partner_ledger("customer", customer)
    with pytest.raises(PermissionError):
        service.grouped_report("2026-10-01", "2026-10-31")
    with pytest.raises(PermissionError):
        service.save_stocktake([{"product_id": meat, "expected_qty": "0", "counted_qty": "1"}], "권한 없음")
    service.db.execute("UPDATE users SET permissions='[\"reports\"]' WHERE id=?", (staff_id,))
    assert service.grouped_report("2026-10-01", "2026-10-31")["rows"] == []
    assert service.list_stocktakes() == []
    with pytest.raises(PermissionError):
        service.save_stocktake([{"product_id": meat, "expected_qty": "0", "counted_qty": "1"}], "읽기 전용")
    service.db.execute("UPDATE users SET permissions='[\"partners\"]' WHERE id=?", (staff_id,))
    with pytest.raises(PermissionError):
        service.partner_ledger("supplier", supplier)


def test_stocktake_extension_keeps_business_rows_and_future_version_on_reopen(store):
    service, supplier, _, _, meat, _ = store
    document_id = post(service, "purchase", supplier, meat, "1.125", 1004, paid=200)
    before = {table: [tuple(row) for row in service.db.execute(f"SELECT * FROM {table} ORDER BY id")]
              for table in ("products", "documents", "document_items", "payments", "stock_movements")}
    service.db.execute("PRAGMA user_version=41")
    reopened = POSService(service.path)
    try:
        assert reopened.db.execute("PRAGMA user_version").fetchone()[0] == 41
        for table, original in before.items():
            assert [tuple(row) for row in reopened.db.execute(f"SELECT * FROM {table} ORDER BY id")] == original
        reopened.login("admin", "offline-test-password")
        assert reopened.get_document(document_id)["total"] == 1130
        assert reopened.partner_ledger("supplier", supplier)["closing_balance"] == 930
        assert reopened.list_stocktakes(date.today().isoformat(), date.today().isoformat()) == []
        assert reopened.db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        reopened.close()
