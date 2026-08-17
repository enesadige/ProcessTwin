"""Bind typed analytics answer requirements to existing canonical rows only."""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from apps.orchestration.analytics_answer_requirements import (
    AnalyticsAnswerRequirement,
    AnalyticsAnswerRequirementKind,
    AnalyticsAnswerRequirements,
)
from apps.orchestration.result_merge import AnalyticsSummary
from apps.orchestration.structured_query import StructuredQueryLocation, StructuredQueryTimeWindow


class AnalyticsAnswerFactKind(StrEnum):
    CANONICAL_VALUE = "canonical_value"


class AnalyticsRequirementResolutionState(StrEnum):
    RESOLVED = "resolved"
    MISSING = "missing"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class AnalyticsAnswerFact(BaseModel):
    """One known canonical analytics value selected for a requested requirement."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: AnalyticsAnswerFactKind = AnalyticsAnswerFactKind.CANONICAL_VALUE
    requirement_index: int = Field(ge=0)
    requirement_kind: AnalyticsAnswerRequirementKind
    metric: str
    aggregation: str
    value: int | float | str
    unit: str
    group_by: str | None = None
    group_label: str | None = None
    scope: StructuredQueryLocation | None = None
    time_window: StructuredQueryTimeWindow | None = None
    canonical_source_ref: str


class AnalyticsRequirementResolution(BaseModel):
    """Resolution outcome for one requested requirement without derived claims."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement_index: int = Field(ge=0)
    requirement_kind: AnalyticsAnswerRequirementKind
    state: AnalyticsRequirementResolutionState
    facts: tuple[AnalyticsAnswerFact, ...] = ()


