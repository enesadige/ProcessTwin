"""Small OpenAI-compatible chat adapter for configured cloud LLM providers."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import httpx
from django.conf import settings

from apps.orchestration.providers.base import LLMProvider, LLMProviderError

NVIDIA_LLM_PROVIDER = "nvidia"
NVIDIA_LLM_MODEL = "z-ai/glm-5.2"
NVIDIA_LLM_BASE_URL = "https://integrate.api.nvidia.com/v1"
GROQ_LLM_PROVIDER = "groq"
GROQ_LLM_MODEL = "openai/gpt-oss-120b"
GROQ_LLM_BASE_URL = "https://api.groq.com/openai/v1"
_TRANSIENT_STATUS_CODES = frozenset({408, 500, 502, 503, 504})


class OpenAICompatibleLLMProviderError(LLMProviderError):
    """Safe OpenAI-compatible provider failure with no payload details."""


class OpenAICompatibleLLMProvider(LLMProvider):
    """Normalize chat completions from a fixed allowlisted provider/model pair."""

    supports_thinking = False
    thinking_enabled = False
    supports_grounded_narrative = True

    def __init__(
        self,
        *,
        provider_name: str,
        model_name: str,
        base_url: str,
        api_key_env: str,
        client_factory: Callable[[str, float, str], Any] | None = None,
    ) -> None:
        self.provider_name = provider_name
        self.model_name = model_name
        self._base_url_value = base_url
        self._api_key_env = api_key_env
        self._client_factory = client_factory or self._build_http_client
        self._client: Any | None = None

    def generate(self, *, request: Mapping[str, Any]) -> Mapping[str, Any]:
        contents, format_schema = self._validate_request(request)
        try:
            response = self._get_client().post(
                "/chat/completions", json=self._request_payload(contents, format_schema)
            )
        except httpx.TimeoutException as exc:
            raise OpenAICompatibleLLMProviderError(
                message="Cloud LLM request timed out.", code="timeout"
            ) from exc
        except httpx.RequestError as exc:
            raise OpenAICompatibleLLMProviderError(
                message="Cloud LLM network error.", code="network_error"
            ) from exc
        error = self._response_error(response)
        if error is not None:
            raise error
        return self._normalize_response(response)

    def _get_client(self) -> Any:
        if self._client is None:
            api_key = (getattr(settings, self._api_key_env, "") or "").strip()
            if not api_key:
                raise OpenAICompatibleLLMProviderError(
                    message="Cloud LLM API key is not configured.", code="missing_api_key"
                )
            self._client = self._client_factory(
                self._base_url(), self._timeout_seconds(), api_key
            )
        return self._client

    @staticmethod
    def _build_http_client(base_url: str, timeout_seconds: float, api_key: str) -> httpx.Client:
        return httpx.Client(
            base_url=base_url,
            timeout=timeout_seconds,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    @staticmethod
    def _validate_request(request: Mapping[str, Any]) -> tuple[str, Mapping[str, Any] | None]:
        if not isinstance(request, Mapping):
            raise OpenAICompatibleLLMProviderError(
                message="Cloud LLM request must be an object.", code="invalid_request"
            )
        if set(request) - {"contents", "format_schema"}:
            raise OpenAICompatibleLLMProviderError(
                message="Cloud LLM request contains unsupported fields.", code="invalid_request"
            )
        contents = request.get("contents")
        if not isinstance(contents, str) or not contents.strip():
            raise OpenAICompatibleLLMProviderError(
                message="Cloud LLM request contents are invalid.", code="invalid_request"
            )
        format_schema = request.get("format_schema")
        if format_schema is not None and not isinstance(format_schema, Mapping):
            raise OpenAICompatibleLLMProviderError(
                message="Cloud LLM format schema is invalid.", code="invalid_request"
            )
        return contents, format_schema

    def _request_payload(
        self, contents: str, format_schema: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": contents}],
            "temperature": 0,
            "stream": False,
        }
        if format_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "processtwin_semantic_decomposition",
                    "strict": True,
                    "schema": dict(format_schema),
                },
            }
        return payload

    def _base_url(self) -> str:
        base_url = self._base_url_value.strip().rstrip("/")
        if not base_url.startswith("https://"):
            raise OpenAICompatibleLLMProviderError(
                message="Cloud LLM endpoint configuration is invalid.", code="configuration_error"
            )
        return base_url

    @staticmethod
    def _timeout_seconds() -> float:
        timeout_ms = getattr(settings, "CLOUD_LLM_TIMEOUT_MS", 120000)
        if not isinstance(timeout_ms, int) or timeout_ms <= 0:
            raise OpenAICompatibleLLMProviderError(
                message="Cloud LLM timeout configuration is invalid.", code="configuration_error"
            )
        return timeout_ms / 1000

    @staticmethod
    def _response_error(response: Any) -> OpenAICompatibleLLMProviderError | None:
        status_code = getattr(response, "status_code", None)
        if not isinstance(status_code, int):
            return OpenAICompatibleLLMProviderError(
                message="Cloud LLM response is invalid.", code="invalid_response"
            )
        if 200 <= status_code < 300:
            return None
        if status_code in {401, 403}:
            return OpenAICompatibleLLMProviderError(
                message="Cloud LLM authentication failed.", code="authentication_failed"
            )
        if status_code == 429:
            return OpenAICompatibleLLMProviderError(
                message="Cloud LLM rate limit was reached.", code="rate_limited"
            )
        if status_code == 404:
            return OpenAICompatibleLLMProviderError(
                message="Cloud LLM model was not found.", code="model_not_found"
            )
        if status_code in {400, 422}:
            return OpenAICompatibleLLMProviderError(
                message="Cloud LLM request is invalid.", code="invalid_request"
            )
        if status_code in _TRANSIENT_STATUS_CODES:
            return OpenAICompatibleLLMProviderError(
                message="Cloud LLM provider is unavailable.", code="provider_unavailable"
            )
        return OpenAICompatibleLLMProviderError(
            message="Cloud LLM provider is unavailable.", code="provider_unavailable"
        )

    def _normalize_response(self, response: Any) -> Mapping[str, Any]:
        try:
            payload = response.json()
        except (TypeError, ValueError) as exc:
            raise OpenAICompatibleLLMProviderError(
                message="Cloud LLM response is invalid.", code="invalid_response"
            ) from exc
        if not isinstance(payload, Mapping):
            raise OpenAICompatibleLLMProviderError(
                message="Cloud LLM response is invalid.", code="invalid_response"
            )
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
            raise OpenAICompatibleLLMProviderError(
                message="Cloud LLM response is invalid.", code="invalid_response"
            )
        message = choices[0].get("message")
        content = message.get("content") if isinstance(message, Mapping) else None
        if not isinstance(content, str) or not content.strip():
            raise OpenAICompatibleLLMProviderError(
                message="Cloud LLM response is invalid.", code="invalid_response"
            )
        usage = payload.get("usage")
        input_tokens = usage.get("prompt_tokens") if isinstance(usage, Mapping) else None
        output_tokens = usage.get("completion_tokens") if isinstance(usage, Mapping) else None
        total_tokens = usage.get("total_tokens") if isinstance(usage, Mapping) else None
        valid_usage = all(
            isinstance(value, int) and value >= 0
            for value in (input_tokens, output_tokens, total_tokens)
        )
        return {
            "content": content.strip(),
            "finish_reason": str(choices[0].get("finish_reason") or "unknown").lower(),
            "provider": self.provider_name,
            "model": self.model_name,
            "usage": {
                "input_tokens": input_tokens if valid_usage else 0,
                "output_tokens": output_tokens if valid_usage else 0,
                "total_tokens": total_tokens if valid_usage else 0,
                "available": valid_usage,
            },
        }


def nvidia_provider(*, client_factory: Callable[[str, float, str], Any] | None = None):
    return OpenAICompatibleLLMProvider(
        provider_name=NVIDIA_LLM_PROVIDER,
        model_name=NVIDIA_LLM_MODEL,
        base_url=NVIDIA_LLM_BASE_URL,
        api_key_env="NVIDIA_API_KEY",
        client_factory=client_factory,
    )


def groq_provider(*, client_factory: Callable[[str, float, str], Any] | None = None):
    return OpenAICompatibleLLMProvider(
        provider_name=GROQ_LLM_PROVIDER,
        model_name=GROQ_LLM_MODEL,
        base_url=GROQ_LLM_BASE_URL,
        api_key_env="GROQ_API_KEY",
        client_factory=client_factory,
    )
