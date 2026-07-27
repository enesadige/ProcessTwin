from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from apps.core.exceptions import DomainValidationError

MONEY_QUANT = Decimal("0.01")
PERCENT_QUANT = Decimal("0.0001")


def require_decimal(value: Decimal | int | str, *, field_name: str = "value") -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise DomainValidationError(
            f"{field_name} must be a valid decimal",
            details={"field": field_name, "value": value},
        ) from exc


def quantize_money(value: Decimal | int | str) -> Decimal:
    return require_decimal(value, field_name="money").quantize(MONEY_QUANT, ROUND_HALF_UP)


def quantize_percent(value: Decimal | int | str) -> Decimal:
    return require_decimal(value, field_name="percent").quantize(PERCENT_QUANT, ROUND_HALF_UP)
