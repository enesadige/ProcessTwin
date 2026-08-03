from collections.abc import Callable
from dataclasses import dataclass

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from apps.rag.providers.base import EmbeddingProvider
from apps.rag.providers.gemini import GeminiEmbeddingProvider
from apps.rag.providers.mock import MockEmbeddingProvider
from apps.rag.providers.ollama import (
    OllamaEmbeddingProvider,
    Qwen3Embedding06BProvider,
    Qwen3Embedding4BBaselineProvider,
    Qwen3Embedding4BProvider,
)

MOCK_PROFILE = "mock"
GEMINI_PROFILE = "gemini"
OLLAMA_NOMIC_PROFILE = "ollama-nomic-v2"
OLLAMA_QWEN3_06B_PROFILE = "ollama-qwen3-0.6b"
OLLAMA_QWEN3_4B_BASELINE_PROFILE = "ollama-qwen3-4b-baseline"
OLLAMA_QWEN3_4B_PROFILE = "ollama-qwen3-4b"


@dataclass(frozen=True)
class EmbeddingProviderDescriptor:
    profile: str
    provider: str
    model: str
    dimensions: int
    embedding_version: str
    document_prompt_version: str
    query_prompt_version: str
    production_semantic_allowed: bool
    adapter_factory: Callable[[], EmbeddingProvider]

    def create_provider(self) -> EmbeddingProvider:
        provider = self.adapter_factory()
        actual = provider.metadata()
        expected = {
            "provider": self.provider,
            "model": self.model,
            "dimensions": self.dimensions,
            "embedding_version": self.embedding_version,
            "document_prompt_version": self.document_prompt_version,
            "query_prompt_version": self.query_prompt_version,
        }
        if any(actual.get(key) != value for key, value in expected.items()):
            raise ImproperlyConfigured("Embedding provider descriptor mismatch.")
        return provider

    def metadata(self) -> dict[str, str | int | bool]:
        return {
            "profile": self.profile,
            "provider": self.provider,
            "model": self.model,
            "dimensions": self.dimensions,
            "embedding_version": self.embedding_version,
            "prompt_version": self.document_prompt_version,
            "document_prompt_version": self.document_prompt_version,
            "query_prompt_version": self.query_prompt_version,
            "production_semantic_allowed": self.production_semantic_allowed,
        }


def _descriptor(profile: str, provider) -> EmbeddingProviderDescriptor:
    return EmbeddingProviderDescriptor(
        profile=profile,
        provider=provider.provider_name,
        model=provider.model_name,
        dimensions=provider.dimensions,
        embedding_version=provider.embedding_version,
        document_prompt_version=provider.document_prompt_version,
        query_prompt_version=provider.query_prompt_version,
        production_semantic_allowed=provider.production_semantic_allowed,
        adapter_factory=provider,
    )


DESCRIPTORS = {
    MOCK_PROFILE: _descriptor(MOCK_PROFILE, MockEmbeddingProvider),
    GEMINI_PROFILE: _descriptor(GEMINI_PROFILE, GeminiEmbeddingProvider),
    OLLAMA_NOMIC_PROFILE: _descriptor(OLLAMA_NOMIC_PROFILE, OllamaEmbeddingProvider),
    OLLAMA_QWEN3_06B_PROFILE: _descriptor(
        OLLAMA_QWEN3_06B_PROFILE,
        Qwen3Embedding06BProvider,
    ),
    OLLAMA_QWEN3_4B_BASELINE_PROFILE: _descriptor(
        OLLAMA_QWEN3_4B_BASELINE_PROFILE,
        Qwen3Embedding4BBaselineProvider,
    ),
    OLLAMA_QWEN3_4B_PROFILE: _descriptor(
        OLLAMA_QWEN3_4B_PROFILE,
        Qwen3Embedding4BProvider,
    ),
}

PROVIDER_DEFAULT_PROFILES = {
    "mock": MOCK_PROFILE,
    "gemini": GEMINI_PROFILE,
    "ollama": OLLAMA_QWEN3_4B_PROFILE,
}


def get_embedding_descriptor(
    provider_name: str | None = None,
    *,
    embedding_profile: str | None = None,
) -> EmbeddingProviderDescriptor:
    selected = provider_name or getattr(settings, "RAG_EMBEDDING_PROVIDER", "gemini")
    profile = embedding_profile or PROVIDER_DEFAULT_PROFILES.get(selected, selected)
    try:
        descriptor = DESCRIPTORS[profile]
    except KeyError as exc:
        raise ImproperlyConfigured("Unsupported embedding provider configuration.") from exc
    if provider_name and provider_name in PROVIDER_DEFAULT_PROFILES:
        if descriptor.provider != provider_name:
            raise ImproperlyConfigured("Embedding provider and profile do not match.")
    if descriptor.provider == "mock" and not getattr(
        settings,
        "RAG_ALLOW_MOCK_EMBEDDINGS",
        False,
    ):
        raise ImproperlyConfigured("Mock embedding provider is disabled outside tests.")
    return descriptor
