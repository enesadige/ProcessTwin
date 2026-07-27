from __future__ import annotations

from datetime import date, datetime

from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from apps.core.exceptions import DomainValidationError


def now() -> datetime:
    return timezone.now()


def require_date(value: str | date, *, field_name: str = "date") -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value

    parsed = parse_date(value) if isinstance(value, str) else None
    if parsed is None:
        raise DomainValidationError(
            f"{field_name} must be a valid ISO date",
            details={"field": field_name, "value": value},
        )
    return parsed


def require_datetime(value: str | datetime, *, field_name: str = "datetime") -> datetime:
    if isinstance(value, datetime):
        return value if timezone.is_aware(value) else timezone.make_aware(value)

    parsed = parse_datetime(value) if isinstance(value, str) else None
    if parsed is None:
        raise DomainValidationError(
            f"{field_name} must be a valid ISO datetime",
            details={"field": field_name, "value": value},
        )

    return parsed if timezone.is_aware(parsed) else timezone.make_aware(parsed)
