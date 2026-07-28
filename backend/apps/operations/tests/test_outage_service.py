from datetime import datetime, timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.datasets.management.commands.seed_maltepe_mvp import get_target_dataset_slug
from apps.datasets.models import DatasetVersion
from apps.network.models import NetworkDevice
from apps.operations.models import Outage, OutageStatus, OutageType
from apps.operations.services.outages import OutageService, OutageServiceInputError


@pytest.mark.django_db
def test_outage_service_calculates_main_bng_duration_in_exact_seconds_and_minutes():
    snapshot = seed_snapshot()
    outage = get_outage(snapshot, "OUT-MAL-BNG-001")

    duration = OutageService().calculate_duration(outage=outage)

    assert duration.seconds == 12000
    assert duration.minutes == 200
    assert duration.is_ongoing is False


@pytest.mark.django_db
def test_outage_service_calculates_short_olt_and_dslam_outages():
    snapshot = seed_snapshot()
    service = OutageService()

    olt_duration = service.calculate_duration(outage=get_outage(snapshot, "OUT-MAL-OLT-001"))
    dslam_duration = service.calculate_duration(
        outage=get_outage(snapshot, "OUT-MAL-DSLAM-001")
    )

    assert olt_duration.seconds == 2700
    assert olt_duration.minutes == 45
    assert olt_duration.is_ongoing is False
    assert dslam_duration.seconds == 4200
    assert dslam_duration.minutes == 70
    assert dslam_duration.is_ongoing is False


@pytest.mark.django_db
def test_outage_service_calculates_ongoing_outage_with_explicit_evaluation_time():
    snapshot = seed_snapshot()
    source_device = NetworkDevice.objects.get(data_snapshot=snapshot, code="BNG-MAL-001")
    started_at = timezone.datetime(2026, 7, 20, 10, 15, tzinfo=timezone.get_current_timezone())
    outage = Outage.objects.create(
        data_snapshot=snapshot,
        outage_code="OUT-MAL-ONGOING-001",
        source_device=source_device,
        outage_type=OutageType.DEVICE,
        status=OutageStatus.OPEN,
        detected_at=started_at,
        started_at=started_at,
    )

    duration = OutageService().calculate_duration(
        outage=outage,
        evaluation_time=started_at + timedelta(minutes=95, seconds=30),
    )

    assert duration.seconds == 5730
    assert duration.minutes == 95
    assert duration.is_ongoing is True


@pytest.mark.django_db
def test_outage_service_rejects_ongoing_outage_without_evaluation_time():
    snapshot = seed_snapshot()
    source_device = NetworkDevice.objects.get(data_snapshot=snapshot, code="BNG-MAL-001")
    started_at = timezone.now()
    outage = Outage.objects.create(
        data_snapshot=snapshot,
        outage_code="OUT-MAL-ONGOING-001",
        source_device=source_device,
        outage_type=OutageType.DEVICE,
        status=OutageStatus.OPEN,
        detected_at=started_at,
        started_at=started_at,
    )

    with pytest.raises(OutageServiceInputError, match="evaluation_time is required"):
        OutageService().calculate_duration(outage=outage)


@pytest.mark.django_db
def test_outage_service_rejects_naive_evaluation_time():
    snapshot = seed_snapshot()
    source_device = NetworkDevice.objects.get(data_snapshot=snapshot, code="BNG-MAL-001")
    started_at = timezone.now()
    outage = Outage.objects.create(
        data_snapshot=snapshot,
        outage_code="OUT-MAL-ONGOING-001",
        source_device=source_device,
        outage_type=OutageType.DEVICE,
        status=OutageStatus.OPEN,
        detected_at=started_at,
        started_at=started_at,
    )

    with pytest.raises(OutageServiceInputError, match="timezone-aware"):
        OutageService().calculate_duration(
            outage=outage,
            evaluation_time=datetime(2026, 7, 20, 10, 30),
        )


@pytest.mark.django_db
def test_outage_service_rejects_negative_closed_duration():
    snapshot = seed_snapshot()
    outage = get_outage(snapshot, "OUT-MAL-BNG-001")
    outage.ended_at = outage.started_at - timedelta(seconds=1)

    with pytest.raises(OutageServiceInputError, match="ended_at must be later"):
        OutageService().calculate_duration(outage=outage)


@pytest.mark.django_db
def test_outage_service_rejects_evaluation_time_before_start():
    snapshot = seed_snapshot()
    source_device = NetworkDevice.objects.get(data_snapshot=snapshot, code="BNG-MAL-001")
    started_at = timezone.now()
    outage = Outage.objects.create(
        data_snapshot=snapshot,
        outage_code="OUT-MAL-ONGOING-001",
        source_device=source_device,
        outage_type=OutageType.DEVICE,
        status=OutageStatus.OPEN,
        detected_at=started_at,
        started_at=started_at,
    )

    with pytest.raises(OutageServiceInputError, match="earlier than outage started_at"):
        OutageService().calculate_duration(
            outage=outage,
            evaluation_time=started_at - timedelta(seconds=1),
        )


@pytest.mark.django_db
def test_outage_service_reports_ongoing_status_without_using_system_clock():
    snapshot = seed_snapshot()
    closed_outage = get_outage(snapshot, "OUT-MAL-BNG-001")
    source_device = NetworkDevice.objects.get(data_snapshot=snapshot, code="BNG-MAL-001")
    started_at = timezone.now()
    ongoing_outage = Outage.objects.create(
        data_snapshot=snapshot,
        outage_code="OUT-MAL-ONGOING-001",
        source_device=source_device,
        outage_type=OutageType.DEVICE,
        status=OutageStatus.OPEN,
        detected_at=started_at,
        started_at=started_at,
    )

    service = OutageService()

    assert service.is_ongoing(closed_outage) is False
    assert service.is_ongoing(ongoing_outage) is True


def seed_snapshot():
    call_command("seed_maltepe_mvp")
    return DatasetVersion.objects.get(slug=get_target_dataset_slug()).snapshots.get()


def get_outage(snapshot, outage_code: str) -> Outage:
    return Outage.objects.get(data_snapshot=snapshot, outage_code=outage_code)
