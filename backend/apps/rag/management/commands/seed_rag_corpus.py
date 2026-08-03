from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.datasets.models import DataSnapshot, GroundTruthCase
from apps.operations.models import AlarmType
from apps.rag.corpus_manifest import (
    CORPUS_KEY,
    DOCUMENTS,
    PROJECT_ROOT,
    SYNTHETIC_NOTICE,
    get_document_metadata,
)
from apps.rag.corpus_utils import content_hash, normalize_markdown
from apps.rag.models import DocumentChunk, SourceDocument
from apps.rules.models import Rule

LOCAL_TZ = ZoneInfo("Europe/Istanbul")
ALLOWED_CORPUS_ROOTS = tuple(
    (PROJECT_ROOT / directory).resolve()
    for directory in (
        "documents/rules",
        "documents/procedures",
        "documents/alarm_catalog",
        "documents/compensation",
    )
)


def parse_datetime(value):
    if value is None:
        return None
    return datetime.fromisoformat(value).astimezone(LOCAL_TZ)


def is_under_allowed_root(path: Path) -> bool:
    resolved = path.resolve()
    return any(resolved == root or root in resolved.parents for root in ALLOWED_CORPUS_ROOTS)


class Command(BaseCommand):
    help = "Validate and seed the deterministic synthetic RAG source corpus."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true")
        parser.add_argument("--validate-only", action="store_true")

    def handle(self, *args, **options):
        if options["reset"] and options["validate_only"]:
            raise CommandError("--reset and --validate-only cannot be used together.")

        resolved = validate_corpus()
        if options["validate_only"]:
            validate_existing_documents(resolved)
            self.stdout.write(self.style.SUCCESS("RAG corpus validation passed."))
            return

        with transaction.atomic():
            if options["reset"]:
                SourceDocument.objects.filter(metadata__corpus_key=CORPUS_KEY).delete()
            created, unchanged = seed_documents(resolved)

        self.stdout.write(
            self.style.SUCCESS(
                "RAG corpus ready: "
                f"created={created}, unchanged={unchanged}, total={len(DOCUMENTS)}."
            )
        )


def validate_corpus():
    if len(DOCUMENTS) != 10:
        raise CommandError(f"Expected exactly 10 corpus documents, found {len(DOCUMENTS)}.")
    codes = [item["document_code"] for item in DOCUMENTS]
    if len(codes) != len(set(codes)):
        raise CommandError("Document codes must be unique.")

    resolved = []
    for descriptor in DOCUMENTS:
        path = (PROJECT_ROOT / descriptor["file_path"]).resolve()
        if not is_under_allowed_root(path):
            raise CommandError(
                f"Corpus file is outside an allowed directory: {descriptor['file_path']}"
            )
        if not path.is_file():
            raise CommandError(f"Corpus file not found: {descriptor['file_path']}")
        content = normalize_markdown(path.read_text(encoding="utf-8"))
        if SYNTHETIC_NOTICE not in content:
            raise CommandError(f"Synthetic notice missing: {descriptor['document_code']}")
        if descriptor["language"] != "tr" or descriptor["source_kind"] != "synthetic":
            raise CommandError(f"Invalid language/source kind: {descriptor['document_code']}")
        if descriptor["scope_type"] == "global" and descriptor["snapshot_identifier"] is not None:
            raise CommandError(
                f"Global document must not have a snapshot: {descriptor['document_code']}"
            )
        if descriptor["scope_type"] != "global" and not descriptor["snapshot_identifier"]:
            raise CommandError(
                f"Snapshot document requires an exact snapshot key: {descriptor['document_code']}"
            )
        resolved.append((descriptor, path, content, content_hash(content)))

    multicity = resolve_snapshot("multi-city-realism-v1-multi-city-realism-snapshot-v1")
    maltepe = resolve_snapshot(
        "maltepe-mvp-synthetic-dataset-maltepe-mvp-v1-maltepe-mvp-fixed-seed-v1-"
        "maltepe-mvp-snapshot"
    )
    actual_rules = set(Rule.objects.filter(data_snapshot=multicity).values_list("code", flat=True))
    manifest_rules = {
        code for item in DOCUMENTS for code in item["rule_refs"] if code != "REFUND-001"
    }
    if actual_rules != manifest_rules:
        raise CommandError(format_difference("rule", actual_rules, manifest_rules))
    actual_alarms = set(
        AlarmType.objects.filter(data_snapshot=multicity).values_list("code", flat=True)
    )
    manifest_alarms = {code for item in DOCUMENTS for code in item["alarm_refs"]}
    if actual_alarms != manifest_alarms:
        raise CommandError(format_difference("alarm", actual_alarms, manifest_alarms))
    actual_cases = set(
        GroundTruthCase.objects.filter(data_snapshot=multicity).values_list("case_code", flat=True)
    )
    manifest_cases = {code for item in DOCUMENTS for code in item["ground_truth_refs"]}
    if actual_cases != manifest_cases:
        raise CommandError(format_difference("ground-truth", actual_cases, manifest_cases))
    validate_refund_versions(maltepe)
    return {"documents": resolved, "multicity": multicity, "maltepe": maltepe}


