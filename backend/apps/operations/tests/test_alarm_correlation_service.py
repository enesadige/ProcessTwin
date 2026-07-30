from datetime import timedelta

import pytest
from django.core.management import call_command

from apps.datasets.management.commands.seed_maltepe_mvp import get_target_dataset_slug
from apps.datasets.models import DatasetVersion, DataSnapshot
from apps.network.models import (
    FailureDomain,
    FailureDomainType,
    NetworkDevice,
    NetworkLink,
    NetworkLinkFailureDomainMembership,
)
from apps.operations.models import (
    Alarm,
    AlarmCategory,
    AlarmStatus,
    AlarmType,
    IncidentAlarm,
    ServiceImpactClass,
    Severity,
)
from apps.operations.services.alarm_correlation import (
    AlarmCorrelationInputError,
    AlarmCorrelationService,
)


@pytest.mark.django_db
def test_alarm_correlation_links_main_bng_unreachable_and_link_down_without_incident_alarm():
    snapshot = seed_snapshot()
    anchor = get_alarm(snapshot, "ALM-OUT-MAL-BNG-001-PRIMARY")
    IncidentAlarm.objects.filter(data_snapshot=snapshot).delete()

    result = get_candidate_result(
        anchor,
        "ALM-OUT-MAL-BNG-001-LINK",
        snapshot,
    )

    assert result.correlated is True
    assert result.evidence_score == 100
    assert result.time_difference_seconds == 0
    assert result.topology_relation == "same_device"
    assert result.type_compatibility == "known_compatible_pair"
    assert result.anchor_alarm_code == anchor.alarm_id
    assert result.snapshot["id"] == snapshot.id
    assert {item["criterion"] for item in result.evidence} == {
        "time_proximity",
        "topology_relation",
        "alarm_type_compatibility",
        "same_district",
    }


@pytest.mark.django_db
def test_alarm_correlation_does_not_correlate_other_bng_branch_seed_alarm():
    snapshot = seed_snapshot()
    anchor = get_alarm(snapshot, "ALM-OUT-MAL-BNG-001-PRIMARY")
    candidate = get_alarm(snapshot, "ALM-OUT-MAL-OLT-001-PRIMARY")

    result = AlarmCorrelationService().score_pair(
        anchor_alarm=anchor,
        candidate_alarm=candidate,
        snapshot=snapshot,
    )

    assert result.correlated is False
    assert result.evidence_score < 60
    assert result.topology_relation == "unrelated"


@pytest.mark.django_db
def test_alarm_correlation_time_window_outside_candidate_gets_low_score():
    snapshot = seed_snapshot()
    anchor = get_alarm(snapshot, "ALM-OUT-MAL-BNG-001-PRIMARY")
    old_alarm = create_alarm(
        snapshot=snapshot,
        alarm_id="ALM-CORR-OLD-LINK",
        alarm_type_code="LINK_DOWN",
        device_code="BNG-MAL-002",
        detected_at=anchor.detected_at + timedelta(minutes=31),
    )

    result = AlarmCorrelationService().score_pair(
        anchor_alarm=anchor,
        candidate_alarm=old_alarm,
        snapshot=snapshot,
    )

    assert result.time_difference_seconds == 31 * 60
    assert result.evidence[0]["score"] == 0
    assert result.evidence_score == 30
    assert result.correlated is False
    assert old_alarm.alarm_id not in [
        item.candidate_alarm_code
        for item in AlarmCorrelationService().find_correlations(
            anchor_alarm=anchor,
            snapshot=snapshot,
        )
    ]


@pytest.mark.django_db
def test_alarm_correlation_excludes_cross_snapshot_alarm_from_candidate_list():
    snapshot = seed_snapshot()
    anchor = get_alarm(snapshot, "ALM-OUT-MAL-BNG-001-PRIMARY")
    other_alarm = create_other_snapshot_alarm()

    results = AlarmCorrelationService().find_correlations(
        anchor_alarm=anchor,
        snapshot=snapshot,
    )

    assert other_alarm.alarm_id not in [result.candidate_alarm_code for result in results]
    with pytest.raises(AlarmCorrelationInputError, match="does not belong to snapshot"):
        AlarmCorrelationService().score_pair(
            anchor_alarm=anchor,
            candidate_alarm=other_alarm,
            snapshot=snapshot,
        )


