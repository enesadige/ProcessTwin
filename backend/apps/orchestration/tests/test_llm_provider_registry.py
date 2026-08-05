from dataclasses import FrozenInstanceError

import pytest
from django.core.exceptions import ImproperlyConfigured

from apps.orchestration.providers import get_llm_descriptor
from apps.orchestration.providers.gemini import GeminiLLMProvider
from apps.orchestration.providers.registry import GEMMA4_MODEL, LLM_PROVIDER_REGISTRY
from apps.rag.providers.registry import get_embedding_descriptor


def test_known_ollama_descriptor_is_fixed_and_disables_thinking():
    descriptor = get_llm_descriptor("ollama")

    assert descriptor.model == GEMMA4_MODEL
    assert descriptor.is_local is True
    assert descriptor.supports_thinking is True
    assert descriptor.thinking_enabled is False
    assert descriptor.production_allowed is True
    assert descriptor.adapter_factory is None


def test_gemini_descriptor_uses_the_fixed_allowlisted_model_and_factory():
    descriptor = get_llm_descriptor("gemini")

    assert descriptor.model == "gemini-3.5-flash"
    assert descriptor.is_local is False
    assert descriptor.thinking_enabled is False
    assert descriptor.production_allowed is True
    assert descriptor.model_version == "gemini-3.5-flash-v1"
    assert descriptor.adapter_factory is GeminiLLMProvider


@pytest.mark.parametrize("provider_name", ["", "unknown", "ollama-custom-model"])
def test_unknown_or_empty_provider_is_rejected(provider_name):
    with pytest.raises(ImproperlyConfigured, match="Unsupported LLM provider"):
        get_llm_descriptor(provider_name)


def test_registry_and_descriptors_are_immutable_and_do_not_construct_adapters():
    with pytest.raises(TypeError):
        LLM_PROVIDER_REGISTRY["new"] = object()
    with pytest.raises(FrozenInstanceError):
        get_llm_descriptor("ollama").thinking_enabled = True
    with pytest.raises(ImproperlyConfigured, match="not implemented"):
        get_llm_descriptor("ollama").create_provider()


@pytest.mark.parametrize(
    ("llm_provider", "embedding_provider", "expected_model"),
    [
        ("gemini", "gemini", "gemini-embedding-2"),
        ("gemini", "ollama", "qwen3-embedding:4b"),
        ("ollama", "gemini", "gemini-embedding-2"),
        ("ollama", "ollama", "qwen3-embedding:4b"),
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
