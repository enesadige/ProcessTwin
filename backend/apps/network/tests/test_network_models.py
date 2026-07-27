import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.datasets.models import DatasetVersion, DataSnapshot
from apps.geography.models import AreaProfileType, City, District, Neighborhood
from apps.network.models import (
    AccessSegment,
    AccessTechnology,
    NetworkDevice,
    NetworkDeviceStatus,
    NetworkDeviceType,
    NetworkLink,
)


def create_snapshot(seed: str = "maltepe-seed-001") -> DataSnapshot:
    dataset = DatasetVersion.objects.create(
        name=f"Maltepe MVP {seed}",
        generator_version="gen-0.1.0",
        seed=seed,
    )
    return DataSnapshot.objects.create(dataset_version=dataset, name="Initial snapshot")


def create_maltepe_location() -> tuple[City, District, Neighborhood]:
    city = City.objects.create(name="İstanbul", plate_code="34")
    district = District.objects.create(
        city=city,
        name="Maltepe",
        profile_type=AreaProfileType.MIXED,
    )
    neighborhood = Neighborhood.objects.create(
        district=district,
        name="Zümrütevler",
        profile_type=AreaProfileType.RESIDENTIAL,
    )
    return city, district, neighborhood


@pytest.mark.django_db
def test_bng_device_can_be_attached_to_maltepe_location():
    snapshot = create_snapshot()
    city, district, neighborhood = create_maltepe_location()

    device = NetworkDevice.objects.create(
        data_snapshot=snapshot,
        code="BNG-MAL-001",
        name="Maltepe BNG 001",
        device_type=NetworkDeviceType.BNG,
        status=NetworkDeviceStatus.ACTIVE,
        vendor="Nokia",
        model_name="7750 SR",
        city=city,
        district=district,
        neighborhood=neighborhood,
        metadata={"mvp_anchor": True},
    )

    assert str(device) == "BNG-MAL-001 (BNG)"
    assert device.display_name == "Maltepe BNG 001"
    assert device.location_name == "İstanbul / Maltepe / Zümrütevler"
    assert device.metadata == {"mvp_anchor": True}


@pytest.mark.django_db
def test_access_segments_store_fiber_vdsl_and_adsl_context():
    snapshot = create_snapshot()
    city, district, _neighborhood = create_maltepe_location()
    bng = NetworkDevice.objects.create(
        data_snapshot=snapshot,
        code="BNG-MAL-001",
        device_type=NetworkDeviceType.BNG,
        city=city,
        district=district,
    )

    fiber_segment = AccessSegment.objects.create(
        data_snapshot=snapshot,
        segment_code="SEG-MAL-FIBER-001",
        name="Maltepe fiber access",
        technology=AccessTechnology.FIBER,
        serving_device=bng,
        city=city,
        district=district,
        estimated_customer_count=1200,
    )
    vdsl_segment = AccessSegment.objects.create(
        data_snapshot=snapshot,
        segment_code="SEG-MAL-VDSL-001",
        name="Maltepe VDSL access",
        technology=AccessTechnology.VDSL,
        serving_device=bng,
        city=city,
        district=district,
        estimated_customer_count=800,
    )

    assert fiber_segment.slug == "seg-mal-fiber-001-maltepe-fiber-access"
    assert fiber_segment.technology == AccessTechnology.FIBER
    assert vdsl_segment.technology == AccessTechnology.VDSL
    assert {choice.value for choice in AccessTechnology} >= {"fiber", "vdsl", "adsl", "gpon"}


@pytest.mark.django_db
def test_device_code_is_unique_per_snapshot_but_reusable_across_snapshots():
    city, district, _neighborhood = create_maltepe_location()
    first_snapshot = create_snapshot("first-seed")
    second_snapshot = create_snapshot("second-seed")

    NetworkDevice.objects.create(
        data_snapshot=first_snapshot,
        code="BNG-MAL-001",
        device_type=NetworkDeviceType.BNG,
        city=city,
        district=district,
    )
    NetworkDevice.objects.create(
        data_snapshot=second_snapshot,
        code="BNG-MAL-001",
        device_type=NetworkDeviceType.BNG,
        city=city,
        district=district,
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            NetworkDevice.objects.create(
                data_snapshot=first_snapshot,
                code="BNG-MAL-001",
                device_type=NetworkDeviceType.BNG,
                city=city,
                district=district,
            )


@pytest.mark.django_db
def test_network_link_connects_two_different_devices():
    snapshot = create_snapshot()
    city, district, _neighborhood = create_maltepe_location()
    bng = NetworkDevice.objects.create(
        data_snapshot=snapshot,
        code="BNG-MAL-001",
        device_type=NetworkDeviceType.BNG,
        city=city,
        district=district,
    )
    olt = NetworkDevice.objects.create(
        data_snapshot=snapshot,
        code="OLT-MAL-001",
        device_type=NetworkDeviceType.OLT,
        city=city,
        district=district,
    )

    link = NetworkLink.objects.create(
        data_snapshot=snapshot,
        link_code="LINK-BNG-MAL-001-OLT-MAL-001",
        source_device=bng,
        target_device=olt,
        capacity_mbps=10000,
    )

    assert str(link) == "LINK-BNG-MAL-001-OLT-MAL-001: BNG-MAL-001 -> OLT-MAL-001"
    assert link.capacity_mbps == 10000

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            NetworkLink.objects.create(
                data_snapshot=snapshot,
                link_code="LINK-SELF",
                source_device=bng,
                target_device=bng,
            )


@pytest.mark.django_db
def test_device_location_chain_is_validated():
    snapshot = create_snapshot()
    istanbul = City.objects.create(name="İstanbul", plate_code="34")
    ankara = City.objects.create(name="Ankara", plate_code="06")
    maltepe = District.objects.create(city=istanbul, name="Maltepe")

    device = NetworkDevice(
        data_snapshot=snapshot,
        code="BNG-MAL-001",
        device_type=NetworkDeviceType.BNG,
        city=ankara,
        district=maltepe,
    )

    with pytest.raises(ValidationError):
        device.full_clean()


@pytest.mark.django_db
def test_segment_and_link_snapshot_consistency_is_validated():
    city, district, _neighborhood = create_maltepe_location()
    first_snapshot = create_snapshot("first-seed")
    second_snapshot = create_snapshot("second-seed")
    bng = NetworkDevice.objects.create(
        data_snapshot=first_snapshot,
        code="BNG-MAL-001",
        device_type=NetworkDeviceType.BNG,
        city=city,
        district=district,
    )
    olt = NetworkDevice.objects.create(
        data_snapshot=first_snapshot,
        code="OLT-MAL-001",
        device_type=NetworkDeviceType.OLT,
        city=city,
        district=district,
    )

    segment = AccessSegment(
        data_snapshot=second_snapshot,
        segment_code="SEG-MAL-FIBER-001",
        name="Maltepe fiber access",
        technology=AccessTechnology.FIBER,
        serving_device=bng,
        city=city,
        district=district,
    )
    link = NetworkLink(
        data_snapshot=second_snapshot,
        link_code="LINK-BNG-MAL-001-OLT-MAL-001",
        source_device=bng,
        target_device=olt,
    )

    with pytest.raises(ValidationError):
        segment.full_clean()
    with pytest.raises(ValidationError):
        link.full_clean()
