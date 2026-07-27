from zoneinfo import ZoneInfo

from data_generator.configs import maltepe_mvp_v1 as seed_config
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
    help = "Create the base Maltepe MVP dataset, snapshot, and geography records."

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
                target_dataset.delete()

            source_started_at = timezone.now()
            city, city_created = get_or_create_city()
            district, district_created = get_or_create_district(city)
            neighborhoods, created_neighborhood_count = get_or_create_neighborhoods(district)

            reference_datetime_iso = reference_datetime.isoformat()
            dataset = DatasetVersion(
                name=seed_config.DATASET_NAME,
                kind=DatasetKind.SYNTHETIC,
                generator_version=seed_config.GENERATOR_VERSION,
                seed=seed_config.DATASET_SEED,
                config=seed_config.build_serializable_config(reference_datetime_iso),
                description=(
                    "Deterministic synthetic base dataset for the Maltepe MVP scenario. "
                    "This command creates only dataset, snapshot, and geography records."
                ),
            )
            dataset.full_clean()
            dataset.save()

            row_counts = {
                "dataset_versions": 1,
                "data_snapshots": 1,
                "cities": 1,
                "districts": 1,
                "neighborhoods": len(neighborhoods),
                "network_devices": 0,
                "network_links": 0,
                "network_ports": 0,
                "access_segments": 0,
                "line_connections": 0,
                "customers": 0,
                "service_packages": 0,
                "subscriptions": 0,
                "subscription_connections": 0,
                "alarms": 0,
                "incidents": 0,
                "outages": 0,
                "operational_events": 0,
            }
            validation_result = {
                "seed_stage": "019_base_dataset_geography",
                "reference_datetime": reference_datetime_iso,
                "created_geography": {
                    "city": city_created,
                    "district": district_created,
                    "neighborhoods": created_neighborhood_count,
                },
                "expected_neighborhoods": seed_config.NEIGHBORHOODS,
                "validated": True,
            }
            now = timezone.now()
            snapshot = DataSnapshot(
                dataset_version=dataset,
                name=seed_config.SNAPSHOT_NAME,
                status=DatasetSnapshotStatus.VALIDATED,
                is_active=activate,
                row_counts=row_counts,
                validation_status=ResultStatus.EXACT,
                validation_result=validation_result,
                source_started_at=source_started_at,
                source_finished_at=now,
                activated_at=now if activate else None,
            )
            snapshot.full_clean()
            snapshot.save()

        state = "active" if activate else "passive"
        self.stdout.write(
            self.style.SUCCESS(
                f"Created {seed_config.DATASET_NAME} / {seed_config.SNAPSHOT_NAME} "
                f"as {state} snapshot with {len(neighborhoods)} neighborhoods."
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
