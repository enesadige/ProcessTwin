"""Seed one idempotent, bounded cross-region correlation scenario for local acceptance."""

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.datasets.models import DataSnapshot
from apps.geography.models import City, District
from apps.network.models import NetworkDevice, NetworkDeviceType, NetworkLink
from apps.operations.contracts import CausalEventStatus, CausalEventType, EventOrigin
from apps.operations.models import (
    Alarm,
    AlarmCategory,
    AlarmStatus,
    AlarmType,
    CausalEvent,
    ServiceImpactClass,
    Severity,
)


class Command(BaseCommand):
    help = "Seed a minimal deterministic cross-region correlation acceptance scenario."

    def add_arguments(self, parser):
        parser.add_argument("--snapshot", required=True)

    def handle(self, *args, **options):
        snapshot = DataSnapshot.objects.filter(snapshot_key=options["snapshot"]).first()
        if snapshot is None:
            raise CommandError("Snapshot was not found.")
        ankara, _ = City.objects.get_or_create(
            name="Correlation Ankara", defaults={"plate_code": "06"}
        )
        izmir, _ = City.objects.get_or_create(
            name="Correlation Izmir", defaults={"plate_code": "35"}
        )
        ankara_district, _ = District.objects.get_or_create(city=ankara, name="Correlation Center")
        izmir_district, _ = District.objects.get_or_create(city=izmir, name="Correlation Center")
        upstream, _ = NetworkDevice.objects.get_or_create(
            data_snapshot=snapshot,
            code="BNG-XREG-001",
            defaults={
                "name": "Cross-region upstream",
                "device_type": NetworkDeviceType.BNG,
                "city": ankara,
                "district": ankara_district,
            },
        )
        downstream, _ = NetworkDevice.objects.get_or_create(
            data_snapshot=snapshot,
            code="OLT-XREG-001",
            defaults={
                "name": "Cross-region downstream",
                "device_type": NetworkDeviceType.OLT,
                "city": izmir,
                "district": izmir_district,
            },
        )
        unrelated, _ = NetworkDevice.objects.get_or_create(
            data_snapshot=snapshot,
            code="BNG-XREG-002",
            defaults={
                "name": "Independent correlation control",
                "device_type": NetworkDeviceType.BNG,
                "city": ankara,
                "district": ankara_district,
            },
        )
        NetworkLink.objects.get_or_create(
            data_snapshot=snapshot,
            link_code="LNK-XREG-001",
            defaults={
                "source_device": upstream,
                "target_device": downstream,
                "capacity_mbps": 10000,
            },
        )
        alarm_type, _ = AlarmType.objects.get_or_create(
            data_snapshot=snapshot,
            code="XREG_UPSTREAM_DOWN",
            defaults={
                "name": "Cross-region upstream down",
                "severity": Severity.CRITICAL,
                "category": AlarmCategory.CORE,
                "service_impact_class": ServiceImpactClass.PARTIAL_OUTAGE,
                "correlation_family": "cross_region_access",
                "is_root_candidate": True,
            },
        )
        reference = snapshot.dataset_version.config.get("reference_datetime")
        started = timezone.now().replace(second=0, microsecond=0)
        if isinstance(reference, str):
            try:
                started = timezone.datetime.fromisoformat(reference.replace("Z", "+00:00"))
            except ValueError:
                pass
        anchor, _ = CausalEvent.objects.get_or_create(
            data_snapshot=snapshot,
            event_code="CE-XREG-0001",
            defaults={
                "event_type": CausalEventType.DEVICE_FAILURE,
                "status": CausalEventStatus.RESOLVED,
                "started_at": started,
                "ended_at": started + timedelta(minutes=20),
                "source_system": "cross-correlation-seed",
                "origin": EventOrigin.SYNTHETIC,
                "root_device": upstream,
            },
        )
        candidate, _ = CausalEvent.objects.get_or_create(
            data_snapshot=snapshot,
            event_code="CE-XREG-0002",
            defaults={
                "event_type": CausalEventType.DEVICE_FAILURE,
                "status": CausalEventStatus.RESOLVED,
                "started_at": started + timedelta(minutes=37),
                "ended_at": started + timedelta(minutes=57),
                "source_system": "cross-correlation-seed",
                "origin": EventOrigin.SYNTHETIC,
                "root_device": downstream,
            },
        )
        temporal_only, _ = CausalEvent.objects.get_or_create(
            data_snapshot=snapshot,
            event_code="CE-XREG-0003",
            defaults={
                "event_type": CausalEventType.DEVICE_FAILURE,
                "status": CausalEventStatus.RESOLVED,
                "started_at": started + timedelta(minutes=10),
                "ended_at": started + timedelta(minutes=30),
                "source_system": "cross-correlation-seed",
                "origin": EventOrigin.SYNTHETIC,
                "root_device": unrelated,
            },
        )
        Alarm.objects.get_or_create(
            data_snapshot=snapshot,
            alarm_id="ALM-XREG-0001",
            defaults={
                "causal_event": anchor,
                "alarm_type": alarm_type,
                "device": upstream,
                "severity": Severity.CRITICAL,
                "status": AlarmStatus.CLEARED,
                "detected_at": anchor.started_at,
                "cleared_at": anchor.started_at + timedelta(minutes=20),
            },
        )
        Alarm.objects.get_or_create(
            data_snapshot=snapshot,
            alarm_id="ALM-XREG-0002",
            defaults={
                "causal_event": candidate,
                "alarm_type": alarm_type,
                "device": downstream,
                "severity": Severity.CRITICAL,
                "status": AlarmStatus.CLEARED,
                "detected_at": candidate.started_at,
                "cleared_at": candidate.started_at + timedelta(minutes=20),
            },
        )
        Alarm.objects.get_or_create(
            data_snapshot=snapshot,
            alarm_id="ALM-XREG-0003",
            defaults={
                "causal_event": temporal_only,
                "alarm_type": alarm_type,
                "device": unrelated,
                "severity": Severity.CRITICAL,
                "status": AlarmStatus.CLEARED,
                "detected_at": temporal_only.started_at,
                "cleared_at": temporal_only.started_at + timedelta(minutes=20),
            },
        )
        self.stdout.write(
            self.style.SUCCESS("Seeded CE-XREG-0001, CE-XREG-0002 and CE-XREG-0003.")
        )