@pytest.mark.django_db
def test_alarm_correlation_does_not_return_anchor_as_candidate():
    snapshot = seed_snapshot()
    anchor = get_alarm(snapshot, "ALM-OUT-MAL-BNG-001-PRIMARY")

    results = AlarmCorrelationService().find_correlations(
        anchor_alarm=anchor,
        snapshot=snapshot,
    )

    assert anchor.alarm_id not in [result.candidate_alarm_code for result in results]
    with pytest.raises(AlarmCorrelationInputError, match="cannot be scored against itself"):
        AlarmCorrelationService().score_pair(
            anchor_alarm=anchor,
            candidate_alarm=anchor,
            snapshot=snapshot,
        )


@pytest.mark.django_db
def test_alarm_correlation_scores_same_device_relation():
    snapshot = seed_snapshot()
    anchor = get_alarm(snapshot, "ALM-OUT-MAL-BNG-001-PRIMARY")
    candidate = create_alarm(
        snapshot=snapshot,
        alarm_id="ALM-CORR-SAME-DEVICE",
        alarm_type_code="BNG_UNREACHABLE",
        device_code="BNG-MAL-001",
        detected_at=anchor.detected_at + timedelta(minutes=2),
    )

    result = AlarmCorrelationService().score_pair(
        anchor_alarm=anchor,
        candidate_alarm=candidate,
        snapshot=snapshot,
    )

    assert result.topology_relation == "same_device"
    assert result.type_compatibility == "same_type_with_topology"
    assert result.evidence_score == 95
    assert result.correlated is True


@pytest.mark.django_db
def test_alarm_correlation_scores_direct_parent_child_relation():
    snapshot = seed_snapshot()
    anchor = get_alarm(snapshot, "ALM-OUT-MAL-BNG-001-PRIMARY")
    candidate = create_alarm(
        snapshot=snapshot,
        alarm_id="ALM-CORR-PARENT-CHILD",
        alarm_type_code="LINK_DOWN",
        device_code="OLT-MAL-ALT-001",
        detected_at=anchor.detected_at + timedelta(minutes=3),
    )

    result = AlarmCorrelationService().score_pair(
        anchor_alarm=anchor,
        candidate_alarm=candidate,
        snapshot=snapshot,
    )

    assert result.topology_relation == "direct_parent_child"
    assert result.type_compatibility == "known_compatible_pair"
    assert result.evidence_score == 90
    assert result.correlated is True


@pytest.mark.django_db
def test_alarm_correlation_scores_same_bng_branch_relation():
    snapshot = seed_snapshot()
    anchor = create_alarm(
        snapshot=snapshot,
        alarm_id="ALM-CORR-BRANCH-ANCHOR",
        alarm_type_code="ACCESS_DEVICE_UNREACHABLE",
        device_code="OLT-MAL-ALT-001",
        detected_at=get_alarm(snapshot, "ALM-OUT-MAL-BNG-001-PRIMARY").detected_at,
    )
    candidate = create_alarm(
        snapshot=snapshot,
        alarm_id="ALM-CORR-BRANCH-CANDIDATE",
        alarm_type_code="LINK_DOWN",
        device_code="DSLAM-MAL-CEV-001",
        detected_at=anchor.detected_at + timedelta(minutes=4),
    )

    result = AlarmCorrelationService().score_pair(
        anchor_alarm=anchor,
        candidate_alarm=candidate,
        snapshot=snapshot,
    )

    assert result.topology_relation == "same_bng_branch"
    assert result.type_compatibility == "known_compatible_pair"
    assert result.evidence_score == 80
    assert result.correlated is True


