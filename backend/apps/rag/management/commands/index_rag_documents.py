from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from apps.rag.models import DocumentChunk, DocumentStatus, SourceDocument
from apps.rag.services.chunking import build_chunk_specs
from apps.rag.services.indexing import (
    chunks_match,
    resolve_snapshot_identifier,
    run_index,
    validate_source_content,
)


class Command(BaseCommand):
    help = "Index active RAG SourceDocument records into deterministic DocumentChunk records."

    def add_arguments(self, parser):
        parser.add_argument(
            "--document-code",
            action="append",
            dest="document_codes",
            help="Process only this exact document code; may be supplied more than once.",
        )
        parser.add_argument("--snapshot-identifier")
        parser.add_argument("--reset", action="store_true")
        parser.add_argument("--validate-only", action="store_true")

    def handle(self, *args, **options):
        if options["reset"] and options["validate_only"]:
            raise CommandError("--reset and --validate-only cannot be used together.")

        documents, resolved_snapshot = self.select_documents(
            document_codes=options["document_codes"],
            snapshot_identifier=options["snapshot_identifier"],
        )
        if options["validate_only"]:
            self.validate_documents(documents)
            self.stdout.write(
                self.style.SUCCESS(f"RAG document validation passed: sources={len(documents)}.")
            )
            return

        run = run_index(
            documents,
            reset_requested=options["reset"],
            data_snapshot=resolved_snapshot if options["snapshot_identifier"] else None,
        )
        self.stdout.write(
            self.style.SUCCESS(
                "RAG documents indexed: "
                f"run={run.pk}, sources={run.source_count}, chunks={run.chunk_count}, "
                f"created={run.metadata.get('created_count', 0)}, "
                f"replaced={run.metadata.get('replaced_count', 0)}, "
                f"unchanged={run.metadata.get('unchanged_count', 0)}."
            )
        )

    def select_documents(self, *, document_codes, snapshot_identifier):
        queryset = (
            SourceDocument.objects.filter(status=DocumentStatus.ACTIVE)
            .select_related("data_snapshot")
            .order_by("document_code", "version", "pk")
        )

        requested_codes = list(dict.fromkeys(document_codes or []))
        if requested_codes:
            found_codes = set(
                SourceDocument.objects.filter(document_code__in=requested_codes).values_list(
                    "document_code", flat=True
                )
            )
            missing_codes = sorted(set(requested_codes) - found_codes)
            if missing_codes:
                raise CommandError(f"Unknown document code(s): {', '.join(missing_codes)}")
            queryset = queryset.filter(document_code__in=requested_codes)

        resolved_snapshot = None
        if snapshot_identifier:
            try:
                resolved_snapshot = resolve_snapshot_identifier(snapshot_identifier)
            except Exception as exc:
                raise CommandError(str(exc)) from exc
            queryset = queryset.filter(
                Q(data_snapshot=resolved_snapshot) | Q(data_snapshot__isnull=True)
            )

        documents = list(queryset)
        if not documents:
            raise CommandError("No active SourceDocument records match the requested scope.")
        return documents, resolved_snapshot

    def validate_documents(self, documents):
        for document in documents:
            validate_source_content(document)
            expected = build_chunk_specs(document)
            existing = list(
                DocumentChunk.objects.filter(source_document=document).order_by("sequence")
            )
            if existing and not chunks_match(existing, expected, document):
                raise CommandError(
                    f"Existing chunks are inconsistent for {document.document_code}."
                )
