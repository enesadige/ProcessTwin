from data_generator.configs import multi_city_realism_v1 as seed_config
from data_generator.seeders.multicity_realism import (
    delete_multicity_realism_dataset_tree,
    parse_reference_datetime,
    seed_multicity_realism_dataset,
)
from data_generator.validators.multicity_realism import validate_multicity_realism_snapshot
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.core.choices import ResultStatus
from apps.datasets.models import DatasetKind, DatasetSnapshotStatus, DatasetVersion, DataSnapshot


class Command(BaseCommand):
    help = "Create or validate the deterministic multi-city realism synthetic dataset."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete and recreate only the multi-city realism dataset.",
        )
        parser.add_argument(
            "--validate-only",
            action="store_true",
            help="Validate the existing multi-city realism snapshot without creating data.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=2000,
            help="Bulk create batch size.",
        )
        parser.add_argument(
            "--reference-datetime",
            default=seed_config.DEFAULT_REFERENCE_DATETIME,
            help="Timezone-aware reference datetime for deterministic generation.",
        )
        parser.add_argument(
            "--dataset-slug",
            help="Create or validate this versioned dataset slug instead of the legacy default.",
        )

    def handle(self, *args, **options):
        reference_datetime = parse_reference_datetime(options["reference_datetime"])
        batch_size = options["batch_size"]
        if batch_size < 1:
            raise CommandError("--batch-size must be positive.")

        dataset_slug = options["dataset_slug"] or seed_config.DATASET_SLUG
        if options["reset"] and options["dataset_slug"]:
            raise CommandError("--reset cannot be used with --dataset-slug.")
        with transaction.atomic():
            dataset = DatasetVersion.objects.filter(slug=dataset_slug).first()
            if options["validate_only"]:
                if dataset is None:
                    raise CommandError("Multi-city realism dataset does not exist.")
                snapshot = dataset.snapshots.order_by("-created_at").first()
                report = validate_multicity_realism_snapshot(snapshot)
                if not report["passed"]:
                    raise CommandError(format_failed_checks(report))
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Validated {dataset.slug} with {report['row_counts']['subscriptions']} "
                        "subscriptions."
                    )
                )
                return

            if dataset and options["reset"]:
                delete_multicity_realism_dataset_tree(dataset)
                dataset = None
            if dataset and not options["reset"]:
                snapshot = dataset.snapshots.order_by("-created_at").first()
                report = validate_multicity_realism_snapshot(snapshot)
                if not report["passed"]:
                    raise CommandError(format_failed_checks(report))
                self.stdout.write(
                    self.style.SUCCESS(
                        "Multi-city realism dataset already exists and is valid; "
                        "no duplicate data was created."
                    )
                )
                return

            source_started_at = timezone.now()
            dataset = DatasetVersion(
                name=seed_config.DATASET_NAME,
                slug=dataset_slug,
                kind=DatasetKind.SYNTHETIC,
                generator_version=seed_config.GENERATOR_VERSION,
                seed=seed_config.DATASET_SEED,
                config=seed_config.build_serializable_config(reference_datetime.isoformat()),
                description=(
                    "Deterministic synthetic multi-city realism dataset. It is not real "
                    "operator inventory, customer, commercial, alarm, incident, or policy data."
                ),
            )
            dataset.full_clean()
            dataset.save()
            snapshot = DataSnapshot(
                dataset_version=dataset,
                name=(
                    seed_config.SNAPSHOT_NAME
                    if dataset_slug == seed_config.DATASET_SLUG
                    else f"{seed_config.SNAPSHOT_NAME} ({dataset_slug})"
                ),
                status=DatasetSnapshotStatus.DRAFT,
                is_active=False,
                source_started_at=source_started_at,
            )
            snapshot.full_clean()
            snapshot.save()
            seed_counts = seed_multicity_realism_dataset(
                snapshot=snapshot,
                batch_size=batch_size,
            )
            report = validate_multicity_realism_snapshot(snapshot, include_final_gate=False)
            if not report["passed"]:
                raise CommandError(format_failed_checks(report))
            snapshot.status = DatasetSnapshotStatus.VALIDATED
            snapshot.validation_status = ResultStatus.EXACT
            snapshot.validation_result = {
                "seed_stage": "039.5.6_multi_city_realism",
                "reference_datetime": reference_datetime.isoformat(),
                "checks": report["checks"],
                "validated": True,
            }
            snapshot.row_counts = report["row_counts"]
            snapshot.source_finished_at = timezone.now()
            snapshot.full_clean()
            snapshot.save()

        self.stdout.write(
            self.style.SUCCESS(
                f"Created {dataset_slug} as passive validated snapshot with "
                f"{seed_counts['customers']} customers, {seed_counts['subscriptions']} "
                f"subscriptions, {seed_counts['alarms']} alarms, and "
                f"{seed_counts['quality_measurements']} quality measurements."
            )
        )


def format_failed_checks(report: dict) -> str:
    failed = [item for item in report["checks"] if not item["passed"]]
    sample = "; ".join(
        f"{item['name']} expected={item['expected']} actual={item['actual']}"
        for item in failed[:10]
    )
    return f"Multi-city realism validation failed: {sample}"
