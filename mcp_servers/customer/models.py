from __future__ import annotations

from datetime import datetime

from pydantic import Field, field_validator, model_validator

from mcp_servers.shared.contracts import BaseMCPInput, TemporalMCPInput

DEFAULT_LIMIT = 50
MAX_LIMIT = 100


class SnapshotRequiredInput(BaseMCPInput):
    snapshot_identifier: str = Field(min_length=1)


class TemporalSnapshotInput(TemporalMCPInput):
    snapshot_identifier: str = Field(min_length=1)


class CustomerProfileInput(SnapshotRequiredInput):
    customer_number: str = Field(min_length=1)
    include_subscriptions: bool = False
    include_display_name: bool = False


class OneCustomerOrSubscriptionInput(SnapshotRequiredInput):
    customer_number: str | None = None
    subscription_number: str | None = None

    @model_validator(mode="after")
    def exactly_one_identifier_is_required(self):
        if bool(self.customer_number) == bool(self.subscription_number):
            raise ValueError("Exactly one of customer_number or subscription_number is required")
        return self


class CustomerSubscriptionInput(OneCustomerOrSubscriptionInput):
    include_connections: bool = True
    include_campaigns: bool = False
    limit: int = Field(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)
    cursor: str | None = None


class CustomerPaymentStatusInput(OneCustomerOrSubscriptionInput):
    from_period: str | None = None
    to_period: str | None = None
    status: str | None = None
    limit: int = Field(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)
    cursor: str | None = None

    @field_validator("from_period", "to_period")
    @classmethod
    def billing_period_must_be_year_month(cls, value: str | None) -> str | None:
        if value is None:
            return value
        parts = value.split("-")
        if len(parts) != 2 or len(parts[0]) != 4 or len(parts[1]) != 2:
            raise ValueError("billing period must use YYYY-MM format")
        if not parts[0].isdigit() or not parts[1].isdigit():
            raise ValueError("billing period must use YYYY-MM format")
        month = int(parts[1])
        if month < 1 or month > 12:
            raise ValueError("billing period month must be between 01 and 12")
        return value


class CustomerOutageHistoryInput(TemporalSnapshotInput):
    customer_number: str | None = None
    subscription_number: str | None = None
    causal_event_code: str | None = Field(default=None, min_length=1)
    from_time: datetime | None = None
    to_time: datetime | None = None
    impact_class: str | None = None
    limit: int = Field(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)
    cursor: str | None = None

    @model_validator(mode="after")
    def exactly_one_identifier_is_required(self):
        if self.causal_event_code:
            return self
        if bool(self.customer_number) == bool(self.subscription_number):
            raise ValueError("Exactly one of customer_number or subscription_number is required")
        return self

    @field_validator("from_time", "to_time")
    @classmethod
    def datetimes_must_be_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return value
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime filters must be timezone-aware")
        return value


class CustomerCompensationHistoryInput(OneCustomerOrSubscriptionInput):
    decision_status: str | None = None
    settlement_status: str | None = None
    from_time: datetime | None = None
    to_time: datetime | None = None
    limit: int = Field(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)
    cursor: str | None = None

    @field_validator("from_time", "to_time")
    @classmethod
    def datetimes_must_be_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return value
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime filters must be timezone-aware")
        return value


class ListCustomersByDeviceInput(TemporalSnapshotInput):
    device_code: str = Field(min_length=1)
    segment: str | None = None
    priority_level: str | None = None
    subscription_status: str | None = None
    limit: int = Field(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)
    cursor: str | None = None
    include_display_name: bool = False


class ListCustomersByLocationInput(SnapshotRequiredInput):
    city: str | None = None
    district: str | None = None
    neighborhood: str | None = None
    segment: str | None = None
    priority_level: str | None = None
    status: str | None = None
    limit: int = Field(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)
    cursor: str | None = None
    include_display_name: bool = False

    @model_validator(mode="after")
    def at_least_one_location_filter_is_required(self):
        if not any((self.city, self.district, self.neighborhood)):
            raise ValueError("At least one location filter is required")
        return self
