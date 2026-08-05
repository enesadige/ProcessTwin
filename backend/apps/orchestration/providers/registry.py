"""Static LLM provider allowlist; adapters are intentionally not created here."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from types import MappingProxyType

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from apps.orchestration.providers.base import LLMProvider

OLLAMA_PROVIDER = "ollama"
GEMINI_PROVIDER = "gemini"
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
        ),
        GEMINI_PROVIDER: LLMProviderDescriptor(
            registry_key=GEMINI_PROVIDER,
            provider=GEMINI_PROVIDER,
            model=None,
            model_version="gemini-model-unconfigured-v1",
            prompt_version="llm-provider-contract-v1",
            is_local=False,
            supports_thinking=False,
            thinking_enabled=False,
        ),
    }
)


def get_llm_descriptor(provider_name: str | None = None) -> LLMProviderDescriptor:
    selected = (provider_name if provider_name is not None else settings.LLM_PROVIDER).strip()
    try:
        return LLM_PROVIDER_REGISTRY[selected]
    except KeyError as exc:
        raise ImproperlyConfigured("Unsupported LLM provider configuration.") from exc
