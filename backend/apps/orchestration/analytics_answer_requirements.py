"""Typed, query-driven analytics answer requirements.

This module describes what an analytics answer must cover. It deliberately
does not inspect canonical result rows, produce values, or render prose.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from apps.orchestration.structured_query import (
    AnalyticsSpecification,
    StructuredQuery,
    StructuredQueryLocation,
    StructuredQueryTimeWindow,
)


class AnalyticsAnswerRequirementKind(StrEnum):
    DIRECT_VALUE = "direct_value"
    RANKING_WINNER = "ranking_winner"
    AGGREGATE_TOTAL_REQUEST = "aggregate_total_request"
    COMPARISON = "comparison"
    MULTI_METRIC = "multi_metric"


class AnalyticsAnswerRequirement(BaseModel):
    """A value-free answer obligation derived from deterministic query intent."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: AnalyticsAnswerRequirementKind
    metric: str | None = None
    metrics: tuple[str, ...] = ()
    aggregation: str | None = None
    group_by: str | None = None
    direction: str | None = None
    requested_rank: int | None = Field(default=None, ge=1)
    locations: tuple[StructuredQueryLocation, ...] = ()
    time_window: StructuredQueryTimeWindow | None = None


class AnalyticsAnswerRequirements(BaseModel):
    """Internal plan for requested analytics coverage; never a response payload."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requirements: tuple[AnalyticsAnswerRequirement, ...] = ()


class AnalyticsAnswerRequirementPlanner:
    """Derive answer obligations from structured analytics intent, not result rows."""

    @classmethod
    def build(
        cls,
        structured_query: StructuredQuery,
        *,
        original_query: str,
    ) -> AnalyticsAnswerRequirements:
        if structured_query.intent.value != "operational_analytics":
            return AnalyticsAnswerRequirements()

        specifications = cls._specifications(structured_query)
        if not specifications:
            return AnalyticsAnswerRequirements()

        locations = tuple(structured_query.analytics_locations)
        requirements: list[AnalyticsAnswerRequirement] = []
        for specification in specifications:
            requirements.extend(
                cls._requirements_for_specification(
                    specification,
                    locations=locations,
                    time_window=structured_query.time_window,
                )
            )

        if cls._aggregate_total_requested(original_query) and len(locations) > 1:
            for specification in specifications:
                requirements.append(
                    cls._requirement(
                        AnalyticsAnswerRequirementKind.AGGREGATE_TOTAL_REQUEST,
                        specification,
                        locations=locations,
                        time_window=structured_query.time_window,
                    )
                )

        metrics = tuple(dict.fromkeys(specification.metric for specification in specifications))
        if len(metrics) > 1:
            requirements.append(
                AnalyticsAnswerRequirement(
                    kind=AnalyticsAnswerRequirementKind.MULTI_METRIC,
                    metrics=metrics,
                    locations=locations,
                    time_window=structured_query.time_window,
                )
            )
        return AnalyticsAnswerRequirements(requirements=tuple(requirements))

    @staticmethod
    def _specifications(structured_query: StructuredQuery) -> tuple[AnalyticsSpecification, ...]:
        if structured_query.analytics_specs:
            return tuple(structured_query.analytics_specs)
        if structured_query.analytics is not None:
            return (structured_query.analytics,)
        return ()

    @classmethod
    def _requirements_for_specification(
        cls,
        specification: AnalyticsSpecification,
        *,
        locations: tuple[StructuredQueryLocation, ...],
        time_window: StructuredQueryTimeWindow | None,
    ) -> list[AnalyticsAnswerRequirement]:
        if specification.comparison:
            return [
                cls._requirement(
                    AnalyticsAnswerRequirementKind.COMPARISON,
                    specification,
                    locations=locations,
                    time_window=time_window,
                )
            ]
        if specification.group_by is not None and specification.limit == 1:
            return [
                cls._requirement(
                    AnalyticsAnswerRequirementKind.RANKING_WINNER,
                    specification,
                    locations=locations,
                    time_window=time_window,
                )
            ]
        return [
            cls._requirement(
                AnalyticsAnswerRequirementKind.DIRECT_VALUE,
                specification,
                locations=locations,
                time_window=time_window,
            )
        ]

    @staticmethod
    def _requirement(
        kind: AnalyticsAnswerRequirementKind,
        specification: AnalyticsSpecification,
        *,
        locations: tuple[StructuredQueryLocation, ...],
        time_window: StructuredQueryTimeWindow | None,
    ) -> AnalyticsAnswerRequirement:
        return AnalyticsAnswerRequirement(
            kind=kind,
            metric=specification.metric,
            aggregation=specification.aggregation,
            group_by=specification.group_by,
            direction=specification.direction,
            requested_rank=specification.limit,
            locations=locations,
            time_window=time_window,
        )

    @staticmethod
    def _aggregate_total_requested(original_query: str) -> bool:
        """Use the existing deterministic Turkish total-intent signal without storing prose."""
        return "toplam" in original_query.casefold()
