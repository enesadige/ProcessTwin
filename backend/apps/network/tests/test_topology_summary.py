from datetime import timedelta

import pytest
from django.utils import timezone

from apps.network.models import (
    AccessSegment,
    AccessTechnology,
    LineConnection,
    NetworkDeviceType,
    NetworkLink,
    NetworkPort,
)
from apps.network.services.topology_summary import (
    TopologySummaryInputError,
    TopologySummaryService,
)
from apps.operations.contracts import CausalEventType, CustomerImpactStatus
from apps.operations.models import CausalEvent, CustomerImpactAssessment
from apps.operations.tests.test_operations_models import (
    create_maltepe_bng,
    create_network_device,
    create_snapshot,
    create_subscription_connection,
)


@pytest.mark.django_db
def test_summary_is_snapshot_local_and_exposes_persisted_scope_only():
    snapshot = create_snapshot("topology-summary")
    root = create_maltepe_bng(snapshot, code="BNG-SUMMARY-001")
    access = create_network_device(
        snapshot,
        code="AN-SUMMARY-001",
        device_type=NetworkDeviceType.ACCESS_NODE,
        access_role="standard_access",
        city=root.city,
        district=root.district,
    )
    NetworkLink.objects.create(
        data_snapshot=snapshot,
        link_code="LNK-SUMMARY-001",
        source_device=root,
        target_device=access,
        metadata={"link_layer": "bng_to_access"},
    )
    port = NetworkPort.objects.create(
        data_snapshot=snapshot,
        device=access,
        port_code="PORT-SUMMARY-001",
    )
    segment = AccessSegment.objects.create(
        data_snapshot=snapshot,
        segment_code="SEG-SUMMARY-001",
        name="Summary segment",
        technology=AccessTechnology.FIBER,
        serving_device=access,
        city=root.city,
        district=root.district,
    )
    line = LineConnection.objects.create(
        data_snapshot=snapshot,
        line_code="LINE-SUMMARY-001",
        port=port,
        access_segment=segment,
        technology=AccessTechnology.FIBER,
        valid_from=timezone.now() - timedelta(days=1),
    )
    connection = create_subscription_connection(snapshot, line)
    started_at = timezone.now() - timedelta(minutes=5)
    event = CausalEvent.objects.create(
        data_snapshot=snapshot,
        event_code="CE-SUMMARY-001",
        event_type=CausalEventType.DEVICE_FAILURE,
        started_at=started_at,
        source_system="test",
        root_device=root,
    )
    CustomerImpactAssessment.objects.create(
        data_snapshot=snapshot,
        causal_event=event,
        subscription=connection.subscription,
        subscription_connection=connection,
        status=CustomerImpactStatus.VERIFIED_IMPACT,
        potential_impact=True,
        assessment_started_at=started_at,
    )

    summary = TopologySummaryService().build(
        snapshot=snapshot,
        device=root,
        causal_event=event,
    )

    assert summary.root_device["code"] == "BNG-SUMMARY-001"
    assert [item["code"] for item in summary.downstream_devices] == ["AN-SUMMARY-001"]
    assert summary.links == [{
        "code": "LNK-SUMMARY-001",
        "source_device_code": "BNG-SUMMARY-001",
        "target_device_code": "AN-SUMMARY-001",
        "status": "active",
        "capacity_mbps": 0,
        "link_layer": "bng_to_access",
    }]
    assert summary.connection_roles == {"primary": 1}
    assert summary.impact_scope == {
        "potential_connection_count": 1,
        "verified_connection_count": 1,
        "verified_subscription_count": 1,
        "verified_customer_count": 1,
    }


@pytest.mark.django_db
def test_summary_rejects_event_from_another_snapshot():
    first_snapshot = create_snapshot("topology-summary-one")
    second_snapshot = create_snapshot("topology-summary-two")
    root = create_maltepe_bng(first_snapshot, code="BNG-SUMMARY-002")
    other_root = create_maltepe_bng(second_snapshot, code="BNG-SUMMARY-003")
    event = CausalEvent.objects.create(
        data_snapshot=second_snapshot,
        event_code="CE-SUMMARY-002",
        event_type=CausalEventType.DEVICE_FAILURE,
        started_at=timezone.now(),
        source_system="test",
        root_device=other_root,
    )

    with pytest.raises(TopologySummaryInputError, match="does not belong"):
        TopologySummaryService().build(
            snapshot=first_snapshot,
            device=root,
            causal_event=event,
        )
