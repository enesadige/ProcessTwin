"""Future-compatible LLM adapter contract without runtime implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any

from apps.core.exceptions import ProcessTwinError


class LLMProviderError(ProcessTwinError):
    """Safe normalized LLM adapter failure without request or response content."""


class LLMProvider(ABC):
    """Common interface for a future provider adapter.

    The registry is deliberately usable without constructing an adapter. This
    keeps imports and provider selection free of network side effects.
    """

    provider_name: str
    model_name: str | None
    supports_thinking: bool
    thinking_enabled: bool
    supports_grounded_narrative: bool = False
    supports_request_unload: bool = False

    @abstractmethod
    def generate(self, *, request: Mapping[str, Any]) -> Mapping[str, Any]:
        """Execute a future normalized generation request."""
        raise NotImplementedError

    def metadata(self) -> dict[str, str | bool | None]:
        return {
            "provider": self.provider_name,
            "model": self.model_name,
            "supports_thinking": self.supports_thinking,
            "thinking_enabled": self.thinking_enabled,
        }
