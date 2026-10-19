"""New independent journal guarantees; no legacy implementation is imported."""

from datetime import date, timedelta

import pytest

from pos2.store import Store


@pytest.fixture
def shop(tmp_path):
    store = Store(tmp_path / "standalone.db")
    store.setup_admin("admin", "관리자", "NewOffline2026!")
    supplier = store.save_partner({"kind": "supplier", "code": "SUP", "name": "축산 공급사",
                                   "opening_date": "2025-01-01"})
    customer = store.save_partner({"kind": "customer", "code": "CUS", "name": "동네 식당",
                                   "opening_date": "2025-01-01"})
    product = store.save_product({"code": "MEAT", "name": "삼겹살", "base_unit": "kg",
                                  "supplier_id": supplier, "purchase_price": 100, "sale_price": 200})
    yield store, supplier, customer, product
    store.close()


def trade(shop, kind="purchase", quantity="10", price=100, paid=0, **extra):
    store, supplier, customer, product = shop
    data = {"kind": kind, "date": "2025-01-10", "partner_id": supplier if kind.startswith("purchase") else customer,
            "lines": [{"product_id": product, "qty": quantity, "unit_price": price}], "paid": paid,
            "method": "transfer"}
    data.update(extra)
    return store.post_document(data)


def returned(shop, source, quantity, paid=0, **extra):
    store = shop[0]
    original = store.document(source)
    line = original["lines"][0]
    data = {"kind": original["kind"] + "_return", "date": "2025-01-11", "partner_id": original["partner_id"],
            "source_id": source, "lines": [{"product_id": line["product_id"], "unit_id": line["unit_id"],
                                            "source_line_id": line["id"], "qty": quantity}],
            "paid": paid, "method": "transfer"}
    data.update(extra)
    return store.post_document(data)


def stock(shop):
    return shop[0].db.execute("SELECT stock_qty,stock_cost FROM products WHERE id=?", (shop[3],)).fetchone()


def test_draft_is_persistent_editable_and_has_no_accounting_effect(shop):
    store, supplier, _, product = shop
    draft = store.save_draft({"kind": "purchase", "date": "2025-01-10", "partner_id": supplier,
                              "lines": [], "paid": 0})
    store.save_draft({"kind": "purchase", "date": "2025-01-10", "partner_id": supplier,
                      "lines": [{"product_id": product, "qty": "2", "unit_price": 100}], "paid": 50}, id=draft)
    assert tuple(stock(shop)) == (0, 0)
    assert store.db.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 0
    other = Store(store.path)
    other.login("admin", "NewOffline2026!")
    assert other.document(draft)["total"] == 200
    other.close()
    store.post_document({"kind": "purchase", "date": "2025-01-10", "partner_id": supplier,
                         "lines": [{"product_id": product, "qty": "2", "unit_price": 100}], "paid": 50}, draft_id=draft)
    assert tuple(stock(shop)) == (2000, 200)
    assert store.document(draft)["cash_paid"] == 50
    with pytest.raises(ValueError):
        store.delete_draft(draft)
    with pytest.raises(ValueError):
        store.save_draft({"kind": "purchase", "date": "2025-01-10", "partner_id": supplier, "lines": []}, id=draft)


def test_delete_only_unposted_draft_and_post_requires_lines(shop):
    store, supplier, _, _ = shop
    data = {"kind": "purchase", "date": "2025-01-10", "partner_id": supplier, "lines": []}
    draft = store.save_draft(data)
    with pytest.raises(ValueError):
        store.post_document(data, draft_id=draft)
    store.delete_draft(draft)
    assert store.documents() == []


def test_price_snapshots_do_not_change_master_prices(shop):
    document = trade(shop, quantity="1.5", price=123)
    assert shop[0].document(document)["total"] == 185
    assert tuple(stock(shop)) == (1500, 185)
    assert shop[0].products()[0]["purchase_price"] == 100


