"""Exact, shared business values for the independent offline application."""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

LIMIT = 9_000_000_000_000
PERMISSIONS = frozenset({"catalog", "trade", "inventory", "loyalty", "reports", "admin"})
from .permissions import DENIAL_PERMISSIONS
ALLOWED_PERMISSIONS = PERMISSIONS | DENIAL_PERMISSIONS


def decimal(value):
    try:
        result = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("올바른 숫자를 입력하세요.") from None
    if not result.is_finite():
        raise ValueError("유한한 숫자만 사용할 수 있습니다.")
    return result


def rounded(value):
    number = decimal(value)
    if abs(number) > LIMIT:
        raise ValueError("금액 허용 범위를 초과했습니다.")
    return int(number.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def money(value, positive=False):
    from .currency import money_input
    return money_input(value, positive=positive)


def qty(value, allow_zero=False, signed=False):
    number = decimal(value)
    scaled = number * 1000
    if scaled != scaled.to_integral_value():
        raise ValueError("수량은 소수점 셋째 자리까지만 입력하세요.")
    if abs(scaled) > LIMIT:
        raise ValueError("수량 허용 범위를 초과했습니다.")
    if (not signed and scaled < 0) or (not allow_zero and scaled == 0):
        raise ValueError("수량은 0보다 커야 합니다.")
    return int(scaled)


def qtext(scaled):
    return format(Decimal(int(scaled)) / 1000, ".3f")


def day(value):
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    try:
        return date.fromisoformat(str(value)).isoformat()
    except (ValueError, TypeError):
        raise ValueError("날짜는 YYYY-MM-DD 형식으로 입력하세요.") from None


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def text(value, label="값", required=False, maximum=2000):
    result = str(value if value is not None else "").strip()
    if required and not result:
        raise ValueError(f"{label}을(를) 입력하세요.")
    if len(result) > maximum:
        raise ValueError(f"{label}은(는) {maximum}자 이하여야 합니다.")
    return result
