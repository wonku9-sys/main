"""Real fresh database tests of local prices, members, gifts and point hooks."""

import sqlite3

import pytest

from pos2.store import Store


@pytest.fixture
def store(tmp_path):
    instance = Store(tmp_path / "fresh.db")
    instance.setup_admin("admin", "관리자", "Fresh-Only-2026!")
    yield instance
    instance.close()


@pytest.fixture
def setup(store):
    member = store.save_member({"code": "M1", "name": "오프라인 회원", "phone": "010-1234-5678"})
    product = store.save_product({"code": "P1", "name": "정육", "base_unit": "kg", "tracked": False,
                                  "purchase_price": 100, "sale_price": 200})
    return member, product


def sale(store, member, product, price=1000, quantity="1", used=0, date="2026-10-10"):
    total = round(float(quantity) * price)
    return store.post_document({"kind": "sale", "date": date, "partner_id": 1, "member_id": member,
                                "lines": [{"product_id": product, "qty": quantity, "unit_price": price}],
                                "paid": total - used, "points_used": used})


def return_sale(store, id, product, quantity, date="2026-10-11"):
    original = store.document(id)
    return store.post_document({"kind": "sale_return", "date": date, "partner_id": 1, "source_id": id,
                                "lines": [{"product_id": product, "qty": quantity,
                                           "source_line_id": original["lines"][0]["id"]}], "paid": 0})


def points(store, member):
    return next(row["points"] for row in store.members() if row["id"] == member)


def test_member_crud_points_ignored_and_history_delete_guard(store):
    member = store.save_member({"code": "M1", "name": "회원", "points": 99999, "birthday": "2000-02-29"})
    assert points(store, member) == 0
    store.save_member({"name": "새 이름"}, member)
    assert store.members("새 이름")[0]["code"] == "M1"
    with pytest.raises(ValueError, match="코드"):
        store.save_member({"code": "M1", "name": "중복"})
    with pytest.raises(ValueError, match="날짜"):
        store.save_member({"birthday": "2001-02-29"}, member)
    store.adjust_points(member, 100, "잔액 이전")
    store.adjust_points(member, -100, "잔액 정리")
    with pytest.raises(ValueError, match="사용 중지"):
        store.delete_member(member)
    store.save_member({"active": False}, member)
    assert not store.members()[0]["active"]
    unused = store.save_member({"code": "UNUSED", "name": "미사용"})
    store.delete_member(unused)
    assert len(store.members()) == 1


@pytest.mark.parametrize("delta", ["0", "1.5", "nan", "9000000000001"])
def test_bad_point_adjustment_never_changes_books(store, setup, delta):
    member, _ = setup
    with pytest.raises(ValueError):
        store.adjust_points(member, delta, "검증")
    assert points(store, member) == 0
    assert store.point_history(member) == []


def test_adjustments_immutable_audited_and_reopen(store, setup):
    member, _ = setup
    store.adjust_points(member, 1234, "이전 포인트")
    with pytest.raises(ValueError, match="부족"):
        store.adjust_points(member, -1235, "차감 초과")
    history = store.point_history(member)
    assert len(history) == 1 and history[0]["balance"] == 1234
    assert history[0]["user_name"] == "관리자"
    with pytest.raises(sqlite3.IntegrityError, match="수정"):
        store.db.execute("UPDATE point_entries SET delta=0")
    with pytest.raises(sqlite3.IntegrityError, match="삭제"):
        store.db.execute("DELETE FROM point_entries")
    with StoreForRead(store.path) as reopened:
        assert points(reopened, member) == 1234
        assert reopened.point_history(member)[0]["reason"] == "이전 포인트"


class StoreForRead:
    def __init__(self, path):
        self.store = Store(path)
    def __enter__(self):
        self.store.login("admin", "Fresh-Only-2026!")
        return self.store
    def __exit__(self, *_):
        self.store.close()


