from datetime import datetime

import pytest
from django.core.exceptions import ValidationError
from django.test import override_settings

from apps.datasets.models import DatasetVersion, DataSnapshot
from apps.rag.corpus_utils import content_hash
from apps.rag.models import DocumentChunk, DocumentChunkEmbedding, SourceDocument
from apps.rag.providers.mock import MockEmbeddingProvider
from apps.rag.services import search as search_service
from apps.rag.services.search import (
    CHARACTER_FRAGMENT_FACTOR,
    CONTENT_WEIGHT,
    H1_BOILERPLATE_FACTOR,
    HEADING_WEIGHT,
    MIN_CANDIDATE_LIMIT,
    SECTION_PATH_WEIGHT,
    SEMANTIC_WEIGHT,
    SearchRequest,
    candidate_limit,
    hybrid_section_score,
    lexical_relevance,
    rerank_semantic_results,
    search,
    section_information_factor,
)


def search_fixture():
    dataset = DatasetVersion.objects.create(
        name="Search dataset", generator_version="test", seed="search"
    )
    snapshot = DataSnapshot.objects.create(
        dataset_version=dataset, name="Search snapshot", snapshot_key="search-snapshot"
    )
    docs = []
    for code, title, text in (
        ("REFUND-001-V1-SOURCE", "REFUND-001 v1", "minimum 180 dakika"),
        ("SYN-FAILOVER-MAINTENANCE-2026", "Failover", "başarısız yedek hat geçişi"),
    ):
        content = f"# {title}\n\n{text}\n"
        document = SourceDocument.objects.create(
            data_snapshot=snapshot if code.startswith("REFUND") else None,
            document_code=code,
            title=title,
            document_type="procedure",
            source_kind="synthetic",
            version=1,
            language="tr",
            content=content,
            content_hash=content_hash(content),
            status="active",
        )
        chunk = DocumentChunk.objects.create(
            source_document=document,
            sequence=0,
            heading=title,
            text=text,
            content_hash=content_hash(text),
        )
        provider = MockEmbeddingProvider()
        DocumentChunkEmbedding.objects.create(
            document_chunk=chunk,
            provider=provider.provider_name,
            model=provider.model_name,
            dimensions=provider.dimensions,
            embedding_version=provider.embedding_version,
            prompt_version=provider.document_prompt_version,
            content_hash=chunk.content_hash,
            embedding=provider.embed(text),
        )
        docs.append(document)
    return snapshot, docs


@pytest.mark.django_db
def test_full_text_includes_snapshot_and_global_documents():
    snapshot, _ = search_fixture()
    result = search(
        SearchRequest(
            query="REFUND-001",
            snapshot_identifier=snapshot.snapshot_key,
            search_mode="full_text",
        )
    )

    assert result["result_count"] == 1
    assert result["results"][0]["document_code"] == "REFUND-001-V1-SOURCE"
    assert result["results"][0]["exact_code_match"] is True


@pytest.mark.django_db
@override_settings(RAG_EMBEDDING_PROVIDER="mock")
def test_semantic_search_returns_scores_without_vectors_in_payload():
    snapshot, _ = search_fixture()
    result = search(
        SearchRequest(
            query="başarısız yedek hat geçişi",
            snapshot_identifier=snapshot.snapshot_key,
            search_mode="semantic",
        )
    )

    assert result["results"]
    assert result["results"][0]["semantic_score"] is not None
    assert "embedding" not in result["results"][0]
    assert result["embedding"]["provider"] == "mock"


@pytest.mark.django_db
@override_settings(RAG_EMBEDDING_PROVIDER="mock")
def test_semantic_search_rejects_partial_selected_provider_set():
    snapshot, _ = search_fixture()
    DocumentChunkEmbedding.objects.filter(document_chunk__sequence=0).first().delete()

    with pytest.raises(
        search_service.EmbeddingPrerequisiteError,
        match="embedding_prerequisite_error",
    ):
        search(
            SearchRequest(
                query="başarısız yedek hat geçişi",
                snapshot_identifier=snapshot.snapshot_key,
                search_mode="semantic",
            )
        )


