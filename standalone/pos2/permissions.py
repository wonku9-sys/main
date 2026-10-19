"""Per-menu restrictions layered over legacy business-area permissions.

Old accounts retain their existing area rights. The administrator editor writes
explicit deny entries for unchecked menus/actions; absence never adds an area.
"""

MENU_POLICIES = {
    "home": ("첫화면", (), ()),
    "diary": ("보안 일기장", (), ()),
    "worklog": ("업무일지", (), ("create","edit","delete")),
    "household": ("가계부", (), ("create","edit","delete")),
    "lucky_numbers": ("행운의 숫자", (), ()),
    "products": ("상품장 · 확장단위", ("catalog",), ("create", "edit", "delete")),
    "categories": ("상품 분류", ("catalog",), ("create", "edit", "delete")),
    "suppliers": ("공급사관리", ("catalog",), ("create", "edit", "delete")),
    "customers": ("판매처", ("catalog",), ("create", "edit", "delete")),
    "labels": ("라벨 출력", ("catalog",), ()),
    "purchases": ("매입전표", ("trade",), ("create", "edit", "delete")),
    "purchase_suppliers": ("공급사별 매입현황", ("trade",), ()),
    "purchase_categories": ("분류별 매입현황", ("trade",), ()),
    "purchase_products": ("단품별 매입현황", ("trade",), ()),
    "purchase_documents": ("전표별 매입현황", ("trade",), ()),
    "purchase_statement": ("매입계산서", ("trade",), ()),
    "payments": ("결제관리", ("trade",), ("create", "delete")),
    "sales": ("매출장 · 고객반품", ("trade",), ("create", "edit", "delete")),
    "sales_cancelled": ("취소내역", ("trade",), ()),
    "sales_held": ("보류내역", ("trade",), ()),
    "ledger": ("거래처 원장", ("trade",), ()),
    "inventory": ("현재고 · 입출고", ("inventory",), ()),
    "opening_stock": ("기초재고 등록", ("inventory",), ("create",)),
    "stock_waste": ("재고 폐기", ("inventory",), ("create",)),
    "inventory_assets": ("재고자산 현황", ("inventory",), ()),
    "counts": ("실사 입력 · 적용", ("inventory",), ("create", "edit", "delete")),
    "closings": ("현금 · 월재고 마감", ("inventory", "trade"), ("create",)),
    "members": ("회원조회/등록", ("loyalty",), ("create", "edit", "delete")),
    "promotions": ("특매 그룹", ("loyalty",), ("create", "edit", "delete")),
    "prices": ("가격 변경 예약", ("loyalty",), ("create", "edit", "delete")),
    "gifts": ("사은품 · 교환", ("loyalty",), ("create", "edit", "delete")),
    "overview": ("업무 현황", ("reports",), ()),
    "reports": ("일 · 월 · 상세 집계", ("reports",), ()),
    "commission": ("공급사 판매 수수료", ("reports",), ()),
    "users": ("사용자 관리", ("admin",), ()),
    "permissions": ("권한 설정", ("admin",), ()),
    "settings": ("매장 설정 · 백업", ("admin",), ()),
}
from .offline_menus import REPORT_VIEWS, SALES_VIEWS, BASIC_VIEWS, MEMBER_VIEWS, FORM_VIEWS
MENU_POLICIES.update({key: (value[0], (value[3],), ()) for key, value in {**REPORT_VIEWS, **SALES_VIEWS}.items()})
MENU_POLICIES.update({key: (title, ("admin" if key == "user_access" else "catalog",), ()) for key, title in BASIC_VIEWS.items()})
MENU_POLICIES.update({key: (title, ("loyalty",), ()) for key, title in MEMBER_VIEWS.items()})
MENU_POLICIES.update({key: (value[0], ("loyalty" if key == "member_tax" else "trade",), ("create", "edit", "delete")) for key, value in FORM_VIEWS.items()})
ACTIONS = {"create": "등록", "edit": "수정·편집", "delete": "삭제·취소"}
DENIAL_PERMISSIONS = frozenset(value for key, (_, bases, actions) in MENU_POLICIES.items() if (bases or key in {"diary","worklog","household"}) and "admin" not in bases
                               for value in (f"deny:{key}", *(f"deny:{key}.{action}" for action in actions)))


def has_menu(actor, key):
    if key not in MENU_POLICIES:
        return False
    if not actor:
        return False
    if key in {"home","lucky_numbers"}:
        return True
    if actor.get("role") == "admin":
        return True
    permissions = set(actor.get("permissions", []))
    if key in {"diary","worklog","household"}:
        return f"deny:{key}" not in permissions
    return bool(set(MENU_POLICIES[key][1]) - {"admin"}) and bool(set(MENU_POLICIES[key][1]) & permissions) and f"deny:{key}" not in permissions


def can_action(actor, key, operation):
    return has_menu(actor, key) and operation in MENU_POLICIES[key][2] and (actor.get("role") == "admin" or f"deny:{key}.{operation}" not in set(actor.get("permissions", [])))


def menu_key_for(widget):
    explicit = getattr(widget, "menu_key", None)
    if explicit:
        return explicit
    name = type(widget).__name__
    if name in {"PartnersPage", "SupplierPicker"}:
        return "suppliers" if getattr(widget, "kind", "supplier") == "supplier" else "customers"
    if name in {"TradeDialog", "TradesPage"}:
        return "purchases" if getattr(widget, "kind", "purchase").startswith("purchase") else "sales"
    return {
        "ProductsPage": "products", "ProductDialog": "products", "CategoriesPage": "categories", "CategoryDialog": "categories",
        "ProductCatalogDialog": "products",
        "SuppliersPage": "suppliers", "SupplierDialog": "suppliers", "SupplierGroupsDialog": "suppliers",
        "SupplierPaymentsPage": "payments", "SupplierPaymentDialog": "payments", "LedgerPage": "ledger",
        "CountsPage": "counts", "CountEditor": "counts", "InventoryPage": "inventory", "ClosingsPage": "closings",
        "MembersPage": "members", "MemberDialog": "members", "PromotionsPage": "promotions", "PromotionDialog": "promotions",
        "PricesPage": "prices", "GiftsPage": "gifts", "OverviewPage": "overview", "ReportPage": "reports", "CommissionPage": "commission",
        "LabelsPage": "labels", "LabelDialog": "labels", "UsersPage": "users", "SettingsPage": "settings", "PermissionsPage": "permissions",
    }.get(name)


def restrict_button(button, callback):
    owner = getattr(callback, "__self__", None)
    store = getattr(owner, "store", None)
    key = menu_key_for(owner) if owner else None
    method = getattr(callback, "__name__", "")
    operation = {"add": "create", "add_root": "create", "add_child": "create", "new_trade": "create", "create": "create", "pay": "create", "redeem": "create",
                 "edit": "edit", "apply": "edit", "bulk_category": "edit", "add_unit": "edit", "edit_unit": "edit", "apply_changes": "edit",
                 "delete": "delete", "cancel": "delete", "delete_draft": "delete", "return_trade": "delete", "delete_unit": "delete", "void": "delete", "void_payment": "delete"}.get(method)
    if method in {"void_payment", "settle"} and key == "purchases":
        key, operation = "payments", "delete" if method == "void_payment" else "create"
    if store and key and operation and operation in MENU_POLICIES[key][2] and not can_action(store.actor, key, operation):
        button.setEnabled(False)
        button.setToolTip(f"{ACTIONS[operation]} 권한이 없습니다.")