@pytest.mark.django_db
def test_alarm_correlation_handles_device_with_multiple_bng_branches():
    snapshot = seed_snapshot()
    NetworkLink.objects.create(
        data_snapshot=snapshot,
        link_code="LINK-CORR-MULTI-BNG2-OLT",
        source_device=NetworkDevice.objects.get(data_snapshot=snapshot, code="BNG-MAL-002"),
        target_device=NetworkDevice.objects.get(data_snapshot=snapshot, code="OLT-MAL-ALT-001"),
        capacity_mbps=10000,
    )
    anchor = create_alarm(
        snapshot=snapshot,
        alarm_id="ALM-CORR-MULTI-BRANCH-ANCHOR",
        alarm_type_code="ACCESS_DEVICE_UNREACHABLE",
        device_code="OLT-MAL-ALT-001",
        detected_at=get_alarm(snapshot, "ALM-OUT-MAL-BNG-001-PRIMARY").detected_at,
    )
    candidate = create_alarm(
        snapshot=snapshot,
        alarm_id="ALM-CORR-MULTI-BRANCH-CANDIDATE",
        alarm_type_code="LINK_DOWN",
        device_code="DSLAM-MAL-ZUM-001",
        detected_at=anchor.detected_at + timedelta(minutes=4),
    )

    result = AlarmCorrelationService().score_pair(
        anchor_alarm=anchor,
        candidate_alarm=candidate,
        snapshot=snapshot,
    )

    assert result.topology_relation == "same_bng_branch"
    assert result.type_compatibility == "known_compatible_pair"
    assert result.evidence_score == 80
    assert result.correlated is True


@pytest.mark.django_db
def test_alarm_correlation_results_are_sorted_by_score_then_alarm_code():
    snapshot = seed_snapshot()
    anchor = get_alarm(snapshot, "ALM-OUT-MAL-BNG-001-PRIMARY")
    create_alarm(
        snapshot=snapshot,
        alarm_id="ALM-CORR-A-SAME-SCORE",
        alarm_type_code="BNG_UNREACHABLE",
        device_code="BNG-MAL-001",
        detected_at=anchor.detected_at + timedelta(minutes=2),
    )
    create_alarm(
        snapshot=snapshot,
        alarm_id="ALM-CORR-B-SAME-SCORE",
        alarm_type_code="BNG_UNREACHABLE",
        device_code="BNG-MAL-001",
        detected_at=anchor.detected_at + timedelta(minutes=2),
    )

    results = AlarmCorrelationService().find_correlations(
        anchor_alarm=anchor,
        snapshot=snapshot,
    )
    top_codes = [result.candidate_alarm_code for result in results[:3]]

    assert top_codes == [
        "ALM-OUT-MAL-BNG-001-LINK",
        "ALM-CORR-A-SAME-SCORE",
        "ALM-CORR-B-SAME-SCORE",
    ]


