from decimal import Decimal

import pytest

from apps.core.choices import ResultStatus
from apps.core.exceptions import DomainValidationError, InsufficientDataError
from apps.core.responses import build_api_payload
from apps.core.utils.dates import require_date, require_datetime
from apps.core.utils.decimals import quantize_money, quantize_percent, require_decimal


def test_result_status_values_are_stable():
    assert ResultStatus.EXACT == "exact"
    assert ResultStatus.LIMITED == "limited"
    assert ResultStatus.INSUFFICIENT_DATA == "insufficient_data"
    assert ResultStatus.FAILED == "failed"


def test_api_payload_uses_standard_shape():
    payload = build_api_payload(
        data={"count": 3},
        result_status=ResultStatus.LIMITED,
        meta={"source": "unit-test"},
    )

    assert payload == {
        "status": ResultStatus.LIMITED,
        "data": {"count": 3},
        "meta": {"source": "unit-test"},
    }


def test_exception_payload_uses_standard_shape():
    error = InsufficientDataError("Missing outage window", details={"field": "started_at"})

    assert error.to_response_payload() == {
        "status": ResultStatus.INSUFFICIENT_DATA,
        "error": {
            "code": "insufficient_data",
            "message": "Missing outage window",
            "details": {"field": "started_at"},
        },
    }


def test_date_helpers_parse_iso_values():
    assert require_date("2026-07-27").isoformat() == "2026-07-27"
    assert require_datetime("2026-07-27T10:00:00+03:00").isoformat().startswith(
        "2026-07-27T10:00:00"
    )


def test_date_helpers_raise_domain_error_for_invalid_values():
    with pytest.raises(DomainValidationError):
        require_date("not-a-date", field_name="incident_date")


def test_decimal_helpers_are_deterministic():
    assert require_decimal("399.90") == Decimal("399.90")
    assert quantize_money("47.994") == Decimal("47.99")
    assert quantize_money("47.995") == Decimal("48.00")
    assert quantize_percent("0.123456") == Decimal("0.1235")
