from __future__ import annotations

from apps.orchestration.analytics_answer_facts import (
    AnalyticsAnswerFactResolver,
    AnalyticsRequirementResolutionState,
)
from apps.orchestration.analytics_answer_requirements import (
    AnalyticsAnswerRequirement,
    AnalyticsAnswerRequirementKind,
    AnalyticsAnswerRequirements,
)
from apps.orchestration.result_merge import AnalyticsSummary
from apps.orchestration.structured_query import StructuredQueryLocation, StructuredQueryTimeWindow


def _window() -> StructuredQueryTimeWindow:
    return StructuredQueryTimeWindow.model_validate(
        {
            "from_time": "2026-01-01T00:00:00Z",
            "to_time": "2026-12-31T23:59:59Z",
        }
    )


def _requirement(kind, *, metric="alarm_count", group_by=None, locations=(), comparison=False):
    return AnalyticsAnswerRequirement(
        kind=kind,
        metric=metric,
        aggregation="count",
        group_by=group_by,
        direction="desc",
        requested_rank=1 if kind == AnalyticsAnswerRequirementKind.RANKING_WINNER else None,
        locations=locations,
        time_window=_window(),
    )


def _summary(
    *,
    metric="alarm_count",
    group_by=None,
    filters=None,
    rows=None,
    comparison=False,
    limit=None,
    excluded_unknown_count=0,
):
    return AnalyticsSummary(
        metric=metric,
        aggregation="count",
        group_by=group_by,
        ranking_direction="desc",
        limit=limit,
        comparison=comparison,
        filters={
            "from_time": "2026-01-01T00:00:00Z",
            "to_time": "2026-12-31T23:59:59Z",
            **(filters or {}),
        },
        rows=rows or [],
        included_event_count=1,
        excluded_unknown_count=excluded_unknown_count,
        deduplication_grain="causal_event",
    )


def _resolve(requirements, summaries):
    return AnalyticsAnswerFactResolver.resolve(
        AnalyticsAnswerRequirements(requirements=tuple(requirements)),
        summaries,
    )


def test_direct_value_binds_only_the_requested_scope_row():
    izmir = StructuredQueryLocation(city="İzmir")
    result = _resolve(
        [
            _requirement(
                AnalyticsAnswerRequirementKind.DIRECT_VALUE,
                metric="outage_count",
                locations=(izmir,),
            )
        ],
        [
            _summary(
                metric="outage_count",
                filters={"city": "İzmir"},
                rows=[{"label": "Toplam", "value": 13, "event_count": 13}],
            ),
            _summary(
                metric="outage_count",
                filters={"city": "Ankara"},
                rows=[{"label": "Toplam", "value": 99, "event_count": 99}],
            ),
        ],
    )

    assert [fact.value for fact in result.facts] == [13]
    assert result.facts[0].scope == izmir
    assert result.facts[0].canonical_source_ref == "analytics_summary[0].rows[0]"
    assert result.resolutions[0].state == AnalyticsRequirementResolutionState.RESOLVED


def test_ranking_binds_the_existing_top_row_without_interpretation():
    requirement = _requirement(
        AnalyticsAnswerRequirementKind.RANKING_WINNER,
        group_by="alarm_type",
        locations=(StructuredQueryLocation(city="İzmir"),),
    )
    result = _resolve(
        [requirement],
        [
            _summary(
                group_by="alarm_type",
                filters={"city": "İzmir"},
                limit=1,
                rows=[
                    {"label": "FAILOVER_UNSUCCESSFUL", "value": 17, "event_count": 17},
                    {"label": "UPLINK_DOWN", "value": 12, "event_count": 12},
                ],
            )
        ],
    )

    assert [(fact.group_label, fact.value) for fact in result.facts] == [
        ("FAILOVER_UNSUCCESSFUL", 17)
    ]
    assert result.facts[0].scope is not None
    assert result.facts[0].scope.city == "İzmir"
    assert not hasattr(result.facts[0], "failover_status")
    assert not hasattr(result.facts[0], "causal_interpretation")


def test_requested_total_binds_constituents_without_computing_a_total():
    izmir = StructuredQueryLocation(city="İzmir")
    istanbul = StructuredQueryLocation(city="İstanbul")
    result = _resolve(
        [
            _requirement(
                AnalyticsAnswerRequirementKind.AGGREGATE_TOTAL_REQUEST, locations=(izmir, istanbul)
            )
        ],
        [
            _summary(
                filters={"city": "İzmir"},
                rows=[{"label": "Toplam", "value": 88, "event_count": 88}],
            ),
            _summary(
                filters={"city": "İstanbul"},
                rows=[{"label": "Toplam", "value": 72, "event_count": 72}],
            ),
        ],
    )

    assert [fact.value for fact in result.facts] == [88, 72]
    assert 160 not in [fact.value for fact in result.facts]
    assert result.resolutions[0].state == AnalyticsRequirementResolutionState.RESOLVED


