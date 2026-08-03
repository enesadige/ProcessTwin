import math
from io import StringIO

import pytest
from django.core.management import call_command

from apps.rag.corpus_utils import content_hash
from apps.rag.models import DocumentChunk, DocumentChunkEmbedding, IndexRun, SourceDocument
from apps.rag.providers.base import (
    EMBEDDING_DIMENSIONS,
    PROMPT_VERSION,
    document_embedding_input,
)
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


def test_document_embedding_input_is_section_aware_and_structured():
    value = document_embedding_input(
        "Failover Prosedürü",
        "SYN-FAILOVER-2026",
        ["Ağ Operasyonları", "Failover Adımları"],
        "Failover Adımları",
        "## Failover Adımları\n\nPrimary yol kesildiğinde yedek yol doğrulanır.",
    )

    assert value.splitlines() == [
        "document_title: Failover Prosedürü",
        "document_code: SYN-FAILOVER-2026",
        "section_path: Ağ Operasyonları > Failover Adımları",
        "section_heading: Failover Adımları",
        "content:",
        "Primary yol kesildiğinde yedek yol doğrulanır.",
    ]
    assert PROMPT_VERSION == "rag-section-aware-document-v2"


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
    assert DocumentChunkEmbedding.objects.get().dimensions == EMBEDDING_DIMENSIONS


@pytest.mark.django_db
def test_previous_prompt_version_is_not_current():
    document = make_document()
    chunk = DocumentChunk.objects.create(
        source_document=document,
        sequence=0,
        heading="Baslik",
        section_path=["Baslik"],
        text="Sentetik arama metni.",
        content_hash=content_hash("Sentetik arama metni."),
    )
    DocumentChunkEmbedding.objects.create(
        document_chunk=chunk,
        provider="mock",
        model="mock-embedding-768",
        dimensions=EMBEDDING_DIMENSIONS,
        embedding_version="mock-sha256-v1",
        prompt_version="rag-embedding-prompt-v1",
        content_hash=chunk.content_hash,
        embedding=[0.0] * EMBEDDING_DIMENSIONS,
    )
    provider = MockEmbeddingProvider()

    result = generate_embeddings([document], provider=provider, validate_only=True)

    assert result["pending_count"] == 1
    assert DocumentChunkEmbedding.objects.get().prompt_version == "rag-embedding-prompt-v1"


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
    original = list(DocumentChunkEmbedding.objects.get(document_chunk=chunk).embedding)

    class FailingProvider(MockEmbeddingProvider):
        provider_name = "failing"

        def embed(self, text, *, is_query=False):
            raise RuntimeError("provider failure")

    with pytest.raises(RuntimeError):
        generate_embeddings([document], provider=FailingProvider(), force=True)

    assert list(DocumentChunkEmbedding.objects.get(document_chunk=chunk).embedding) == original
    assert IndexRun.objects.filter(status="failed").exists()


@pytest.mark.django_db
def test_force_updates_only_selected_provider_identity():
    document = make_document()
    chunk = DocumentChunk.objects.create(
        source_document=document,
        sequence=0,
        text="Sentetik arama metni.",
        content_hash=content_hash("Sentetik arama metni."),
    )

    class GeminiProvider(MockEmbeddingProvider):
        provider_name = "gemini"
        model_name = "gemini-embedding-2"
        embedding_version = "asymmetric-retrieval-v1"
        document_prompt_version = "rag-section-aware-document-v2"
        query_prompt_version = "gemini-search-query-v1"

    class OllamaProvider(MockEmbeddingProvider):
        provider_name = "ollama"
        model_name = "nomic-embed-text-v2-moe"
        embedding_version = "nomic-embed-v2-moe-768-v1"
        document_prompt_version = "nomic-section-aware-document-v1"
        query_prompt_version = "nomic-search-query-v1"

    generate_embeddings([document], provider=GeminiProvider())
    generate_embeddings([document], provider=OllamaProvider())
    ollama_record = DocumentChunkEmbedding.objects.get(
        document_chunk=chunk,
        provider="ollama",
    )
    ollama_vector = list(ollama_record.embedding)
    ollama_updated_at = ollama_record.updated_at

    result = generate_embeddings([document], provider=GeminiProvider(), force=True)

    ollama_record.refresh_from_db()
    assert result.embedding_count == 1
    assert DocumentChunkEmbedding.objects.filter(document_chunk=chunk).count() == 2
    assert list(ollama_record.embedding) == ollama_vector
    assert ollama_record.updated_at == ollama_updated_at