def test_expanded_units_share_stock_and_use_registered_separate_price(shop):
    store, supplier, _, product = shop
    unit = store.save_unit({"product_id": product, "name": "500g", "factor": "0.5",
                            "barcode": "00123456", "purchase_price": 50, "sale_price": 110})
    posted = trade(shop, quantity="2", price=50,
                   lines=[{"product_id": product, "unit_id": unit, "qty": "2", "unit_price": 50}])
    line = store.document(posted)["lines"][0]
    assert (line["input_qty"], line["base_qty"], line["factor"], line["unit_name"]) == ("2.000", "1.000", "0.500", "500g")
    assert tuple(stock(shop)) == (1000, 100)
    assert store.lookup_barcode("00123456")["unit"]["id"] == unit
    with pytest.raises(ValueError, match="환산"):
        trade(shop, lines=[{"product_id": product, "unit_id": unit, "qty": "0.001", "unit_price": 50}])
    assert tuple(stock(shop)) == (1000, 100)


def test_duplicate_sale_rows_cannot_bypass_stock_or_partially_post(shop):
    trade(shop, quantity="1")
    store, _, _, product = shop
    before = store.db.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    with pytest.raises(ValueError, match="재고"):
        trade(shop, "sale", lines=[{"product_id": product, "qty": "0.7", "unit_price": 200},
                                   {"product_id": product, "qty": "0.7", "unit_price": 200}])
    assert tuple(stock(shop)) == (1000, 100)
    assert store.db.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == before


def test_sale_duplicate_lines_allocate_cost_without_rounding_residue(shop):
    trade(shop, quantity="3", price=1)
    trade(shop, quantity="1", price=0)
    store, _, _, product = shop
    sale = trade(shop, "sale", lines=[{"product_id": product, "qty": "1", "unit_price": 1},
                                      {"product_id": product, "qty": "3", "unit_price": 1}])
    assert [line["cost"] for line in store.document(sale)["lines"]] == [1, 2]
    assert tuple(stock(shop)) == (0, 0)


def test_source_returns_use_original_cost_and_sum_to_full_rounding_residue(shop):
    trade(shop, quantity="3", price=1)
    trade(shop, quantity="1", price=0)
    sale = trade(shop, "sale", quantity="3", price=1)
    first = returned(shop, sale, "1")
    second = returned(shop, sale, "1")
    third = returned(shop, sale, "1")
    assert [shop[0].document(item)["lines"][0]["cost"] for item in (first, second, third)] == [1, 0, 1]
    assert tuple(stock(shop)) == (4000, 3)
    assert shop[0].document(sale)["lines"][0]["remaining_qty"] == "0.000"
    with pytest.raises(ValueError):
        returned(shop, sale, "0.001")


def test_source_returns_do_not_accept_arbitrary_product_unit_or_refund_price(shop):
    original = trade(shop, quantity="2", paid=200)
    store, _, _, product = shop
    source = store.document(original)["lines"][0]
    with pytest.raises(ValueError, match="가격"):
        returned(shop, original, "1", lines=[{"product_id": product, "qty": "1", "unit_price": 999,
                                             "source_line_id": source["id"]}])
    with pytest.raises(ValueError, match="초과"):
        returned(shop, original, "1", lines=[{"product_id": product, "qty": "1.1", "source_line_id": source["id"]},
                                             {"product_id": product, "qty": "1.1", "source_line_id": source["id"]}])
    assert tuple(stock(shop)) == (2000, 200)


def test_returns_offset_unpaid_original_and_prevent_cash_refund_of_unpaid_goods(shop):
    original = trade(shop, quantity="10", paid=500)
    with pytest.raises(ValueError, match="정산"):
        returned(shop, original, "3", paid=1)
    credit = returned(shop, original, "3")
    assert shop[0].document(original)["balance"] == 200
    assert shop[0].document(credit)["refundable"] == 0
    with pytest.raises(ValueError):
        shop[0].add_payment(original, 201, "2025-01-11")
    shop[0].add_payment(original, 200, "2025-01-11", "transfer")
    assert shop[0].ledger(shop[1])["closing"] == 0


