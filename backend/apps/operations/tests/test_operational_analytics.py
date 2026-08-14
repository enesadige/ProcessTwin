from datetime import UTC, datetime, timedelta

import pytest
from django.utils import timezone

from apps.geography.models import AreaProfileType, City, District
from apps.network.models import NetworkDeviceType
from apps.operations.contracts import (
    CausalEventStatus,
    CausalEventType,
    CustomerImpactStatus,
    EventOrigin,
)
from apps.operations.models import (
    Alarm,
    AlarmStatus,
    CausalEvent,
    CustomerImpactAssessment,
    Severity,
)
from apps.operations.services.analytics import AnalyticsSpec, OperationalAnalyticsService
from apps.operations.tests.test_operations_models import (
    create_access_line,
    create_alarm_type,
    create_network_device,
    create_snapshot,
    create_subscription_connection,
)


@pytest.mark.django_db
def test_customer_impact_sum_uses_event_grain_and_excludes_unknown_events():
    snapshot = create_snapshot()
    root, _, _, _, line = create_access_line(snapshot)
    connection = create_subscription_connection(snapshot, line)
    started = timezone.now() - timedelta(hours=2)
    known = CausalEvent.objects.create(
        data_snapshot=snapshot,
        event_code="CE-ANALYTICS-001",
        event_type=CausalEventType.DEVICE_FAILURE,
        status=CausalEventStatus.RESOLVED,
        started_at=started,
        ended_at=started + timedelta(minutes=5),
        source_system="test",
        origin=EventOrigin.SYNTHETIC,
        root_device=root,
    )
    CausalEvent.objects.create(
        data_snapshot=snapshot,
        event_code="CE-ANALYTICS-002",
        event_type=CausalEventType.DEVICE_FAILURE,
        status=CausalEventStatus.RESOLVED,
        started_at=started + timedelta(minutes=10),
        ended_at=started + timedelta(minutes=15),
        source_system="test",
        origin=EventOrigin.SYNTHETIC,
        root_device=root,
    )
    CustomerImpactAssessment.objects.create(
        data_snapshot=snapshot,
        causal_event=known,
        subscription=connection.subscription,
        subscription_connection=connection,
        status=CustomerImpactStatus.VERIFIED_IMPACT.value,
        potential_impact=True,
        assessment_started_at=started,
        assessment_ended_at=started + timedelta(minutes=5),
    )

    result = OperationalAnalyticsService().analyze(
        snapshot=snapshot,
        spec=AnalyticsSpec(
            metric="affected_customers", aggregation="sum", group_by="city"
        ),
    )

    assert result["rows"][0]["value"] == 1
    assert result["included_event_count"] == 1
    assert result["excluded_unknown_count"] == 1
    assert result["deduplication_grain"] == "causal_event"


@pytest.mark.django_db
def test_event_grouping_uses_canonical_event_code_not_a_missing_generic_field():
    snapshot = create_snapshot()
    root, _, _, _, _ = create_access_line(snapshot)
    started = timezone.now() - timedelta(hours=1)
    CausalEvent.objects.create(
        data_snapshot=snapshot,
        event_code="CE-ANALYTICS-EVENT-001",
        event_type=CausalEventType.DEVICE_FAILURE,
        status=CausalEventStatus.RESOLVED,
        started_at=started,
        ended_at=started + timedelta(minutes=5),
        source_system="test",
        origin=EventOrigin.SYNTHETIC,
        root_device=root,
    )

    result = OperationalAnalyticsService().analyze(
        snapshot=snapshot,
        spec=AnalyticsSpec(metric="event_count", aggregation="count", group_by="event"),
    )

    assert result["rows"] == [
        {"label": "CE-ANALYTICS-EVENT-001", "value": 1, "event_count": 1}
    ]


