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


class SearchRulesInput(SnapshotRequiredInput):
    rule_set_code: str | None = None
    rule_code: str | None = None
    family: str | None = None
    rule_type: str | None = None
    status: str | None = None
    action_type: str | None = None
    price_basis: str | None = None
    conflict_group: str | None = None
    active_at: datetime | None = None
    limit: int = Field(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)
    cursor: str | None = None

    @field_validator("active_at")
    @classmethod
    def active_at_must_be_timezone_aware(cls, value: datetime | None) -> datetime | None:
        return validate_optional_aware_datetime(value, "active_at")


class GetRuleInput(SnapshotRequiredInput):
    rule_code: str = Field(min_length=1)
    version: int | None = Field(default=None, ge=1)
    effective_at: datetime | None = None
    include_raw_config: bool = False
    include_schema_summary: bool = True

    @field_validator("effective_at")
    @classmethod
    def effective_at_must_be_timezone_aware(cls, value: datetime | None) -> datetime | None:
        return validate_optional_aware_datetime(value, "effective_at")

    @model_validator(mode="after")
    def version_and_effective_at_are_mutually_exclusive(self):
        if self.version is not None and self.effective_at is not None:
            raise ValueError("version and effective_at cannot be used together")
        return self


class GetRulesEffectiveAtInput(TemporalSnapshotInput):
    family: str | None = None
    rule_type: str | None = None
    rule_code: str | None = None
    rule_set_code: str | None = None
    conflict_group: str | None = None
    limit: int = Field(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)
    cursor: str | None = None

    @model_validator(mode="after")
    def evaluation_time_is_required(self):
        if self.evaluation_time is None:
            raise ValueError("evaluation_time is required")
        return self


class RuleVersionHistoryInput(SnapshotRequiredInput):
    rule_code: str = Field(min_length=1)
    include_raw_config: bool = False
    limit: int = Field(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)
    cursor: str | None = None


class FindRelatedRulesInput(SnapshotRequiredInput):
    rule_code: str | None = None
    rule_set_code: str | None = None
    family: str | None = None
    conflict_group: str | None = None
    action_type: str | None = None
    price_basis: str | None = None
    limit: int = Field(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)
    cursor: str | None = None

    @model_validator(mode="after")
    def at_least_one_relation_input_is_required(self):
        if not any(
            (
                self.rule_code,
                self.rule_set_code,
                self.family,
                self.conflict_group,
                self.action_type,
                self.price_basis,
            )
        ):
            raise ValueError("At least one relation input is required")
        return self


class DetectRuleConflictsInput(TemporalSnapshotInput):
    rule_set_code: str | None = None
    rule_code: str | None = None
    conflict_group: str | None = None
    limit: int = Field(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)
    cursor: str | None = None

    @model_validator(mode="after")
    def at_least_one_scope_filter_is_required(self):
        if not any((self.rule_set_code, self.rule_code, self.conflict_group)):
            raise ValueError("At least one conflict scope filter is required")
        return self


class RuleEvidenceInput(SnapshotRequiredInput):
    evidence_hash: str | None = None
    evaluation_code: str | None = None
    rule_code: str | None = None
    rule_set_code: str | None = None
    outage_code: str | None = None
    subscription_number: str | None = None
    decision: str | None = None
    limit: int = Field(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)
    cursor: str | None = None

    @model_validator(mode="after")
    def at_least_one_identifier_is_required(self):
        if not any(
            (
                self.evidence_hash,
                self.evaluation_code,
                self.rule_code,
                self.rule_set_code,
                self.outage_code,
                self.subscription_number,
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
