from datetime import datetime

import pytest
from django.core.management import call_command
from django.utils.dateparse import parse_datetime

from apps.datasets.management.commands.seed_maltepe_mvp import get_target_dataset_slug
from apps.datasets.models import DatasetVersion, DataSnapshot
from apps.geography.models import City
from apps.network.models import NetworkDevice, NetworkDeviceType, NetworkLink
from apps.network.services.topology import (
    NetworkTopologyCycleError,
    NetworkTopologyInputError,
    NetworkTopologyService,
)


@pytest.mark.django_db
def test_get_children_returns_direct_bng_maltepe_children_in_deterministic_order():
    snapshot = seed_snapshot()
    service = NetworkTopologyService()
    bng_001 = get_device(snapshot, "BNG-MAL-001")
    bng_002 = get_device(snapshot, "BNG-MAL-002")

    first_children = service.get_children(
        device=bng_001,
        snapshot=snapshot,
        evaluation_time=get_reference_datetime(snapshot),
    )
    second_children = service.get_children(
        device=bng_002,
        snapshot=snapshot,
        evaluation_time=get_reference_datetime(snapshot),
    )

    assert [device.code for device in first_children] == [
        "AN-MAL-GF-001",
        "DSLAM-MAL-ALT-001",
        "DSLAM-MAL-CEV-001",
        "DSLAM-MAL-KUC-001",
        "OLT-MAL-ALT-001",
        "OLT-MAL-CEV-001",
        "OLT-MAL-KUC-001",
    ]
    assert count_by_type(first_children) == {
        NetworkDeviceType.ACCESS_NODE: 1,
        NetworkDeviceType.DSLAM: 3,
        NetworkDeviceType.OLT: 3,
    }
    assert [device.code for device in second_children] == [
        "AN-MAL-GF-002",
        "DSLAM-MAL-FIN-001",
        "DSLAM-MAL-ZUM-001",
        "OLT-MAL-FIN-001",
        "OLT-MAL-ZUM-001",
    ]
    assert count_by_type(second_children) == {
        NetworkDeviceType.ACCESS_NODE: 1,
        NetworkDeviceType.DSLAM: 2,
        NetworkDeviceType.OLT: 2,
    }


@pytest.mark.django_db
def test_get_ancestors_returns_parent_bng_from_nearest_parent_to_root():
    snapshot = seed_snapshot()
    service = NetworkTopologyService()
    olt = get_device(snapshot, "OLT-MAL-ALT-001")

    ancestors = service.get_ancestors(
        device=olt,
        snapshot=snapshot,
        evaluation_time=get_reference_datetime(snapshot),
    )

    assert [device.code for device in ancestors] == ["BNG-MAL-001"]


@pytest.mark.django_db
def test_get_ancestors_supports_multiple_upstream_branches_deterministically():
    snapshot = seed_snapshot()
    service = NetworkTopologyService()
    olt = get_device(snapshot, "OLT-MAL-ALT-001")
    second_bng = get_device(snapshot, "BNG-MAL-002")
    NetworkLink.objects.create(
        data_snapshot=snapshot,
        link_code="LINK-MULTI-PARENT-BNG2-OLT",
        source_device=second_bng,
        target_device=olt,
        capacity_mbps=10000,
    )

    ancestors = service.get_ancestors(
        device=olt,
        snapshot=snapshot,
        evaluation_time=get_reference_datetime(snapshot),
    )

    assert [device.code for device in ancestors] == ["BNG-MAL-001", "BNG-MAL-002"]


@pytest.mark.django_db
def test_get_subgraph_returns_only_requested_bng_branch_without_duplicates():
    snapshot = seed_snapshot()
    service = NetworkTopologyService()
    bng = get_device(snapshot, "BNG-MAL-001")

    subgraph = service.get_subgraph(
        device=bng,
        snapshot=snapshot,
        evaluation_time=get_reference_datetime(snapshot),
    )
    device_codes = [device.code for device in subgraph.devices]
    link_codes = [link.link_code for link in subgraph.links]

    assert device_codes == [
        "AN-MAL-GF-001",
        "BNG-MAL-001",
        "DSLAM-MAL-ALT-001",
        "DSLAM-MAL-CEV-001",
        "DSLAM-MAL-KUC-001",
        "OLT-MAL-ALT-001",
        "OLT-MAL-CEV-001",
        "OLT-MAL-KUC-001",
    ]
    assert len(device_codes) == len(set(device_codes))
    assert len(link_codes) == 7
    assert len(link_codes) == len(set(link_codes))
    assert "BNG-MAL-002" not in device_codes
    assert "AN-MAL-GF-002" not in device_codes
    assert not any("-FIN-" in code or "-ZUM-" in code for code in device_codes)


