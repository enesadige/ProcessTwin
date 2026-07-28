from zoneinfo import ZoneInfo

from data_generator.configs import maltepe_mvp_v1 as seed_config
from data_generator.seeders.customers import seed_customer_subscriptions
from data_generator.seeders.network import seed_network_topology
from data_generator.seeders.operations import seed_operations
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.text import slugify

from apps.core.choices import ResultStatus
from apps.datasets.models import (
    DatasetKind,
    DatasetSnapshotStatus,
    DatasetVersion,
    DataSnapshot,
)
from apps.geography.models import AreaProfileType, City, District, Neighborhood

ISTANBUL_TZ = ZoneInfo("Europe/Istanbul")


class Command(BaseCommand):
    help = (
        "Create the Maltepe MVP dataset, snapshot, geography, network topology, customers, "
        "service packages, subscriptions, subscription connections, and operations records."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--reference-datetime",
            default=seed_config.DEFAULT_REFERENCE_DATETIME,
            help="Timezone-aware reference datetime for repeatable seed generation.",
        )
        parser.add_argument(
            "--activate",
            action="store_true",
            help="Mark the new snapshot active only when no other active snapshot exists.",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete only the deterministic Maltepe MVP dataset before recreating it.",
        )

    def handle(self, *args, **options):
        reference_datetime = parse_reference_datetime(options["reference_datetime"])
        activate = options["activate"]
        reset = options["reset"]
        target_slug = get_target_dataset_slug()

        with transaction.atomic():
            if activate:
                active_snapshots = DataSnapshot.objects.filter(is_active=True)
                if reset:
                    active_snapshots = active_snapshots.exclude(dataset_version__slug=target_slug)
                if active_snapshots.exists():
                    raise CommandError(
                        "Another active data snapshot already exists. "
                        "No snapshot was activated or deactivated."
                    )

            target_dataset = DatasetVersion.objects.filter(slug=target_slug).first()
            if target_dataset and not reset:
                raise CommandError(
                    "Maltepe MVP dataset already exists. Use --reset to recreate only this "
                    "deterministic seed dataset."
                )
            if target_dataset and reset:
                delete_target_dataset_tree(target_dataset)

            source_started_at = timezone.now()
            city, city_created = get_or_create_city()
            district, district_created = get_or_create_district(city)
            neighborhoods, created_neighborhood_count = get_or_create_neighborhoods(district)
            neighborhoods_by_name = {
                neighborhood.name: neighborhood for neighborhood in neighborhoods
            }

            reference_datetime_iso = reference_datetime.isoformat()
            dataset = DatasetVersion(
                name=seed_config.DATASET_NAME,
                kind=DatasetKind.SYNTHETIC,
                generator_version=seed_config.GENERATOR_VERSION,
                seed=seed_config.DATASET_SEED,
                config=seed_config.build_serializable_config(reference_datetime_iso),
                description=(
                    "Deterministic synthetic dataset for the Maltepe MVP scenario. "
                    "Current seed stage creates dataset, snapshot, geography, network topology, "
                    "customer subscription, and operations records."
                ),
            )
            dataset.full_clean()
            dataset.save()
            snapshot = DataSnapshot(
                dataset_version=dataset,
                name=seed_config.SNAPSHOT_NAME,
                status=DatasetSnapshotStatus.VALIDATED,
                is_active=activate,
                source_started_at=source_started_at,
                activated_at=source_started_at if activate else None,
            )
            snapshot.full_clean()
            snapshot.save()

            network_counts = seed_network_topology(
                snapshot=snapshot,
                city=city,
                district=district,
                neighborhoods_by_name=neighborhoods_by_name,
                reference_datetime=reference_datetime,
            )
            customer_counts = seed_customer_subscriptions(
                snapshot=snapshot,
                city=city,
                district=district,
                neighborhoods_by_name=neighborhoods_by_name,
                reference_datetime=reference_datetime,
            )
            operations_counts = seed_operations(snapshot=snapshot)

            row_counts = {
                "dataset_versions": 1,
                "data_snapshots": 1,
                "cities": 1,
                "districts": 1,
                "neighborhoods": len(neighborhoods),
                "network_devices": network_counts["network_devices"],
                "network_links": network_counts["network_links"],
                "network_ports": network_counts["network_ports"],
                "access_segments": network_counts["access_segments"],
                "line_connections": network_counts["line_connections"],
                "customers": customer_counts["customers"],
                "service_packages": customer_counts["service_packages"],
                "subscriptions": customer_counts["subscriptions"],
                "subscription_connections": customer_counts["subscription_connections"],
                "alarm_types": operations_counts["alarm_types"],
                "alarms": operations_counts["alarms"],
                "incidents": operations_counts["incidents"],
                "incident_alarms": operations_counts["incident_alarms"],
                "outages": operations_counts["outages"],
                "operational_events": operations_counts["operational_events"],
                "quality_measurements": operations_counts["quality_measurements"],
            }
            validation_result = {
                "seed_stage": "022_operations",
                "reference_datetime": reference_datetime_iso,
                "created_geography": {
                    "city": city_created,
                    "district": district_created,
                    "neighborhoods": created_neighborhood_count,
                },
                "expected_neighborhoods": seed_config.NEIGHBORHOODS,
                "network_counts": network_counts,
                "customer_counts": customer_counts,
                "operations_counts": operations_counts,
                "validated": True,
            }
            now = timezone.now()
            snapshot.row_counts = row_counts
            snapshot.validation_status = ResultStatus.EXACT
            snapshot.validation_result = validation_result
            snapshot.source_finished_at = now
            if activate:
                snapshot.activated_at = now
            snapshot.full_clean()
            snapshot.save()

        state = "active" if activate else "passive"
        self.stdout.write(
            self.style.SUCCESS(
                f"Created {seed_config.DATASET_NAME} / {seed_config.SNAPSHOT_NAME} "
                f"as {state} snapshot with {len(neighborhoods)} neighborhoods, "
                f"{network_counts['network_devices']} devices, "
                f"{network_counts['network_ports']} ports, and "
                f"{customer_counts['subscriptions']} subscriptions, "
                f"{operations_counts['outages']} outages."
            )
        )