def test_partial_paid_full_return_refunds_only_original_paid(shop):
    original = trade(shop, paid=500)
    credit = returned(shop, original, "10", paid=500)
    assert tuple(stock(shop)) == (0, 0)
    assert shop[0].document(credit)["cash_paid"] == 500
    assert shop[0].document(credit)["refundable"] == 0
    assert shop[0].ledger(shop[1])["closing"] == 0
    with pytest.raises(ValueError):
        shop[0].add_payment(credit, 1, "2025-01-11", "transfer")


def test_partial_payments_void_preserves_history_and_prevents_unfunded_refund(shop):
    original = trade(shop, quantity="1", paid=100)
    returned(shop, original, "1", paid=100)
    initial = shop[0].document(original)["payments"][0]["id"]
    with pytest.raises(ValueError, match="환불"):
        shop[0].void_payment(initial, "실수")
    assert not shop[0].document(original)["payments"][0]["voided"]


def test_unlinked_payment_void_recomputes_balance_without_deleting_history(shop):
    original = trade(shop, quantity="1", paid=30)
    payment = shop[0].add_payment(original, 70, "2025-01-11", "transfer", "잔금")
    assert shop[0].document(original)["balance"] == 0
    shop[0].void_payment(payment, "중복 입금 확인")
    assert shop[0].document(original)["balance"] == 70
    assert len(shop[0].document(original)["payments"]) == 2
    assert shop[0].document(original)["payments"][1]["voided"] == 1


def test_safe_cancel_reverses_latest_posting_but_preserves_journal(shop):
    purchase = trade(shop, quantity="2")
    sale = trade(shop, "sale", quantity="1", price=200)
    with pytest.raises(ValueError, match="이후 재고"):
        shop[0].cancel_document(purchase, "이전 입고 오류")
    shop[0].cancel_document(sale, "잘못 등록한 외상")
    assert tuple(stock(shop)) == (2000, 200)
    assert shop[0].document(sale)["status"] == "cancelled"
    assert shop[0].document(sale)["cancel_reason"] == "잘못 등록한 외상"
    assert len(shop[0].document(sale)["lines"]) == 1
    with pytest.raises(ValueError):
        shop[0].cancel_document(sale, "다시")


def test_cannot_cancel_paid_or_source_with_posted_returns(shop):
    original = trade(shop, quantity="2", paid=100)
    with pytest.raises(ValueError, match="정산"):
        shop[0].cancel_document(original, "삭제 아님")
    returned(shop, original, "1")
    initial = shop[0].document(original)["payments"][0]["id"]
    shop[0].void_payment(initial, "지급 입력 오류")
    with pytest.raises(ValueError, match="반품"):
        shop[0].cancel_document(original, "원전표 보존")


def test_untracked_products_do_not_enforce_inventory_or_create_moves(shop):
    store, _, _, product = shop
    store.save_product({"tracked": False}, id=product)
    sale = trade(shop, "sale", quantity="1.5", price=200)
    assert tuple(stock(shop)) == (0, 0)
    assert store.document(sale)["lines"][0]["cost"] == 150
    assert store.db.execute("SELECT COUNT(*) FROM stock_events").fetchone()[0] == 0
    returned(shop, sale, "0.5")
    assert tuple(stock(shop)) == (0, 0)


def test_ledger_opening_balance_respects_initial_date_and_period_boundaries(shop):
    store, supplier, _, _ = shop
    store.save_partner({"opening_balance": 400, "opening_date": "2025-01-05"}, id=supplier)
    purchase = trade(shop, quantity="2", paid=50)
    store.add_payment(purchase, 50, "2025-01-12", "transfer")
    assert store.ledger(supplier, end="2025-01-04")["closing"] == 0
    period = store.ledger(supplier, "2025-01-11", "2025-01-12")
    assert (period["opening"], period["charge"], period["payment"], period["closing"]) == (550, 0, 50, 500)
    assert period["entries"][-1]["balance"] == 500


