"""Currency is integer hundredths in SQLite and Decimal won at public boundaries."""
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps
import json

from .common import LIMIT, decimal, now


MONEY_COLUMNS = {
    "stock_adjustments": ("stock_cost",),
    "sales_forms": ("total",),
    "partners": ("opening_balance",),
    "products": ("purchase_price", "sale_price", "stock_cost"),
    "product_units": ("purchase_price", "sale_price"),
    "documents": ("total", "cash_paid", "points_used"),
    "document_lines": ("unit_price", "total", "cost", "commission_amount"),
    "payments": ("amount",),
    "supplier_settlements": ("amount", "opening_amount"),
    "stock_events": ("cost_delta", "balance_cost"),
    "member_prices": ("price",),
    "promotion_items": ("purchase_price", "sale_price"),
    "price_schedules": ("purchase_price", "sale_price"),
    "loyalty_return_actions": ("return_total",),
    "inventory_count_lines": ("expected_cost", "counted_cost"),
    "inventory_closes": ("stock_cost",),
    "inventory_close_lines": ("stock_cost",),
    "cash_closes": ("opening_cash", "cash_receipts", "cash_refunds", "cash_net", "expected_cash", "counted_cash", "difference"),
}
MONEY_KEYS = frozenset(key for columns in MONEY_COLUMNS.values() for key in columns) | {
    'asset_total','debt_total','net_assets','cash_assets','locked_assets','saved_amount','gap','monthly_saving','projected_balance',
    'fixed_total','variable_total','budget_total','available_total','necessary_total','living_total','split_original_amount',
    'handling_revenue','storage_revenue','extra_revenue','rent_cost','management_cost','other_cost','hourly_rate','revenue_total','labor_cost','total_cost',
    'fuel_total','average_unit_price',
    "opening_cost","week_cost","month_cost","change_week","change_month",
    "income_total","expense_total","closing_balance","previous_total","comparable_total",
    "balance", "net_balance", "refundable", "unrefunded_credit", "charge", "payment", "closing", "opening",
    "purchase", "returns", "cap", "as_of", "cost_difference", "sale_receipts", "refunds", "profit",
    "purchase_total", "sale_total", "taxable_sale_total", "exempt_sale_total", "transfer_receipts", "transfer_refunds", "transfer_net",
    "commission_fee", "payable", "amount", "return_total", "credit_applied", "net_total", "taxable_total", "exempt_total", "vat", "supply_value",
}


def amount(scaled):
    return (Decimal(scaled) / 100).quantize(Decimal("0.01"))


def money_input(value, positive=False, signed=False):
    number = decimal(value)
    scaled = number * 100
    if scaled != scaled.to_integral_value():
        raise ValueError("금액과 단가는 소수점 두 자리까지만 입력하세요.")
    if abs(scaled) > LIMIT or not signed and scaled < 0 or positive and scaled <= 0:
        raise ValueError("금액 허용 범위를 확인하세요. 최소 양수 금액은 0.01원입니다.")
    return int(scaled)


def public_input(value, positive=False):
    return amount(money_input(value, positive=positive))


def round_amount(value, mode="decimal"):
    if mode not in {"decimal", "won"}:
        raise ValueError("반올림 설정을 확인하세요.")
    return decimal(value).quantize(Decimal("1") if mode == "won" else Decimal("0.01"), rounding=ROUND_HALF_UP)


def convert_result(value, key=None):
    if isinstance(value, dict):
        return {name: convert_result(item, key if name in {"old", "new"} else name) for name, item in value.items()}
    if isinstance(value, list):
        return [convert_result(item) for item in value]
    if isinstance(value, tuple):
        return tuple(convert_result(item) for item in value)
    if type(value) is int and key in MONEY_KEYS:
        return amount(value)
    return value


def currency_boundary(cls):
    """Nested domain calls retain minor units; only the outer result is public."""
    methods = {}
    for base in reversed(cls.__mro__[:-1]):
        methods.update({name: function for name, function in vars(base).items() if not name.startswith("_") and callable(function)})
    def wrap(name, function):
        @wraps(function)
        def call(self, *args, **kwargs):
            depth = getattr(self, "_currency_depth", 0)
            self._currency_depth = depth + 1
            own_read=name in {'inventory_status','products','trade_products','lookup_barcode','document','household_financial_overview','household_cash_forecast','household_annual_report','household_custom_report','work_log_report','sales_period_comparison'} and not self.db.in_transaction
            if own_read:self.db.execute('BEGIN')
            try:
                result = function(self, *args, **kwargs)
                if own_read:self.db.commit()
            except BaseException:
                if own_read:self.db.rollback()
                raise
            finally:
                self._currency_depth = depth
            return convert_result(result) if depth == 0 and name not in {"point_history"} else result
        return call
    for name, function in methods.items():
        setattr(cls, name, wrap(name, function))
    return cls


def upgrade_currency(store, version):
    if version >= 204:
        return
    # Snapshot the original units before a lossless x100 conversion. Never
    # overwrite a user's backup and do not migrate any quantity or point count.
    if version and store.path:
        from datetime import datetime
        import secrets
        target = store._backup_directory() / f"형식변경전-자동백업_{datetime.now():%Y%m%d_%H%M%S}_{secrets.token_hex(4)}.db"
        store._backup_file(target)
        store.migration_backup_path = str(target)
    db = store.db
    db.execute("BEGIN IMMEDIATE")
    try:
        for table, columns in MONEY_COLUMNS.items():
            for column in columns:
                if db.execute(f'SELECT 1 FROM "{table}" WHERE ABS("{column}")>? LIMIT 1', (LIMIT // 100,)).fetchone():
                    raise ValueError("기존 금액이 새 소수점 저장 범위를 초과합니다. 원본 장부와 보호 백업을 보관하고 문의하세요.")
        protected = [tuple(row) for row in db.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name IN ('inventory_closes','inventory_close_lines','cash_closes')")]
        for name, _ in protected:
            db.execute(f'DROP TRIGGER "{name}"')
        for table, columns in MONEY_COLUMNS.items():
            db.execute(f'UPDATE "{table}" SET ' + ",".join(f'"{column}"="{column}"*100' for column in columns))
        for _, sql in protected:
            db.execute(sql)
        db.execute("PRAGMA user_version=204")
        db.execute("INSERT INTO audit(at,user_id,action,entity,entity_id,detail) VALUES(?,NULL,'currency_upgrade','settings',NULL,?)", (now(), json.dumps({"from_version": version, "currency_scale": 100, "quantity_unchanged": True})))
        db.commit()
    except BaseException:
        db.rollback()
        raise