def parse_reference_datetime(value: str):
    parsed = parse_datetime(value)
    if parsed is None:
        raise CommandError("Invalid --reference-datetime value. Use ISO 8601 format.")
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, ISTANBUL_TZ)
    return parsed.astimezone(ISTANBUL_TZ)


def get_target_dataset_slug() -> str:
    return slugify(
        f"{seed_config.DATASET_NAME}-{seed_config.GENERATOR_VERSION}-{seed_config.DATASET_SEED}"
    )


def delete_target_dataset_tree(dataset: DatasetVersion) -> None:
    from apps.customers.models import (
        CampaignEnrollment,
        CompensationHistory,
        Customer,
        PaymentRecord,
        ServicePackage,
        Subscription,
        SubscriptionConnection,
    )
    from apps.network.models import (
        AccessSegment,
        LineConnection,
        NetworkDevice,
        NetworkLink,
        NetworkPort,
    )
    from apps.operations.models import (
        Alarm,
        AlarmType,
        Incident,
        IncidentAlarm,
        OperationalEvent,
        Outage,
        QualityMeasurement,
    )

    snapshots = list(dataset.snapshots.all())
    for snapshot in snapshots:
        QualityMeasurement.objects.filter(data_snapshot=snapshot).delete()
        Outage.objects.filter(data_snapshot=snapshot).delete()
        OperationalEvent.objects.filter(data_snapshot=snapshot).delete()
        IncidentAlarm.objects.filter(data_snapshot=snapshot).delete()
        Alarm.objects.filter(data_snapshot=snapshot).delete()
        Incident.objects.filter(data_snapshot=snapshot).delete()
        AlarmType.objects.filter(data_snapshot=snapshot).delete()
        CompensationHistory.objects.filter(data_snapshot=snapshot).delete()
        CampaignEnrollment.objects.filter(data_snapshot=snapshot).delete()
        PaymentRecord.objects.filter(data_snapshot=snapshot).delete()
        SubscriptionConnection.objects.filter(data_snapshot=snapshot).delete()
        Subscription.objects.filter(data_snapshot=snapshot).delete()
        ServicePackage.objects.filter(data_snapshot=snapshot).delete()
        Customer.objects.filter(data_snapshot=snapshot).delete()
        LineConnection.objects.filter(data_snapshot=snapshot).delete()
        NetworkLink.objects.filter(data_snapshot=snapshot).delete()
        NetworkPort.objects.filter(data_snapshot=snapshot).delete()
        AccessSegment.objects.filter(data_snapshot=snapshot).delete()
        NetworkDevice.objects.filter(data_snapshot=snapshot).delete()
    dataset.delete()


def get_or_create_city() -> tuple[City, bool]:
    city = City.objects.filter(
        name=seed_config.CITY["name"],
        country_code=seed_config.CITY["country_code"],
    ).first()
    if city:
        return city, False
    city = City(
        name=seed_config.CITY["name"],
        country_code=seed_config.CITY["country_code"],
        plate_code=seed_config.CITY["plate_code"],
    )
    city.full_clean()
    city.save()
    return city, True


def get_or_create_district(city: City) -> tuple[District, bool]:
    district = District.objects.filter(city=city, name=seed_config.DISTRICT["name"]).first()
    if district:
        return district, False
    district = District(
        city=city,
        name=seed_config.DISTRICT["name"],
        profile_type=AreaProfileType(seed_config.DISTRICT["profile_type"]),
    )
    district.full_clean()
    district.save()
    return district, True


def get_or_create_neighborhoods(district: District) -> tuple[list[Neighborhood], int]:
    neighborhoods = []
    created_count = 0
    for name in seed_config.NEIGHBORHOODS:
        neighborhood = Neighborhood.objects.filter(district=district, name=name).first()
        if neighborhood:
            neighborhoods.append(neighborhood)
            continue
        neighborhood = Neighborhood(district=district, name=name)
        neighborhood.full_clean()
        neighborhood.save()
        neighborhoods.append(neighborhood)
        created_count += 1
    return neighborhoods, created_count