@pytest.mark.parametrize("field,value", [("qty", "0.0001"), ("qty", "-1"), ("qty", "NaN"),
                                          ("unit_price", "-1"), ("unit_price", "Infinity")])
def test_bad_numeric_input_is_rejected_atomically(shop, field, value):
    line = {"product_id": shop[3], "qty": "1", "unit_price": 100, field: value}
    with pytest.raises(ValueError):
        trade(shop, lines=[line])
    assert tuple(stock(shop)) == (0, 0)
    assert shop[0].documents() == []


def test_permissions_are_rechecked_on_every_write_and_picker(shop):
    store, supplier, _, _ = shop
    user = store.save_user({"code": "staff", "name": "판매직원", "password": "NewOffline2026!",
                            "role": "staff", "permissions": ["trade"]})
    store.login("staff", "NewOffline2026!")
    assert store.trade_partners("supplier")[0]["id"] == supplier
    store.db.execute("UPDATE users SET permissions='[]' WHERE id=?", (user,))
    with pytest.raises(PermissionError):
        trade(shop)
    with pytest.raises(PermissionError):
        store.trade_members()
    assert tuple(stock(shop)) == (0, 0)


def test_member_sale_requires_full_settlement_and_return_restores_exact_points(shop):
    store = shop[0]
    trade(shop, quantity="20", price=100)
    member = store.save_member({"code": "M1", "name": "단골손님"})
    store.adjust_points(member, 2000, "이전 적립")
    with pytest.raises(ValueError, match="전액"):
        trade(shop, "sale", quantity="10", price=200, paid=999, member_id=member, points_used=1000)
    sale = trade(shop, "sale", quantity="10", price=200, paid=1000, member_id=member, points_used=1000)
    assert store.document(sale)["points_earned"] == 10
    first = returned(shop, sale, "3", paid=300)
    second = returned(shop, sale, "7", paid=700)
    assert store.document(first)["points_used"] == 300
    assert store.document(second)["points_used"] == 700
    assert store.db.execute("SELECT points FROM members WHERE id=?", (member,)).fetchone()[0] == 2000
    assert store.ledger(shop[2])["closing"] == 0


def test_point_failure_rolls_back_document_stock_and_member_ledger(shop):
    store = shop[0]
    trade(shop, quantity="10")
    member = store.save_member({"code": "M1", "name": "단골손님"})
    before = store.db.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    with pytest.raises(ValueError, match="포인트"):
        trade(shop, "sale", quantity="10", price=200, paid=1000, member_id=member, points_used=1000)
    assert tuple(stock(shop)) == (10000, 1000)
    assert store.db.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == before
    assert store.db.execute("SELECT points FROM members WHERE id=?", (member,)).fetchone()[0] == 0


def test_closed_month_rejects_backdated_trade_and_payment(shop):
    original = trade(shop, quantity="1")
    shop[0].inventory_close("2025-01")
    with pytest.raises(ValueError, match="마감"):
        trade(shop, date="2025-01-30")
    with pytest.raises(ValueError, match="마감"):
        shop[0].add_payment(original, 1, "2025-01-20", "transfer")
    assert tuple(stock(shop)) == (1000, 100)


def test_cash_close_rejects_new_cash_and_void_without_affecting_stock(shop):
    original = trade(shop, quantity="1", paid=100, method="cash")
    shop[0].cash_close({"date": "2025-01-10", "opening_cash": 200, "counted_cash": 100, "memo": "마감"})
    payment = shop[0].document(original)["payments"][0]["id"]
    with pytest.raises(ValueError, match="현금마감"):
        shop[0].void_payment(payment, "마감 후 정정")
    with pytest.raises(ValueError, match="현금마감"):
        trade(shop, quantity="1", paid=100, method="cash")
    assert tuple(stock(shop)) == (1000, 100)