@pytest.mark.django_db
def test_service_uses_snapshot_reference_datetime_when_evaluation_time_is_omitted():
    snapshot = seed_snapshot()
    service = NetworkTopologyService()
    bng = get_device(snapshot, "BNG-MAL-001")

    children = service.get_children(device=bng, snapshot=snapshot)

    assert len(children) == 7


@pytest.mark.django_db
def test_service_rejects_naive_evaluation_time():
    snapshot = seed_snapshot()
    service = NetworkTopologyService()
    bng = get_device(snapshot, "BNG-MAL-001")

    with pytest.raises(NetworkTopologyInputError, match="timezone-aware"):
        service.get_children(
            device=bng,
            snapshot=snapshot,
            evaluation_time=datetime(2026, 8, 1, 0, 0, 0),
        )


@pytest.mark.django_db
def test_service_isolates_cross_snapshot_devices():
    snapshot = seed_snapshot()
    other_snapshot = DataSnapshot.objects.create(
        dataset_version=DatasetVersion.objects.create(
            name="Other Topology Dataset",
            generator_version="other-v1",
            seed="other-seed",
        ),
        name="Other Snapshot",
    )
    bng = get_device(snapshot, "BNG-MAL-001")

    with pytest.raises(NetworkTopologyInputError, match="does not belong to snapshot"):
        NetworkTopologyService().get_children(
            device=bng,
            snapshot=other_snapshot,
            evaluation_time=get_reference_datetime(snapshot),
        )


@pytest.mark.django_db
def test_service_rejects_unknown_device_and_missing_snapshot():
    snapshot = seed_snapshot()
    city = City.objects.get(name="İstanbul")
    unknown_device = NetworkDevice(
        data_snapshot=snapshot,
        code="BNG-MAL-UNKNOWN",
        device_type=NetworkDeviceType.BNG,
        city=city,
    )
    service = NetworkTopologyService()

    with pytest.raises(NetworkTopologyInputError, match="persisted NetworkDevice"):
        service.get_children(
            device=unknown_device,
            snapshot=snapshot,
            evaluation_time=get_reference_datetime(snapshot),
        )
    with pytest.raises(NetworkTopologyInputError, match="DataSnapshot"):
        service.get_children(
            device=get_device(snapshot, "BNG-MAL-001"),
            snapshot=None,
            evaluation_time=get_reference_datetime(snapshot),
        )


@pytest.mark.django_db
def test_get_ancestors_reports_cycle_without_infinite_loop():
    snapshot = seed_snapshot()
    bng = get_device(snapshot, "BNG-MAL-001")
    olt = get_device(snapshot, "OLT-MAL-ALT-001")
    NetworkLink.objects.create(
        data_snapshot=snapshot,
        link_code="LINK-VALIDATOR-CYCLE-OLT-BNG",
        source_device=olt,
        target_device=bng,
        capacity_mbps=10000,
    )

    with pytest.raises(NetworkTopologyCycleError, match="cycle"):
        NetworkTopologyService().get_ancestors(
            device=olt,
            snapshot=snapshot,
            evaluation_time=get_reference_datetime(snapshot),
        )


@pytest.mark.django_db
def test_get_subgraph_reports_cycle_without_duplicate_results():
    snapshot = seed_snapshot()
    bng = get_device(snapshot, "BNG-MAL-001")
    olt = get_device(snapshot, "OLT-MAL-ALT-001")
    NetworkLink.objects.create(
        data_snapshot=snapshot,
        link_code="LINK-VALIDATOR-CYCLE-OLT-BNG",
        source_device=olt,
        target_device=bng,
        capacity_mbps=10000,
    )

    with pytest.raises(NetworkTopologyCycleError, match="cycle"):
        NetworkTopologyService().get_subgraph(
            device=bng,
            snapshot=snapshot,
            evaluation_time=get_reference_datetime(snapshot),
        )


def seed_snapshot() -> DataSnapshot:
    call_command("seed_maltepe_mvp")
    return DatasetVersion.objects.get(slug=get_target_dataset_slug()).snapshots.get()


def get_device(snapshot: DataSnapshot, code: str) -> NetworkDevice:
    return NetworkDevice.objects.get(data_snapshot=snapshot, code=code)


def get_reference_datetime(snapshot: DataSnapshot):
    return parse_datetime(snapshot.dataset_version.config["reference_datetime"])


def count_by_type(devices: list[NetworkDevice]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for device in devices:
        counts[device.device_type] = counts.get(device.device_type, 0) + 1
    return counts
