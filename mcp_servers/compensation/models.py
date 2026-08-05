from __future__ import annotations

from datetime import datetime

from pydantic import Field, field_validator, model_validator

from mcp_servers.shared.contracts import BaseMCPInput, TemporalMCPInput

DEFAULT_LIMIT = 50
MAX_LIMIT = 100


class SnapshotRequiredInput(BaseMCPInput):
    snapshot_identifier: str = Field(min_length=1)


class CompensationRuleInput(SnapshotRequiredInput):
    outage_code: str = Field(min_length=1)
    subscription_number: str = Field(min_length=1)
    rule_code: str | None = None
    rule_set_code: str | None = None
    evaluation_time: datetime | None = None

    @field_validator("evaluation_time")
    @classmethod
    def evaluation_time_must_be_timezone_aware(cls, value: datetime | None) -> datetime | None:
        return validate_optional_aware_datetime(value, "evaluation_time")

    @model_validator(mode="after")
    def rule_code_or_rule_set_code_is_required(self):
        if not self.rule_code and not self.rule_set_code:
            raise ValueError("rule_code or rule_set_code is required")
        return self


class RefundEligibilityInput(CompensationRuleInput):
    pass


class RefundAmountInput(CompensationRuleInput):
    persist: bool = False


class CompensationOptionsInput(SnapshotRequiredInput):
    outage_code: str = Field(min_length=1)
    subscription_number: str = Field(min_length=1)
    rule_set_code: str = Field(min_length=1)
    evaluation_time: datetime | None = None
    include_ineligible: bool = False

    @field_validator("evaluation_time")
    @classmethod
    def evaluation_time_must_be_timezone_aware(cls, value: datetime | None) -> datetime | None:
        return validate_optional_aware_datetime(value, "evaluation_time")


class CampaignEligibilityInput(SnapshotRequiredInput):
    subscription_number: str = Field(min_length=1)
    campaign_code: str | None = None
    evaluation_time: datetime | None = None

    @field_validator("evaluation_time")
    @classmethod
    def evaluation_time_must_be_timezone_aware(cls, value: datetime | None) -> datetime | None:
        return validate_optional_aware_datetime(value, "evaluation_time")


class RankCompensationOptionsInput(TemporalMCPInput):
    snapshot_identifier: str = Field(min_length=1)
    outage_code: str = Field(min_length=1)
    subscription_number: str = Field(min_length=1)
    rule_set_code: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=MAX_LIMIT)


class CompensationEvidenceInput(SnapshotRequiredInput):
    causal_event_code: str | None = Field(default=None, min_length=1)
    evaluation_code: str | None = None
    evidence_hash: str | None = None
    outage_code: str | None = None
    subscription_number: str | None = None
    rule_code: str | None = None
    decision: str | None = None
    limit: int = Field(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)
    cursor: str | None = None

    @model_validator(mode="after")
    def at_least_one_identifier_is_required(self):
        if self.causal_event_code:
            return self
        if not any(
            (
                self.evaluation_code,
                self.evidence_hash,
                self.outage_code,
                self.subscription_number,
                self.rule_code,
            )
        ):
            raise ValueError("At least one evidence identifier is required")
        return self


def validate_optional_aware_datetime(value: datetime | None, field_name: str) -> datetime | None:
    if value is None:
        return value
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value
