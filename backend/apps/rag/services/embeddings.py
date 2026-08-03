import hashlib
import json

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.rag.models import DocumentChunk, IndexRun, IndexRunStatus, SourceDocument
from apps.rag.providers import GeminiEmbeddingProvider, MockEmbeddingProvider
from apps.rag.providers.base import EMBEDDING_DIMENSIONS, PROMPT_VERSION, document_embedding_input
from apps.rag.providers.base import EmbeddingProviderError as ProviderError
from apps.rag.services.indexing import resolve_snapshot_identifier

ALLOWED_PROVIDERS = {"mock", "gemini"}


def get_provider(name: str | None = None):
    provider_name = name or getattr(settings, "RAG_EMBEDDING_PROVIDER", "mock")
    if provider_name not in ALLOWED_PROVIDERS:
        raise ValidationError("Unsupported embedding provider.")
    return MockEmbeddingProvider() if provider_name == "mock" else GeminiEmbeddingProvider()


def embedding_metadata(chunk, provider) -> dict:
    return {
        "content_hash": chunk.content_hash,
        "provider": provider.provider_name,
        "model": provider.model_name,
        "embedding_version": provider.embedding_version,
        "prompt_version": provider.prompt_version,
        "dimensions": EMBEDDING_DIMENSIONS,
    }


def is_current_embedding(chunk, provider) -> bool:
    metadata = chunk.metadata or {}
    expected = embedding_metadata(chunk, provider)
    return (
        chunk.embedding is not None
        and chunk.embedding_provider == provider.provider_name
        and chunk.embedding_model == provider.model_name
        and chunk.embedding_version == provider.embedding_version
        and chunk.embedding_dimensions == EMBEDDING_DIMENSIONS
        and all(metadata.get(key) == value for key, value in expected.items())
    )


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
        return {"chunk_count": len(chunks), "pending_count": len(pending), "embedding_count": 0}

    run = IndexRun.objects.create(
        data_snapshot=data_snapshot,
        status=IndexRunStatus.PENDING,
        embedding_provider=provider.provider_name,
        embedding_model=provider.model_name,
        embedding_dimensions=EMBEDDING_DIMENSIONS,
        source_digest=source_digest(documents, provider),
        metadata={
            "provider": provider.provider_name,
            "model": provider.model_name,
            "embedding_version": provider.embedding_version,
            "prompt_version": PROMPT_VERSION,
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
        results = []
        for chunk in pending:
            text = document_embedding_input(
                chunk.source_document.title,
                chunk.heading,
                chunk.text,
            )
            values = provider.embed(text)
            if len(values) != EMBEDDING_DIMENSIONS:
                raise ProviderError("invalid_embedding_dimensions")
            results.append((chunk, values))
        with transaction.atomic():
            for chunk, values in results:
                metadata = dict(chunk.metadata or {})
                metadata.update(embedding_metadata(chunk, provider))
                chunk.embedding = values
                chunk.embedding_provider = provider.provider_name
                chunk.embedding_model = provider.model_name
                chunk.embedding_version = provider.embedding_version
                chunk.embedding_dimensions = EMBEDDING_DIMENSIONS
                chunk.metadata = metadata
                chunk.save(
                    update_fields=[
                        "embedding",
                        "embedding_provider",
                        "embedding_model",
                        "embedding_version",
                        "embedding_dimensions",
                        "metadata",
                        "updated_at",
                    ]
                )
            run.status = IndexRunStatus.SUCCEEDED
            run.completed_at = timezone.now()
            run.source_count = len(documents)
            run.chunk_count = len(chunks)
            run.embedding_count = len(results)
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
