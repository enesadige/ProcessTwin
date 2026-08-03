import json

from django.core.management.base import BaseCommand, CommandError

from apps.rag.benchmark_manifest import (
    BENCHMARK_CASES,
    DETERMINISTIC_PROFILE,
    SEMANTIC_PROFILE,
)
from apps.rag.providers.registry import DESCRIPTORS
from apps.rag.services.benchmark import run_benchmark

PROFILES = {DETERMINISTIC_PROFILE, SEMANTIC_PROFILE, "all"}


class Command(BaseCommand):
    help = "Run the versioned ProcessTwin RAG retrieval benchmark."

    def add_arguments(self, parser):
        parser.add_argument("--profile", default=DETERMINISTIC_PROFILE)
        parser.add_argument("--format", dest="output_format", default="text")
        parser.add_argument("--case-code", action="append", dest="case_codes")
        parser.add_argument("--category", action="append", dest="categories")
        parser.add_argument(
            "--embedding-provider",
            choices=("gemini", "ollama"),
        )
        parser.add_argument(
            "--embedding-profile",
            choices=sorted(
                key
                for key, descriptor in DESCRIPTORS.items()
                if descriptor.production_semantic_allowed
            ),
        )

    def handle(self, *args, **options):
        selected = self._select_cases(options)
        provider = options["embedding_provider"]
        embedding_profile = options["embedding_profile"]
        if provider and embedding_profile:
            from apps.rag.providers import get_embedding_descriptor

            get_embedding_descriptor(provider, embedding_profile=embedding_profile)
        selection = embedding_profile or provider
        report = (
            run_benchmark(selected, embedding_provider=selection)
            if selection
            else run_benchmark(selected)
        )
        if options["output_format"] == "json":
            self.stdout.write(json.dumps(report, ensure_ascii=False, sort_keys=True))
        else:
            self._write_text(report)
        if not report["success"]:
            raise CommandError("RAG benchmark failed.")

    def _select_cases(self, options):
        profile = options["profile"]
        if profile not in PROFILES:
            raise CommandError(f"Unknown profile: {profile}")
        if options["output_format"] not in {"text", "json"}:
            raise CommandError(f"Unknown format: {options['output_format']}")
        known_codes = {case.case_code for case in BENCHMARK_CASES}
        requested_codes = set(options["case_codes"] or ())
        unknown_codes = requested_codes - known_codes
        if unknown_codes:
            raise CommandError("Unknown case code: " + ", ".join(sorted(unknown_codes)))
        known_categories = {case.category for case in BENCHMARK_CASES}
        requested_categories = set(options["categories"] or ())
        unknown_categories = requested_categories - known_categories
        if unknown_categories:
            raise CommandError("Unknown category: " + ", ".join(sorted(unknown_categories)))
        selected = tuple(
            case
            for case in BENCHMARK_CASES
            if (profile == "all" or case.profile == profile)
            and (not requested_codes or case.case_code in requested_codes)
            and (not requested_categories or case.category in requested_categories)
        )
        if not selected:
            raise CommandError("No benchmark cases matched the requested filters.")
        return selected

    def _write_text(self, report):
        metrics = report["metrics"]
        self.stdout.write(
            f"{report['benchmark_version']}: passed={metrics['passed']}/{metrics['total']} "
            f"hit@1={metrics['hit_at_1']:.3f} hit@3={metrics['hit_at_3']:.3f} "
            f"mrr={metrics['mean_reciprocal_rank']:.3f}"
        )
        for error in report["profile_errors"]:
            self.stdout.write(f"PROFILE ERROR {error['profile']}: {error['message']}")
        for result in report["cases"]:
            status = "PASS" if result["passed"] else "FAIL"
            self.stdout.write(
                f"{status} {result['case_code']} expected={result['expected_document_code']} "
                f"rank={result['actual_rank']} reasons={','.join(result['failure_reasons']) or '-'}"
            )