@pytest.mark.django_db
def test_alarm_correlation_uses_shared_failure_domain_for_fiber_route_evidence():
    snapshot = seed_snapshot()
    first_link = NetworkLink.objects.get(
        data_snapshot=snapshot,
        link_code="LINK-BNG-MAL-001-OLT-MAL-ALT-001",
    )
    second_link = NetworkLink.objects.get(
        data_snapshot=snapshot,
        link_code="LINK-BNG-MAL-002-OLT-MAL-ZUM-001",
    )
    fiber_route = FailureDomain.objects.create(
        data_snapshot=snapshot,
        code="FD-FIBER-CORR-001",
        name="Synthetic fiber route",
        domain_type=FailureDomainType.FIBER_ROUTE,
    )
    for link in (first_link, second_link):
        NetworkLinkFailureDomainMembership.objects.create(
            data_snapshot=snapshot,
            network_link=link,
            failure_domain=fiber_route,
        )
    fiber_alarm_type = AlarmType.objects.create(
        data_snapshot=snapshot,
        code="FIBER_CUT_SUSPECTED",
        name="Synthetic fiber cut",
        severity=Severity.CRITICAL,
        category=AlarmCategory.TRANSPORT,
        service_impact_class=ServiceImpactClass.PARTIAL_OUTAGE,
        correlation_family="fiber_route",
        is_root_candidate=True,
    )
    anchor = Alarm.objects.create(
        data_snapshot=snapshot,
        alarm_id="ALM-FIBER-ANCHOR",
        alarm_type=fiber_alarm_type,
        network_link=first_link,
        severity=Severity.CRITICAL,
        status=AlarmStatus.OPEN,
        detected_at=get_alarm(snapshot, "ALM-OUT-MAL-BNG-001-PRIMARY").detected_at,
    )
    candidate = Alarm.objects.create(
        data_snapshot=snapshot,
        alarm_id="ALM-FIBER-CANDIDATE",
        alarm_type=fiber_alarm_type,
        network_link=second_link,
        severity=Severity.CRITICAL,
        status=AlarmStatus.OPEN,
        detected_at=anchor.detected_at,
    )

    result = AlarmCorrelationService().score_pair(
        anchor_alarm=anchor,
        candidate_alarm=candidate,
        snapshot=snapshot,
    )

    assert result.topology_relation == "shared_failure_domain"
    assert result.type_compatibility == "same_type_with_topology"
    assert result.evidence_score == 90
    assert result.correlated is True


def seed_snapshot() -> DataSnapshot:
    call_command("seed_maltepe_mvp")
    return DatasetVersion.objects.get(slug=get_target_dataset_slug()).snapshots.get()


def get_alarm(snapshot: DataSnapshot, alarm_id: str) -> Alarm:
    return Alarm.objects.select_related("alarm_type", "device", "device__district").get(
        data_snapshot=snapshot,
        alarm_id=alarm_id,
    )


def create_alarm(
    *,
    snapshot: DataSnapshot,
    alarm_id: str,
    alarm_type_code: str,
    device_code: str,
    detected_at,
) -> Alarm:
    alarm_type = AlarmType.objects.get(data_snapshot=snapshot, code=alarm_type_code)
    device = NetworkDevice.objects.get(data_snapshot=snapshot, code=device_code)
    return Alarm.objects.create(
        data_snapshot=snapshot,
        alarm_id=alarm_id,
        alarm_type=alarm_type,
        device=device,
        severity=Severity.MAJOR,
        status=AlarmStatus.OPEN,
        detected_at=detected_at,
    )


def get_candidate_result(anchor: Alarm, candidate_alarm_code: str, snapshot: DataSnapshot):
    results = AlarmCorrelationService().find_correlations(
        anchor_alarm=anchor,
        snapshot=snapshot,
    )
    return next(result for result in results if result.candidate_alarm_code == candidate_alarm_code)


def create_other_snapshot_alarm() -> Alarm:
    dataset = DatasetVersion.objects.create(
        name="Other Alarm Correlation Dataset",
        generator_version="other-v1",
        seed="other-seed",
    )
    snapshot = DataSnapshot.objects.create(dataset_version=dataset, name="Other Snapshot")
    source_alarm = Alarm.objects.select_related("alarm_type", "device").first()
    alarm_type = AlarmType.objects.create(
        data_snapshot=snapshot,
        code="LINK_DOWN",
        name="Other link down",
        severity=Severity.MAJOR,
        category=source_alarm.alarm_type.category,
    )
    device = NetworkDevice.objects.create(
        data_snapshot=snapshot,
        code="BNG-OTHER-001",
        device_type=source_alarm.device.device_type,
        city=source_alarm.device.city,
        district=source_alarm.device.district,
    )
    return Alarm.objects.create(
        data_snapshot=snapshot,
        alarm_id="ALM-OTHER-SNAPSHOT-001",
        alarm_type=alarm_type,
        device=device,
        severity=Severity.MAJOR,
        detected_at=source_alarm.detected_at,
    )