def test_supplier_tax_and_commission_are_immutable_line_snapshots(shop):
    store, supplier, _, product = shop
    store.save_partner({"supplier_mode": "commission", "commission_bps": 6667}, id=supplier)
    trade(shop, quantity="3", price=1)
    trade(shop, quantity="1", price=0)
    sale = trade(shop, "sale", quantity="3", price=1)
    original = store.document(sale)["lines"][0]
    assert (original["supplier_id"], original["commission_bps"], original["commission_amount"], original["tax_mode"]) == (supplier, 6667, 2, "exempt")
    store.save_partner({"commission_bps": 100}, id=supplier)
    store.save_product({"tax_mode": "taxable"}, id=product)
    return_ids = [returned(shop, sale, "1") for _ in range(3)]
    fees = [store.document(item)["lines"][0]["commission_amount"] for item in return_ids]
    assert fees == [1, 0, 1]
    assert all(store.document(item)["lines"][0]["tax_mode"] == "exempt" for item in return_ids)
    assert store.document(sale)["lines"][0]["commission_bps"] == 6667


def test_refund_cannot_be_funded_by_a_payment_after_refund_date(shop):
    original = trade(shop, quantity="1")
    shop[0].add_payment(original, 100, "2025-01-15", "transfer")
    with pytest.raises(ValueError, match="정산 가능"):
        returned(shop, original, "1", paid=100)
    credit = returned(shop, original, "1")
    shop[0].add_payment(credit, 100, "2025-01-15", "transfer")
    assert shop[0].ledger(shop[1])["closing"] == 0


def test_void_cannot_remove_the_payment_that_funded_an_earlier_refund(shop):
    original = trade(shop, quantity="1", paid=50)
    shop[0].add_payment(original, 50, "2025-01-12", "transfer")
    returned(shop, original, "1", paid=50)
    first = shop[0].document(original)["payments"][0]["id"]
    with pytest.raises(ValueError, match="환불 당시"):
        shop[0].void_payment(first, "아직 후일 입금으로 충당할 수 없음")
    assert shop[0].document(original)["cash_paid"] == 100


def test_future_posting_and_payment_are_drafts_not_current_inventory(shop):
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    with pytest.raises(ValueError, match="미래"):
        trade(shop, date=tomorrow)
    posted = trade(shop, quantity="1")
    with pytest.raises(ValueError, match="미래"):
        shop[0].add_payment(posted, 100, tomorrow, "transfer")
    assert tuple(stock(shop)) == (1000, 100)


def test_draft_posting_rechecks_current_catalog_and_competing_status(shop):
    store, supplier, _, product = shop
    data = {"kind": "purchase", "date": "2025-01-10", "partner_id": supplier,
            "lines": [{"product_id": product, "qty": "1", "unit_price": 100}]}
    draft = store.save_draft(data)
    store.save_product({"name": "새 상품명"}, id=product)
    second = Store(store.path)
    second.login("admin", "NewOffline2026!")
    second.post_document(data, draft_id=draft)
    second.close()
    assert store.document(draft)["lines"][0]["product_name"] == "새 상품명"
    with pytest.raises(ValueError, match="확정"):
        store.post_document(data, draft_id=draft)
    assert tuple(stock(shop)) == (1000, 100)


def test_member_draft_can_wait_for_full_payment_without_awarding_points(shop):
    store = shop[0]
    trade(shop)
    member = store.save_member({"code": "M1", "name": "단골"})
    data = {"kind": "sale", "date": "2025-01-10", "partner_id": shop[2], "member_id": member,
            "lines": [{"product_id": shop[3], "qty": "1", "unit_price": 200}], "paid": 0}
    draft = store.save_draft(data)
    assert store.db.execute("SELECT points FROM members WHERE id=?", (member,)).fetchone()[0] == 0
    with pytest.raises(ValueError, match="전액"):
        store.post_document(data, draft_id=draft)
    assert store.document(draft)["status"] == "draft"
    assert tuple(stock(shop)) == (10000, 1000)


