from pathlib import Path

from data_generator.exporters.synthetic_review_pack import (
    ExportOptions,
    export_synthetic_review_pack,
)
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


class Command(BaseCommand):
    help = "Export a read-only synthetic data review pack for external data-model review."

    def add_arguments(self, parser):
        parser.add_argument("--snapshot-key", help="Explicit DataSnapshot.snapshot_key to export.")
        parser.add_argument(
            "--dataset-slug", help="DatasetVersion.slug to resolve to one snapshot."
        )
        parser.add_argument(
            "--output-dir",
            required=True,
            help="Output directory for the review pack.",
        )
        parser.add_argument(
            "--sample-size",
            type=int,
            default=50,
            help="Maximum sample rows per table.",
        )
        parser.add_argument(
            "--include-full-data",
            action="store_true",
            help="Export full synthetic table data in addition to samples.",
        )
        parser.add_argument(
            "--include-maltepe-regression",
            action="store_true",
            help="Also export the active Maltepe regression snapshot in a separate folder.",
        )
        parser.add_argument("--zip", action="store_true", help="Create a zip archive.")
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Overwrite the output directory or zip if they already exist.",
        )

    def handle(self, *args, **options):
        try:
            result = export_synthetic_review_pack(
                ExportOptions(
                    snapshot_key=options.get("snapshot_key"),
                    dataset_slug=options.get("dataset_slug"),
                    output_dir=Path(options["output_dir"]),
                    sample_size=options["sample_size"],
                    include_full_data=options["include_full_data"],
                    include_maltepe_regression=options["include_maltepe_regression"],
                    make_zip=options["zip"],
                    overwrite=options["overwrite"],
                    progress=self.write_progress,
                )
            )
        except (FileExistsError, ValidationError, ValueError) as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                "Exported synthetic review pack "
                f"for {result.dataset_slug}/{result.snapshot_key} to {result.output_dir}."
            )
        )
        if result.zip_path:
            self.stdout.write(f"Zip: {result.zip_path} ({result.zip_size_bytes} bytes)")
        self.stdout.write(f"CSV files: {result.csv_count}")
        self.stdout.write(f"CSV rows: {result.total_csv_rows}")
        self.stdout.write(f"XLSX created: {result.xlsx_created}")
        self.stdout.write(f"DB counts unchanged: {result.db_counts_unchanged}")
        if result.inconsistencies:
            self.stdout.write(self.style.WARNING("Inconsistencies:"))
            for item in result.inconsistencies:
                self.stdout.write(f"- {item}")

    def write_progress(self, message: str) -> None:
        timestamp = timezone.now().isoformat(timespec="seconds")
        self.stdout.write(f"[{timestamp}] {message}")
