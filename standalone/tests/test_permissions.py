from datetime import date
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

from pos2.app import MainWindow
from pos2.catalog_ui import CategoriesPage, ProductDialog, ProductsPage, UsersPage
from pos2.permission_ui import PermissionsPage
from pos2.permissions import MENU_POLICIES, can_action, has_menu
from pos2.store import Store
from pos2.widgets import authorize_output


@pytest.fixture
def shop(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    owner = Store(tmp_path / "permissions.db")
    owner.setup_admin("owner", "관리자", "Admin-Local-2026!")
    supplier = owner.save_partner({"kind": "supplier", "name": "축산 공급사"})
    customer = owner.save_partner({"kind": "customer", "name": "판매처"})
    product = owner.save_product({"name": "삼겹살", "supplier_id": supplier, "purchase_price": 100})
    unit = owner.save_unit({"product_id": product, "name": "박스", "factor": "2"})
    category = owner.save_category({"name": "권한 시험 분류"})
    member = owner.save_member({"code": "M1", "name": "회원"})
    gift = owner.save_gift({"code": "G1", "name": "사은품", "points": 100, "stock": 10})
    trade = {"kind": "purchase", "date": date.today(), "partner_id": supplier, "lines": [{"product_id": product, "qty": "10", "unit_price": 100}]}
    posted = owner.post_document(trade)
    draft = owner.save_draft(trade)
    payment = owner.add_payment(posted, 100, date.today(), "transfer")
    staff_id = owner.save_user({"code": "staff", "name": "직원", "role": "staff", "password": "Staff-Local-2026!", "permissions": ["catalog", "trade", "inventory", "loyalty", "reports"]})
    staff = Store(owner.path)
    staff.login("staff", "Staff-Local-2026!")
    window = SimpleNamespace(store=owner, notify=lambda *_: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_: QMessageBox.StandardButton.Ok)
    yield SimpleNamespace(app=app, owner=owner, staff=staff, staff_id=staff_id, window=window, supplier=supplier, customer=customer, product=product, unit=unit, category=category, member=member, gift=gift, posted=posted, draft=draft, payment=payment, trade=trade)
    for widget in app.topLevelWidgets():
        widget.close()
    staff.close()
    owner.close()


BLOCKS = [
    ("products.create", lambda s: s.staff.save_product({"name": "금지"})),
    ("products.edit", lambda s: s.staff.save_product({"name": "금지"}, s.product)),
    ("products.delete", lambda s: s.staff.delete_product(s.product)),
    ("products.edit", lambda s: s.staff.save_unit({"product_id": s.product, "name": "추가팩", "factor": "1"})),
    ("products.delete", lambda s: s.staff.delete_unit(s.unit)),
    ("products.edit", lambda s: s.staff.bulk_category([s.product], "권한 시험 분류")),
    ("categories.create", lambda s: s.staff.save_category({"name": "금지"})),
    ("categories.edit", lambda s: s.staff.save_category({"name": "금지"}, s.category)),
    ("categories.delete", lambda s: s.staff.delete_category(s.category)),
    ("suppliers.create", lambda s: s.staff.save_partner({"kind": "supplier", "name": "금지"})),
    ("suppliers.edit", lambda s: s.staff.save_partner({"name": "금지"}, s.supplier)),
    ("suppliers.delete", lambda s: s.staff.delete_partner(s.supplier)),
    ("customers.edit", lambda s: s.staff.save_partner({"name": "금지"}, s.customer)),
    ("customers.create", lambda s: s.staff.save_partner({"kind": "customer", "name": "금지"})),
    ("customers.delete", lambda s: s.staff.delete_partner(s.customer)),
    ("purchases.create", lambda s: s.staff.post_document(s.trade)),
    ("purchases.edit", lambda s: s.staff.save_draft(s.trade, s.draft)),
    ("purchases.delete", lambda s: s.staff.delete_draft(s.draft)),
    ("purchases.delete", lambda s: s.staff.cancel_document(s.posted, "금지")),
    ("payments.create", lambda s: s.staff.settle_supplier(s.supplier, 100, date.today(), "transfer")),
    ("payments.create", lambda s: s.staff.add_payment(s.posted, 100, date.today(), "transfer")),
    ("payments.delete", lambda s: s.staff.void_payment(s.payment, "금지")),
    ("payments.delete", lambda s: s.staff.void_supplier_settlement(999, "금지")),
    ("payments.delete", lambda s: s.staff.void_supplier_payment(s.payment, "금지")),
    ("sales.create", lambda s: s.staff.save_draft({**s.trade, "kind": "sale", "partner_id": s.customer})),
    ("counts.create", lambda s: s.staff.create_count({"title": "금지", "date": date.today(), "items": [{"product_id": s.product, "counted_qty": "10"}]})),
    ("counts.edit", lambda s: s.staff.apply_count(999)),
    ("counts.delete", lambda s: s.staff.delete_count(999)),
    ("closings.create", lambda s: s.staff.cash_close({"date": date.today(), "opening_cash": 0, "counted_cash": 0})),
    ("closings.create", lambda s: s.staff.inventory_close("2025-01")),
    ("members.create", lambda s: s.staff.save_member({"code": "M2", "name": "금지"})),
    ("members.edit", lambda s: s.staff.save_member({"name": "금지"}, s.member)),
    ("members.delete", lambda s: s.staff.delete_member(s.member)),
    ("members.edit", lambda s: s.staff.adjust_points(s.member, 100, "금지")),
    ("members.edit", lambda s: s.staff.save_member_price({"member_id": s.member, "product_id": s.product, "price": 100})),
    ("members.delete", lambda s: s.staff.delete_member_price(999)),
    ("promotions.create", lambda s: s.staff.save_promotion({})),
    ("promotions.create", lambda s: s.staff.clone_promotion(999, "2025-01-01", "2025-01-02")),
    ("promotions.edit", lambda s: s.staff.extend_promotion(999, "2025-01-02")),
    ("promotions.delete", lambda s: s.staff.delete_promotion(999)),
    ("prices.create", lambda s: s.staff.save_price_schedule({})),
    ("prices.edit", lambda s: s.staff.save_price_schedule({}, 999)),
    ("prices.delete", lambda s: s.staff.delete_price_schedule(999)),
    ("gifts.create", lambda s: s.staff.save_gift({})),
    ("gifts.edit", lambda s: s.staff.save_gift({}, s.gift)),
    ("gifts.create", lambda s: s.staff.redeem_gift(s.member, s.gift, 1, "금지")),
    ("gifts.delete", lambda s: s.staff.return_gift(999, 1, "금지")),
]


@pytest.mark.parametrize("permission,operation", BLOCKS, ids=[p for p, _ in BLOCKS])
def test_every_write_path_rechecks_actual_action_permission_in_local_engine(shop, permission, operation):
    record = next(row for row in shop.owner.list_users() if row["id"] == shop.staff_id)
    shop.owner.save_user({"permissions": record["permissions"] + [f"deny:{permission}"]}, shop.staff_id)
    before = shop.owner.db.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
    with pytest.raises(PermissionError, match="권한"):
        operation(shop)
    assert shop.owner.db.execute("SELECT COUNT(*) FROM audit").fetchone()[0] == before


def test_admin_permission_menu_saves_read_only_and_independent_edit_delete_flags(shop):
    page = PermissionsPage(shop.window)
    page.user.setCurrentIndex(page.user.findData(shop.staff_id))
    for key, checks in page.checks.items():
        checks["view"].setChecked(key == "products")
        for name, box in checks.items():
            if name != "view":
                box.setChecked(False)
    page.checks["products"]["edit"].setChecked(True)
    page.save()
    shop.staff._require()
    assert has_menu(shop.staff.actor, "products")
    assert can_action(shop.staff.actor, "products", "edit")
    assert not can_action(shop.staff.actor, "products", "create")
    assert not can_action(shop.staff.actor, "products", "delete")
    assert not has_menu(shop.staff.actor, "suppliers")
    shop.staff.save_product({"name": "수정 가능"}, shop.product)
    with pytest.raises(PermissionError):
        shop.staff.save_product({"name": "등록 불가"})
    window = MainWindow(shop.staff)
    # Public entertainment contains no business or private records.
    assert set(window.items) == {"home", "products", "lucky_numbers"}
    assert window.open_page("products")
    products = window.pages["products"]
    buttons = {button.text(): button for surface in (products,products.header) for button in surface.findChildren(QPushButton)}
    assert any(not button.isEnabled() for name, button in buttons.items() if "등록" in name)
    with pytest.raises(PermissionError):
        shop.staff.save_user({"permissions": ["admin"]}, shop.staff_id)


def test_permission_revocation_blocks_already_open_editor_and_output(shop):
    window = MainWindow(shop.staff)
    assert window.open_page("products")
    page = window.current_page
    product = next(row for row in shop.staff.products() if row["id"] == shop.product)
    dialog = ProductDialog(shop.staff, product)
    dialog.fields["name"].setText("권한 회수 후 저장 금지")
    rights = next(r for r in shop.owner.list_users() if r["id"] == shop.staff_id)["permissions"]
    shop.owner.save_user({"permissions": rights + ["deny:products.edit"]}, shop.staff_id)
    assert not dialog.save(False)
    assert "권한" in dialog.error_label.text()
    shop.owner.save_user({"permissions": rights + ["deny:products"]}, shop.staff_id)
    assert not authorize_output(page)
    assert page.grid.rowCount() == 0
    assert not window.open_page("products")
    assert not page.isEnabled()


def test_read_only_category_context_blocks_edit_delete_and_keeps_tree_view(shop):
    rights = next(r for r in shop.owner.list_users() if r["id"] == shop.staff_id)["permissions"]
    shop.owner.save_user({"permissions": rights + ["deny:categories.create", "deny:categories.edit", "deny:categories.delete"]}, shop.staff_id)
    shop.staff._require()
    page = CategoriesPage(SimpleNamespace(store=shop.staff, notify=lambda *_: None))
    page.tree.setCurrentItem(page.items[shop.category])
    menu = {entry.text(): entry for entry in page.make_context_menu().actions()}
    assert not menu["분류 추가"].isEnabled() and not menu["분류 삭제"].isEnabled()
    assert not menu["분류 등록정보 / 수정"].isEnabled()
    assert menu["하위분류 보기"].isEnabled()


def test_legacy_area_permissions_still_work_and_privileges_cannot_be_forged(shop):
    shop.staff.save_product({"name": "종전 권한 유지"})
    for key in ("products", "categories", "purchases", "sales", "payments", "members"):
        assert has_menu(shop.staff.actor, key)
    with pytest.raises(ValueError):
        shop.owner.save_user({"permissions": ["allow:admin"]}, shop.staff_id)
    with pytest.raises(PermissionError):
        shop.staff.require_menu("permissions")


def test_category_creation_cannot_be_bypassed_by_product_fields(shop):
    rights = next(r for r in shop.owner.list_users() if r["id"] == shop.staff_id)["permissions"]
    shop.owner.save_user({"permissions": rights + ["deny:categories.create"]}, shop.staff_id)
    with pytest.raises(PermissionError):
        shop.staff.save_product({"name": "우회 금지", "category": "임의 생성 분류"})
    assert not shop.owner.products("우회 금지")


def test_editing_a_different_document_kind_cannot_bypass_original_menu_rights(shop):
    rights = next(r for r in shop.owner.list_users() if r["id"] == shop.staff_id)["permissions"]
    shop.owner.save_user({"permissions": rights + ["deny:purchases.edit"]}, shop.staff_id)
    with pytest.raises(PermissionError):
        shop.staff.save_draft({**shop.trade, "kind": "sale", "partner_id": shop.customer}, shop.draft)
    assert shop.owner.document(shop.draft)["kind"] == "purchase"


def test_users_menu_permission_button_opens_selected_staff_and_preserves_restrictions(shop):
    shop.owner.save_user({"permissions": ["catalog", "deny:products.delete"]}, shop.staff_id)
    shop.owner.save_user({"name": "이름만 변경"}, shop.staff_id)
    assert "deny:products.delete" in next(r for r in shop.owner.list_users() if r["id"] == shop.staff_id)["permissions"]
    window = MainWindow(shop.owner)
    window.open_page("users")
    users = window.current_page
    for index in range(users.grid.rowCount()):
        if users.grid.item(index, 0).data(256)["id"] == shop.staff_id:
            users.grid.selectRow(index)
            break
    users.permissions()
    assert window.current_key == "permissions"
    assert window.current_page.user.currentData() == shop.staff_id
    assert not window.current_page.checks["products"]["delete"].isChecked()
