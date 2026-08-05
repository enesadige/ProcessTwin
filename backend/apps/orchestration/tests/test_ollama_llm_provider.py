from __future__ import annotations

import httpx
import pytest

from apps.orchestration.providers import (
    OllamaLLMProvider,
    OllamaLLMProviderError,
    get_llm_descriptor,
)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, json_error=None):
        self.status_code = status_code
        self._payload = payload
        self._json_error = json_error

    def json(self):
        if self._json_error is not None:
            raise self._json_error
        return self._payload


class FakeClient:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def post(self, path, *, json):
        self.calls.append({"path": path, "json": json})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def success_response(*, content="Safe answer.", usage=True, model="gemma4:12b-it-qat"):
    payload = {
        "model": model,
        "message": {"content": content},
        "done_reason": "stop",
    }
    if usage:
        payload.update({"prompt_eval_count": 11, "eval_count": 7})
    return FakeResponse(payload=payload)


def provider_with_outcomes(settings, outcomes):
    settings.OLLAMA_BASE_URL = "http://127.0.0.1:11434/api/"
    client = FakeClient(outcomes)
    base_urls = []
    provider = OllamaLLMProvider(
        client_factory=lambda base_url, timeout_seconds: (
            base_urls.append((base_url, timeout_seconds)) or client
        )
    )
    return provider, client, base_urls


def test_ollama_provider_matches_registry_metadata_and_factory_without_network():
    provider = get_llm_descriptor("ollama").create_provider()

    assert isinstance(provider, OllamaLLMProvider)
    assert provider.metadata() == {
        "provider": "ollama",
        "model": "gemma4:12b-it-qat",
        "supports_thinking": True,
        "thinking_enabled": False,
    }


def test_request_body_has_fixed_model_thinking_and_stream_contract(settings):
    provider, client, base_urls = provider_with_outcomes(settings, [success_response()])
    request = {"contents": "Kisa ve guvenli yanit."}

    response = provider.generate(request=request)

    assert request == {"contents": "Kisa ve guvenli yanit."}
    assert base_urls == [("http://127.0.0.1:11434", 30.0)]
    assert client.calls == [
        {
            "path": "/api/chat",
            "json": {
                "model": "gemma4:12b-it-qat",
                "messages": [{"role": "user", "content": "Kisa ve guvenli yanit."}],
                "think": False,
                "stream": False,
            },
        }
    ]
    assert response == {
        "content": "Safe answer.",
        "finish_reason": "stop",
        "provider": "ollama",
        "model": "gemma4:12b-it-qat",
        "usage": {
            "input_tokens": 11,
            "output_tokens": 7,
            "total_tokens": 18,
            "available": True,
        },
    }


@pytest.mark.parametrize(
    "input_data",
    [
        {},
        {"contents": ""},
        {"contents": "safe", "model": "override"},
        {"contents": "safe", "think": True},
        {"contents": "safe", "stream": True},
    ],
)
def test_request_overrides_are_rejected_before_network(settings, input_data):
    called = False

    def client_factory(base_url, timeout_seconds):
        nonlocal called
        called = True
        raise AssertionError("Network client must not be created for invalid requests.")

    with pytest.raises(OllamaLLMProviderError) as exc_info:
        OllamaLLMProvider(client_factory=client_factory).generate(request=input_data)
    assert exc_info.value.code == "invalid_request"
    assert called is False


def test_usage_unavailable_does_not_claim_estimated_token_counts(settings):
    provider, _, _ = provider_with_outcomes(settings, [success_response(usage=False)])

    assert provider.generate(request={"contents": "safe"})["usage"] == {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "available": False,
    }


@pytest.mark.parametrize(
    "response",
    [
        success_response(content=""),
        success_response(model="wrong-model"),
        FakeResponse(payload={"model": "gemma4:12b-it-qat", "message": {}}),
        FakeResponse(payload="not-an-object"),
        FakeResponse(json_error=ValueError("raw response")),
    ],
)
def test_malformed_responses_are_safe_invalid_response(settings, response):
    provider, _, _ = provider_with_outcomes(settings, [response])

    with pytest.raises(OllamaLLMProviderError) as exc_info:
        provider.generate(request={"contents": "prompt containing token=private"})
    assert exc_info.value.code == "invalid_response"
    assert "private" not in str(exc_info.value)
    assert "raw response" not in str(exc_info.value)


@pytest.mark.parametrize(
    ("status_code", "expected_code"),
    [(404, "model_not_found"), (400, "invalid_request"), (403, "invalid_request")],
)
def test_persistent_http_errors_are_mapped_without_retry(settings, status_code, expected_code):
    settings.OLLAMA_LLM_MAX_ATTEMPTS = 3
    provider, client, _ = provider_with_outcomes(settings, [FakeResponse(status_code=status_code)])

    with pytest.raises(OllamaLLMProviderError) as exc_info:
        provider.generate(request={"contents": "private prompt"})
    assert exc_info.value.code == expected_code
    assert len(client.calls) == 1
    assert "private" not in str(exc_info.value)


def test_transient_http_errors_retry_only_to_configured_limit(settings):
    settings.OLLAMA_LLM_MAX_ATTEMPTS = 2
    provider, client, _ = provider_with_outcomes(
        settings, [FakeResponse(status_code=503), success_response()]
    )

    assert provider.generate(request={"contents": "safe"})["content"] == "Safe answer."
    assert len(client.calls) == 2


@pytest.mark.parametrize(
    ("exception", "expected_code"),
    [
        (httpx.TimeoutException("private timeout"), "timeout"),
        (httpx.ConnectError("private network"), "network_error"),
    ],
)
def test_network_errors_are_redacted_and_retry_to_limit(settings, exception, expected_code):
    settings.OLLAMA_LLM_MAX_ATTEMPTS = 2
    provider, client, _ = provider_with_outcomes(settings, [exception, exception])

    with pytest.raises(OllamaLLMProviderError) as exc_info:
        provider.generate(request={"contents": "prompt with token=private"})
    assert exc_info.value.code == expected_code
    assert len(client.calls) == 2
    assert "private" not in str(exc_info.value)


@pytest.mark.parametrize(
    ("setting_name", "value"),
    [("OLLAMA_LLM_TIMEOUT_MS", 0), ("OLLAMA_LLM_MAX_ATTEMPTS", 4)],
)
def test_invalid_operational_settings_fail_safely_without_network(settings, setting_name, value):
    setattr(settings, setting_name, value)
    invoked = False

    def client_factory(base_url, timeout_seconds):
        nonlocal invoked
        invoked = True
        raise AssertionError("Client factory must not be invoked.")

    with pytest.raises(OllamaLLMProviderError) as exc_info:
        OllamaLLMProvider(client_factory=client_factory).generate(request={"contents": "safe"})
    assert exc_info.value.code == "configuration_error"
    assert invoked is False


def test_provider_input_contract_is_mapping_only(settings):
    with pytest.raises(OllamaLLMProviderError) as exc_info:
        OllamaLLMProvider().generate(request=[("contents", "safe")])  # type: ignore[arg-type]
    assert exc_info.value.code == "invalid_request"
