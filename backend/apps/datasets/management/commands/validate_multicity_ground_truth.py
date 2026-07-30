import json

from data_generator.configs import multi_city_realism_v1 as dataset_config
from data_generator.configs import multicity_ground_truth_v1 as gt_config
from data_generator.seeders.multicity_ground_truth import seed_multicity_ground_truth
from data_generator.validators.multicity_ground_truth import validate_multicity_ground_truth
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.datasets.models import DataSnapshot


class Command(BaseCommand):
    help = "Seed and validate deterministic ground-truth cases for multi-city realism."

    def add_arguments(self, parser):
        parser.add_argument(
            "--case-code",
            help="Run a single ground-truth case by code.",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="Print a machine-readable validation summary.",
        )

    def handle(self, *args, **options):
        snapshot = (
            DataSnapshot.objects.select_related("dataset_version")
            .filter(dataset_version__slug=dataset_config.DATASET_SLUG)
            .first()
        )
        if snapshot is None:
            raise CommandError("multi-city-realism-v1 snapshot does not exist.")

        case_code = options.get("case_code")
        if case_code and case_code not in {
            item["case_code"] for item in gt_config.GROUND_TRUTH_CASES
        }:
            raise CommandError(f"Unknown ground-truth case code: {case_code}")

        with transaction.atomic():
            seed_multicity_ground_truth(snapshot)
            report = validate_multicity_ground_truth(snapshot, case_code=case_code)
            if not report["passed"]:
                raise CommandError(format_failed_checks(report, as_json=options["json"]))

        if options["json"]:
            self.stdout.write(
                json.dumps(
                    {
                        "passed": True,
                        "case_count": report["case_count"],
                        "failed_count": 0,
                    },
                    default=str,
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return
        self.stdout.write(
            self.style.SUCCESS(f"Validated {report['case_count']} multi-city ground-truth case(s).")
        )


def format_failed_checks(report: dict, *, as_json: bool) -> str:
    failed = report["failed"]
    if as_json:
        return json.dumps(
            {
                "passed": False,
                "case_count": report["case_count"],
                "failed_count": len(failed),
                "failed": failed[:20],
            },
            default=str,
            ensure_ascii=False,
            sort_keys=True,
        )
    sample = "; ".join(
        f"{item['name']} expected={item['expected']} actual={item['actual']}"
        for item in failed[:10]
    )
    return f"Multi-city ground-truth validation failed: {sample}"
