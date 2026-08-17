from __future__ import annotations

from apps.orchestration.analytics_answer_derivations import (
    AnalyticsDerivationState,
    AnalyticsDerivedFactKind,
    AnalyticsDerivedFactResolver,
)
from apps.orchestration.analytics_answer_facts import (
    AnalyticsAnswerFact,
    AnalyticsAnswerFactKind,
    AnalyticsAnswerFactSet,
    AnalyticsRequirementResolution,
    AnalyticsRequirementResolutionState,
)
from apps.orchestration.analytics_answer_requirements import (
    AnalyticsAnswerRequirement,
    AnalyticsAnswerRequirementKind,
    AnalyticsAnswerRequirements,
)
from apps.orchestration.structured_query import StructuredQueryLocation, StructuredQueryTimeWindow


def _window(year: int = 2026) -> StructuredQueryTimeWindow:
    return StructuredQueryTimeWindow.model_validate(
        {
            "from_time": f"{year}-01-01T00:00:00Z",
            "to_time": f"{year}-12-31T23:59:59Z",
        }
    )


def _total_requirement(locations):
    return AnalyticsAnswerRequirement(
        kind=AnalyticsAnswerRequirementKind.AGGREGATE_TOTAL_REQUEST,
        metric="alarm_count",
        aggregation="count",
        group_by="city",
        direction="desc",
        locations=locations,
        time_window=_window(),
    )


def _fact(
    city: str,
    value: int | float,
    *,
    metric: str = "alarm_count",
    aggregation: str = "count",
    time_window: StructuredQueryTimeWindow | None = None,
    source_ref: str | None = None,
):
    return AnalyticsAnswerFact(
        kind=AnalyticsAnswerFactKind.CANONICAL_VALUE,
        requirement_index=0,
        requirement_kind=AnalyticsAnswerRequirementKind.AGGREGATE_TOTAL_REQUEST,
        metric=metric,
        aggregation=aggregation,
        value=value,
        unit="count" if aggregation == "count" else metric,
        group_by="city",
        group_label=city,
        scope=StructuredQueryLocation(city=city),
        time_window=time_window or _window(),
        canonical_source_ref=source_ref or f"summary.{city}",
    )


def _fact_set(facts=(), state=AnalyticsRequirementResolutionState.RESOLVED):
    facts = tuple(facts)
    return AnalyticsAnswerFactSet(
        facts=facts,
        resolutions=(
            AnalyticsRequirementResolution(
                requirement_index=0,
                requirement_kind=AnalyticsAnswerRequirementKind.AGGREGATE_TOTAL_REQUEST,
                state=state,
                facts=facts,
            ),
        ),
    )


def _derive(requirement, facts):
    return AnalyticsDerivedFactResolver.resolve(
        AnalyticsAnswerRequirements(requirements=(requirement,)),
        facts,
    )


def test_safe_distinct_city_total_is_derived_from_exact_canonical_constituents():
    istanbul = StructuredQueryLocation(city="İstanbul")
    izmir = StructuredQueryLocation(city="İzmir")
    result = _derive(
        _total_requirement((istanbul, izmir)),
        _fact_set((_fact("İstanbul", 72), _fact("İzmir", 88))),
    )

    assert [item.value for item in result.facts] == [160]
    derived = result.facts[0]
    assert derived.kind == AnalyticsDerivedFactKind.AGGREGATE_TOTAL
    assert derived.supporting_canonical_refs == ("summary.İstanbul", "summary.İzmir")
    assert derived.derivation_method == "sum_distinct_city_constituents"
    assert result.resolutions[0].state == AnalyticsDerivationState.RESOLVED


def test_unknown_constituent_blocks_total_without_zero_filling():
    istanbul = StructuredQueryLocation(city="İstanbul")
    izmir = StructuredQueryLocation(city="İzmir")
    result = _derive(
        _total_requirement((istanbul, izmir)),
        _fact_set((_fact("İstanbul", 72),), AnalyticsRequirementResolutionState.UNKNOWN),
    )

    assert result.facts == ()
    assert result.resolutions[0].state == AnalyticsDerivationState.UNRESOLVED


def test_missing_constituent_blocks_total():
    istanbul = StructuredQueryLocation(city="İstanbul")
    izmir = StructuredQueryLocation(city="İzmir")
    result = _derive(
        _total_requirement((istanbul, izmir)),
        _fact_set((_fact("İstanbul", 72),), AnalyticsRequirementResolutionState.MISSING),
    )

    assert result.facts == ()
    assert result.resolutions[0].state == AnalyticsDerivationState.UNRESOLVED


