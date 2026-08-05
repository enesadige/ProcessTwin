"""Static LLM provider allowlist; adapters are intentionally not created here."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from types import MappingProxyType

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from apps.orchestration.providers.base import LLMProvider
from apps.orchestration.providers.gemini import GeminiLLMProvider
from apps.orchestration.providers.mock import MockLLMProvider
from apps.orchestration.providers.ollama import OllamaLLMProvider

OLLAMA_PROVIDER = "ollama"
GEMINI_PROVIDER = "gemini"
MOCK_PROVIDER = "mock"
GEMMA4_MODEL = "gemma4:12b-it-qat"


@dataclass(frozen=True)
class LLMProviderDescriptor:
    """Fixed provider metadata, independent from embedding descriptors."""

    registry_key: str
    provider: str
    model: str | None
    model_version: str
    prompt_version: str
    is_local: bool
    supports_thinking: bool
    thinking_enabled: bool
    production_allowed: bool
    adapter_factory: Callable[[], LLMProvider] | None = None

    def create_provider(self) -> LLMProvider:
        if self.adapter_factory is None:
            raise ImproperlyConfigured("LLM provider adapter is not implemented.")
        provider = self.adapter_factory()
        if provider.metadata() != {
            "provider": self.provider,
            "model": self.model,
            "supports_thinking": self.supports_thinking,
            "thinking_enabled": self.thinking_enabled,
        }:
            raise ImproperlyConfigured("LLM provider descriptor mismatch.")
        return provider

    def metadata(self) -> dict[str, str | bool | None]:
        return {
            "registry_key": self.registry_key,
            "provider": self.provider,
            "model": self.model,
            "model_version": self.model_version,
            "prompt_version": self.prompt_version,
            "is_local": self.is_local,
            "supports_thinking": self.supports_thinking,
            "thinking_enabled": self.thinking_enabled,
            "production_allowed": self.production_allowed,
        }


LLM_PROVIDER_REGISTRY = MappingProxyType(
    {
        OLLAMA_PROVIDER: LLMProviderDescriptor(
            registry_key=OLLAMA_PROVIDER,
            provider=OLLAMA_PROVIDER,
            model=GEMMA4_MODEL,
            model_version="gemma4-12b-it-qat-registry-v1",
            prompt_version="llm-provider-contract-v1",
            is_local=True,
            supports_thinking=True,
            thinking_enabled=False,
            production_allowed=True,
            adapter_factory=OllamaLLMProvider,
        ),
        GEMINI_PROVIDER: LLMProviderDescriptor(
            registry_key=GEMINI_PROVIDER,
            provider=GEMINI_PROVIDER,
            model="gemini-3.5-flash",
            model_version="gemini-3.5-flash-v1",
            prompt_version="llm-provider-contract-v1",
            is_local=False,
            supports_thinking=False,
            thinking_enabled=False,
            production_allowed=True,
            adapter_factory=GeminiLLMProvider,
        ),
        MOCK_PROVIDER: LLMProviderDescriptor(
            registry_key=MOCK_PROVIDER,
            provider=MOCK_PROVIDER,
            model="mock-llm-v1",
            model_version="mock-llm-deterministic-v1",
            prompt_version="mock-llm-contract-v1",
            is_local=True,
            supports_thinking=False,
            thinking_enabled=False,
            production_allowed=False,
            adapter_factory=MockLLMProvider,
        ),
    }
)


def get_llm_descriptor(provider_name: str | None = None) -> LLMProviderDescriptor:
    selected = (provider_name if provider_name is not None else settings.LLM_PROVIDER).strip()
    try:
        descriptor = LLM_PROVIDER_REGISTRY[selected]
    except KeyError as exc:
        raise ImproperlyConfigured("Unsupported LLM provider configuration.") from exc
    if not descriptor.production_allowed and not getattr(
        settings, "LLM_ALLOW_MOCK_PROVIDER", False
    ):
        raise ImproperlyConfigured("Mock LLM provider is disabled outside tests.")
    return descriptor