@pytest.mark.django_db
def test_failed_failover_alarm_filter_preserves_unknown_impact_exclusion():
    snapshot = create_snapshot("analytics-failed-failover-unknown")
    root, _, _, _, _ = create_access_line(snapshot)
    started = timezone.now() - timedelta(hours=1)
    event = CausalEvent.objects.create(
        data_snapshot=snapshot,
        event_code="CE-ANALYTICS-FAILED-001",
        event_type=CausalEventType.DEVICE_FAILURE,
        status=CausalEventStatus.RESOLVED,
        started_at=started,
        ended_at=started + timedelta(minutes=5),
        source_system="test",
        origin=EventOrigin.SYNTHETIC,
        root_device=root,
    )
    Alarm.objects.create(
        data_snapshot=snapshot,
        causal_event=event,
        alarm_id="ALM-ANALYTICS-FAILED-001",
        alarm_type=create_alarm_type(snapshot, code="FAILOVER_UNSUCCESSFUL"),
        device=root,
        severity=Severity.CRITICAL,
        status=AlarmStatus.CLEARED,
        detected_at=started,
        cleared_at=started + timedelta(minutes=5),
    )

    result = OperationalAnalyticsService().analyze(
        snapshot=snapshot,
        spec=AnalyticsSpec(
            metric="affected_customers",
            aggregation="sum",
            group_by="event",
            failed_failover=True,
        ),
    )

    assert result["rows"] == []
    assert result["included_event_count"] == 0
    assert result["excluded_unknown_count"] == 1


@pytest.mark.django_db
def test_city_and_month_filters_apply_as_an_intersection_for_unknown_exclusions():
    snapshot = create_snapshot("analytics-city-month-intersection")
    _fallback_root, _, _, _, line = create_access_line(snapshot)
    connection = create_subscription_connection(snapshot, line)
    izmir = City.objects.create(name="İzmir", plate_code="35")
    konak = District.objects.create(
        city=izmir,
        name="Konak",
        profile_type=AreaProfileType.MIXED,
    )
    ankara = City.objects.create(name="Ankara", plate_code="06")
    cankaya = District.objects.create(
        city=ankara,
        name="Çankaya",
        profile_type=AreaProfileType.MIXED,
    )
    izmir_root = create_network_device(
        snapshot,
        code="AGG-IZM-ANALYTICS-001",
        device_type=NetworkDeviceType.BNG,
        city=izmir,
        district=konak,
    )
    ankara_root = create_network_device(
        snapshot,
        code="AGG-ANK-ANALYTICS-001",
        device_type=NetworkDeviceType.BNG,
        city=ankara,
        district=cankaya,
    )
    june = datetime(2026, 6, 10, tzinfo=UTC)
    known = CausalEvent.objects.create(
        data_snapshot=snapshot,
        event_code="CE-IZM-JUNE-KNOWN",
        event_type=CausalEventType.DEVICE_FAILURE,
        status=CausalEventStatus.RESOLVED,
        started_at=june,
        ended_at=june + timedelta(minutes=5),
        source_system="test",
        origin=EventOrigin.SYNTHETIC,
        root_device=izmir_root,
    )
    CausalEvent.objects.create(
        data_snapshot=snapshot,
        event_code="CE-IZM-JUNE-UNKNOWN",
        event_type=CausalEventType.DEVICE_FAILURE,
        status=CausalEventStatus.RESOLVED,
        started_at=june + timedelta(minutes=10),
        ended_at=june + timedelta(minutes=15),
        source_system="test",
        origin=EventOrigin.SYNTHETIC,
        root_device=izmir_root,
    )
    CausalEvent.objects.create(
        data_snapshot=snapshot,
        event_code="CE-ANK-JULY-UNKNOWN",
        event_type=CausalEventType.DEVICE_FAILURE,
        status=CausalEventStatus.RESOLVED,
        started_at=june + timedelta(days=31),
        ended_at=june + timedelta(days=31, minutes=5),
        source_system="test",
        origin=EventOrigin.SYNTHETIC,
        root_device=ankara_root,
    )
    CustomerImpactAssessment.objects.create(
        data_snapshot=snapshot,
        causal_event=known,
        subscription=connection.subscription,
        subscription_connection=connection,
        status=CustomerImpactStatus.VERIFIED_IMPACT.value,
        potential_impact=True,
        assessment_started_at=june,
        assessment_ended_at=june + timedelta(minutes=5),
    )

    result = OperationalAnalyticsService().analyze(
        snapshot=snapshot,
        spec=AnalyticsSpec(
            metric="affected_customers",
            aggregation="sum",
            group_by="city",
            city="İzmir",
            from_time=june - timedelta(days=1),
            to_time=june + timedelta(days=1),
        ),
    )

    assert result["rows"] == [{"label": "İzmir", "value": 1, "event_count": 1}]
    assert result["included_event_count"] == 1
    assert result["excluded_unknown_count"] == 1