def test_date_prices_precedence_preserves_master_and_unit_independence(store, setup):
    member, product = setup
    store.save_price_schedule({"product_id": product, "date": "2026-10-01", "purchase_price": 80})
    store.save_price_schedule({"product_id": product, "date": "2026-10-05", "sale_price": 180})
    promo = store.save_promotion({"title": "한돈 행사", "start": "2026-10-10", "end": "2026-10-20",
                                  "items": [{"product_id": product, "sale_price": 150, "purchase_price": 70}]})
    assert store.quote(product, "2026-09-30")["price"] == 200
    assert store.quote(product, "2026-10-04")["purchase_price"] == 80
    scheduled = store.quote(product, "2026-10-06")
    assert (scheduled["price"], scheduled["purchase_price"]) == (180, 80)
    assert "예약" in scheduled["source"]
    assert store.quote(product, "2026-10-10")["price"] == 150
    assert store.quote(product, "2026-10-20")["price"] == 150
    assert store.quote(product, "2026-10-21")["price"] == 180
    fixed = store.save_member_price({"member_id": member, "product_id": product, "price": 160})
    assert store.quote(product, "2026-10-15", member_id=member)["price"] == 160
    assert store.quote(product, "2026-10-15", member_id=member)["purchase_price"] == 70
    unit = store.save_unit({"product_id": product, "name": "박스", "factor": "3", "purchase_price": 250, "sale_price": 510})
    quote = store.quote(product, "2026-10-15", unit_id=unit, member_id=member)
    assert (quote["price"], quote["purchase_price"]) == (510, 250)
    assert "확장" in quote["source"]
    store.delete_member_price(fixed)
    store.delete_promotion(promo)
    assert store.quote(product, "2026-10-15", member_id=member)["price"] == 180
    assert store.products()[0]["sale_price"] == 200
    assert store.products()[0]["purchase_price"] == 100


def test_schedule_uniqueness_nulls_deactivation_and_invalid_dates(store, setup):
    _, product = setup
    data = {"product_id": product, "date": "2026-10-01", "sale_price": 99}
    id = store.save_price_schedule(data)
    with pytest.raises(ValueError, match="이미"):
        store.save_price_schedule(data)
    with pytest.raises(ValueError):
        store.save_price_schedule(dict(data, date="2026-02-30"))
    with pytest.raises(ValueError, match="입력"):
        store.save_price_schedule(dict(data, sale_price=None))
    store.delete_price_schedule(id)
    assert store.quote(product, "2026-10-02")["price"] == 200
    second = store.save_price_schedule(data)
    assert second != id
    assert len(store.price_schedules()) == 2


def test_promotion_copy_extend_overlap_and_atomic_items(store, setup):
    _, product = setup
    data = {"title": "행사", "start": "2026-10-01", "end": "2026-10-10",
            "items": [{"product_id": product, "sale_price": 120}]}
    first = store.save_promotion(data)
    with pytest.raises(ValueError, match="겹칩니다"):
        store.clone_promotion(first, "2026-10-10", "2026-10-15")
    with pytest.raises(ValueError, match="두 번"):
        store.save_promotion(dict(data, items=data["items"] * 2), first)
    assert store.promotion(first)["items"][0]["sale_price"] == 120
    second = store.clone_promotion(first, "2026-10-15", "2026-10-20")
    with pytest.raises(ValueError, match="겹칩니다"):
        store.extend_promotion(first, "2026-10-15")
    assert store.promotion(first)["end"] == "2026-10-10"
    store.extend_promotion(first, "2026-10-14")
    assert store.quote(product, "2026-10-14")["price"] == 120
    assert len(store.promotions()) == 2
    store.delete_promotion(second)
    assert not store.promotion(second)["active"]
    assert store.promotion(second)["items"]


def test_sale_points_cash_only_earn_and_duplicate_hooks_rejected(store, setup):
    member, product = setup
    store.adjust_points(member, 2000, "이전 잔액")
    id = sale(store, member, product, price=10000, used=1000)
    record = store.document(id)
    assert record["points_earned"] == 90
    assert points(store, member) == 1090
    assert {r["kind"] for r in store.point_history(member)} == {"adjust", "sale_use", "sale_earn"}
    with pytest.raises(ValueError, match="완료"):
        with store._tx():
            store._sale_points(id, member, 10000, 1000)
    assert points(store, member) == 1090


@pytest.mark.parametrize("used,enabled", [(999, True), (1050, True), (1000, False), (3000, True)])
def test_usage_policy_failure_rolls_back_entire_sale(store, setup, used, enabled):
    member, product = setup
    store.adjust_points(member, 2000, "이전 잔액")
    store.save_settings({"point_enabled": enabled})
    before = store.db.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
    with pytest.raises(ValueError):
        sale(store, member, product, price=5000, used=used)
    assert points(store, member) == 2000
    assert store.documents() == []
    assert store.db.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 0
    assert store.db.execute("SELECT COUNT(*) FROM audit").fetchone()[0] == before