@pytest.mark.django_db
def test_provider_failure_does_not_change_other_provider_set():
    document = make_document()
    chunk = DocumentChunk.objects.create(
        source_document=document,
        sequence=0,
        text="Sentetik arama metni.",
        content_hash=content_hash("Sentetik arama metni."),
    )

    class OllamaProvider(MockEmbeddingProvider):
        provider_name = "ollama"
        model_name = "nomic-embed-text-v2-moe"
        embedding_version = "nomic-embed-v2-moe-768-v1"
        document_prompt_version = "nomic-section-aware-document-v1"
        query_prompt_version = "nomic-search-query-v1"

    class FailingGemini(MockEmbeddingProvider):
        provider_name = "gemini"
        model_name = "gemini-embedding-2"
        document_prompt_version = "rag-section-aware-document-v2"

        def embed_many(self, texts, *, is_query=False):
            raise RuntimeError("secret provider detail")

    generate_embeddings([document], provider=OllamaProvider())
    original = list(
        DocumentChunkEmbedding.objects.get(document_chunk=chunk, provider="ollama").embedding
    )

    with pytest.raises(RuntimeError):
        generate_embeddings([document], provider=FailingGemini())

    assert list(
        DocumentChunkEmbedding.objects.get(document_chunk=chunk, provider="ollama").embedding
    ) == original
    failed = IndexRun.objects.filter(status="failed").latest("pk")
    assert failed.error_summary == "embedding_generation_failed"
    assert "secret" not in failed.error_summary


@pytest.mark.django_db
def test_generation_metadata_records_provider_identity_and_counts():
    document = make_document()
    DocumentChunk.objects.create(
        source_document=document,
        sequence=0,
        text="Sentetik arama metni.",
        content_hash=content_hash("Sentetik arama metni."),
    )
    provider = MockEmbeddingProvider()

    run = generate_embeddings([document], provider=provider)

    assert run.metadata["provider"] == "mock"
    assert run.metadata["document_prompt_version"] == provider.document_prompt_version
    assert run.metadata["query_prompt_version"] == provider.query_prompt_version
    assert run.metadata["created_count"] == 1
    assert run.metadata["unchanged_count"] == 0


@pytest.mark.django_db
def test_idempotent_run_does_not_send_empty_provider_batch():
    document = make_document()
    DocumentChunk.objects.create(
        source_document=document,
        sequence=0,
        text="Sentetik arama metni.",
        content_hash=content_hash("Sentetik arama metni."),
    )

    class StrictProvider(MockEmbeddingProvider):
        def embed_many(self, texts, *, is_query=False):
            if not texts:
                raise RuntimeError("empty batch must not reach provider")
            return super().embed_many(texts, is_query=is_query)

    provider = StrictProvider()
    generate_embeddings([document], provider=provider)

    second = generate_embeddings([document], provider=provider)

    assert second.status == "succeeded"
    assert second.embedding_count == 0
    assert second.metadata["unchanged_count"] == 1


def test_generation_command_passes_allowlisted_embedding_profile(monkeypatch):
    captured = {}
    provider = MockEmbeddingProvider()

    def fake_get_provider(name, *, embedding_profile=None):
        captured.update({"provider": name, "profile": embedding_profile})
        return provider

    monkeypatch.setattr(
        "apps.rag.management.commands.generate_rag_embeddings.get_provider",
        fake_get_provider,
    )
    monkeypatch.setattr(
        "apps.rag.management.commands.generate_rag_embeddings.selected_documents",
        lambda **_kwargs: ([object()], None),
    )
    monkeypatch.setattr(
        "apps.rag.management.commands.generate_rag_embeddings.generate_embeddings",
        lambda *_args, **_kwargs: {
            "chunk_count": 1,
            "pending_count": 1,
            "embedding_count": 0,
        },
    )

    call_command(
        "generate_rag_embeddings",
        "--provider",
        "ollama",
        "--embedding-profile",
        "ollama-qwen3-0.6b",
        "--validate-only",
        stdout=StringIO(),
    )

    assert captured == {
        "provider": "ollama",
        "profile": "ollama-qwen3-0.6b",
    }


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
