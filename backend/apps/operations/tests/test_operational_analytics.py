from datetime import timedelta

import pytest
from django.utils import timezone

from apps.operations.contracts import (
    CausalEventStatus,
    CausalEventType,
    CustomerImpactStatus,
    EventOrigin,
)
from apps.operations.models import CausalEvent, CustomerImpactAssessment
from apps.operations.services.analytics import AnalyticsSpec, OperationalAnalyticsService
from apps.operations.tests.test_operations_models import (
    create_access_line,
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
