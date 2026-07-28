import pytest
from data_generator.configs import maltepe_mvp_v1 as seed_config
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.core.choices import ResultStatus
from apps.datasets.management.commands.seed_maltepe_mvp import get_target_dataset_slug
from apps.datasets.models import DatasetSnapshotStatus, DatasetVersion, DataSnapshot
from apps.geography.models import City, District, Neighborhood
from apps.network.models import (
    AccessTechnology,
    LineConnection,
    NetworkDevice,
    NetworkDeviceType,
    NetworkLink,
    NetworkPort,
    NetworkPortStatus,
)


@pytest.mark.django_db
def test_seed_maltepe_mvp_creates_passive_dataset_snapshot_and_geography():
    call_command("seed_maltepe_mvp")

    dataset = DatasetVersion.objects.get(slug=get_target_dataset_slug())
    snapshot = dataset.snapshots.get()
    city = City.objects.get(name="İstanbul")
    district = District.objects.get(city=city, name="Maltepe")
    neighborhoods = list(
        Neighborhood.objects.filter(district=district)
        .order_by("name")
        .values_list("name", flat=True)
    )

    assert dataset.kind == "synthetic"
    assert dataset.generator_version == seed_config.GENERATOR_VERSION
    assert dataset.seed == seed_config.DATASET_SEED
    assert dataset.config["reference_datetime"] == seed_config.DEFAULT_REFERENCE_DATETIME
    assert dataset.config["customer_plan"]["vip_customers"] == 20
    assert snapshot.name == seed_config.SNAPSHOT_NAME
    assert snapshot.status == DatasetSnapshotStatus.VALIDATED
    assert snapshot.validation_status == ResultStatus.EXACT
    assert snapshot.is_active is False
    assert snapshot.activated_at is None
    assert snapshot.row_counts["neighborhoods"] == 5
    assert snapshot.row_counts["network_devices"] == 14
    assert snapshot.row_counts["network_links"] == 12
    assert snapshot.row_counts["network_ports"] == 177
    assert snapshot.row_counts["access_segments"] == 17
    assert snapshot.row_counts["line_connections"] == 240
    assert neighborhoods == sorted(seed_config.NEIGHBORHOODS)


@pytest.mark.django_db
def test_seed_maltepe_mvp_rejects_duplicate_without_reset():
    call_command("seed_maltepe_mvp")

    with pytest.raises(CommandError, match="already exists"):
        call_command("seed_maltepe_mvp")

    assert DatasetVersion.objects.filter(slug=get_target_dataset_slug()).count() == 1


@pytest.mark.django_db
def test_seed_maltepe_mvp_reset_recreates_only_target_dataset_and_keeps_geography():
    call_command("seed_maltepe_mvp")
    city_id = City.objects.get(name="İstanbul").id
    other_dataset = DatasetVersion.objects.create(
        name="Other Dataset",
        generator_version="other-v1",
        seed="other-seed",
    )

    call_command("seed_maltepe_mvp", "--reset")

    assert DatasetVersion.objects.filter(slug=get_target_dataset_slug()).count() == 1
    assert DatasetVersion.objects.filter(id=other_dataset.id).exists()
    assert City.objects.get(name="İstanbul").id == city_id
    assert City.objects.filter(name="İstanbul").count() == 1


@pytest.mark.django_db
def test_seed_maltepe_mvp_can_create_passive_snapshot_when_another_snapshot_is_active():
    other_dataset = DatasetVersion.objects.create(
        name="Other Active Dataset",
        generator_version="other-active-v1",
        seed="other-active-seed",
    )
    DataSnapshot.objects.create(
        dataset_version=other_dataset,
        name="Other active snapshot",
        is_active=True,
    )

    call_command("seed_maltepe_mvp")

    snapshot = DatasetVersion.objects.get(slug=get_target_dataset_slug()).snapshots.get()
    assert snapshot.is_active is False
    assert DataSnapshot.objects.filter(is_active=True).get().dataset_version == other_dataset


@pytest.mark.django_db
def test_seed_maltepe_mvp_activate_creates_active_snapshot_when_none_exists():
    call_command("seed_maltepe_mvp", "--activate")

    snapshot = DatasetVersion.objects.get(slug=get_target_dataset_slug()).snapshots.get()
    assert snapshot.is_active is True
    assert snapshot.activated_at is not None


@pytest.mark.django_db
def test_seed_maltepe_mvp_activate_rejects_existing_active_snapshot():
    other_dataset = DatasetVersion.objects.create(
        name="Other Active Dataset",
        generator_version="other-active-v1",
        seed="other-active-seed",
    )
    DataSnapshot.objects.create(
        dataset_version=other_dataset,
        name="Other active snapshot",
        is_active=True,
    )

    with pytest.raises(CommandError, match="Another active data snapshot"):
        call_command("seed_maltepe_mvp", "--activate")

    assert not DatasetVersion.objects.filter(slug=get_target_dataset_slug()).exists()


