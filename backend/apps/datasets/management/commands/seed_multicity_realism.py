import json

from data_generator.configs import multi_city_realism_v1 as seed_config
from data_generator.seeders.multicity_realism import (
    delete_multicity_realism_dataset_tree,
    parse_reference_datetime,
    reconcile_multicity_ground_truth_links,
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
        parser.add_argument(
            "--reconcile-ground-truth",
            action="store_true",
            help="Repair scenario resource links in an existing snapshot without reseeding it.",
        )
        parser.add_argument(
            "--checkpointed-v3",
            action="store_true",
            help="Build the resumable multi-city V3 candidate from an immutable source snapshot.",
        )
        parser.add_argument(
            "--resume",
            action="store_true",
            help="Resume a checkpointed V3 candidate from its last committed event.",
        )
        parser.add_argument(
            "--status",
            action="store_true",
            help="Print persisted checkpointed V3 progress without writing data.",
        )
        parser.add_argument(
            "--source-snapshot-id",
            type=int,
            default=54,
            help="Immutable source snapshot for a checkpointed V3 candidate.",
        )
        parser.add_argument(
            "--preview-v3-schedule",
            action="store_true",
            help=(
                "Print the static checkpointed V3 schedule without accessing or writing a snapshot."
            ),
        )
        parser.add_argument(
            "--repair-v3",
            action="store_true",
            help="Create or resume the checkpointed V3 repair revision from snapshot 73.",
        )
        parser.add_argument(
            "--repair-resume",
            action="store_true",
            help="Resume a checkpointed V3 repair revision.",
        )
        parser.add_argument(
            "--repair-status",
            action="store_true",
            help="Print persisted checkpointed V3 repair progress without writing data.",
        )
        parser.add_argument(
            "--repair-source-snapshot-id",
            type=int,
            default=73,
            help="Validated V3 source snapshot for the repair revision.",
        )

    def handle(self, *args, **options):
        if options["preview_v3_schedule"]:
            from data_generator.seeders.causal_timeline import timeline_schedule_preview

            self.stdout.write(json.dumps(timeline_schedule_preview(), ensure_ascii=False, indent=2))
            return
        if options["repair_v3"] or options["repair_resume"] or options["repair_status"]:
            return self._handle_v3_repair(**options)
        if options["checkpointed_v3"] or options["status"] or options["resume"]:
            return self._handle_checkpointed_v3(**options)
        reference_datetime = parse_reference_datetime(options["reference_datetime"])
        batch_size = options["batch_size"]
        if batch_size < 1:
            raise CommandError("--batch-size must be positive.")

        dataset_slug = options["dataset_slug"] or seed_config.DATASET_SLUG
        if options["reset"] and options["dataset_slug"]:
            raise CommandError("--reset cannot be used with --dataset-slug.")
        with transaction.atomic():
            dataset = DatasetVersion.objects.filter(slug=dataset_slug).first()
            if options["reconcile_ground_truth"]:
                if dataset is None:
                    raise CommandError("Multi-city realism dataset does not exist.")
                snapshot = dataset.snapshots.order_by("-created_at").first()
                result = reconcile_multicity_ground_truth_links(snapshot)
                self.stdout.write(self.style.SUCCESS(str(result)))
                return
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

    def _handle_checkpointed_v3(self, **options):
        from data_generator.seeders.checkpointed_v3 import (
            initialize_run,
            resume_or_build,
            status,
        )

        dataset_slug = options.get("dataset_slug") or "multi-city-realism-v3"
        dataset = DatasetVersion.objects.filter(slug=dataset_slug).first()
        if options["status"]:
            if dataset is None:
                raise CommandError(f"Checkpointed V3 dataset {dataset_slug} does not exist.")
            snapshot = dataset.snapshots.order_by("-created_at").first()
            self.stdout.write(
                json.dumps(status(snapshot), ensure_ascii=False, indent=2, default=str)
            )
            return
        if not options["checkpointed_v3"]:
            raise CommandError("--resume requires --checkpointed-v3.")
        source = DataSnapshot.objects.filter(pk=options["source_snapshot_id"]).first()
        if source is None:
            raise CommandError("Source snapshot does not exist.")
        if dataset is None:
            with transaction.atomic():
                dataset = DatasetVersion.objects.create(
                    name="Multi-city Realism Dataset v3",
                    slug=dataset_slug,
                    kind=DatasetKind.SYNTHETIC,
                    generator_version="multi-city-realism-generator-v3-checkpointed",
                    seed="multi-city-realism-v3-fixed-seed",
                    config={
                        **source.dataset_version.config,
                        "source_snapshot_id": source.id,
                        "dataset_slug": dataset_slug,
                        "generator_version": "multi-city-realism-generator-v3-checkpointed",
                        "seed": "multi-city-realism-v3-fixed-seed",
                    },
                    description=(
                        "Checkpointed synthetic V3 candidate cloned from an immutable "
                        "accepted base world."
                    ),
                )
                snapshot = DataSnapshot.objects.create(
                    dataset_version=dataset,
                    name="Multi-city Realism Snapshot v3",
                    status=DatasetSnapshotStatus.DRAFT,
                    is_active=False,
                    source_started_at=timezone.now(),
                )
                initialize_run(snapshot=snapshot, source=source)
        else:
            snapshot = dataset.snapshots.order_by("-created_at").first()
            if not options["resume"]:
                raise CommandError("Candidate already exists; use --resume or --status.")
        resume_or_build(
            snapshot=snapshot,
            source=source,
            batch_size=options["batch_size"],
            stdout=self.stdout,
        )

    def _handle_v3_repair(self, **options):
        from data_generator.seeders.v3_repair import initialize, run, status

        dataset_slug = options.get("dataset_slug") or "multi-city-realism-v3-repair-r1"
        dataset = DatasetVersion.objects.filter(slug=dataset_slug).first()
        if options["repair_status"]:
            if dataset is None:
                raise CommandError(f"Checkpointed V3 repair dataset {dataset_slug} does not exist.")
            snapshot = dataset.snapshots.order_by("-created_at").first()
            self.stdout.write(
                json.dumps(status(snapshot), ensure_ascii=False, indent=2, default=str)
            )
            return
        if not options["repair_v3"]:
            raise CommandError("--repair-resume requires --repair-v3.")
        source = DataSnapshot.objects.filter(pk=options["repair_source_snapshot_id"]).first()
        if source is None:
            raise CommandError("Repair source snapshot does not exist.")
        if source.status != DatasetSnapshotStatus.VALIDATED or source.is_active:
            raise CommandError("Repair source must be a validated inactive snapshot.")
        if dataset is None:
            with transaction.atomic():
                dataset = DatasetVersion.objects.create(
                    name="Multi-city Realism Dataset v3 Repair r1",
                    slug=dataset_slug,
                    kind=DatasetKind.SYNTHETIC,
                    generator_version="multi-city-realism-v3-repair-r1",
                    seed="multi-city-realism-v3-fixed-seed",
                    config={
                        **source.dataset_version.config,
                        "repair_source_snapshot_id": source.id,
                        "dataset_slug": dataset_slug,
                        "generator_version": "multi-city-realism-v3-repair-r1",
                    },
                    description=(
                        "Inactive repair revision of a validated V3 candidate. "
                        "It preserves the base world and operational timeline while repairing "
                        "hitless evidence and compensation persistence."
                    ),
                )
                snapshot = DataSnapshot.objects.create(
                    dataset_version=dataset,
                    name="Multi-city Realism Snapshot v3 Repair r1",
                    status=DatasetSnapshotStatus.DRAFT,
                    is_active=False,
                    source_started_at=timezone.now(),
                )
                initialize(snapshot=snapshot, source=source)
        else:
            snapshot = dataset.snapshots.order_by("-created_at").first()
            if not options["repair_resume"]:
                raise CommandError(
                    "Repair candidate already exists; use --repair-v3 --repair-resume."
                )
        run(snapshot=snapshot, source=source, batch_size=options["batch_size"], stdout=self.stdout)


def format_failed_checks(report: dict) -> str:
    failed = [item for item in report["checks"] if not item["passed"]]
    sample = "; ".join(
        f"{item['name']} expected={item['expected']} actual={item['actual']}"
        for item in failed[:10]
    )
    return f"Multi-city realism validation failed: {sample}"