def test_missing_total_constituent_is_not_zero_filled():
    izmir = StructuredQueryLocation(city="İzmir")
    istanbul = StructuredQueryLocation(city="İstanbul")
    result = _resolve(
        [
            _requirement(
                AnalyticsAnswerRequirementKind.AGGREGATE_TOTAL_REQUEST, locations=(izmir, istanbul)
            )
        ],
        [
            _summary(
                filters={"city": "İstanbul"},
                rows=[{"label": "Toplam", "value": 72, "event_count": 72}],
            )
        ],
    )

    assert [fact.value for fact in result.facts] == [72]
    assert result.resolutions[0].state == AnalyticsRequirementResolutionState.MISSING
    assert 0 not in [fact.value for fact in result.facts]


def test_unknown_canonical_scope_does_not_emit_a_zero_fact():
    izmir = StructuredQueryLocation(city="İzmir")
    result = _resolve(
        [_requirement(AnalyticsAnswerRequirementKind.DIRECT_VALUE, locations=(izmir,))],
        [
            _summary(
                filters={"city": "İzmir"},
                rows=[{"label": "Toplam", "value": 0, "event_count": 0}],
                excluded_unknown_count=1,
            )
        ],
    )

    assert result.facts == ()
    assert result.resolutions[0].state == AnalyticsRequirementResolutionState.UNKNOWN


def test_extra_canonical_scope_is_excluded_from_requested_fact_set():
    izmir = StructuredQueryLocation(city="İzmir")
    istanbul = StructuredQueryLocation(city="İstanbul")
    result = _resolve(
        [
            _requirement(
                AnalyticsAnswerRequirementKind.AGGREGATE_TOTAL_REQUEST, locations=(izmir, istanbul)
            )
        ],
        [
            _summary(
                filters={"city": "İzmir"},
                rows=[{"label": "Toplam", "value": 88, "event_count": 88}],
            ),
            _summary(
                filters={"city": "İstanbul"},
                rows=[{"label": "Toplam", "value": 72, "event_count": 72}],
            ),
            _summary(
                filters={"city": "Ankara"},
                rows=[{"label": "Toplam", "value": 99, "event_count": 99}],
            ),
        ],
    )

    assert [fact.value for fact in result.facts] == [88, 72]
    assert all(fact.scope is None or fact.scope.city != "Ankara" for fact in result.facts)


def test_non_analytics_requirements_resolve_to_an_empty_fact_set():
    result = _resolve([], [_summary(rows=[{"label": "Toplam", "value": 13, "event_count": 13}])])

    assert result.facts == ()
    assert result.resolutions == ()


def test_multi_metric_binds_only_the_explicit_metric_requirements():
    izmir = StructuredQueryLocation(city="İzmir")
    result = _resolve(
        [
            _requirement(
                AnalyticsAnswerRequirementKind.DIRECT_VALUE,
                metric="alarm_count",
                locations=(izmir,),
            ),
            _requirement(
                AnalyticsAnswerRequirementKind.DIRECT_VALUE,
                metric="outage_count",
                locations=(izmir,),
            ),
            AnalyticsAnswerRequirement(
                kind=AnalyticsAnswerRequirementKind.MULTI_METRIC,
                metrics=("alarm_count", "outage_count"),
                locations=(izmir,),
                time_window=_window(),
            ),
        ],
        [
            _summary(
                filters={"city": "İzmir"},
                rows=[{"label": "Toplam", "value": 88, "event_count": 88}],
            ),
            _summary(
                metric="outage_count",
                filters={"city": "İzmir"},
                rows=[{"label": "Toplam", "value": 13, "event_count": 13}],
            ),
            _summary(
                metric="event_count",
                filters={"city": "İzmir"},
                rows=[{"label": "Toplam", "value": 101, "event_count": 101}],
            ),
        ],
    )

    assert [(fact.metric, fact.value) for fact in result.facts] == [
        ("alarm_count", 88),
        ("outage_count", 13),
    ]
    assert result.resolutions[-1].state == AnalyticsRequirementResolutionState.NOT_APPLICABLE


def test_comparison_binds_canonical_period_values_without_delta_or_winner():
    requirement = _requirement(AnalyticsAnswerRequirementKind.COMPARISON, metric="outage_count")
    result = _resolve(
        [requirement],
        [
            _summary(
                metric="outage_count",
                group_by=None,
                comparison=True,
                rows=[
                    {"label": "2026-06", "value": 13, "event_count": 13},
                    {"label": "2026-07", "value": 11, "event_count": 11},
                ],
            )
        ],
    )

    assert [fact.value for fact in result.facts] == [13, 11]
    assert not hasattr(result.facts[0], "delta")
    assert not hasattr(result.facts[0], "winner")
