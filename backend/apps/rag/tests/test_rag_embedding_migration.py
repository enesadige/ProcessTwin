import importlib

import pytest
from django.apps import apps as django_apps

from apps.rag.models import DocumentChunk, DocumentChunkEmbedding, SourceDocument

MIGRATION = importlib.import_module("apps.rag.migrations.0002_document_chunk_embedding")


def make_document(code="MIGRATION-DOC"):
    return SourceDocument.objects.create(
        document_code=code,
        title="Migration test",
        document_type="procedure",
        source_kind="synthetic",
        version=1,
        language="tr",
        content="Sentetik içerik",
        content_hash="a" * 64,
        status="active",
    )


def make_legacy_chunks(*, provider="gemini", count=74):
    document = make_document()
    return DocumentChunk.objects.bulk_create(
        [
            DocumentChunk(
                source_document=document,
                sequence=index,
                text=f"Parça {index}",
                content_hash=f"{index:064x}",
                embedding=[float(index == 0)] + [0.0] * 767,
                embedding_provider=provider if index == 0 else "gemini",
                embedding_model="gemini-embedding-2",
                embedding_version="asymmetric-retrieval-v1",
                embedding_dimensions=768,
                metadata={
                    "content_hash": f"{index:064x}",
                    "prompt_version": "rag-section-aware-document-v2",
                },
            )
            for index in range(count)
        ]
    )


@pytest.mark.django_db
def test_gemini_backfill_is_noop_on_clean_database():
    MIGRATION.backfill_gemini_embeddings(django_apps, None)

    assert DocumentChunkEmbedding.objects.count() == 0


@pytest.mark.django_db
def test_gemini_backfill_copies_complete_legacy_set_without_generation():
    make_legacy_chunks()

    MIGRATION.backfill_gemini_embeddings(django_apps, None)

    records = DocumentChunkEmbedding.objects.order_by("document_chunk_id")
    assert records.count() == 74
    assert not records.exclude(
        provider="gemini",
        model="gemini-embedding-2",
        dimensions=768,
        embedding_version="asymmetric-retrieval-v1",
        prompt_version="rag-section-aware-document-v2",
    ).exists()
    assert all(
        list(record.embedding) == list(record.document_chunk.embedding)
        and record.content_hash == record.document_chunk.content_hash
        for record in records.select_related("document_chunk")
    )


@pytest.mark.django_db
def test_gemini_backfill_rejects_partial_legacy_set():
    make_legacy_chunks(count=1)

    with pytest.raises(RuntimeError, match="legacy_embedding_set_is_partial"):
        MIGRATION.backfill_gemini_embeddings(django_apps, None)


@pytest.mark.django_db
def test_gemini_backfill_rejects_mixed_provider_set():
    make_legacy_chunks(provider="ollama")

    with pytest.raises(RuntimeError, match="legacy_embedding_provider_mismatch"):
        MIGRATION.backfill_gemini_embeddings(django_apps, None)
