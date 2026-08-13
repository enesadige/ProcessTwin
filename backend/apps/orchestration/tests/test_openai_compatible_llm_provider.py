from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from apps.orchestration.natural_language_intake import LLMSemanticDecomposer
from apps.orchestration.providers.openai_compatible import (
    GROQ_LLM_BASE_URL,
    GROQ_LLM_MODEL,
    NVIDIA_LLM_BASE_URL,
    NVIDIA_LLM_MODEL,
    OpenAICompatibleLLMProviderError,
    groq_provider,
    nvidia_provider,
)
from apps.orchestration.structured_query import StructuredQuery


class FakeResponse:
    def __init__(self, *, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, path, json):
        self.calls.append((path, json))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def success_payload(content="OK"):
    return {
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
    }


@pytest.mark.parametrize(
    ("factory", "env_name", "base_url", "model", "structured_output_mode"),
    [
        (
            nvidia_provider,
            "NVIDIA_API_KEY",
            NVIDIA_LLM_BASE_URL,
            NVIDIA_LLM_MODEL,
            "json_schema",
        ),
        (
            groq_provider,
            "GROQ_API_KEY",
            GROQ_LLM_BASE_URL,
            GROQ_LLM_MODEL,
            "json_object",
        ),
    ],
)
def test_openai_compatible_provider_uses_allowlisted_endpoint_model_and_safe_key(
    settings, factory, env_name, base_url, model, structured_output_mode
):
    setattr(settings, env_name, "test-secret-key")
    captured = []
    client = FakeClient(FakeResponse(payload=success_payload()))

    def client_factory(received_base_url, timeout, api_key):
        captured.append((received_base_url, timeout, api_key))
        return client

    provider = factory(client_factory=client_factory)
    response = provider.generate(
        request={
            "contents": "Yalnızca OK yaz.",
            "format_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        }
    )

    assert captured == [(base_url, 120.0, "test-secret-key")]
    payload = client.calls[0][1]
    assert client.calls[0][0] == "/chat/completions"
    assert payload["model"] == model
    assert payload["temperature"] == 0
    assert payload["stream"] is False
    if structured_output_mode == "json_schema":
        assert payload["messages"] == [{"role": "user", "content": "Yalnızca OK yaz."}]
        assert payload["response_format"] == {
            "type": "json_schema",
            "json_schema": {
                "name": "processtwin_semantic_decomposition",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            },
        }
    else:
        assert payload["response_format"] == {"type": "json_object"}
        assert payload["messages"][0]["content"].startswith("Yalnızca OK yaz.")
        assert '"type": "object"' in payload["messages"][0]["content"]
    assert response["content"] == "OK"
    assert response["provider"] == provider.provider_name
    assert response["model"] == model
    assert "test-secret-key" not in repr(provider)


@pytest.mark.parametrize(
    ("factory", "env_name"),
    [(nvidia_provider, "NVIDIA_API_KEY"), (groq_provider, "GROQ_API_KEY")],
)
def test_openai_compatible_provider_has_safe_failure_categories(settings, factory, env_name):
    setattr(settings, env_name, "test-secret-key")

    for response, expected_code in (
        (FakeResponse(status_code=429), "rate_limited"),
        (FakeResponse(status_code=401), "authentication_failed"),
        (httpx.TimeoutException("timeout"), "timeout"),
    ):
        provider = factory(client_factory=lambda *_, response=response: FakeClient(response))
        with pytest.raises(OpenAICompatibleLLMProviderError) as exc_info:
            provider.generate(request={"contents": "safe"})
        assert exc_info.value.code == expected_code
        assert "test-secret-key" not in str(exc_info.value)
        assert "test-secret-key" not in repr(exc_info.value.details)


def test_openai_compatible_provider_rejects_invalid_response_without_payload_leak(settings):
    settings.NVIDIA_API_KEY = "test-secret-key"
    provider = nvidia_provider(
        client_factory=lambda *_: FakeClient(FakeResponse(payload={"choices": []}))
    )

    with pytest.raises(OpenAICompatibleLLMProviderError) as exc_info:
        provider.generate(request={"contents": "safe"})

    assert exc_info.value.code == "invalid_response"
    assert "test-secret-key" not in str(exc_info.value)


def test_missing_openai_compatible_key_does_not_construct_client(settings):
    settings.GROQ_API_KEY = ""
    invoked = False

    def client_factory(*_):
        nonlocal invoked
        invoked = True
        return SimpleNamespace()

    with pytest.raises(OpenAICompatibleLLMProviderError) as exc_info:
        groq_provider(client_factory=client_factory).generate(request={"contents": "safe"})

    assert exc_info.value.code == "missing_api_key"
    assert invoked is False


@pytest.mark.parametrize(
    ("factory", "env_name"),
    [(nvidia_provider, "NVIDIA_API_KEY"), (groq_provider, "GROQ_API_KEY")],
)
def test_openai_compatible_provider_supports_existing_phase_2_semantic_contract(
    settings, factory, env_name
):
    setattr(settings, env_name, "test-secret-key")
    client = FakeClient(
        FakeResponse(payload=success_payload('{"dimensions":["outage_classification"]}'))
    )
    provider = factory(client_factory=lambda *_: client)
    deterministic_query = StructuredQuery.model_validate(
        {
            "intent": "outage_impact",
            "requested_outputs": ["summary"],
            "snapshot_identifier": "provider-test-snapshot",
            "causal_event_code": "CE-TEST-001",
        }
    )

    result = LLMSemanticDecomposer(provider).merge(
        original_query="CE-TEST-001 tam hizmet kesintisi miydi?",
        deterministic_query=deterministic_query,
    )

    assert result.accepted is True
    assert result.structured_query.semantic_decomposition_status == "accepted"
    assert "response_format" in client.calls[0][1]
