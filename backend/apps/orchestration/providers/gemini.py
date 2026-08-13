"""Gemini LLM adapter with a fixed allowlisted model and safe error contract."""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Mapping
from typing import Any

from django.conf import settings

from apps.orchestration.providers.base import LLMProvider, LLMProviderError

GEMINI_LLM_MODEL = "gemini-3.6-flash"
GEMINI_LLM_PROVIDER = "gemini"
GEMINI_LLM_PROMPT_VERSION = "llm-provider-contract-v1"
GEMINI_INTERACTIONS_API_FAMILY = "interactions"
GEMINI_GENERATE_CONTENT_API_FAMILY = "generate_content"
TRANSIENT_ERROR_CODES = frozenset(
    {"timeout", "network_error", "rate_limited", "provider_unavailable"}
)


class GeminiLLMProviderError(LLMProviderError):
    """Safe Gemini adapter failure; never include provider request/response data."""


class GeminiLLMProvider(LLMProvider):
    provider_name = GEMINI_LLM_PROVIDER
    model_name = GEMINI_LLM_MODEL
    supports_thinking = False
    thinking_enabled = False
    supports_grounded_narrative = True

    def __init__(
        self,
        *,
        client_factory: Callable[[str, int], Any] | None = None,
        model_name: str | None = None,
    ) -> None:
        self._client_factory = client_factory or self._build_sdk_client
        self._client: Any | None = None
        self.model_name = model_name or GEMINI_LLM_MODEL

    def generate(self, *, request: Mapping[str, Any]) -> Mapping[str, Any]:
        contents, format_schema = self._validate_request(request)
        client = self._get_client()
        max_attempts = self._max_attempts()
        retry_count = 0
        total_retry_delay_ms = 0
        for attempt in range(max_attempts):
            try:
                if self._api_family() == GEMINI_INTERACTIONS_API_FAMILY:
                    response = client.interactions.create(
                        model=self.model_name,
                        input=contents,
                        stream=False,
                        response_format=self._interaction_response_format(format_schema),
                    )
                    normalized = self._normalize_interaction_response(response)
                else:
                    response = client.models.generate_content(
                        model=self.model_name, contents=contents
                    )
                    normalized = self._normalize_response(response)
                return self._with_retry_metadata(
                    normalized,
                    attempt_count=attempt + 1,
                    retry_count=retry_count,
                    total_retry_delay_ms=total_retry_delay_ms,
                )
            except GeminiLLMProviderError:
                raise
            except Exception as exc:
                error = self._map_exception(exc)
                if error.code in TRANSIENT_ERROR_CODES and attempt + 1 < max_attempts:
                    delay_ms = self._retry_delay_ms(exc, attempt)
                    retry_count += 1
                    total_retry_delay_ms += delay_ms
                    time.sleep(delay_ms / 1000)
                    continue
                if error.code in TRANSIENT_ERROR_CODES:
                    error.details.update(
                        {
                            "attempt_count": attempt + 1,
                            "retry_count": retry_count,
                            "total_retry_delay_ms": total_retry_delay_ms,
                        }
                    )
                raise error from exc
        raise GeminiLLMProviderError(
            message="Gemini provider is unavailable.", code="provider_unavailable"
        )

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        api_key = (getattr(settings, "GEMINI_API_KEY", "") or "").strip()
        if not api_key:
            raise GeminiLLMProviderError(
                message="Gemini API key is not configured.", code="missing_api_key"
            )
        self._client = self._client_factory(api_key, self._timeout_ms())
        return self._client

    @staticmethod
    def _build_sdk_client(api_key: str, timeout_ms: int) -> Any:
        try:
            from google import genai
        except ImportError as exc:
            raise GeminiLLMProviderError(
                message="Gemini SDK is unavailable.", code="provider_unavailable"
            ) from exc
        return genai.Client(api_key=api_key, http_options={"timeout": timeout_ms})

    @staticmethod
    def _validate_request(request: Mapping[str, Any]) -> tuple[str, Mapping[str, Any] | None]:
        if not isinstance(request, Mapping):
            raise GeminiLLMProviderError(
                message="Gemini request must be an object.", code="invalid_request"
            )
        if set(request) - {"contents", "format_schema"}:
            raise GeminiLLMProviderError(
                message="Gemini request contains unsupported fields.", code="invalid_request"
            )
        contents = request.get("contents")
        if not isinstance(contents, str) or not contents.strip():
            raise GeminiLLMProviderError(
                message="Gemini request contents are invalid.", code="invalid_request"
            )
        format_schema = request.get("format_schema")
        if format_schema is not None and not isinstance(format_schema, Mapping):
            raise GeminiLLMProviderError(
                message="Gemini format schema is invalid.", code="invalid_request"
            )
        return contents, format_schema

    @staticmethod
    def _interaction_response_format(
        format_schema: Mapping[str, Any] | None,
    ) -> dict[str, Any] | None:
        if format_schema is None:
            return None
        return {
            "type": "text",
            "mime_type": "application/json",
            "schema": dict(format_schema),
        }

    @staticmethod
    def _timeout_ms() -> int:
        timeout_ms = getattr(settings, "GEMINI_LLM_TIMEOUT_MS", 15000)
        if not isinstance(timeout_ms, int) or timeout_ms <= 0:
            raise GeminiLLMProviderError(
                message="Gemini timeout configuration is invalid.", code="invalid_request"
            )
        return timeout_ms

    @staticmethod
    def _max_attempts() -> int:
        max_attempts = getattr(settings, "GEMINI_LLM_MAX_ATTEMPTS", 2)
        if not isinstance(max_attempts, int) or not 1 <= max_attempts <= 3:
            raise GeminiLLMProviderError(
                message="Gemini retry configuration is invalid.", code="invalid_request"
            )
        return max_attempts

    @staticmethod
    def _retry_delay_ms(exc: Exception, attempt: int) -> int:
        provider_delay = GeminiLLMProvider._provider_retry_delay_ms(exc)
        if provider_delay is not None:
            return provider_delay
        initial = getattr(settings, "GEMINI_LLM_RETRY_INITIAL_BACKOFF_MS", 250)
        maximum = getattr(settings, "GEMINI_LLM_RETRY_MAX_BACKOFF_MS", 2000)
        jitter = getattr(settings, "GEMINI_LLM_RETRY_JITTER_MS", 100)
        if not all(isinstance(value, int) and value >= 0 for value in (initial, maximum, jitter)):
            raise GeminiLLMProviderError(
                message="Gemini retry configuration is invalid.", code="invalid_request"
            )
        if maximum < initial:
            raise GeminiLLMProviderError(
                message="Gemini retry configuration is invalid.", code="invalid_request"
            )
        base = min(maximum, initial * (2**attempt))
        return base + round(random.uniform(0, jitter))

    @staticmethod
    def _provider_retry_delay_ms(exc: Exception) -> int | None:
        for name in ("retry_after_ms", "retry_delay_ms"):
            value = getattr(exc, name, None)
            if isinstance(value, (int, float)) and 0 <= value <= 120_000:
                return round(value)
        retry_after = getattr(exc, "retry_after", None)
        if isinstance(retry_after, (int, float)) and 0 <= retry_after <= 120:
            return round(retry_after * 1000)
        response = getattr(exc, "response", None)
        headers = getattr(response, "headers", None)
        if headers is not None:
            value = headers.get("retry-after")
            try:
                seconds = float(value)
            except (TypeError, ValueError):
                return None
            if 0 <= seconds <= 120:
                return round(seconds * 1000)
        return None

    @staticmethod
    def _with_retry_metadata(
        response: Mapping[str, Any],
        *,
        attempt_count: int,
        retry_count: int,
        total_retry_delay_ms: int,
    ) -> Mapping[str, Any]:
        return {
            **response,
            "retry": {
                "attempt_count": attempt_count,
                "retry_count": retry_count,
                "total_retry_delay_ms": total_retry_delay_ms,
            },
        }

    @staticmethod
    def _api_family() -> str:
        family = getattr(settings, "GEMINI_LLM_API_FAMILY", GEMINI_INTERACTIONS_API_FAMILY)
        if family not in {GEMINI_INTERACTIONS_API_FAMILY, GEMINI_GENERATE_CONTENT_API_FAMILY}:
            raise GeminiLLMProviderError(
                message="Gemini API family configuration is invalid.", code="invalid_request"
            )
        return family

    def _normalize_interaction_response(self, response: Any) -> Mapping[str, Any]:
        content = getattr(response, "output_text", None)
        if not isinstance(content, str) or not content.strip():
            raise GeminiLLMProviderError(
                message="Gemini response is invalid.", code="invalid_response"
            )
        return {
            "content": content.strip(),
            "finish_reason": str(getattr(response, "status", "completed")).lower(),
            "provider": self.provider_name,
            "model": self.model_name,
            "usage": self._usage(response),
        }

    def _normalize_response(self, response: Any) -> Mapping[str, Any]:
        content = self._response_content(response)
        if not content:
            raise GeminiLLMProviderError(
                message="Gemini response is invalid.", code="invalid_response"
            )
        candidate = self._first_candidate(response)
        return {
            "content": content,
            "finish_reason": self._finish_reason(candidate),
            "provider": self.provider_name,
            "model": self.model_name,
            "usage": self._usage(response),
        }

    @staticmethod
    def _first_candidate(response: Any) -> Any:
        candidates = getattr(response, "candidates", None)
        if not isinstance(candidates, (list, tuple)) or not candidates:
            raise GeminiLLMProviderError(
                message="Gemini response is invalid.", code="invalid_response"
            )
        return candidates[0]

    def _response_content(self, response: Any) -> str:
        candidate = self._first_candidate(response)
        content = getattr(response, "text", None)
        if isinstance(content, str) and content.strip():
            return content.strip()
        candidate_content = getattr(candidate, "content", None)
        parts = getattr(candidate_content, "parts", None)
        if not isinstance(parts, (list, tuple)):
            raise GeminiLLMProviderError(
                message="Gemini response is invalid.", code="invalid_response"
            )
        text_parts = [getattr(part, "text", "") for part in parts]
        content = "".join(part for part in text_parts if isinstance(part, str)).strip()
        if not content:
            raise GeminiLLMProviderError(
                message="Gemini response is invalid.", code="invalid_response"
            )
        return content

    @staticmethod
    def _finish_reason(candidate: Any) -> str:
        finish_reason = getattr(candidate, "finish_reason", None)
        value = getattr(finish_reason, "name", finish_reason)
        return str(value).lower() if value is not None else "unknown"

    @staticmethod
    def _usage(response: Any) -> dict[str, int | bool]:
        usage_metadata = getattr(response, "usage_metadata", None)
        if usage_metadata is None:
            return {
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "available": False,
            }
        input_tokens = getattr(usage_metadata, "prompt_token_count", None)
        output_tokens = getattr(usage_metadata, "candidates_token_count", None)
        total_tokens = getattr(usage_metadata, "total_token_count", None)
        usage_counts = (input_tokens, output_tokens, total_tokens)
        if not all(isinstance(value, int) and value >= 0 for value in usage_counts):
            return {
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "available": False,
            }
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "available": True,
        }

    @staticmethod
    def _map_exception(exc: Exception) -> GeminiLLMProviderError:
        status_code = getattr(exc, "status_code", None)
        if status_code is None:
            response = getattr(exc, "response", None)
            status_code = getattr(response, "status_code", None)
        message = str(exc).lower()
        # Gemini may report an invalid API key as HTTP 400 rather than 401.
        # Classify only stable provider categories before the generic 400 mapping.
        if any(marker in message for marker in ("api key", "apikey", "unauthenticated")):
            return GeminiLLMProviderError(
                message="Gemini authentication failed.", code="invalid_api_key"
            )
        if "permission" in message or "forbidden" in message:
            return GeminiLLMProviderError(
                message="Gemini permission was denied.", code="permission_denied"
            )
        if "not found" in message or ("model" in message and "found" in message):
            return GeminiLLMProviderError(
                message="Gemini model was not found.", code="model_not_found"
            )
        if status_code == 401:
            return GeminiLLMProviderError(
                message="Gemini authentication failed.", code="invalid_api_key"
            )
        if status_code == 403:
            return GeminiLLMProviderError(
                message="Gemini permission was denied.", code="permission_denied"
            )
        if status_code == 404:
            return GeminiLLMProviderError(
                message="Gemini model was not found.", code="model_not_found"
            )
        if status_code == 400:
            return GeminiLLMProviderError(
                message="Gemini request is invalid.", code="invalid_request"
            )
        if status_code == 429:
            return GeminiLLMProviderError(
                message="Gemini rate limit was reached.", code="rate_limited"
            )
        if status_code == 408:
            return GeminiLLMProviderError(message="Gemini request timed out.", code="timeout")
        if status_code in {500, 502, 503, 504}:
            return GeminiLLMProviderError(
                message="Gemini provider is unavailable.", code="provider_unavailable"
            )
        if "timeout" in message:
            return GeminiLLMProviderError(message="Gemini request timed out.", code="timeout")
        if any(marker in message for marker in ("connect", "network", "dns", "socket")):
            return GeminiLLMProviderError(message="Gemini network error.", code="network_error")
        if any(marker in message for marker in ("api key", "authentication", "unauthenticated")):
            return GeminiLLMProviderError(
                message="Gemini authentication failed.", code="invalid_api_key"
            )
        if isinstance(exc, (TypeError, ValueError)):
            return GeminiLLMProviderError(
                message="Gemini request is invalid.", code="invalid_request"
            )
        return GeminiLLMProviderError(
            message="Gemini provider is unavailable.", code="provider_unavailable"
        )
