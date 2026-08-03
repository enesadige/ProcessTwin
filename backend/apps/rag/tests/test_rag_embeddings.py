import math

import pytest

from apps.rag.corpus_utils import content_hash
from apps.rag.models import DocumentChunk, IndexRun, SourceDocument
from apps.rag.providers.base import EMBEDDING_DIMENSIONS
from apps.rag.providers.mock import MockEmbeddingProvider
from apps.rag.services.embeddings import generate_embeddings


def make_document(code="TEST-RAG-DOC"):
    content = "# Baslik\n\nSentetik arama metni.\n"
    return SourceDocument.objects.create(
        document_code=code,
        title="Test dokumani",
        document_type="procedure",
        source_kind="synthetic",
        version=1,
        language="tr",
        content=content,
        content_hash=content_hash(content),
        is_synthetic=True,
        status="active",
    )


@pytest.mark.django_db
def test_mock_embedding_is_deterministic_and_normalized():
    provider = MockEmbeddingProvider()
    first = provider.embed("same input")
    second = provider.embed("same input")

    assert first == second
    assert len(first) == EMBEDDING_DIMENSIONS
    assert math.isclose(math.sqrt(sum(value * value for value in first)), 1.0, rel_tol=1e-6)


@pytest.mark.django_db
def test_generation_is_idempotent_and_validate_only_does_not_write():
    document = make_document()
    DocumentChunk.objects.create(
        source_document=document,
        sequence=0,
        heading="Baslik",
        text="Sentetik arama metni.",
        content_hash=content_hash("Sentetik arama metni."),
    )
    provider = MockEmbeddingProvider()

    first = generate_embeddings([document], provider=provider)
    second = generate_embeddings([document], provider=provider)
    runs_before_validate = IndexRun.objects.count()
    validation = generate_embeddings([document], provider=provider, validate_only=True)

    assert first.embedding_count == 1
    assert second.embedding_count == 0
    assert validation["pending_count"] == 0
    assert IndexRun.objects.count() == runs_before_validate
    assert DocumentChunk.objects.get().embedding_dimensions == EMBEDDING_DIMENSIONS


@pytest.mark.django_db
def test_provider_failure_preserves_existing_embedding(monkeypatch):
    document = make_document()
    chunk = DocumentChunk.objects.create(
        source_document=document,
        sequence=0,
        text="Sentetik arama metni.",
        content_hash=content_hash("Sentetik arama metni."),
    )
    provider = MockEmbeddingProvider()
    generate_embeddings([document], provider=provider)
    original = list(DocumentChunk.objects.get(pk=chunk.pk).embedding)

    class FailingProvider(MockEmbeddingProvider):
        provider_name = "failing"

        def embed(self, text, *, is_query=False):
            raise RuntimeError("provider failure")

    with pytest.raises(RuntimeError):
        generate_embeddings([document], provider=FailingProvider(), force=True)

    assert list(DocumentChunk.objects.get(pk=chunk.pk).embedding) == original
    assert IndexRun.objects.filter(status="failed").exists()


@pytest.mark.django_db
def test_gemini_output_dimension_is_checked_without_network(monkeypatch):
    from apps.rag.providers.gemini import GeminiEmbeddingProvider

    provider = GeminiEmbeddingProvider.__new__(GeminiEmbeddingProvider)
    provider._client = type(
        "Client",
        (),
        {
            "models": type(
                "Models",
                (),
                {
                    "embed_content": lambda *_args, **_kwargs: type(
                        "Response",
                        (),
                        {"embeddings": [type("Embedding", (), {"values": [0.0] * 3})()]},
                    )()
                },
            )()
        },
    )()

    with pytest.raises(Exception, match="gemini_invalid_dimensions"):
        provider.embed("query")
