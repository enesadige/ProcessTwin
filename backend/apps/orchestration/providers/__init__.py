"""LLM provider contracts and static provider registry."""

from apps.orchestration.providers.base import LLMProvider
from apps.orchestration.providers.registry import LLMProviderDescriptor, get_llm_descriptor

__all__ = ["LLMProvider", "LLMProviderDescriptor", "get_llm_descriptor"]