def test_points_only_sale_cancellation_restores_points_and_stock_atomically(shop):
    store = shop[0]
    trade(shop)
    member = store.save_member({"code": "M1", "name": "단골"})
    store.adjust_points(member, 2000, "이월")
    posted = trade(shop, "sale", quantity="5", price=200, paid=0, member_id=member, points_used=1000)
    assert store.db.execute("SELECT points FROM members WHERE id=?", (member,)).fetchone()[0] == 1000
    store.cancel_document(posted, "중복 포인트 판매")
    assert store.db.execute("SELECT points FROM members WHERE id=?", (member,)).fetchone()[0] == 2000
    assert tuple(stock(shop)) == (10000, 1000)


def test_unpaid_return_credit_is_not_counted_as_a_cash_refund_debt(shop):
    source = trade(shop, quantity="10", paid=0)
    credit = returned(shop, source, "3")
    original, returned_doc = shop[0].document(source), shop[0].document(credit)
    assert original["balance"] == original["net_balance"] == 700
    assert (returned_doc["balance"], returned_doc["net_balance"], returned_doc["refundable"]) == (0, 0, 0)
    assert returned_doc["credit_applied"] == returned_doc["unrefunded_credit"] == 300
    assert sum(row["net_balance"] for row in shop[0].documents()) == shop[0].ledger(shop[1])["closing"] == 700
    shop[0].add_payment(source, 700, "2025-01-12", "transfer")
    assert shop[0].document(credit)["balance"] == 0
    assert sum(row["net_balance"] for row in shop[0].documents()) == shop[0].ledger(shop[1])["closing"] == 0


def test_multiple_returns_allocate_one_shared_refund_debt_and_recompute_on_payment(shop):
    source = trade(shop, quantity="10", paid=700)
    credits = [returned(shop, source, "2") for _ in range(3)]
    docs = [shop[0].document(identifier) for identifier in credits]
    assert [row["balance"] for row in docs] == [0, 100, 200]
    assert [row["refundable"] for row in docs] == [200, 200, 200]
    assert sum(row["credit_applied"] for row in docs) == 300
    assert sum(row["net_balance"] for row in shop[0].documents()) == shop[0].ledger(shop[1])["closing"] == -300
    payment = shop[0].add_payment(credits[0], 200, "2025-01-12", "transfer")
    assert [shop[0].document(identifier)["balance"] for identifier in credits] == [0, 0, 100]
    assert sum(row["net_balance"] for row in shop[0].documents()) == shop[0].ledger(shop[1])["closing"] == -100
    shop[0].void_payment(payment, "환불 계좌 확인 전 취소")
    assert [shop[0].document(identifier)["balance"] for identifier in credits] == [0, 100, 200]
    assert sum(row["net_balance"] for row in shop[0].documents()) == shop[0].ledger(shop[1])["closing"] == -300


def test_refund_balances_recompute_after_later_source_settlement_is_voided(shop):
    source = trade(shop, quantity="10", paid=0)
    payment = shop[0].add_payment(source, 700, "2025-01-11", "transfer")
    credits = [returned(shop, source, "2") for _ in range(3)]
    assert sum(shop[0].document(identifier)["balance"] for identifier in credits) == 300
    shop[0].void_payment(payment, "입금 확인 오류")
    assert shop[0].document(source)["balance"] == 400
    assert all(shop[0].document(identifier)["balance"] == 0 for identifier in credits)
    assert sum(row["net_balance"] for row in shop[0].documents()) == shop[0].ledger(shop[1])["closing"] == 400
