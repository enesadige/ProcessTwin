"""Deterministic local test provider with no model or network dependency."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any

from apps.core.exceptions import ProcessTwinError
from apps.orchestration.providers.base import LLMProvider
from apps.orchestration.services import sanitize_json

MOCK_LLM_MODEL = "mock-llm-v1"
MOCK_LLM_PROVIDER = "mock"
MOCK_SUCCESS_SCENARIO = "deterministic_success"
MOCK_EMPTY_SCENARIO = "deterministic_empty"
MOCK_FAILURE_SCENARIO = "controlled_failure"
SUPPORTED_MOCK_SCENARIOS = frozenset(
    {MOCK_SUCCESS_SCENARIO, MOCK_EMPTY_SCENARIO, MOCK_FAILURE_SCENARIO}
)


class MockLLMProviderError(ProcessTwinError):
    """Safe, stable mock-provider failure for deterministic tests."""


class MockLLMProvider(LLMProvider):
    provider_name = MOCK_LLM_PROVIDER
    model_name = MOCK_LLM_MODEL
    supports_thinking = False
    thinking_enabled = False

    def generate(self, *, request: Mapping[str, Any]) -> Mapping[str, Any]:
        canonical_request = self._canonical_request(request)
        scenario = canonical_request.get("mock_scenario", MOCK_SUCCESS_SCENARIO)
        if not isinstance(scenario, str) or scenario not in SUPPORTED_MOCK_SCENARIOS:
            raise MockLLMProviderError(
                message="Mock provider scenario is invalid.",
                code="mock_llm_invalid_scenario",
            )
        if scenario == MOCK_FAILURE_SCENARIO:
            raise MockLLMProviderError(
                message="Mock provider controlled failure.",
                code="mock_llm_controlled_failure",
            )

        canonical_json = json.dumps(
            canonical_request,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )
        fingerprint = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()[:16]
        input_tokens = max(1, math.ceil(len(canonical_json) / 4))
        is_empty = scenario == MOCK_EMPTY_SCENARIO
        output_tokens = 0 if is_empty else 8
        return {
            "content": "" if is_empty else f"mock-response:{fingerprint}",
            "finish_reason": "stop",
            "model": self.model_name,
            "provider": self.provider_name,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            },
            "usage_is_mock_estimate": True,
        }

    def _canonical_request(self, request: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(request, Mapping):
            raise MockLLMProviderError(
                message="Mock provider request must be an object.",
                code="mock_llm_invalid_request",
            )
        sanitized = sanitize_json(dict(request))
        try:
            json.dumps(sanitized, ensure_ascii=False, sort_keys=True, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise MockLLMProviderError(
                message="Mock provider request must contain JSON-compatible values.",
                code="mock_llm_invalid_request",
            ) from exc
        return sanitized
