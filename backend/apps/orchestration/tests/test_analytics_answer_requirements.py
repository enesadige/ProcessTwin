from __future__ import annotations

import pytest

from apps.geography.models import AreaProfileType, City, District
from apps.network.models import NetworkDevice, NetworkDeviceType
from apps.operations.tests.test_operations_models import create_maltepe_bng, create_snapshot
from apps.orchestration.analytics_answer_requirements import (
    AnalyticsAnswerRequirementKind,
    AnalyticsAnswerRequirementPlanner,
)
from apps.orchestration.natural_language_intake import DeterministicStructuredQueryParser


def _analytics_snapshot(slug: str, *cities: tuple[str, str]):
    snapshot = create_snapshot(slug)
    for city_name, plate_code in cities:
        city = City.objects.create(name=city_name, plate_code=plate_code)
        district = District.objects.create(
            city=city,
            name=f"{city_name} Merkez",
            profile_type=AreaProfileType.MIXED,
        )
        NetworkDevice.objects.create(
            data_snapshot=snapshot,
            code=f"AGG-{plate_code}-REQUIREMENTS-001",
            name="Requirements scope device",
            device_type=NetworkDeviceType.METRO_AGGREGATION,
            city=city,
            district=district,
        )
    return snapshot


def _plan(question: str, snapshot):
    query = (
        DeterministicStructuredQueryParser()
        .parse(
            original_query=question,
            snapshot=snapshot,
        )
        .structured_query
    )
    return query, AnalyticsAnswerRequirementPlanner.build(query, original_query=question)


@pytest.mark.django_db
def test_direct_count_requirement_preserves_typed_scope_without_a_value():
    snapshot = _analytics_snapshot("requirements-direct-count", ("İzmir", "35"))
    query, plan = _plan("2026 yılında İzmir şehrinde kaç kesinti yaşandı?", snapshot)

    assert query.analytics is not None
    assert [item.kind for item in plan.requirements] == [
        AnalyticsAnswerRequirementKind.DIRECT_VALUE
    ]
    requirement = plan.requirements[0]
    assert requirement.metric == "outage_count"
    assert requirement.locations[0].city == "İzmir"
    assert requirement.time_window == query.time_window
    assert "13" not in str(plan.model_dump())


@pytest.mark.django_db
def test_alarm_type_ranking_requires_only_the_requested_winner_contract():
    snapshot = _analytics_snapshot("requirements-ranking", ("İzmir", "35"))
    _query, plan = _plan(
        "2026 yılında İzmir şehrinde en çok görülen alarm tipi nedir?",
        snapshot,
    )

    assert [item.kind for item in plan.requirements] == [
        AnalyticsAnswerRequirementKind.RANKING_WINNER
    ]
    requirement = plan.requirements[0]
    assert requirement.metric == "alarm_count"
    assert requirement.group_by == "alarm_type"
    assert requirement.direction == "desc"
    assert requirement.requested_rank == 1
    assert requirement.locations[0].city == "İzmir"
    assert requirement.time_window is not None
    assert not hasattr(requirement, "absence_of_other_groups")


@pytest.mark.django_db
def test_multi_city_total_request_has_typed_scope_requirements_without_total_value():
    snapshot = _analytics_snapshot(
        "requirements-total",
        ("İzmir", "35"),
        ("İstanbul", "34"),
    )
    _query, plan = _plan(
        "2026 yılında İzmir ve İstanbul şehirlerinde toplam kaç alarm oluştu?",
        snapshot,
    )

    assert [item.kind for item in plan.requirements] == [
        AnalyticsAnswerRequirementKind.AGGREGATE_TOTAL_REQUEST,
    ]
    total = plan.requirements[0]
    assert total.metric == "alarm_count"
    assert [item.city for item in total.locations] == ["İstanbul", "İzmir"]
    assert total.time_window is not None
    assert "160" not in str(plan.model_dump())


@pytest.mark.django_db
def test_single_scope_query_does_not_invent_ranking_or_total_requirements():
    snapshot = _analytics_snapshot("requirements-single-scope", ("İzmir", "35"))
    _query, plan = _plan("2026 yılında İzmir şehrinde kaç alarm oluştu?", snapshot)

    assert [item.kind for item in plan.requirements] == [
        AnalyticsAnswerRequirementKind.DIRECT_VALUE
    ]


@pytest.mark.django_db
def test_anchored_non_analytics_query_has_no_analytics_requirements():
    snapshot = create_snapshot("requirements-anchored-non-analytics")
    create_maltepe_bng(snapshot, code="AGG-ANK-002")
    question = "AGG-ANK-002 cihazındaki kesintinin kök nedeni nedir?"

    _query, plan = _plan(question, snapshot)

    assert plan.requirements == ()


@pytest.mark.django_db
def test_comparison_requirement_uses_existing_typed_comparison_semantics():
    snapshot = _analytics_snapshot("requirements-comparison", ("İzmir", "35"))
    _query, plan = _plan(
        "Haziran 2026 ile Temmuz 2026 kesinti sayılarını karşılaştır.",
        snapshot,
    )

    assert [item.kind for item in plan.requirements] == [AnalyticsAnswerRequirementKind.COMPARISON]
    requirement = plan.requirements[0]
    assert requirement.metric == "outage_count"
    assert requirement.group_by == "time_bucket"
    assert requirement.time_window is not None


@pytest.mark.django_db
def test_multiple_explicit_analytics_metrics_get_a_multi_metric_requirement():
    snapshot = _analytics_snapshot("requirements-multi-metric", ("İzmir", "35"))
    _query, plan = _plan(
        "2026 yılında İzmir şehrinde kaç alarm ve kaç kesinti yaşandı?",
        snapshot,
    )

    assert plan.requirements[-1].kind == AnalyticsAnswerRequirementKind.MULTI_METRIC
    assert plan.requirements[-1].metrics == ("outage_count", "alarm_count")
