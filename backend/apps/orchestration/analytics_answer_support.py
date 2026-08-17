"""Render typed requested analytics facts as closed-world provider support."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from apps.orchestration.analytics_answer_derivations import (
    AnalyticsDerivedFact,
    AnalyticsDerivedFactResolver,
    AnalyticsDerivedFactSet,
)
from apps.orchestration.analytics_answer_facts import (
    AnalyticsAnswerFact,
    AnalyticsAnswerFactResolver,
    AnalyticsAnswerFactSet,
)
from apps.orchestration.analytics_answer_requirements import (
    AnalyticsAnswerRequirementKind,
    AnalyticsAnswerRequirementPlanner,
    AnalyticsAnswerRequirements,
)
from apps.orchestration.result_merge import AnalyticsSummary
from apps.orchestration.structured_query import StructuredQuery


class AnalyticsAnswerSupportKind(StrEnum):
    CANONICAL = "canonical"
    DERIVED = "derived"


class AnalyticsAnswerSupportStatement(BaseModel):
    """One provider-visible statement with its typed source identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    support_id: str
    kind: AnalyticsAnswerSupportKind
    requirement_index: int = Field(ge=0)
    requirement_kind: AnalyticsAnswerRequirementKind
    text: str
    canonical_source_refs: tuple[str, ...]


class AnalyticsAnswerSupport(BaseModel):
    """Closed-world analytics support constructed before narrative synthesis."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requirements: AnalyticsAnswerRequirements
    canonical_facts: AnalyticsAnswerFactSet
    derived_facts: AnalyticsDerivedFactSet
    statements: tuple[AnalyticsAnswerSupportStatement, ...] = ()


class AnalyticsAnswerSupportBuilder:
    """Bridge typed requirements/facts into provider support without prose synthesis."""

    @classmethod
    def build(
        cls,
        *,
        original_query: str,
        structured_query: Mapping[str, Any] | None,
        summaries: Iterable[AnalyticsSummary],
    ) -> AnalyticsAnswerSupport:
        if not isinstance(structured_query, Mapping):
            return cls._empty_support()
        try:
            query = StructuredQuery.model_validate(structured_query)
        except ValidationError:
            # Legacy/unit-test callers may supply an intentionally partial mapping.
            # A valid persisted StructuredQuery is required before typed support exists.
            return cls._empty_support()
        requirements = AnalyticsAnswerRequirementPlanner.build(
            query,
            original_query=original_query,
        )
        canonical_facts = AnalyticsAnswerFactResolver.resolve(requirements, summaries)
        derived_facts = AnalyticsDerivedFactResolver.resolve(requirements, canonical_facts)
        statements = (
            *(cls._canonical_statement(fact) for fact in canonical_facts.facts),
            *(cls._derived_statement(fact) for fact in derived_facts.facts),
        )
        return AnalyticsAnswerSupport(
            requirements=requirements,
            canonical_facts=canonical_facts,
            derived_facts=derived_facts,
            statements=tuple(statements),
        )

    @staticmethod
    def _empty_support() -> AnalyticsAnswerSupport:
        requirements = AnalyticsAnswerRequirements()
        return AnalyticsAnswerSupport(
            requirements=requirements,
            canonical_facts=AnalyticsAnswerFactSet(),
            derived_facts=AnalyticsDerivedFactSet(),
        )

    @classmethod
    def _canonical_statement(cls, fact: AnalyticsAnswerFact) -> AnalyticsAnswerSupportStatement:
        scope = cls._scope_prefix(fact.time_window, fact.scope)
        metric = cls._metric_label(fact.metric)
        if fact.requirement_kind == AnalyticsAnswerRequirementKind.RANKING_WINNER:
            text = (
                f"{scope}en yüksek {cls._group_label(fact.group_by)}: "
                f"{fact.group_label} ({fact.value} {metric})."
            )
        else:
            text = f"{scope}{fact.value} {metric}."
        return AnalyticsAnswerSupportStatement(
            support_id=f"canonical:{fact.requirement_index}:{fact.canonical_source_ref}",
            kind=AnalyticsAnswerSupportKind.CANONICAL,
            requirement_index=fact.requirement_index,
            requirement_kind=fact.requirement_kind,
            text=text,
            canonical_source_refs=(fact.canonical_source_ref,),
        )

    @classmethod
    def _derived_statement(cls, fact: AnalyticsDerivedFact) -> AnalyticsAnswerSupportStatement:
        scope = cls._scope_prefix(fact.time_window, None, fact.locations)
        text = f"{scope}toplam {cls._metric_label(fact.metric)}: {fact.value}."
        return AnalyticsAnswerSupportStatement(
            support_id=(f"derived:{fact.originating_requirement_index}:{fact.derivation_method}"),
            kind=AnalyticsAnswerSupportKind.DERIVED,
            requirement_index=fact.originating_requirement_index,
            requirement_kind=fact.originating_requirement_kind,
            text=text,
            canonical_source_refs=fact.supporting_canonical_refs,
        )

    @staticmethod
    def _scope_prefix(time_window, scope=None, locations=()) -> str:
        parts: list[str] = []
        if (
            time_window is not None
            and time_window.from_time is not None
            and time_window.to_time is not None
            and time_window.from_time.month == 1
            and time_window.from_time.day == 1
            and time_window.to_time.month == 12
            and time_window.to_time.day == 31
            and time_window.from_time.year == time_window.to_time.year
        ):
            parts.append(f"{time_window.from_time.year} yılında")
        if scope is not None:
            location = scope.neighborhood or scope.district or scope.city
            if location:
                parts.append(f"{location}'de")
        elif locations:
            location_labels = [
                location.neighborhood or location.district or location.city
                for location in locations
            ]
            if all(location_labels):
                parts.append(" ve ".join(location_labels))
        return (" ".join(parts) + " ") if parts else ""

    @staticmethod
    def _metric_label(metric: str) -> str:
        return {
            "outage_count": "kesinti",
            "event_count": "olay",
            "alarm_count": "alarm",
            "full_outage_count": "tam hizmet kesintisi",
            "failed_failover_count": "başarısız failover olayı",
            "affected_customers": "doğrulanmış müşteri etkisi",
            "affected_subscriptions": "doğrulanmış abonelik etkisi",
            "potential_subscriptions": "potansiyel abonelik kapsamı",
            "compensation_amount": "toplam tazminat",
        }.get(metric, metric)

    @staticmethod
    def _group_label(group_by: str | None) -> str:
        return {
            "alarm_type": "alarm tipi",
            "root_alarm_type": "kök alarm tipi",
        }.get(group_by or "", group_by or "grup")