def test_extra_unrequested_fact_is_not_included_in_total():
    istanbul = StructuredQueryLocation(city="İstanbul")
    izmir = StructuredQueryLocation(city="İzmir")
    requested_facts = (_fact("İstanbul", 72), _fact("İzmir", 88))
    extra_fact = _fact("Ankara", 99)
    result = _derive(
        _total_requirement((istanbul, izmir)),
        AnalyticsAnswerFactSet(
            facts=(*requested_facts, extra_fact),
            resolutions=(
                AnalyticsRequirementResolution(
                    requirement_index=0,
                    requirement_kind=AnalyticsAnswerRequirementKind.AGGREGATE_TOTAL_REQUEST,
                    state=AnalyticsRequirementResolutionState.RESOLVED,
                    facts=requested_facts,
                ),
            ),
        ),
    )

    assert [item.value for item in result.facts] == [160]
    assert "summary.Ankara" not in result.facts[0].supporting_canonical_refs


def test_mixed_time_windows_block_total():
    istanbul = StructuredQueryLocation(city="İstanbul")
    izmir = StructuredQueryLocation(city="İzmir")
    result = _derive(
        _total_requirement((istanbul, izmir)),
        _fact_set((_fact("İstanbul", 72), _fact("İzmir", 88, time_window=_window(2025)))),
    )

    assert result.facts == ()


def test_mixed_metric_blocks_total():
    istanbul = StructuredQueryLocation(city="İstanbul")
    izmir = StructuredQueryLocation(city="İzmir")
    result = _derive(
        _total_requirement((istanbul, izmir)),
        _fact_set((_fact("İstanbul", 72), _fact("İzmir", 13, metric="outage_count"))),
    )

    assert result.facts == ()


def test_unproven_overlapping_city_and_district_scopes_block_total():
    istanbul = StructuredQueryLocation(city="İstanbul")
    kadikoy = StructuredQueryLocation(city="İstanbul", district="Kadıköy")
    result = _derive(
        _total_requirement((istanbul, kadikoy)),
        _fact_set((_fact("İstanbul", 72), _fact("İstanbul", 20, source_ref="summary.kadikoy"))),
    )

    assert result.facts == ()


def test_duplicate_city_scope_blocks_total_without_double_counting():
    izmir = StructuredQueryLocation(city="İzmir")
    result = _derive(
        _total_requirement((izmir, izmir)),
        _fact_set((_fact("İzmir", 88), _fact("İzmir", 88, source_ref="summary.İzmir.duplicate"))),
    )

    assert result.facts == ()


def test_comparison_has_no_derivation_until_dimensions_are_typed():
    requirement = AnalyticsAnswerRequirement(
        kind=AnalyticsAnswerRequirementKind.COMPARISON,
        metric="outage_count",
        aggregation="count",
        group_by="time_bucket",
        direction="desc",
        time_window=_window(),
    )
    fact_set = AnalyticsAnswerFactSet()

    result = _derive(requirement, fact_set)

    assert result.facts == ()
    assert result.resolutions[0].state == AnalyticsDerivationState.NOT_APPLICABLE


def test_comparison_unknown_value_has_no_derived_result():
    requirement = AnalyticsAnswerRequirement(
        kind=AnalyticsAnswerRequirementKind.COMPARISON,
        metric="outage_count",
        aggregation="count",
        group_by="time_bucket",
        direction="desc",
        time_window=_window(),
    )
    fact_set = AnalyticsAnswerFactSet(
        resolutions=(
            AnalyticsRequirementResolution(
                requirement_index=0,
                requirement_kind=AnalyticsAnswerRequirementKind.COMPARISON,
                state=AnalyticsRequirementResolutionState.UNKNOWN,
            ),
        )
    )

    result = _derive(requirement, fact_set)

    assert result.facts == ()
    assert result.resolutions[0].state == AnalyticsDerivationState.NOT_APPLICABLE


def test_ranking_is_not_recomputed_or_interpreted():
    requirement = AnalyticsAnswerRequirement(
        kind=AnalyticsAnswerRequirementKind.RANKING_WINNER,
        metric="alarm_count",
        aggregation="count",
        group_by="alarm_type",
        direction="desc",
        requested_rank=1,
        locations=(StructuredQueryLocation(city="İzmir"),),
        time_window=_window(),
    )

    result = _derive(requirement, AnalyticsAnswerFactSet())

    assert result.facts == ()
    assert result.resolutions[0].state == AnalyticsDerivationState.NOT_APPLICABLE


def test_multi_metric_facts_are_not_combined():
    requirement = AnalyticsAnswerRequirement(
        kind=AnalyticsAnswerRequirementKind.MULTI_METRIC,
        metrics=("alarm_count", "outage_count"),
        locations=(StructuredQueryLocation(city="İzmir"),),
        time_window=_window(),
    )

    result = _derive(requirement, AnalyticsAnswerFactSet())

    assert result.facts == ()
    assert result.resolutions[0].state == AnalyticsDerivationState.NOT_APPLICABLE
