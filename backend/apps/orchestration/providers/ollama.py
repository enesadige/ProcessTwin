"""Ollama chat adapter with a fixed Gemma model and safe error contract."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import httpx
from django.conf import settings

from apps.orchestration.providers.base import LLMProvider, LLMProviderError

OLLAMA_LLM_MODEL = "gemma4:12b-it-qat"
OLLAMA_LLM_PROVIDER = "ollama"
_TRANSIENT_STATUS_CODES = frozenset({500, 502, 503, 504})


class OllamaLLMProviderError(LLMProviderError):
    """Safe Ollama adapter failure without provider request or response data."""


class OllamaLLMProvider(LLMProvider):
    provider_name = OLLAMA_LLM_PROVIDER
    model_name = OLLAMA_LLM_MODEL
    supports_thinking = True
    thinking_enabled = False
    supports_grounded_narrative = True
    supports_request_unload = True

    def __init__(
        self,
        *,
        client_factory: Callable[[str, float], Any] | None = None,
    ) -> None:
        self._client_factory = client_factory or self._build_http_client
        self._client: Any | None = None

    def generate(self, *, request: Mapping[str, Any]) -> Mapping[str, Any]:
        contents, format_schema, release_after = self._validate_request(request)
        max_attempts = self._max_attempts()
        payload = self._request_payload(contents, format_schema, release_after=release_after)

        for attempt in range(max_attempts):
            try:
                response = self._get_client().post("/api/chat", json=payload)
                error = self._response_error(response)
                if error is not None:
                    if (
                        getattr(response, "status_code", None) in _TRANSIENT_STATUS_CODES
                        and attempt + 1 < max_attempts
                    ):
                        continue
                    raise error
                return self._normalize_response(response)
            except OllamaLLMProviderError:
                raise
            except httpx.TimeoutException as exc:
                error = OllamaLLMProviderError(message="Ollama request timed out.", code="timeout")
                if attempt + 1 < max_attempts:
                    continue
                raise error from exc
            except httpx.RequestError as exc:
                error = OllamaLLMProviderError(
                    message="Ollama network error.", code="network_error"
                )
                if attempt + 1 < max_attempts:
                    continue
                raise error from exc

        raise OllamaLLMProviderError(
            message="Ollama provider is unavailable.", code="provider_unavailable"
        )

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = self._client_factory(self._base_url(), self._timeout_seconds())
        return self._client

    @staticmethod
    def _build_http_client(base_url: str, timeout_seconds: float) -> httpx.Client:
        return httpx.Client(base_url=base_url, timeout=timeout_seconds)

    @staticmethod
    def _validate_request(
        request: Mapping[str, Any],
    ) -> tuple[str, Mapping[str, Any] | None, bool]:
        if not isinstance(request, Mapping):
            raise OllamaLLMProviderError(
                message="Ollama request must be an object.", code="invalid_request"
            )
        if set(request) - {"contents", "format_schema", "release_after"}:
            raise OllamaLLMProviderError(
                message="Ollama request contains unsupported fields.", code="invalid_request"
            )
        contents = request.get("contents")
        if not isinstance(contents, str) or not contents.strip():
            raise OllamaLLMProviderError(
                message="Ollama request contents are invalid.", code="invalid_request"
            )
        format_schema = request.get("format_schema")
        if format_schema is not None and not isinstance(format_schema, Mapping):
            raise OllamaLLMProviderError(
                message="Ollama format schema is invalid.", code="invalid_request"
            )
        release_after = request.get("release_after", False)
        if not isinstance(release_after, bool):
            raise OllamaLLMProviderError(
                message="Ollama unload setting is invalid.", code="invalid_request"
            )
        return contents, format_schema, release_after

    @classmethod
    def _request_payload(
        cls,
        contents: str,
        format_schema: Mapping[str, Any] | None = None,
        *,
        release_after: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": cls.model_name,
            "messages": [{"role": "user", "content": contents}],
            "think": False,
            "stream": False,
            "raw": False,
            "options": {"temperature": 0},
        }
        if format_schema is not None:
            payload["format"] = dict(format_schema)
        if release_after:
            payload["keep_alive"] = 0
        return payload

    @staticmethod
    def _base_url() -> str:
        base_url = getattr(settings, "OLLAMA_BASE_URL", "")
        if not isinstance(base_url, str):
            raise OllamaLLMProviderError(
                message="Ollama endpoint configuration is invalid.", code="configuration_error"
            )
        normalized = base_url.strip().rstrip("/")
        if normalized.endswith("/api"):
            normalized = normalized[: -len("/api")]
        if not normalized:
            raise OllamaLLMProviderError(
                message="Ollama endpoint configuration is invalid.", code="configuration_error"
            )
        return normalized

    @staticmethod
    def _timeout_seconds() -> float:
        timeout_ms = getattr(settings, "OLLAMA_LLM_TIMEOUT_MS", 30000)
        if not isinstance(timeout_ms, int) or timeout_ms <= 0:
            raise OllamaLLMProviderError(
                message="Ollama timeout configuration is invalid.", code="configuration_error"
            )
        return timeout_ms / 1000

    @staticmethod
    def _max_attempts() -> int:
        max_attempts = getattr(settings, "OLLAMA_LLM_MAX_ATTEMPTS", 2)
        if not isinstance(max_attempts, int) or not 1 <= max_attempts <= 3:
            raise OllamaLLMProviderError(
                message="Ollama retry configuration is invalid.", code="configuration_error"
            )
        return max_attempts

    @classmethod
    def _response_error(cls, response: Any) -> OllamaLLMProviderError | None:
        status_code = getattr(response, "status_code", None)
        if not isinstance(status_code, int):
            return OllamaLLMProviderError(
                message="Ollama response is invalid.", code="invalid_response"
            )
        if 200 <= status_code < 300:
            return None
        if status_code == 404:
            return OllamaLLMProviderError(
                message="Ollama model was not found.", code="model_not_found"
            )
        if status_code in {400, 401, 403, 422}:
            return OllamaLLMProviderError(
                message="Ollama request is invalid.", code="invalid_request"
            )
        return OllamaLLMProviderError(
            message="Ollama provider is unavailable.", code="provider_unavailable"
        )

    def _normalize_response(self, response: Any) -> Mapping[str, Any]:
        try:
            payload = response.json()
        except (TypeError, ValueError) as exc:
            raise OllamaLLMProviderError(
                message="Ollama response is invalid.", code="invalid_response"
            ) from exc
        if not isinstance(payload, Mapping) or payload.get("model") != self.model_name:
            raise OllamaLLMProviderError(
                message="Ollama response is invalid.", code="invalid_response"
            )
        message = payload.get("message")
        content = message.get("content") if isinstance(message, Mapping) else None
        if not isinstance(content, str) or not content.strip():
            raise OllamaLLMProviderError(
                message="Ollama response is invalid.", code="invalid_response"
            )
        return {
            "content": content.strip(),
            "finish_reason": self._finish_reason(payload),
            "provider": self.provider_name,
            "model": self.model_name,
            "usage": self._usage(payload),
            "timings": self._timings(payload),
        }

    @staticmethod
    def _finish_reason(payload: Mapping[str, Any]) -> str:
        value = payload.get("done_reason")
        return value.lower() if isinstance(value, str) and value else "unknown"

    @staticmethod
    def _usage(payload: Mapping[str, Any]) -> dict[str, int | bool]:
        input_tokens = payload.get("prompt_eval_count")
        output_tokens = payload.get("eval_count")
        counts = (input_tokens, output_tokens)
        if not all(isinstance(value, int) and value >= 0 for value in counts):
            return {
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "available": False,
            }
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "available": True,
        }

    @staticmethod
    def _timings(payload: Mapping[str, Any]) -> dict[str, int | None]:
        """Keep non-sensitive Ollama timing telemetry when the server supplies it."""
        fields = ("load_duration", "prompt_eval_duration", "eval_duration")
        return {
            field: value if isinstance(value := payload.get(field), int) and value >= 0 else None
            for field in fields
        }