def resolve_snapshot(snapshot_key):
    try:
        return DataSnapshot.objects.get(snapshot_key=snapshot_key)
    except DataSnapshot.DoesNotExist as exc:
        raise CommandError(f"Required snapshot not found: {snapshot_key}") from exc
    except DataSnapshot.MultipleObjectsReturned as exc:
        raise CommandError(f"Snapshot key is not unique: {snapshot_key}") from exc


def format_difference(name, actual, expected):
    missing = sorted(actual - expected)
    extra = sorted(expected - actual)
    return f"{name} coverage mismatch; missing={missing}; extra={extra}"


def validate_refund_versions(maltepe):
    rule = Rule.objects.filter(data_snapshot=maltepe, code="REFUND-001").first()
    if rule is None:
        raise CommandError("Maltepe REFUND-001 rule is missing.")
    versions = {version.version: version for version in rule.versions.all()}
    expected = {
        1: ("2026-01-01T00:00:00+03:00", "2026-07-14T23:59:59+03:00", 180),
        2: ("2026-07-15T00:00:00+03:00", None, 120),
    }
    for version_number, (start, end, minimum_minutes) in expected.items():
        version = versions.get(version_number)
        if version is None:
            raise CommandError(f"REFUND-001 v{version_number} is missing.")
        if version.valid_from != parse_datetime(start) or version.valid_to != parse_datetime(end):
            raise CommandError(
                f"REFUND-001 v{version_number} validity does not match the manifest."
            )
        if version.price_basis != "contracted_monthly_price":
            raise CommandError(f"REFUND-001 v{version_number} price basis mismatch.")
        conditions = version.condition_tree.get("conditions", [])
        found_minimum = next(
            (
                item.get("value")
                for item in conditions
                if item.get("field") == "impact_duration_minutes"
            ),
            None,
        )
        if found_minimum != minimum_minutes:
            raise CommandError(f"REFUND-001 v{version_number} minimum duration mismatch.")


def document_fields(descriptor, content, digest, snapshot):
    return {
        "data_snapshot": snapshot,
        "document_code": descriptor["document_code"],
        "title": descriptor["title"],
        "document_type": descriptor["document_type"],
        "source_kind": descriptor["source_kind"],
        "version": descriptor["version"],
        "language": descriptor["language"],
        "content": content,
        "content_hash": digest,
        "is_synthetic": True,
        "status": "active",
        "valid_from": parse_datetime(descriptor["valid_from"]),
        "valid_to": parse_datetime(descriptor["valid_to"]),
        "metadata": get_document_metadata(descriptor),
    }


def seed_documents(resolved):
    created = 0
    unchanged = 0
    for descriptor, _path, content, digest in resolved["documents"]:
        snapshot = None
        if descriptor["snapshot_identifier"]:
            snapshot = resolve_snapshot(descriptor["snapshot_identifier"])
        fields = document_fields(descriptor, content, digest, snapshot)
        existing = SourceDocument.objects.filter(
            data_snapshot=snapshot,
            document_code=descriptor["document_code"],
            version=descriptor["version"],
        ).first()
        if existing:
            comparable = {
                key: getattr(existing, key)
                for key in fields
                if key not in {"data_snapshot", "metadata"}
            }
            expected = {
                key: value
                for key, value in fields.items()
                if key not in {"data_snapshot", "metadata"}
            }
            if comparable != expected or existing.metadata != fields["metadata"]:
                raise CommandError(
                    f"Existing document differs at the same version: {descriptor['document_code']}."
                )
            unchanged += 1
            continue
        SourceDocument.objects.create(**fields)
        created += 1
    return created, unchanged


def validate_existing_documents(resolved):
    for descriptor, _path, content, digest in resolved["documents"]:
        snapshot = None
        if descriptor["snapshot_identifier"]:
            snapshot = resolve_snapshot(descriptor["snapshot_identifier"])
        existing = SourceDocument.objects.filter(
            data_snapshot=snapshot,
            document_code=descriptor["document_code"],
            version=descriptor["version"],
        ).first()
        if existing is None:
            raise CommandError(f"SourceDocument is missing: {descriptor['document_code']}")
        fields = document_fields(descriptor, content, digest, snapshot)
        if (
            existing.content_hash != fields["content_hash"]
            or existing.metadata != fields["metadata"]
        ):
            raise CommandError(
                f"SourceDocument content or metadata mismatch: {descriptor['document_code']}"
            )
    corpus_documents = SourceDocument.objects.filter(metadata__corpus_key=CORPUS_KEY)
    if corpus_documents.count() != len(DOCUMENTS):
        raise CommandError(
            f"Expected 10 corpus SourceDocument records, found {corpus_documents.count()}."
        )
    if DocumentChunk.objects.filter(source_document__in=corpus_documents).exists():
        raise CommandError("Corpus must not contain DocumentChunk records in task 047.")
