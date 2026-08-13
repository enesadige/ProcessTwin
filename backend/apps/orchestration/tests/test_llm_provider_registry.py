from dataclasses import FrozenInstanceError

import pytest
from django.core.exceptions import ImproperlyConfigured

from apps.orchestration.facade import OrchestrationRequest
from apps.orchestration.providers import get_llm_descriptor
from apps.orchestration.providers.ollama import OllamaLLMProvider
from apps.orchestration.providers.registry import (
    GEMMA4_MODEL,
    GROQ_PROVIDER,
    LLM_PROVIDER_REGISTRY,
    NVIDIA_PROVIDER,
)
from apps.rag.providers.registry import get_embedding_descriptor


def test_known_ollama_descriptor_is_fixed_and_disables_thinking():
    descriptor = get_llm_descriptor("ollama")

    assert descriptor.model == GEMMA4_MODEL
    assert descriptor.is_local is True
    assert descriptor.supports_thinking is True
    assert descriptor.thinking_enabled is False
    assert descriptor.production_allowed is True
    assert descriptor.adapter_factory is OllamaLLMProvider


@pytest.mark.parametrize("model", ["gemini-2.5-flash", "gemini-3.6-flash"])
def test_gemini_descriptor_resolves_configured_allowlisted_model(settings, model):
    settings.LLM_MODEL = model
    descriptor = get_llm_descriptor("gemini")

    assert descriptor.model == model
    assert descriptor.is_local is False
    assert descriptor.thinking_enabled is False
    assert descriptor.production_allowed is True
    assert descriptor.model_version == f"{model}-interactions-v1"
    assert descriptor.create_provider().metadata()["model"] == model


def test_gemini_descriptor_keeps_default_when_no_model_override(settings):
    settings.LLM_MODEL = "gemini-3.6-flash"

    descriptor = get_llm_descriptor("gemini")

    assert descriptor.model == "gemini-3.6-flash"


def test_gemini_selection_uses_gemini_default_when_process_default_is_gemma(settings):
    settings.LLM_MODEL = GEMMA4_MODEL

    descriptor = get_llm_descriptor("gemini")

    assert descriptor.provider == "gemini"
    assert descriptor.model == "gemini-3.6-flash"


@pytest.mark.parametrize(
    ("provider_name", "model"),
    [(NVIDIA_PROVIDER, "z-ai/glm-5.2"), (GROQ_PROVIDER, "openai/gpt-oss-120b")],
)
def test_openai_compatible_descriptors_are_fixed_allowlisted_pairs(provider_name, model):
    descriptor = get_llm_descriptor(provider_name)

    assert descriptor.provider == provider_name
    assert descriptor.model == model
    assert descriptor.is_local is False
    assert descriptor.create_provider().metadata()["model"] == model


@pytest.mark.parametrize("provider_name", [NVIDIA_PROVIDER, GROQ_PROVIDER])
def test_orchestration_request_allows_registered_cloud_generation_providers(provider_name):
    request = OrchestrationRequest.model_validate(
        {
            "snapshot_identifier": "provider-test-snapshot",
            "idempotency_key": "provider-test-key",
            "original_query": "CE-TEST-001 olayını incele.",
            "llm_provider": provider_name,
            "embedding_provider": "ollama",
        }
    )

    assert request.llm_provider == provider_name


def test_resolved_model_is_written_to_query_run_provider_provenance(settings, db):
    from apps.operations.tests.test_operations_models import create_snapshot
    from apps.orchestration.models import QueryRun
    from apps.orchestration.services import QueryRunService

    settings.LLM_MODEL = "gemini-2.5-flash"
    descriptor = get_llm_descriptor("gemini")
    snapshot = create_snapshot("gemini-model-provenance")
    run, _ = QueryRunService().create_or_get(
        data_snapshot=snapshot,
        idempotency_key="gemini-model-provenance-key",
        original_query="test",
    )

    QueryRunService().save_provider_provenance(
        run,
        requested_llm_provider="gemini",
        resolved_llm_provider=descriptor.provider,
        resolved_llm_model=descriptor.model,
        requested_embedding_provider="ollama",
        resolved_embedding_provider="ollama",
        resolved_embedding_model="qwen3-embedding:4b",
        embedding_prompt_version="qwen3-telecom-query-v1",
        structured_query_parser="deterministic",
        structured_query_parser_version="structured-query.v1",
    )

    persisted = QueryRun.objects.get(pk=run.pk)
    assert persisted.resolved_llm_provider == "gemini"
    assert persisted.resolved_llm_model == "gemini-2.5-flash"


@pytest.mark.parametrize("provider_name", ["", "unknown", "ollama-custom-model"])
def test_unknown_or_empty_provider_is_rejected(provider_name):
    with pytest.raises(ImproperlyConfigured, match="Unsupported LLM provider"):
        get_llm_descriptor(provider_name)


def test_registry_and_descriptors_are_immutable_and_construct_allowlisted_adapters_only():
    with pytest.raises(TypeError):
        LLM_PROVIDER_REGISTRY["new"] = object()
    with pytest.raises(FrozenInstanceError):
        get_llm_descriptor("ollama").thinking_enabled = True
    assert isinstance(get_llm_descriptor("ollama").create_provider(), OllamaLLMProvider)


@pytest.mark.parametrize(
    ("llm_provider", "embedding_provider", "expected_model"),
    [
        ("gemini", "gemini", "gemini-embedding-2"),
        ("gemini", "ollama", "qwen3-embedding:4b"),
        ("ollama", "gemini", "gemini-embedding-2"),
        ("ollama", "ollama", "qwen3-embedding:4b"),
        ("nvidia", "ollama", "qwen3-embedding:4b"),
        ("groq", "ollama", "qwen3-embedding:4b"),
    ],
)
def test_llm_and_embedding_provider_selection_remain_independent(
    settings, llm_provider, embedding_provider, expected_model
):
    settings.LLM_PROVIDER = llm_provider
    settings.RAG_EMBEDDING_PROVIDER = embedding_provider

    assert get_llm_descriptor().provider == llm_provider
    embedding = get_embedding_descriptor()
    assert embedding.model == expected_model
    assert embedding.dimensions == 768
    assert embedding.query_prompt_version in {"gemini-search-query-v1", "qwen3-telecom-query-v1"}


def test_descriptor_metadata_contains_no_network_configuration_or_credentials():
    metadata = get_llm_descriptor("ollama").metadata()
    serialized = str(metadata).lower()

    assert "base_url" not in metadata
    assert "api_key" not in metadata
    assert "token" not in metadata
    assert "http" not in serialized