@pytest.mark.django_db
def test_seed_maltepe_mvp_stores_custom_reference_datetime_as_istanbul_iso_string():
    call_command("seed_maltepe_mvp", "--reference-datetime", "2026-09-01T00:00:00+03:00")

    dataset = DatasetVersion.objects.get(slug=get_target_dataset_slug())
    assert dataset.config["reference_datetime"] == "2026-09-01T00:00:00+03:00"


@pytest.mark.django_db
def test_seed_maltepe_mvp_creates_expected_network_topology_counts():
    call_command("seed_maltepe_mvp")
    snapshot = DatasetVersion.objects.get(slug=get_target_dataset_slug()).snapshots.get()

    assert NetworkDevice.objects.filter(data_snapshot=snapshot).count() == 14
    assert NetworkDevice.objects.filter(
        data_snapshot=snapshot,
        device_type=NetworkDeviceType.BNG,
        code__in=["BNG-MAL-001", "BNG-MAL-002"],
    ).count() == 2
    assert NetworkDevice.objects.filter(
        data_snapshot=snapshot,
        device_type=NetworkDeviceType.OLT,
    ).count() == 5
    assert NetworkDevice.objects.filter(
        data_snapshot=snapshot,
        device_type=NetworkDeviceType.DSLAM,
    ).count() == 5
    assert NetworkDevice.objects.filter(
        data_snapshot=snapshot,
        device_type=NetworkDeviceType.ACCESS_NODE,
    ).count() == 2
    assert NetworkLink.objects.filter(data_snapshot=snapshot).count() == 12
    assert NetworkPort.objects.filter(data_snapshot=snapshot).count() == 177
    assert LineConnection.objects.filter(data_snapshot=snapshot, is_active=True).count() == 240


@pytest.mark.django_db
def test_seed_maltepe_mvp_creates_expected_port_and_line_distribution():
    call_command("seed_maltepe_mvp")
    snapshot = DatasetVersion.objects.get(slug=get_target_dataset_slug()).snapshots.get()

    assert NetworkPort.objects.filter(
        data_snapshot=snapshot,
        inventory_status=NetworkPortStatus.ACTIVE,
        metadata__seed_role="gpon_pon_port",
    ).count() == 10
    assert NetworkPort.objects.filter(
        data_snapshot=snapshot,
        inventory_status=NetworkPortStatus.RESERVED,
        metadata__seed_role="reserved_gpon_pon_port",
    ).count() == 2
    assert NetworkPort.objects.filter(
        data_snapshot=snapshot,
        inventory_status=NetworkPortStatus.ACTIVE,
        metadata__seed_role__in=["vdsl_customer_port", "adsl_customer_port"],
    ).count() == 110
    assert NetworkPort.objects.filter(
        data_snapshot=snapshot,
        inventory_status=NetworkPortStatus.RESERVED,
        metadata__seed_role="reserved_dslam_customer_port",
    ).count() == 20
    assert NetworkPort.objects.filter(
        data_snapshot=snapshot,
        inventory_status=NetworkPortStatus.ACTIVE,
        metadata__seed_role="general_fiber_customer_port",
    ).count() == 30
    assert NetworkPort.objects.filter(
        data_snapshot=snapshot,
        inventory_status=NetworkPortStatus.RESERVED,
        metadata__seed_role="reserved_general_fiber_customer_port",
    ).count() == 5
    assert LineConnection.objects.filter(
        data_snapshot=snapshot,
        technology=AccessTechnology.GPON,
    ).count() == 100
    assert LineConnection.objects.filter(
        data_snapshot=snapshot,
        technology=AccessTechnology.FIBER,
    ).count() == 30
    assert LineConnection.objects.filter(
        data_snapshot=snapshot,
        technology=AccessTechnology.VDSL,
    ).count() == 90
    assert LineConnection.objects.filter(
        data_snapshot=snapshot,
        technology=AccessTechnology.ADSL,
    ).count() == 20


@pytest.mark.django_db
def test_seed_maltepe_mvp_supports_gpon_fan_out_without_dslam_port_fan_out():
    call_command("seed_maltepe_mvp")
    snapshot = DatasetVersion.objects.get(slug=get_target_dataset_slug()).snapshots.get()

    gpon_port = NetworkPort.objects.filter(
        data_snapshot=snapshot,
        metadata__seed_role="gpon_pon_port",
    ).first()
    assert gpon_port.line_connections.count() > 1

    dslam_active_ports = NetworkPort.objects.filter(
        data_snapshot=snapshot,
        metadata__seed_role__in=["vdsl_customer_port", "adsl_customer_port"],
    )
    assert all(port.line_connections.count() == 1 for port in dslam_active_ports)


@pytest.mark.django_db
def test_seed_maltepe_mvp_reset_recreates_network_without_duplicates():
    call_command("seed_maltepe_mvp")
    call_command("seed_maltepe_mvp", "--reset")
    snapshot = DatasetVersion.objects.get(slug=get_target_dataset_slug()).snapshots.get()

    assert NetworkDevice.objects.filter(data_snapshot=snapshot).count() == 14
    assert NetworkPort.objects.filter(data_snapshot=snapshot).count() == 177
    assert LineConnection.objects.filter(data_snapshot=snapshot).count() == 240