def test_partial_return_points_cumulative_rounding_and_inactive_member(store, setup):
    member, product = setup
    store.save_settings({"earn_bps": 10000, "point_min": 0, "point_step": 1})
    store.adjust_points(member, 1000, "이전 잔액")
    id = sale(store, member, product, price=101, used=5)
    assert store.document(id)["points_earned"] == 96
    first = return_sale(store, id, product, "0.333", "2026-10-13")
    # Backdated second return still uses registration-order cumulative allocation.
    second = return_sale(store, id, product, "0.333", "2026-10-11")
    store.save_member({"active": False}, member)
    third = return_sale(store, id, product, "0.334", "2026-10-12")
    returns = [store.document(item) for item in (first, second, third)]
    assert sum(row["total"] for row in returns) == 101
    assert sum(row["points_used"] for row in returns) == 5
    assert sum(row["points_earned"] for row in returns) == 96
    assert points(store, member) == 1000
    assert len(store.member_history(member)) == 4
    assert store.best_members("2026-10-01", "2026-10-31")[0]["total"] == 0
    with pytest.raises(ValueError):
        return_sale(store, id, product, "0.001")


def test_spent_earned_points_block_return_without_partial_writes(store, setup):
    member, product = setup
    id = sale(store, member, product, price=10000)
    store.adjust_points(member, -100, "적립분 사용")
    with pytest.raises(ValueError, match="복원"):
        return_sale(store, id, product, "1")
    assert len(store.documents()) == 1
    assert points(store, member) == 0
    assert store.db.execute("SELECT COUNT(*) FROM loyalty_return_actions").fetchone()[0] == 0
    store.adjust_points(member, 100, "반품을 위한 포인트 복원")
    returned = return_sale(store, id, product, "1")
    assert store.document(returned)["points_earned"] == 100
    assert points(store, member) == 0


def test_fully_points_paid_sale_cancel_restores_exact_points(store, setup):
    member, product = setup
    store.adjust_points(member, 2000, "이전 잔액")
    id = sale(store, member, product, price=1000, used=1000)
    assert points(store, member) == 1000
    store.cancel_document(id, "잘못 입력")
    assert points(store, member) == 2000
    assert store.document(id)["status"] == "cancelled"
    assert store.point_history(member)[0]["kind"] == "cancel_restore"


def test_gift_redemption_atomic_returns_historical_price_and_immutable_log(store, setup):
    member, _ = setup
    store.adjust_points(member, 5000, "이전 잔액")
    gift = store.save_gift({"code": "G1", "name": "보냉백", "points": 1000, "stock": 5})
    redemption = store.redeem_gift(member, gift, 3, "고객 요청")
    assert points(store, member) == 2000
    assert store.gifts()[0]["stock"] == 2
    store.save_gift({"points": 1500}, gift)
    store.return_gift(redemption, 1, "지급 오류")
    assert points(store, member) == 3000
    assert store.gifts()[0]["stock"] == 3
    store.return_gift(redemption, 2, "전체 반환")
    assert points(store, member) == 5000
    assert store.gifts()[0]["stock"] == 5
    with pytest.raises(ValueError, match="초과"):
        store.return_gift(redemption, 1, "중복 반품")
    assert len(store.gift_history(member)) == 3
    with pytest.raises(sqlite3.IntegrityError):
        store.db.execute("DELETE FROM gift_redemptions WHERE id=?", (redemption,))
    assert len(store.gift_history(member)) == 3


@pytest.mark.parametrize("quantity", ["0", "0.5", "6", "nan"])
def test_invalid_gift_requests_change_nothing(store, setup, quantity):
    member, _ = setup
    store.adjust_points(member, 1000, "이전")
    gift = store.save_gift({"code": "G1", "name": "기념품", "points": 400, "stock": 5})
    with pytest.raises(ValueError):
        store.redeem_gift(member, gift, quantity, "검증")
    assert points(store, member) == 1000
    assert store.gifts()[0]["stock"] == 5
    assert store.gift_history() == []


def test_permission_recheck_minimal_trade_members_and_no_global_settings_leak(store, setup):
    member, product = setup
    id = store.save_user({"code": "staff", "name": "판매 담당", "password": "Fresh-Staff-2026!",
                          "role": "staff", "permissions": ["trade"]})
    store.login("staff", "Fresh-Staff-2026!")
    minimal = store.trade_members()[0]
    assert set(minimal) == {"id", "code", "name", "points", "active"}
    assert store.quote(product, "2026-10-10")["price"] == 200
    sale(store, member, product)
    for operation in (lambda: store.members(), lambda: store.adjust_points(member, 5, "임의"),
                      lambda: store.settings(), lambda: store.save_member({"name": "변경"}, member)):
        with pytest.raises(PermissionError):
            operation()
    store.db.execute("UPDATE users SET permissions='[]' WHERE id=?", (id,))
    with pytest.raises(PermissionError):
        store.quote(product, "2026-10-10")
