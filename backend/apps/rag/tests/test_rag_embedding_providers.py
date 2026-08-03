import math

import httpx
import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from apps.rag.providers import get_embedding_descriptor
from apps.rag.providers.base import EmbeddingProviderError
from apps.rag.providers.ollama import (
    OllamaEmbeddingProvider,
    Qwen3Embedding06BProvider,
    Qwen3Embedding4BBaselineProvider,
    Qwen3Embedding4BProvider,
)
from apps.rag.providers.registry import (
    OLLAMA_NOMIC_PROFILE,
    OLLAMA_QWEN3_06B_PROFILE,
    OLLAMA_QWEN3_4B_BASELINE_PROFILE,
    OLLAMA_QWEN3_4B_PROFILE,
)


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def test_provider_registry_contains_fixed_gemini_and_ollama_descriptors():
    gemini = get_embedding_descriptor("gemini")
    ollama = get_embedding_descriptor("ollama", embedding_profile=OLLAMA_NOMIC_PROFILE)
    qwen_small = get_embedding_descriptor(
        "ollama",
        embedding_profile=OLLAMA_QWEN3_06B_PROFILE,
    )
    qwen_large = get_embedding_descriptor(
        "ollama",
        embedding_profile=OLLAMA_QWEN3_4B_PROFILE,
    )
    qwen_large_baseline = get_embedding_descriptor(
        "ollama",
        embedding_profile=OLLAMA_QWEN3_4B_BASELINE_PROFILE,
    )

    assert gemini.metadata() == {
        "profile": "gemini",
        "provider": "gemini",
        "model": "gemini-embedding-2",
        "dimensions": 768,
        "embedding_version": "asymmetric-retrieval-v1",
        "prompt_version": "rag-section-aware-document-v2",
        "document_prompt_version": "rag-section-aware-document-v2",
        "query_prompt_version": "gemini-search-query-v1",
        "production_semantic_allowed": True,
    }
    assert ollama.metadata() == {
        "profile": "ollama-nomic-v2",
        "provider": "ollama",
        "model": "nomic-embed-text-v2-moe",
        "dimensions": 768,
        "embedding_version": "nomic-embed-v2-moe-768-v1",
        "prompt_version": "nomic-section-aware-document-v1",
        "document_prompt_version": "nomic-section-aware-document-v1",
        "query_prompt_version": "nomic-search-query-v1",
        "production_semantic_allowed": True,
    }
    assert qwen_small.model == "qwen3-embedding:0.6b"
    assert qwen_small.embedding_version == "qwen3-embedding-0.6b-768-v1"
    assert qwen_small.document_prompt_version == "qwen3-section-document-v1"
    assert qwen_small.query_prompt_version == "qwen3-telecom-query-v1"
    assert qwen_large.model == "qwen3-embedding:4b"
    assert qwen_large.embedding_version == "qwen3-embedding-4b-768-v1"
    assert qwen_large_baseline.model == qwen_large.model
    assert qwen_large_baseline.document_prompt_version == qwen_large.document_prompt_version
    assert qwen_large_baseline.query_prompt_version == "qwen3-query-baseline-v1"


def test_unknown_and_production_mock_provider_are_rejected(settings):
    with pytest.raises(ImproperlyConfigured):
        get_embedding_descriptor("unknown")
    settings.RAG_ALLOW_MOCK_EMBEDDINGS = False
    with pytest.raises(ImproperlyConfigured, match="disabled outside tests"):
        get_embedding_descriptor("mock")


@pytest.mark.parametrize(
    ("llm_provider", "embedding_provider", "expected"),
    [
        ("gemini", "gemini", "gemini"),
        ("gemini", "ollama", "ollama"),
        ("ollama", "gemini", "gemini"),
        ("ollama", "ollama", "ollama"),
    ],
)
def test_llm_and_embedding_provider_settings_are_independent(
    settings, llm_provider, embedding_provider, expected
):
    settings.LLM_PROVIDER = llm_provider
    settings.RAG_EMBEDDING_PROVIDER = embedding_provider

    assert get_embedding_descriptor().provider == expected
    assert settings.LLM_PROVIDER == llm_provider


def test_ollama_runtime_defaults_to_validated_qwen_profile(settings):
    settings.RAG_EMBEDDING_PROVIDER = "ollama"

    descriptor = get_embedding_descriptor()

    assert descriptor.profile == OLLAMA_QWEN3_4B_PROFILE
    assert descriptor.model == "qwen3-embedding:4b"


def test_provider_and_profile_mismatch_is_rejected():
    with pytest.raises(ImproperlyConfigured, match="do not match"):
        get_embedding_descriptor("gemini", embedding_profile=OLLAMA_QWEN3_06B_PROFILE)