@pytest.mark.django_db
def test_grouped_comparison_keeps_dimension_periods_and_unknown_exclusions():
    snapshot = create_snapshot("analytics-grouped-comparison")
    root, _, _, _, line = create_access_line(snapshot)
    connection = create_subscription_connection(snapshot, line)
    june = datetime(2026, 6, 10, tzinfo=UTC)
    july = datetime(2026, 7, 10, tzinfo=UTC)
    for code, started in (("CE-COMPARE-JUNE", june), ("CE-COMPARE-JULY", july)):
        event = CausalEvent.objects.create(
            data_snapshot=snapshot,
            event_code=code,
            event_type=CausalEventType.DEVICE_FAILURE,
            status=CausalEventStatus.RESOLVED,
            started_at=started,
            ended_at=started + timedelta(minutes=5),
            source_system="test",
            origin=EventOrigin.SYNTHETIC,
            root_device=root,
        )
        CustomerImpactAssessment.objects.create(
            data_snapshot=snapshot,
            causal_event=event,
            subscription=connection.subscription,
            subscription_connection=connection,
            status=CustomerImpactStatus.VERIFIED_IMPACT.value,
            potential_impact=True,
            assessment_started_at=started,
            assessment_ended_at=started + timedelta(minutes=5),
        )
    CausalEvent.objects.create(
        data_snapshot=snapshot,
        event_code="CE-COMPARE-UNKNOWN",
        event_type=CausalEventType.DEVICE_FAILURE,
        status=CausalEventStatus.RESOLVED,
        started_at=july,
        ended_at=july + timedelta(minutes=5),
        source_system="test",
        origin=EventOrigin.SYNTHETIC,
        root_device=root,
    )

    result = OperationalAnalyticsService().analyze(
        snapshot=snapshot,
        spec=AnalyticsSpec(
            metric="affected_customers",
            aggregation="sum",
            group_by="city",
            time_grain="month",
            comparison=True,
            from_time=june - timedelta(days=1),
            to_time=july + timedelta(days=1),
        ),
    )

    assert result["comparison"] is True
    assert result["included_event_count"] == 2
    assert result["excluded_unknown_count"] == 1
    assert len(result["rows"]) == 1
    row = result["rows"][0]
    assert [period["label"] for period in row["period_values"]] == ["2026-06", "2026-07"]
    assert row["absolute_change"] == 0
    assert row["signed_change"] == 0
    assert row["period_values"] == [
        {
            "label": "2026-06",
            "value": 1,
            "event_count": 1,
            "included_event_count": 1,
            "excluded_unknown_count": 0,
            "trend_direction": "unchanged",
            "absolute_change": None,
            "signed_change": None,
        },
        {
            "label": "2026-07",
            "value": 1,
            "event_count": 1,
            "included_event_count": 1,
            "excluded_unknown_count": 1,
            "trend_direction": "unchanged",
            "absolute_change": 0,
            "signed_change": 0,
        },
    ]
    assert row["excluded_unknown_count"] == 1

    global_result = OperationalAnalyticsService().analyze(
        snapshot=snapshot,
        spec=AnalyticsSpec(
            metric="affected_customers",
            aggregation="sum",
            group_by="time_bucket",
            time_grain="month",
            comparison=True,
            from_time=june - timedelta(days=1),
            to_time=july + timedelta(days=1),
        ),
    )

    assert global_result["rows"] == [
        {
            "label": "2026-06",
            "value": 1,
            "event_count": 1,
            "included_event_count": 1,
            "excluded_unknown_count": 0,
            "trend_direction": "unchanged",
            "absolute_change": None,
            "signed_change": None,
        },
        {
            "label": "2026-07",
            "value": 1,
            "event_count": 1,
            "included_event_count": 1,
            "excluded_unknown_count": 1,
            "trend_direction": "unchanged",
            "absolute_change": 0,
            "signed_change": 0,
        },
    ]
