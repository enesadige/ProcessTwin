"""Derive only semantically safe analytics facts from typed canonical bindings."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from apps.orchestration.analytics_answer_facts import (
    AnalyticsAnswerFact,
    AnalyticsAnswerFactSet,
    AnalyticsRequirementResolutionState,
)
from apps.orchestration.analytics_answer_requirements import (
    AnalyticsAnswerRequirement,
    AnalyticsAnswerRequirementKind,
    AnalyticsAnswerRequirements,
)
from apps.orchestration.structured_query import StructuredQueryLocation, StructuredQueryTimeWindow


class AnalyticsDerivedFactKind(StrEnum):
    AGGREGATE_TOTAL = "aggregate_total"


class AnalyticsDerivationState(StrEnum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    NOT_APPLICABLE = "not_applicable"


class AnalyticsDerivedFact(BaseModel):
    """A deterministic fact with explicit canonical support references."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: AnalyticsDerivedFactKind
    originating_requirement_index: int = Field(ge=0)
    originating_requirement_kind: AnalyticsAnswerRequirementKind
    metric: str
    aggregation: str
    value: int | float
    unit: str
    locations: tuple[StructuredQueryLocation, ...]
    time_window: StructuredQueryTimeWindow | None = None
    supporting_canonical_refs: tuple[str, ...]
    derivation_method: str


class AnalyticsDerivationResolution(BaseModel):
    """Known unresolved states are preserved instead of being zero-filled."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    originating_requirement_index: int = Field(ge=0)
    originating_requirement_kind: AnalyticsAnswerRequirementKind
    state: AnalyticsDerivationState
    facts: tuple[AnalyticsDerivedFact, ...] = ()


class AnalyticsDerivedFactSet(BaseModel):
    """Derived facts for later response stages; this module renders no prose."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    facts: tuple[AnalyticsDerivedFact, ...] = ()
    resolutions: tuple[AnalyticsDerivationResolution, ...] = ()


class AnalyticsDerivedFactResolver:
    """Derive only facts whose arithmetic and scope semantics are explicit."""

    @classmethod
    def resolve(
        cls,
        requirements: AnalyticsAnswerRequirements,
        canonical_facts: AnalyticsAnswerFactSet,
    ) -> AnalyticsDerivedFactSet:
        facts: list[AnalyticsDerivedFact] = []
        resolutions: list[AnalyticsDerivationResolution] = []
        for requirement_index, requirement in enumerate(requirements.requirements):
            resolution = cls._resolve_requirement(
                requirement_index,
                requirement,
                canonical_facts,
            )
            facts.extend(resolution.facts)
            resolutions.append(resolution)
        return AnalyticsDerivedFactSet(facts=tuple(facts), resolutions=tuple(resolutions))

    @classmethod
    def _resolve_requirement(
        cls,
        requirement_index: int,
        requirement: AnalyticsAnswerRequirement,
        canonical_facts: AnalyticsAnswerFactSet,
    ) -> AnalyticsDerivationResolution:
        if requirement.kind != AnalyticsAnswerRequirementKind.AGGREGATE_TOTAL_REQUEST:
            return cls._resolution(
                requirement_index,
                requirement,
                AnalyticsDerivationState.NOT_APPLICABLE,
            )
        return cls._resolve_city_total(requirement_index, requirement, canonical_facts)

    @classmethod
    def _resolve_city_total(
        cls,
        requirement_index: int,
        requirement: AnalyticsAnswerRequirement,
        canonical_facts: AnalyticsAnswerFactSet,
    ) -> AnalyticsDerivationResolution:
        resolution = next(
            (
                item
                for item in canonical_facts.resolutions
                if item.requirement_index == requirement_index
            ),
            None,
        )
        if resolution is None or resolution.state != AnalyticsRequirementResolutionState.RESOLVED:
            return cls._resolution(
                requirement_index,
                requirement,
                AnalyticsDerivationState.UNRESOLVED,
            )

        facts = tuple(
            item
            for item in resolution.facts
            if item.requirement_index == requirement_index
            and item.requirement_kind == AnalyticsAnswerRequirementKind.AGGREGATE_TOTAL_REQUEST
        )
        if not cls._safe_distinct_city_total(requirement, facts):
            return cls._resolution(
                requirement_index,
                requirement,
                AnalyticsDerivationState.UNRESOLVED,
            )

        total = sum(item.value for item in facts)
        derived_fact = AnalyticsDerivedFact(
            kind=AnalyticsDerivedFactKind.AGGREGATE_TOTAL,
            originating_requirement_index=requirement_index,
            originating_requirement_kind=requirement.kind,
            metric=requirement.metric or "",
            aggregation=requirement.aggregation or "",
            value=total,
            unit="count",
            locations=requirement.locations,
            time_window=requirement.time_window,
            supporting_canonical_refs=tuple(item.canonical_source_ref for item in facts),
            derivation_method="sum_distinct_city_constituents",
        )
        return cls._resolution(
            requirement_index,
            requirement,
            AnalyticsDerivationState.RESOLVED,
            facts=(derived_fact,),
        )

    @staticmethod
    def _safe_distinct_city_total(
        requirement: AnalyticsAnswerRequirement,
        facts: tuple[AnalyticsAnswerFact, ...],
    ) -> bool:
        if requirement.aggregation != "count" or len(requirement.locations) < 2:
            return False
        expected_cities = tuple(location.city for location in requirement.locations)
        if (
            any(
                city is None or location.district is not None or location.neighborhood is not None
                for city, location in zip(expected_cities, requirement.locations, strict=True)
            )
            or len(set(expected_cities)) != len(expected_cities)
            or len(facts) != len(requirement.locations)
        ):
            return False

        actual_cities = tuple(item.scope.city if item.scope is not None else None for item in facts)
        if set(actual_cities) != set(expected_cities) or len(set(actual_cities)) != len(
            actual_cities
        ):
            return False
        if any(
            item.metric != requirement.metric
            or item.aggregation != requirement.aggregation
            or item.unit != "count"
            or item.time_window != requirement.time_window
            or isinstance(item.value, bool)
            or not isinstance(item.value, (int, float))
            for item in facts
        ):
            return False
        return len({item.canonical_source_ref for item in facts}) == len(facts)

    @staticmethod
    def _resolution(
        requirement_index: int,
        requirement: AnalyticsAnswerRequirement,
        state: AnalyticsDerivationState,
        *,
        facts: tuple[AnalyticsDerivedFact, ...] = (),
    ) -> AnalyticsDerivationResolution:
        return AnalyticsDerivationResolution(
            originating_requirement_index=requirement_index,
            originating_requirement_kind=requirement.kind,
            state=state,
            facts=facts,
        )
