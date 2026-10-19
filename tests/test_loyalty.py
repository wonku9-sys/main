"""Offline membership ledgers, permissions and date-limited exact prices."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import sqlite3

import pytest

from seoyoung_pos.service import MAX_INTEGER, POSService


@pytest.fixture
def service(tmp_path):
    result = POSService(tmp_path / "loyalty.sqlite3")
    result.create_initial_admin("admin", "관리자", "local-test-password")
    result.login("admin", "local-test-password")
    yield result
    result.close()


def member(service, **changes):
    return service.save_member({"code": "M001", "name": "서영 고객", "phone": "010-1234-5678", **changes})


def product(service, **changes):
    return service.save_product({"code": "P001", "name": "국내산 삼겹살", "unit": "kg",
                                 "purchase_price": 18000, "sale_price": 28000, **changes})


def promotion(service, base_product_id, **changes):
    return service.save_promotion({"product_id": base_product_id, "title": "주말 특매",
                                   "date_from": "2026-10-01", "date_to": "2026-10-03",
                                   "sale_price": 25001, **changes})


def staff(service, permissions):
    service.save_user({"username": "staff", "name": "직원", "password": "local-staff-password",
                       "role": "staff", "permissions": permissions})
    service.login("staff", "local-staff-password")


def test_member_crud_search_partial_update_and_duplicate_rollback(service):
    identifier = member(service)
    assert service.list_members("010-1234")[0]["points"] == 0
    service.save_member({"name": "이름 변경", "memo": "예약 고객"}, identifier)
    row = service.list_members("M001")[0]
    assert row["name"] == "이름 변경"
    assert row["phone"] == "010-1234-5678"
    assert row["active"] is True
    assert row["created_at"] and row["updated_at"]
    with pytest.raises(ValueError):
        member(service, code="m001", name="다른 회원")
    assert len(service.list_members()) == 1
    service.save_member({"active": False}, identifier)
    assert service.list_members(active_only=True) == []
    assert service.list_members()[0]["active"] is False
    service.delete_member(identifier)
    assert service.list_members() == []


@pytest.mark.parametrize("data", [{"code": "", "name": "고객"}, {"code": "M1", "name": " "},
                                  {"code": "M1", "name": "고객", "active": "false"}])
def test_member_validation(service, data):
    with pytest.raises(ValueError):
        service.save_member(data)
    assert service.list_members() == []


def test_points_integer_ledger_balances_and_history_are_immutable(service):
    identifier = member(service)
    first = service.adjust_member_points(identifier, 1000, "개점 적립", "2026-10-19")
    second = service.adjust_member_points(identifier, -250, "수동 사용", "2026-10-20")
    assert service.member_points(identifier) == 750
    assert service.list_members()[0]["points"] == 750
    history = service.member_point_history(identifier)
    assert [row["id"] for row in history] == [second, first]
    assert [row["balance"] for row in history] == [750, 1000]
    assert history[0]["username"] == "admin"
    assert history[0]["reason"] == "수동 사용"
    with pytest.raises(sqlite3.IntegrityError):
        service.db.execute("UPDATE point_movements SET points=42 WHERE id=?", (first,))
    with pytest.raises(sqlite3.IntegrityError):
        service.db.execute("DELETE FROM point_movements WHERE id=?", (first,))
    assert service.member_points(identifier) == 750
    assert service.db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


@pytest.mark.parametrize("points", [0, "0", "1.5", "-0.5", "NaN", "Infinity", "1e999999999", MAX_INTEGER + 1])
def test_invalid_points_do_not_create_history(service, points):
    identifier = member(service)
    with pytest.raises(ValueError):
        service.adjust_member_points(identifier, points, "잘못된 입력")
    assert service.member_points(identifier) == 0
    assert service.member_point_history(identifier) == []


def test_points_cannot_overspend_overflow_or_delete_history(service):
    identifier = member(service)
    service.adjust_member_points(identifier, MAX_INTEGER, "초기 등록")
    with pytest.raises(ValueError):
        service.adjust_member_points(identifier, 1, "초과")
    service.adjust_member_points(identifier, -MAX_INTEGER, "전액 사용")
    assert service.member_points(identifier) == 0
    with pytest.raises(ValueError):
        service.adjust_member_points(identifier, -1, "잔액 부족")
    with pytest.raises(ValueError):
        service.delete_member(identifier)
    assert len(service.member_point_history(identifier)) == 2


def test_points_require_reason_valid_date_and_active_member(service):
    identifier = member(service)
    for reason, date in (("", "2026-10-19"), (" ", "2026-10-19"), ("적립", "2026-02-30"), ("적립", "20261019")):
        with pytest.raises(ValueError):
            service.adjust_member_points(identifier, 100, reason, date)
    service.save_member({"active": False}, identifier)
    with pytest.raises(ValueError):
        service.adjust_member_points(identifier, 100, "중지 계정")
    assert service.member_points(identifier) == 0


def test_point_write_rolls_back_if_audit_fails(service, monkeypatch):
    identifier = member(service)

    def fail(*args):
        raise RuntimeError("simulated audit failure")

    monkeypatch.setattr(service, "_audit", fail)
    with pytest.raises(RuntimeError):
        service.adjust_member_points(identifier, 10, "장애 확인")
    assert service.member_points(identifier) == 0
    assert service.member_point_history(identifier) == []


def test_concurrent_points_cannot_spend_same_balance_twice(service):
    identifier = member(service)
    service.adjust_member_points(identifier, 200, "초기 잔액")
    barrier = Barrier(2)
    database_path = service.path

    def spend():
        connection = POSService(database_path)
        try:
            connection.login("admin", "local-test-password")
            barrier.wait(timeout=10)
            try:
                connection.adjust_member_points(identifier, -150, "동시 차감")
                return True
            except ValueError:
                return False
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: spend(), range(2)))
    assert sorted(results) == [False, True]
    assert service.member_points(identifier) == 50
    assert len(service.member_point_history(identifier)) == 2


def test_member_and_promotion_data_survive_reopen_and_backup(service, tmp_path):
    identifier = member(service)
    product_id = product(service)
    promotion(service, product_id)
    service.adjust_member_points(identifier, 321, "장부 보존")
    backup = tmp_path / "backup.sqlite3"
    service.backup(backup)
    for path in (service.path, backup):
        reopened = POSService(path)
        try:
            reopened.login("admin", "local-test-password")
            assert reopened.member_points(identifier) == 321
            assert reopened.get_effective_price(product_id, "2026-10-02") == 25001
            assert len(reopened.member_point_history(identifier)) == 1
        finally:
            reopened.close()


def test_promotions_use_inclusive_dates_exact_prices_and_base_fallback(service):
    product_id = product(service)
    identifier = promotion(service, product_id, purchase_price=17001)
    assert service.get_effective_price(product_id, "2026-09-30") == 28000
    for day in ("2026-10-01", "2026-10-02", "2026-10-03"):
        assert service.get_effective_price(product_id, day) == 25001
        assert service.get_effective_price(product_id, day, "purchase") == 17001
    assert service.get_effective_price(product_id, "2026-10-04") == 28000
    row = service.list_promotions("삼겹살", on_date="2026-10-02")[0]
    assert row["id"] == identifier
    assert row["product_code"] == "P001" and row["unit"] == "kg"
    service.save_promotion({"sale_price": 0, "purchase_price": None}, identifier)
    assert service.get_effective_price(product_id, "2026-10-02") == 0
    assert service.get_effective_price(product_id, "2026-10-02", "purchase") == 18000


def test_promotion_partial_update_disable_delete_and_search(service):
    product_id = product(service)
    identifier = promotion(service, product_id)
    service.save_promotion({"title": "한돈 할인"}, identifier)
    assert service.list_promotions("한돈")[0]["sale_price"] == 25001
    service.save_promotion({"active": False}, identifier)
    assert service.list_promotions(active_only=True) == []
    assert service.get_effective_price(product_id, "2026-10-02") == 28000
    assert service.list_promotions(product_id=product_id)[0]["active"] is False
    assert service.list_promotions(on_date="2026-10-04") == []
    service.delete_promotion(identifier)
    assert service.list_promotions() == []


@pytest.mark.parametrize("start,end", [("2026-09-30", "2026-10-01"), ("2026-10-03", "2026-10-04"),
                                      ("2026-10-02", "2026-10-02"), ("2026-09-30", "2026-10-04")])
def test_promotion_overlap_rejected_including_shared_boundary(service, start, end):
    product_id = product(service)
    promotion(service, product_id)
    with pytest.raises(ValueError):
        promotion(service, product_id, date_from=start, date_to=end)
    assert len(service.list_promotions()) == 1


def test_nonoverlapping_same_product_and_overlapping_other_product_allowed(service):
    first_product = product(service)
    second_product = product(service, code="P002", name="목살")
    first = promotion(service, first_product)
    promotion(service, first_product, date_from="2026-10-04", date_to="2026-10-06", sale_price=22000)
    promotion(service, second_product, sale_price=23000)
    service.save_promotion({"title": "이름만 수정"}, first)
    assert len(service.list_promotions()) == 3
    assert service.get_effective_price(first_product, "2026-10-05") == 22000
    assert service.get_effective_price(second_product, "2026-10-02") == 23000


def test_enabling_or_editing_to_conflicting_promotion_is_atomic(service):
    product_id = product(service)
    promotion(service, product_id)
    inactive = promotion(service, product_id, active=False, sale_price=19000)
    with pytest.raises(ValueError):
        service.save_promotion({"active": True}, inactive)
    row = next(row for row in service.list_promotions() if row["id"] == inactive)
    assert row["active"] is False and row["sale_price"] == 19000
    service.save_promotion({"date_from": "2026-10-04", "date_to": "2026-10-05", "active": True}, inactive)
    with pytest.raises(ValueError):
        service.save_promotion({"date_from": "2026-10-03", "sale_price": 1}, inactive)
    row = next(row for row in service.list_promotions() if row["id"] == inactive)
    assert row["date_from"] == "2026-10-04" and row["sale_price"] == 19000


@pytest.mark.parametrize("changes", [{"date_from": "2026-02-30"}, {"date_from": "20261001"},
                                    {"date_from": "2026-10-04"}, {"date_to": None},
                                    {"title": " "}, {"sale_price": None},
                                    {"sale_price": "0.5"}, {"sale_price": -1},
                                    {"sale_price": "NaN"}, {"sale_price": MAX_INTEGER + 1},
                                    {"product_id": 999999}, {"active": "false"}])
def test_promotion_validation_rolls_back(service, changes):
    product_id = product(service)
    with pytest.raises(ValueError):
        promotion(service, product_id, **changes)
    assert service.list_promotions() == []


def test_missing_rows_return_clear_errors(service):
    for action in (lambda: service.save_member({"name": "변경"}, 99999),
                   lambda: service.delete_member(99999), lambda: service.member_points(99999),
                   lambda: service.member_point_history(99999),
                   lambda: service.adjust_member_points(99999, 1, "오입력"),
                   lambda: service.save_promotion({"title": "변경"}, 99999),
                   lambda: service.delete_promotion(99999),
                   lambda: service.get_effective_price(99999, "2026-10-19")):
        with pytest.raises(ValueError):
            action()


def test_separate_permissions_do_not_expand_old_catalog_access(service):
    identifier = member(service)
    product_id = product(service)
    promotion(service, product_id)
    staff(service, ["products"])
    for action in (service.list_members, service.list_promotions,
                   lambda: service.save_member({"code": "M2", "name": "다른 회원"}),
                   lambda: service.adjust_member_points(identifier, 1, "권한 없음"),
                   lambda: promotion(service, product_id, active=False)):
        with pytest.raises(PermissionError):
            action()
    assert service.get_effective_price(product_id, "2026-10-02") == 25001


def test_reports_can_read_but_not_write_members_and_promotions(service):
    identifier = member(service)
    product_id = product(service)
    promotion_id = promotion(service, product_id)
    service.adjust_member_points(identifier, 99, "초기 적립")
    staff(service, ["reports"])
    assert service.list_members()[0]["points"] == 99
    assert service.member_points(identifier) == 99
    assert len(service.member_point_history(identifier)) == 1
    assert len(service.list_promotions()) == 1
    for action in (lambda: service.delete_member(identifier), lambda: service.delete_promotion(promotion_id),
                   lambda: service.save_member({"name": "변경"}, identifier),
                   lambda: service.save_promotion({"title": "변경"}, promotion_id),
                   lambda: service.adjust_member_points(identifier, -1, "금지")):
        with pytest.raises(PermissionError):
            action()


def test_members_only_and_promotions_only_workflow_permissions(service):
    product_id = product(service)
    staff_id = service.save_user({"username": "staff", "name": "직원", "password": "local-staff-password",
                                 "role": "staff", "permissions": ["members"]})
    service.login("staff", "local-staff-password")
    identifier = member(service)
    service.adjust_member_points(identifier, 10, "직원 수동 적립")
    assert service.member_points(identifier) == 10
    with pytest.raises(PermissionError):
        service.list_promotions()
    service.login("admin", "local-test-password")
    service.save_user({"username": "staff", "name": "직원", "role": "staff", "permissions": ["promotions"]}, staff_id)
    service.login("staff", "local-staff-password")
    assert service.list_promotion_products() == [{"id": product_id, "code": "P001", "name": "국내산 삼겹살",
                                                  "unit": "kg", "purchase_price": 18000, "sale_price": 28000}]
    assert service.list_promotion_products("없는 상품") == []
    promotion(service, product_id)
    assert len(service.list_promotions()) == 1
    assert service.get_effective_price(product_id, "2026-10-02") == 25001
    with pytest.raises(PermissionError):
        service.list_members()


def test_logged_out_calls_and_revoked_permissions_are_denied(service):
    identifier = member(service)
    staff_id = service.save_user({"username": "staff", "name": "직원", "password": "local-staff-password",
                                 "role": "staff", "permissions": ["members"]})
    service.login("staff", "local-staff-password")
    service.db.execute("UPDATE users SET permissions='[]' WHERE id=?", (staff_id,))
    with pytest.raises(PermissionError):
        service.adjust_member_points(identifier, 1, "권한 취소")
    service.logout()
    for action in (service.list_members, service.list_promotions,
                   lambda: service.member_points(identifier),
                   lambda: service.get_effective_price(1, "2026-10-19")):
        with pytest.raises(PermissionError):
            action()


def test_migration_is_idempotent_preserves_old_data_and_future_version(service):
    product_id = product(service)
    identifier = member(service)
    service.adjust_member_points(identifier, 100, "원장 보존")
    service.db.execute("PRAGMA user_version=77")
    service._migrate_loyalty()
    service._migrate_loyalty()
    assert service.db.execute("PRAGMA user_version").fetchone()[0] == 77
    assert service.list_products()[0]["id"] == product_id
    assert service.member_points(identifier) == 100
    assert len(service.member_point_history(identifier)) == 1
    assert service.db.execute("PRAGMA foreign_key_check").fetchall() == []