class AnalyticsAnswerFactSet(BaseModel):
    """Canonical fact bindings and explicit unresolved states for later stages."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    facts: tuple[AnalyticsAnswerFact, ...] = ()
    resolutions: tuple[AnalyticsRequirementResolution, ...] = ()


class AnalyticsAnswerFactResolver:
    """Resolve only typed requirements; never calculate or interpret analytics."""

    @classmethod
    def resolve(
        cls,
        requirements: AnalyticsAnswerRequirements,
        summaries: Iterable[AnalyticsSummary],
    ) -> AnalyticsAnswerFactSet:
        canonical_summaries = tuple(summaries)
        facts: list[AnalyticsAnswerFact] = []
        resolutions: list[AnalyticsRequirementResolution] = []
        for requirement_index, requirement in enumerate(requirements.requirements):
            resolution = cls._resolve_requirement(
                requirement_index,
                requirement,
                canonical_summaries,
            )
            facts.extend(resolution.facts)
            resolutions.append(resolution)
        return AnalyticsAnswerFactSet(facts=tuple(facts), resolutions=tuple(resolutions))

    @classmethod
    def _resolve_requirement(
        cls,
        requirement_index: int,
        requirement: AnalyticsAnswerRequirement,
        summaries: tuple[AnalyticsSummary, ...],
    ) -> AnalyticsRequirementResolution:
        if requirement.kind == AnalyticsAnswerRequirementKind.MULTI_METRIC:
            return cls._resolution(
                requirement_index,
                requirement,
                AnalyticsRequirementResolutionState.NOT_APPLICABLE,
            )
        if requirement.kind == AnalyticsAnswerRequirementKind.RANKING_WINNER:
            return cls._resolve_ranking(requirement_index, requirement, summaries)
        if requirement.kind == AnalyticsAnswerRequirementKind.COMPARISON:
            return cls._resolve_comparison(requirement_index, requirement, summaries)
        return cls._resolve_scoped_values(requirement_index, requirement, summaries)

    @classmethod
    def _resolve_ranking(
        cls,
        requirement_index: int,
        requirement: AnalyticsAnswerRequirement,
        summaries: tuple[AnalyticsSummary, ...],
    ) -> AnalyticsRequirementResolution:
        matches = cls._matching_summaries(requirement, summaries)
        if not matches:
            return cls._resolution(
                requirement_index, requirement, AnalyticsRequirementResolutionState.MISSING
            )
        summary_index, summary = matches[0]
        if summary.excluded_unknown_count:
            return cls._resolution(
                requirement_index, requirement, AnalyticsRequirementResolutionState.UNKNOWN
            )
        if summary.limit != requirement.requested_rank or not summary.rows:
            return cls._resolution(
                requirement_index, requirement, AnalyticsRequirementResolutionState.MISSING
            )
        return cls._resolution(
            requirement_index,
            requirement,
            AnalyticsRequirementResolutionState.RESOLVED,
            facts=(
                cls._fact(
                    requirement_index,
                    requirement,
                    summary_index,
                    0,
                    summary.rows[0],
                    requirement.locations[0] if len(requirement.locations) == 1 else None,
                ),
            ),
        )

    @classmethod
    def _resolve_comparison(
        cls,
        requirement_index: int,
        requirement: AnalyticsAnswerRequirement,
        summaries: tuple[AnalyticsSummary, ...],
    ) -> AnalyticsRequirementResolution:
        matches = [
            item for item in cls._matching_summaries(requirement, summaries) if item[1].comparison
        ]
        if not matches:
            return cls._resolution(
                requirement_index, requirement, AnalyticsRequirementResolutionState.MISSING
            )
        summary_index, summary = matches[0]
        if summary.excluded_unknown_count:
            return cls._resolution(
                requirement_index, requirement, AnalyticsRequirementResolutionState.UNKNOWN
            )
        if not summary.rows:
            return cls._resolution(
                requirement_index, requirement, AnalyticsRequirementResolutionState.MISSING
            )
        facts = tuple(
            cls._fact(requirement_index, requirement, summary_index, row_index, row)
            for row_index, row in enumerate(summary.rows)
        )
        return cls._resolution(
            requirement_index,
            requirement,
            AnalyticsRequirementResolutionState.RESOLVED,
            facts=facts,
        )

    @classmethod
    def _resolve_scoped_values(
        cls,
        requirement_index: int,
        requirement: AnalyticsAnswerRequirement,
        summaries: tuple[AnalyticsSummary, ...],
    ) -> AnalyticsRequirementResolution:
        scopes = requirement.locations or (None,)
        facts: list[AnalyticsAnswerFact] = []
        missing = False
        unknown = False
        for scope in scopes:
            match = cls._matching_summary_for_scope(requirement, summaries, scope)
            if match is None:
                missing = True
                continue
            summary_index, summary = match
            if summary.excluded_unknown_count:
                unknown = True
                continue
            row_index, row = cls._row_for_scope(summary, scope)
            if row is None:
                missing = True
                continue
            facts.append(
                cls._fact(requirement_index, requirement, summary_index, row_index, row, scope)
            )
        state = (
            AnalyticsRequirementResolutionState.UNKNOWN
            if unknown
            else AnalyticsRequirementResolutionState.MISSING
            if missing
            else AnalyticsRequirementResolutionState.RESOLVED
        )
        return cls._resolution(requirement_index, requirement, state, facts=tuple(facts))

    @classmethod
    def _matching_summary_for_scope(
        cls,
        requirement: AnalyticsAnswerRequirement,
        summaries: tuple[AnalyticsSummary, ...],
        scope: StructuredQueryLocation | None,
    ) -> tuple[int, AnalyticsSummary] | None:
        for summary_index, summary in cls._matching_summaries(requirement, summaries):
            if scope is None or cls._summary_matches_scope(summary, scope):
                return summary_index, summary
        return None

    @staticmethod
    def _matching_summaries(
        requirement: AnalyticsAnswerRequirement,
        summaries: tuple[AnalyticsSummary, ...],
    ) -> list[tuple[int, AnalyticsSummary]]:
        matches: list[tuple[int, AnalyticsSummary]] = []
        for summary_index, summary in enumerate(summaries):
            if (
                summary.metric != requirement.metric
                or summary.aggregation != requirement.aggregation
                or summary.group_by != requirement.group_by
                or summary.ranking_direction != requirement.direction
                or not AnalyticsAnswerFactResolver._time_window_matches(
                    summary, requirement.time_window
                )
            ):
                continue
            matches.append((summary_index, summary))
        return matches

    @staticmethod
    def _summary_matches_scope(
        summary: AnalyticsSummary,
        scope: StructuredQueryLocation,
    ) -> bool:
        for field in ("city", "district", "neighborhood"):
            expected = getattr(scope, field)
            if expected is not None and summary.filters.get(field) != expected:
                return False
        return True

    @staticmethod
    def _time_window_matches(
        summary: AnalyticsSummary,
        time_window: StructuredQueryTimeWindow | None,
    ) -> bool:
        if time_window is None:
            return True
        if time_window.from_time is None or time_window.to_time is None:
            return False
        from_time = summary.filters.get("from_time")
        to_time = summary.filters.get("to_time")
        return str(from_time).replace("+00:00", "Z") == time_window.from_time.isoformat().replace(
            "+00:00", "Z"
        ) and str(to_time).replace("+00:00", "Z") == time_window.to_time.isoformat().replace(
            "+00:00", "Z"
        )

    @staticmethod
    def _row_for_scope(
        summary: AnalyticsSummary,
        scope: StructuredQueryLocation | None,
    ) -> tuple[int, dict[str, Any] | None]:
        if not summary.rows:
            return -1, None
        if scope is None or len(summary.rows) == 1:
            return 0, summary.rows[0]
        for row_index, row in enumerate(summary.rows):
            if row.get("label") in {scope.city, scope.district, scope.neighborhood}:
                return row_index, row
        return -1, None

    @staticmethod
    def _fact(
        requirement_index: int,
        requirement: AnalyticsAnswerRequirement,
        summary_index: int,
        row_index: int,
        row: dict[str, Any],
        scope: StructuredQueryLocation | None = None,
    ) -> AnalyticsAnswerFact:
        value = row.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise ValueError("canonical analytics row value is invalid")
        return AnalyticsAnswerFact(
            requirement_index=requirement_index,
            requirement_kind=requirement.kind,
            metric=requirement.metric or "",
            aggregation=requirement.aggregation or "",
            value=value,
            unit="count" if requirement.aggregation == "count" else requirement.metric or "value",
            group_by=requirement.group_by,
            group_label=str(row.get("label")) if row.get("label") is not None else None,
            scope=scope,
            time_window=requirement.time_window,
            canonical_source_ref=f"analytics_summary[{summary_index}].rows[{row_index}]",
        )

    @staticmethod
    def _resolution(
        requirement_index: int,
        requirement: AnalyticsAnswerRequirement,
        state: AnalyticsRequirementResolutionState,
        *,
        facts: tuple[AnalyticsAnswerFact, ...] = (),
    ) -> AnalyticsRequirementResolution:
        return AnalyticsRequirementResolution(
            requirement_index=requirement_index,
            requirement_kind=requirement.kind,
            state=state,
            facts=facts,
        )
