import hashlib
import json

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.rag.models import (
    DocumentChunk,
    DocumentChunkEmbedding,
    IndexRun,
    IndexRunStatus,
    SourceDocument,
)
from apps.rag.providers import get_embedding_descriptor
from apps.rag.providers.base import EmbeddingProviderError as ProviderError
from apps.rag.services.indexing import resolve_snapshot_identifier


def get_provider(name: str | None = None, *, embedding_profile: str | None = None):
    provider_name = name or getattr(settings, "RAG_EMBEDDING_PROVIDER", "gemini")
    return get_embedding_descriptor(
        provider_name,
        embedding_profile=embedding_profile,
    ).create_provider()


def embedding_metadata(chunk, provider) -> dict:
    return {
        "content_hash": chunk.content_hash,
        "provider": provider.provider_name,
        "model": provider.model_name,
        "embedding_version": provider.embedding_version,
        "prompt_version": provider.document_prompt_version,
        "dimensions": provider.dimensions,
    }


def is_current_embedding(chunk, provider) -> bool:
    expected = embedding_metadata(chunk, provider)
    return DocumentChunkEmbedding.objects.filter(
        document_chunk=chunk,
        provider=expected["provider"],
        model=expected["model"],
        dimensions=expected["dimensions"],
        embedding_version=expected["embedding_version"],
        prompt_version=expected["prompt_version"],
        content_hash=expected["content_hash"],
    ).exists()


def selected_documents(*, document_codes=None, snapshot_identifier=None):
    queryset = SourceDocument.objects.filter(status="active").select_related("data_snapshot")
    if document_codes:
        requested = set(document_codes)
        queryset = queryset.filter(document_code__in=requested)
        found = set(queryset.values_list("document_code", flat=True))
        missing = sorted(requested - found)
        if missing:
            raise ValidationError(f"Unknown document code(s): {', '.join(missing)}")
    resolved_snapshot = None
    if snapshot_identifier:
        resolved_snapshot = resolve_snapshot_identifier(snapshot_identifier)
        queryset = queryset.filter(
            Q(data_snapshot=resolved_snapshot) | Q(data_snapshot__isnull=True)
        )
    documents = list(queryset.order_by("document_code", "version", "pk"))
    if not documents:
        raise ValidationError("No active source documents match the requested scope.")
    return documents, resolved_snapshot


def source_digest(documents, provider) -> str:
    values = [
        {
            "document_code": document.document_code,
            "version": document.version,
            "scope": document.data_snapshot.snapshot_key if document.data_snapshot_id else None,
            "content_hash": document.content_hash,
            **provider.metadata(),
        }
        for document in documents
    ]
    payload = json.dumps(
        sorted(values, key=lambda value: (value["document_code"], value["version"])), sort_keys=True
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def generate_embeddings(
    documents,
    *,
    provider,
    force=False,
    data_snapshot=None,
    validate_only=False,
):
    chunks = list(
        DocumentChunk.objects.filter(source_document__in=documents)
        .select_related("source_document")
        .order_by("source_document__document_code", "source_document__version", "sequence")
    )
    pending = [chunk for chunk in chunks if force or not is_current_embedding(chunk, provider)]
    if validate_only:
        provider.validate_ready()
        return {"chunk_count": len(chunks), "pending_count": len(pending), "embedding_count": 0}

    run = IndexRun.objects.create(
        data_snapshot=data_snapshot,
        status=IndexRunStatus.PENDING,
        embedding_provider=provider.provider_name,
        embedding_model=provider.model_name,
        embedding_dimensions=provider.dimensions,
        source_digest=source_digest(documents, provider),
        metadata={
            "provider": provider.provider_name,
            "model": provider.model_name,
            "embedding_version": provider.embedding_version,
            "document_prompt_version": provider.document_prompt_version,
            "query_prompt_version": provider.query_prompt_version,
            "selected_document_codes": [document.document_code for document in documents],
            "selected_chunk_count": len(chunks),
            "pending_chunk_count": len(pending),
            "force": force,
            "validate_only": False,
        },
    )
    run.status = IndexRunStatus.RUNNING
    run.started_at = timezone.now()
    run.save(update_fields=["status", "started_at", "updated_at"])
    try:
        provider.validate_ready()
        inputs = [
            provider.document_input(
                chunk.source_document.title,
                chunk.source_document.document_code,
                chunk.section_path,
                chunk.heading,
                chunk.text,
            )
            for chunk in pending
        ]
        vectors = provider.embed_many(inputs) if inputs else []
        if len(vectors) != len(pending):
            raise ProviderError("embedding_batch_count_mismatch")
        results = []
        for chunk, values in zip(pending, vectors, strict=True):
            if len(values) != provider.dimensions:
                raise ProviderError("invalid_embedding_dimensions")
            results.append((chunk, values))
        created_count = 0
        replaced_count = 0
        with transaction.atomic():
            for chunk, values in results:
                identity = embedding_metadata(chunk, provider)
                _record, created = DocumentChunkEmbedding.objects.update_or_create(
                    document_chunk=chunk,
                    provider=identity["provider"],
                    model=identity["model"],
                    dimensions=identity["dimensions"],
                    embedding_version=identity["embedding_version"],
                    prompt_version=identity["prompt_version"],
                    content_hash=identity["content_hash"],
                    defaults={"embedding": values},
                )
                created_count += int(created)
                replaced_count += int(not created)
            run.status = IndexRunStatus.SUCCEEDED
            run.completed_at = timezone.now()
            run.source_count = len(documents)
            run.chunk_count = len(chunks)
            run.embedding_count = len(results)
            run.metadata.update(
                {
                    "created_count": created_count,
                    "replaced_count": replaced_count,
                    "unchanged_count": len(chunks) - len(pending),
                }
            )
            run.save(
                update_fields=[
                    "status",
                    "completed_at",
                    "source_count",
                    "chunk_count",
                    "embedding_count",
                    "updated_at",
                    "metadata",
                ]
            )
    except Exception as exc:
        run.status = IndexRunStatus.FAILED
        run.completed_at = timezone.now()
        run.error_summary = safe_embedding_error(exc)
        run.save(update_fields=["status", "completed_at", "error_summary", "updated_at"])
        raise
    return run


def safe_embedding_error(exc):
    if isinstance(exc, (ProviderError, ValidationError)):
        return str(exc)[:240]
    return "embedding_generation_failed"
