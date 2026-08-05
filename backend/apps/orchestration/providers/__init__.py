"""LLM provider contracts and static provider registry."""

from apps.orchestration.providers.base import LLMProvider
from apps.orchestration.providers.gemini import GeminiLLMProvider, GeminiLLMProviderError
from apps.orchestration.providers.mock import MockLLMProvider, MockLLMProviderError
from apps.orchestration.providers.ollama import OllamaLLMProvider, OllamaLLMProviderError
from apps.orchestration.providers.registry import LLMProviderDescriptor, get_llm_descriptor

__all__ = [
    "LLMProvider",
    "LLMProviderDescriptor",
    "GeminiLLMProvider",
    "GeminiLLMProviderError",
    "MockLLMProvider",
    "MockLLMProviderError",
    "OllamaLLMProvider",
    "OllamaLLMProviderError",
    "get_llm_descriptor",
]