@pytest.mark.django_db
@override_settings(RAG_EMBEDDING_PROVIDER="mock")
def test_hybrid_does_not_fallback_for_partial_embedding_set():
    snapshot, _ = search_fixture()
    DocumentChunkEmbedding.objects.first().delete()

    with pytest.raises(search_service.EmbeddingPrerequisiteError):
        search(
            SearchRequest(
                query="başarısız yedek hat geçişi",
                snapshot_identifier=snapshot.snapshot_key,
                search_mode="hybrid",
            )
        )


@pytest.mark.django_db
def test_search_uses_only_the_exact_selected_provider_descriptor(monkeypatch):
    snapshot, _ = search_fixture()
    chunks = list(DocumentChunk.objects.order_by("pk"))

    class Provider(MockEmbeddingProvider):
        provider_name = "gemini"
        model_name = "gemini-embedding-2"
        embedding_version = "asymmetric-retrieval-v1"
        document_prompt_version = "rag-section-aware-document-v2"
        query_prompt_version = "gemini-search-query-v1"

    provider = Provider()
    for index, chunk in enumerate(chunks):
        vector = [0.0] * 768
        vector[index] = 1.0
        DocumentChunkEmbedding.objects.create(
            document_chunk=chunk,
            provider=provider.provider_name,
            model=provider.model_name,
            dimensions=provider.dimensions,
            embedding_version=provider.embedding_version,
            prompt_version=provider.document_prompt_version,
            content_hash=chunk.content_hash,
            embedding=vector,
        )
    query_vector = [0.0] * 768
    query_vector[1] = 1.0
    monkeypatch.setattr(provider, "embed", lambda *args, **kwargs: query_vector)
    monkeypatch.setattr(search_service, "get_provider", lambda _name=None: provider)

    result = search(
        SearchRequest(
            query="yedek geçiş",
            snapshot_identifier=snapshot.snapshot_key,
            search_mode="semantic",
        ),
        embedding_provider="gemini",
    )

    assert result["results"][0]["document_code"] == "SYN-FAILOVER-MAINTENANCE-2026"
    assert result["embedding"]["provider"] == "gemini"
    assert result["embedding"]["document_prompt_version"] == (
        "rag-section-aware-document-v2"
    )


@pytest.mark.django_db
def test_search_does_not_mix_models_from_the_same_ollama_provider(monkeypatch):
    snapshot, _ = search_fixture()
    chunks = list(DocumentChunk.objects.order_by("pk"))

    class QwenProvider(MockEmbeddingProvider):
        provider_name = "ollama"
        model_name = "qwen3-embedding:0.6b"
        embedding_version = "qwen3-embedding-0.6b-768-v1"
        document_prompt_version = "qwen3-section-document-v1"
        query_prompt_version = "qwen3-telecom-query-v1"

    provider = QwenProvider()
    query_vector = [1.0] + [0.0] * 767
    for index, chunk in enumerate(chunks):
        qwen_vector = query_vector if index == 0 else [0.0, 1.0] + [0.0] * 766
        nomic_vector = [0.0, 1.0] + [0.0] * 766 if index == 0 else query_vector
        DocumentChunkEmbedding.objects.create(
            document_chunk=chunk,
            provider="ollama",
            model="qwen3-embedding:0.6b",
            dimensions=768,
            embedding_version="qwen3-embedding-0.6b-768-v1",
            prompt_version="qwen3-section-document-v1",
            content_hash=chunk.content_hash,
            embedding=qwen_vector,
        )
        DocumentChunkEmbedding.objects.create(
            document_chunk=chunk,
            provider="ollama",
            model="nomic-embed-text-v2-moe",
            dimensions=768,
            embedding_version="nomic-embed-v2-moe-768-v1",
            prompt_version="nomic-section-aware-document-v1",
            content_hash=chunk.content_hash,
            embedding=nomic_vector,
        )
    monkeypatch.setattr(provider, "embed", lambda *args, **kwargs: query_vector)
    monkeypatch.setattr(search_service, "get_provider", lambda _name=None: provider)

    result = search(
        SearchRequest(
            query="section query",
            snapshot_identifier=snapshot.snapshot_key,
            search_mode="semantic",
        ),
        embedding_provider="ollama-qwen3-0.6b",
    )

    assert result["results"][0]["chunk_id"] == chunks[0].pk
    assert result["embedding"]["model"] == "qwen3-embedding:0.6b"


