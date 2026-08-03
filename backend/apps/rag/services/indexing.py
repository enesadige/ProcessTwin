import hashlib
import json

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.datasets.models import DataSnapshot
from apps.rag.corpus_utils import content_hash, normalize_markdown
from apps.rag.models import DocumentChunk, IndexRun, IndexRunStatus
from apps.rag.services.chunking import CHUNKING_VERSION, MAX_CHARS, OVERLAP_CHARS, build_chunk_specs


def resolve_snapshot_identifier(identifier):
    try:
        return DataSnapshot.objects.get(snapshot_key=identifier)
    except DataSnapshot.DoesNotExist:
        matches = list(DataSnapshot.objects.filter(dataset_version__slug=identifier))
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValidationError("snapshot_identifier matches multiple snapshots.") from None
        raise ValidationError("snapshot_identifier was not found.") from None


def validate_source_content(source_document):
    normalized = normalize_markdown(source_document.content)
    if normalized != source_document.content:
        raise ValidationError(
            f"SourceDocument content is not canonical: {source_document.document_code}"
        )
    if content_hash(source_document.content) != source_document.content_hash:
        raise ValidationError(
            f"SourceDocument content hash mismatch: {source_document.document_code}"
        )


def source_digest(documents, *, max_chars=MAX_CHARS, overlap_chars=OVERLAP_CHARS):
    values = [
        {
            "document_code": document.document_code,
            "version": document.version,
            "scope": document.data_snapshot.snapshot_key if document.data_snapshot_id else None,
            "content_hash": document.content_hash,
            "chunking_version": CHUNKING_VERSION,
            "max_chars": max_chars,
            "overlap_chars": overlap_chars,
        }
        for document in documents
    ]
    values.sort(key=lambda value: (value["document_code"], value["version"], value["scope"] or ""))
    payload = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def create_index_run(documents, *, reset_requested=False, data_snapshot=None):
    metadata = {
        "chunking_version": CHUNKING_VERSION,
        "max_chars": MAX_CHARS,
        "overlap_chars": OVERLAP_CHARS,
        "selected_document_codes": [document.document_code for document in documents],
        "selected_snapshot_keys": sorted(
            {
                document.data_snapshot.snapshot_key
                for document in documents
                if document.data_snapshot_id
            }
        ),
        "created_count": 0,
        "replaced_count": 0,
        "unchanged_count": 0,
        "total_chunk_count": 0,
        "validate_only": False,
        "reset_requested": reset_requested,
        "corpus_keys": sorted(
            {
                document.metadata.get("corpus_key")
                for document in documents
                if document.metadata.get("corpus_key")
            }
        ),
    }
    run = IndexRun.objects.create(
        data_snapshot=data_snapshot,
        status=IndexRunStatus.PENDING,
        source_digest=source_digest(documents),
        metadata=metadata,
    )
    run.status = IndexRunStatus.RUNNING
    run.started_at = timezone.now()
    run.save(update_fields=["status", "started_at", "updated_at"])
    return run


def run_index(documents, *, reset_requested=False, data_snapshot=None):
    run = create_index_run(documents, reset_requested=reset_requested, data_snapshot=data_snapshot)
    try:
        with transaction.atomic():
            created_count = 0
            replaced_count = 0
            unchanged_count = 0
            total_chunk_count = 0
            for document in documents:
                validate_source_content(document)
                specs = build_chunk_specs(document)
                existing = list(document.chunks.order_by("sequence"))
                if not reset_requested and chunks_match(existing, specs, document):
                    unchanged_count += 1
                else:
                    if existing:
                        replaced_count += 1
                    else:
                        created_count += 1
                    document.chunks.all().delete()
                    DocumentChunk.objects.bulk_create(
                        [
                            DocumentChunk(
                                source_document=document,
                                sequence=spec.sequence,
                                heading=spec.heading,
                                section_path=spec.section_path,
                                text=spec.text,
                                content_hash=spec.content_hash,
                                char_start=spec.char_start,
                                char_end=spec.char_end,
                                valid_from=document.valid_from,
                                valid_to=document.valid_to,
                                rule_code=spec.rule_code,
                                rule_version=spec.rule_version,
                                metadata=spec.metadata,
                            )
                            for spec in specs
                        ]
                    )
                total_chunk_count += len(specs)
            run.metadata.update(
                {
                    "created_count": created_count,
                    "replaced_count": replaced_count,
                    "unchanged_count": unchanged_count,
                    "total_chunk_count": total_chunk_count,
                }
            )
            run.status = IndexRunStatus.SUCCEEDED
            run.completed_at = timezone.now()
            run.source_count = len(documents)
            run.chunk_count = total_chunk_count
            run.embedding_count = 0
            run.save(
                update_fields=[
                    "metadata",
                    "status",
                    "completed_at",
                    "source_count",
                    "chunk_count",
                    "embedding_count",
                    "updated_at",
                ]
            )
    except Exception as exc:
        run.status = IndexRunStatus.FAILED
        run.completed_at = timezone.now()
        run.error_summary = safe_error_summary(exc)
        run.save(update_fields=["status", "completed_at", "error_summary", "updated_at"])
        raise
    return run


def chunks_match(existing, specs, document):
    if len(existing) != len(specs):
        return False
    for chunk, spec in zip(existing, specs, strict=True):
        if (
            chunk.sequence != spec.sequence
            or chunk.heading != spec.heading
            or chunk.section_path != spec.section_path
            or chunk.text != spec.text
            or chunk.content_hash != spec.content_hash
            or chunk.char_start != spec.char_start
            or chunk.char_end != spec.char_end
            or chunk.valid_from != document.valid_from
            or chunk.valid_to != document.valid_to
            or chunk.rule_code != spec.rule_code
            or chunk.rule_version != spec.rule_version
            or chunk.metadata != spec.metadata
        ):
            return False
    return True


def safe_error_summary(exc):
    if isinstance(exc, (ValidationError, ValueError)):
        return str(exc)[:240]
    return "indexing_failed"