@override_settings(OLLAMA_BASE_URL="http://127.0.0.1:11434")
def test_ollama_adapter_uses_fixed_endpoint_model_and_prompts(monkeypatch):
    provider = OllamaEmbeddingProvider()
    captured = {}

    def request(method, path, **kwargs):
        captured.update({"method": method, "path": path, **kwargs})
        return FakeResponse(
            payload={
                "model": "nomic-embed-text-v2-moe",
                "embeddings": [[1.0] + [0.0] * 767],
            }
        )

    monkeypatch.setattr(provider._client, "request", request)
    document = provider.document_input(
        "Başlık",
        "DOC-001",
        ["Ana", "Bölüm"],
        "Bölüm",
        "İçerik",
    )
    query = provider.query_input("yedek bağlantı")
    result = provider.embed(query, is_query=True)

    assert document.startswith("search_document: document_title: Başlık")
    assert "document_code: DOC-001" in document
    assert "section_path: Ana > Bölüm" in document
    assert "section_heading: Bölüm" in document
    assert "content: İçerik" in document
    assert query == "search_query: yedek bağlantı"
    assert captured["method"] == "POST"
    assert captured["path"] == "/api/embed"
    assert captured["timeout"] == provider.timeout
    assert captured["json"]["model"] == "nomic-embed-text-v2-moe"
    assert captured["json"]["input"] == [query]
    assert len(result) == 768


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"embeddings": [[0.0] * 3]}, "ollama_dimension_mismatch"),
        ({"embeddings": []}, "ollama_invalid_response"),
        ({"embeddings": [[math.nan] + [0.0] * 767]}, "ollama_invalid_response"),
        ({"embeddings": [[math.inf] + [0.0] * 767]}, "ollama_invalid_response"),
    ],
)
def test_ollama_adapter_rejects_invalid_responses(monkeypatch, payload, code):
    provider = OllamaEmbeddingProvider()
    monkeypatch.setattr(
        provider._client,
        "request",
        lambda *args, **kwargs: FakeResponse(payload=payload),
    )

    with pytest.raises(EmbeddingProviderError, match=code):
        provider.embed("metin")


def test_ollama_adapter_reports_model_missing_and_service_errors(monkeypatch):
    provider = OllamaEmbeddingProvider()
    monkeypatch.setattr(
        provider._client,
        "request",
        lambda *args, **kwargs: FakeResponse(payload={"models": []}),
    )
    with pytest.raises(EmbeddingProviderError, match="ollama_model_missing"):
        provider.validate_ready()

    calls = 0

    def unavailable(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("local service unavailable")

    monkeypatch.setattr(provider._client, "request", unavailable)
    with pytest.raises(EmbeddingProviderError, match="ollama_unavailable"):
        provider.embed("metin")
    assert calls == 3


def test_ollama_adapter_does_not_retry_client_errors(monkeypatch):
    provider = OllamaEmbeddingProvider()
    calls = 0

    def request(*args, **kwargs):
        nonlocal calls
        calls += 1
        return FakeResponse(status_code=400)

    monkeypatch.setattr(provider._client, "request", request)
    with pytest.raises(EmbeddingProviderError, match="ollama_request_failed"):
        provider.embed("metin")
    assert calls == 1


def test_qwen_adapter_uses_instruction_and_explicit_output_options(monkeypatch):
    provider = Qwen3Embedding06BProvider()
    captured = {}

    def request(method, path, **kwargs):
        captured.update({"method": method, "path": path, **kwargs})
        return FakeResponse(
            payload={
                "model": "qwen3-embedding:0.6b",
                "embeddings": [[1.0] + [0.0] * 767],
            }
        )

    monkeypatch.setattr(provider._client, "request", request)
    document = provider.document_input(
        "Metro SLA",
        "SYN-COMP-2026-METRO-SLA",
        ["Metro", "SLA İhlalleri"],
        "SLA İhlalleri",
        "# SLA İhlalleri\n\nPaket kaybı eşikleri.",
    )
    query = provider.query_input("veriler hedefe ulaşmıyor")
    provider.embed(query, is_query=True)

    assert document.startswith("document_title: Metro SLA")
    assert "search_document:" not in document
    assert "Instruct:" not in document
    assert document.count("SLA İhlalleri") == 2
    assert "content: Paket kaybı eşikleri." in document
    assert query.startswith("Instruct: Given a Turkish telecom operations query")
    assert query.endswith("Query: veriler hedefe ulaşmıyor")
    assert "search_query:" not in query
    assert captured["path"] == "/api/embed"
    assert captured["json"] == {
        "model": "qwen3-embedding:0.6b",
        "input": [query],
        "dimensions": 768,
        "truncate": False,
        "keep_alive": 0,
    }
    assert "think" not in captured["json"]


def test_qwen_4b_baseline_uses_raw_query_without_changing_document_prompt():
    provider = Qwen3Embedding4BBaselineProvider()

    document = provider.document_input(
        "Metro SLA",
        "SYN-COMP-2026-METRO-SLA",
        ["Metro", "SLA İhlalleri"],
        "SLA İhlalleri",
        "# SLA İhlalleri\n\nPaket kaybı eşikleri.",
    )

    assert provider.query_input("  veri paketleri kayboluyor  ") == "veri paketleri kayboluyor"
    assert "Instruct:" not in provider.query_input("veri paketleri kayboluyor")
    assert document.startswith("document_title: Metro SLA")
    assert provider.request_payload(["sorgu"]) == {
        "model": "qwen3-embedding:4b",
        "input": ["sorgu"],
        "dimensions": 768,
        "truncate": False,
        "keep_alive": 0,
    }


def test_qwen_document_batch_uses_bulk_timeout(monkeypatch):
    provider = Qwen3Embedding4BProvider()
    captured = {}

    def request(method, path, **kwargs):
        captured.update(kwargs)
        return FakeResponse(
            payload={
                "model": "qwen3-embedding:4b",
                "embeddings": [[1.0] + [0.0] * 767],
            }
        )

    monkeypatch.setattr(provider._client, "request", request)

    provider.embed_many(["document input"], is_query=False)

    assert captured["timeout"] == provider.bulk_timeout