@pytest.mark.django_db
def test_full_text_supports_corpus_vocabulary_aliases():
    snapshot, _ = search_fixture()
    result = search(
        SearchRequest(
            query="başarısız yedek hat geçişi",
            snapshot_identifier=snapshot.snapshot_key,
            search_mode="full_text",
        )
    )

    assert result["results"][0]["document_code"] == "SYN-FAILOVER-MAINTENANCE-2026"


def test_search_request_rejects_short_or_naive_queries():
    with pytest.raises(ValidationError):
        search(SearchRequest(query="x", snapshot_identifier="snapshot"))
    with pytest.raises(ValidationError):
        search(
            SearchRequest(
                query="valid",
                snapshot_identifier="snapshot",
                evaluation_time=datetime(2026, 1, 1),
            )
        )


def _ranking_item(*, pk, sequence, text, score, metadata=None, exact=False):
    document = SourceDocument(document_code="DOC", version=1)
    chunk = DocumentChunk(
        pk=pk,
        source_document=document,
        sequence=sequence,
        heading="Section",
        text=text,
        metadata=metadata or {},
    )
    return {"chunk": chunk, "score": score, "exact_code_match": exact}


def test_low_information_factors_are_general_and_exact_codes_are_exempt():
    h1 = _ranking_item(pk=1, sequence=0, text="# Başlık\n\n> Sentetik uyarı", score=0.7)
    fragment = _ranking_item(
        pk=2,
        sequence=3,
        text="Bölünmüş içerik",
        score=0.7,
        metadata={"split_reason": "character_limit", "overlap_applied": True},
    )
    exact = {**h1, "exact_code_match": True}

    assert section_information_factor(h1) == H1_BOILERPLATE_FACTOR
    assert section_information_factor(fragment) == CHARACTER_FRAGMENT_FACTOR
    assert section_information_factor(exact) == 1.0


def test_semantic_section_rerank_preserves_raw_score_and_uses_stable_tie_break():
    fragment = _ranking_item(
        pk=2,
        sequence=2,
        text="Fragment",
        score=0.651,
        metadata={"split_reason": "character_limit"},
    )
    section = _ranking_item(pk=1, sequence=1, text="Tam bölüm", score=0.636)

    ranked = rerank_semantic_results([fragment, section], "tam bölüm")

    assert [item["chunk"].pk for item in ranked] == [1, 2]
    assert ranked[0]["score"] == 0.636
    assert [item["rank"] for item in ranked] == [1, 2]


def test_section_reranking_uses_general_normalized_components():
    section = _ranking_item(pk=1, sequence=1, text="planlı bakım tamamlanır", score=0.60)
    section["chunk"].heading = "Planlı Bakım"
    section["chunk"].section_path = ["Operasyon", "Planlı Bakım"]
    generic = _ranking_item(pk=2, sequence=2, text="genel açıklama", score=0.61)
    generic["chunk"].heading = "Genel"
    generic["chunk"].section_path = ["Operasyon", "Genel"]

    ranked = rerank_semantic_results([generic, section], "planlı bakım tamamlanmadı")

    assert ranked[0]["chunk"].pk == 1
    assert ranked[0]["heading_score"] > 0
    assert ranked[0]["section_path_score"] > 0
    assert ranked[0]["content_score"] > 0
    assert ranked[0]["score"] == 0.60
    assert SEMANTIC_WEIGHT > HEADING_WEIGHT + SECTION_PATH_WEIGHT + CONTENT_WEIGHT


def test_lexical_relevance_is_unicode_aware_and_not_synonym_specific():
    assert lexical_relevance("Planlı çalışmalar tamamlanmadı", "Planlı çalışma tamamlandı") > 0
    assert lexical_relevance("hizmet seviyesi", "SLA İhlalleri") == 0


def test_candidate_pool_is_independent_from_small_final_limit(monkeypatch):
    assert MIN_CANDIDATE_LIMIT == 20
    assert candidate_limit(1) == 20
    assert candidate_limit(5) == 20
    assert candidate_limit(20) == 80


def test_hybrid_section_score_keeps_semantic_primary_and_full_text_bounded():
    semantic = {"ranking_score": 0.61, "rank": 1}
    full_text = {"rank": 1}

    assert hybrid_section_score(semantic, None, exact=False) == 0.61
    assert hybrid_section_score(semantic, full_text, exact=False) == pytest.approx(0.62)
    assert hybrid_section_score(semantic, full_text, exact=True) == pytest.approx(1.62)
