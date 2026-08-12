from types import SimpleNamespace

import pytest

from apps.orchestration.providers import (
    GeminiLLMProvider,
    GeminiLLMProviderError,
    get_llm_descriptor,
)


class FakeProviderException(Exception):
    def __init__(self, *, status_code=None, message="provider failure", retry_after=None):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


class FakeModels:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeInteractions(FakeModels):
    def create(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeClient:
    def __init__(self, outcomes):
        self.models = FakeModels(outcomes)
        self.interactions = FakeInteractions(outcomes)


def success_response(*, content="Safe answer.", usage=True, finish_reason="STOP"):
    usage_metadata = (
        SimpleNamespace(
            prompt_token_count=11,
            candidates_token_count=7,
            total_token_count=18,
        )
        if usage
        else None
    )
    return SimpleNamespace(
        text=content,
        candidates=[
            SimpleNamespace(finish_reason=finish_reason, content=SimpleNamespace(parts=[]))
        ],
        usage_metadata=usage_metadata,
    )


def provider_with_outcomes(settings, outcomes):
    settings.GEMINI_API_KEY = "test-secret-key"
    settings.GEMINI_LLM_API_FAMILY = "generate_content"
    client = FakeClient(outcomes)
    provider = GeminiLLMProvider(client_factory=lambda api_key, timeout_ms: client)
    return provider, client


def test_gemini_provider_matches_registry_metadata_and_factory_without_network(settings):
    settings.GEMINI_API_KEY = "test-secret-key"
    settings.LLM_MODEL = "gemini-3.6-flash"

    provider = get_llm_descriptor("gemini").create_provider()

    assert isinstance(provider, GeminiLLMProvider)
    assert provider.metadata() == {
        "provider": "gemini",
        "model": "gemini-3.6-flash",
        "supports_thinking": False,
        "thinking_enabled": False,
    }


def test_missing_key_fails_before_client_factory_is_used(settings):
    settings.GEMINI_API_KEY = ""
    invoked = False

    def client_factory(api_key, timeout_ms):
        nonlocal invoked
        invoked = True
        raise AssertionError("Client factory must not be called without an API key.")

    with pytest.raises(GeminiLLMProviderError) as exc_info:
        GeminiLLMProvider(client_factory=client_factory).generate(request={"contents": "safe"})
    assert exc_info.value.code == "missing_api_key"
    assert invoked is False


def test_gemini_uses_provider_specific_narrative_timeout(settings):
    settings.GEMINI_API_KEY = "test-secret-key"
    settings.GEMINI_LLM_API_FAMILY = "generate_content"
    settings.GEMINI_LLM_TIMEOUT_MS = 120000
    captured = []

    def client_factory(api_key, timeout_ms):
        captured.append(timeout_ms)
        return FakeClient([success_response()])

    GeminiLLMProvider(client_factory=client_factory).generate(request={"contents": "safe"})

    assert captured == [120000]


def test_normalized_request_response_finish_reason_and_usage(settings):
    provider, client = provider_with_outcomes(settings, [success_response()])

    response = provider.generate(request={"contents": "Kısa bir yanıt üret."})

    assert client.models.calls == [
        {"model": "gemini-3.6-flash", "contents": "Kısa bir yanıt üret."}
    ]
    assert response == {
        "content": "Safe answer.",
        "finish_reason": "stop",
        "provider": "gemini",
        "model": "gemini-3.6-flash",
        "usage": {
            "input_tokens": 11,
            "output_tokens": 7,
            "total_tokens": 18,
            "available": True,
        },
        "retry": {"attempt_count": 1, "retry_count": 0, "total_retry_delay_ms": 0},
    }


def test_interactions_family_normalizes_output_text(settings):
    settings.GEMINI_API_KEY = "test-secret-key"
    settings.GEMINI_LLM_API_FAMILY = "interactions"
    interaction = SimpleNamespace(
        output_text="Safe interaction answer.",
        status="completed",
        usage_metadata=None,
    )
    client = FakeClient([interaction])

    response = GeminiLLMProvider(client_factory=lambda api_key, timeout_ms: client).generate(
        request={"contents": "safe"}
    )

    assert client.interactions.calls == [
        {
            "model": "gemini-3.6-flash",
            "input": "safe",
            "stream": False,
            "response_format": None,
        }
    ]
    assert response["content"] == "Safe interaction answer."
    assert response["finish_reason"] == "completed"


def test_usage_unavailable_does_not_claim_estimated_token_counts(settings):
    provider, _ = provider_with_outcomes(settings, [success_response(usage=False)])

    response = provider.generate(request={"contents": "Safe."})

    assert response["usage"] == {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "available": False,
    }


@pytest.mark.parametrize(
    "input_value",
    [
        {},
        {"contents": ""},
        {"contents": "ok", "model": "override"},
        {"contents": "ok", "format_schema": "override"},
    ],
)
def test_invalid_request_is_rejected_without_network(settings, input_value):
    settings.GEMINI_API_KEY = "test-secret-key"
    with pytest.raises(GeminiLLMProviderError) as exc_info:
        GeminiLLMProvider().generate(request=input_value)
    assert exc_info.value.code == "invalid_request"


def test_interactions_uses_native_response_format_for_statement_schema(settings):
    settings.GEMINI_API_KEY = "test-secret-key"
    settings.GEMINI_LLM_API_FAMILY = "interactions"
    interaction = SimpleNamespace(
        output_text='{"headline_id":null,"concepts":["evidence"],"selected_statement_ids":[],"relationships":[]}',
        status="completed",
        usage_metadata=None,
    )
    client = FakeClient([interaction])
    schema = {"type": "object", "additionalProperties": False}

    GeminiLLMProvider(client_factory=lambda api_key, timeout_ms: client).generate(
        request={"contents": "safe", "format_schema": schema}
    )

    assert client.interactions.calls[0]["response_format"] == {
        "type": "text",
        "mime_type": "application/json",
        "schema": schema,
    }


@pytest.mark.parametrize("response", [success_response(content=""), SimpleNamespace(candidates=[])])
def test_empty_or_malformed_response_is_safe_invalid_response(settings, response):
    provider, _ = provider_with_outcomes(settings, [response])
    with pytest.raises(GeminiLLMProviderError) as exc_info:
        provider.generate(request={"contents": "safe"})
    assert exc_info.value.code == "invalid_response"


@pytest.mark.parametrize(
    ("exception", "expected_code"),
    [
        (FakeProviderException(status_code=401, message="Bearer secret"), "invalid_api_key"),
        (FakeProviderException(status_code=403), "permission_denied"),
        (FakeProviderException(status_code=404), "model_not_found"),
        (FakeProviderException(status_code=429), "rate_limited"),
        (FakeProviderException(status_code=408), "timeout"),
        (FakeProviderException(status_code=400), "invalid_request"),
        (FakeProviderException(status_code=400, message="API key is invalid"), "invalid_api_key"),
        (FakeProviderException(status_code=500), "provider_unavailable"),
        (FakeProviderException(message="network failure 192.0.2.1"), "network_error"),
    ],
)
def test_provider_errors_are_mapped_without_secret_or_raw_exception_leaks(
    settings, exception, expected_code
):
    settings.GEMINI_LLM_MAX_ATTEMPTS = 1
    provider, _ = provider_with_outcomes(settings, [exception])
    with pytest.raises(GeminiLLMProviderError) as exc_info:
        provider.generate(request={"contents": "prompt with token=private"})
    assert exc_info.value.code == expected_code
    assert "secret" not in str(exc_info.value).lower()
    assert "192.0.2.1" not in str(exc_info.value)
    assert "private" not in str(exc_info.value)


def test_only_transient_errors_retry_up_to_the_configured_limit(settings, monkeypatch):
    settings.GEMINI_LLM_MAX_ATTEMPTS = 2
    settings.GEMINI_LLM_RETRY_INITIAL_BACKOFF_MS = 10
    settings.GEMINI_LLM_RETRY_MAX_BACKOFF_MS = 20
    settings.GEMINI_LLM_RETRY_JITTER_MS = 0
    slept: list[float] = []
    monkeypatch.setattr("apps.orchestration.providers.gemini.time.sleep", slept.append)
    provider, client = provider_with_outcomes(
        settings,
        [FakeProviderException(status_code=500), success_response()],
    )

    response = provider.generate(request={"contents": "safe"})

    assert response["content"] == "Safe answer."
    assert len(client.models.calls) == 2
    assert slept == [0.01]
    assert response["retry"] == {
        "attempt_count": 2,
        "retry_count": 1,
        "total_retry_delay_ms": 10,
    }


def test_provider_retry_after_wins_over_local_backoff(settings):
    settings.GEMINI_LLM_RETRY_INITIAL_BACKOFF_MS = 10
    settings.GEMINI_LLM_RETRY_MAX_BACKOFF_MS = 20
    settings.GEMINI_LLM_RETRY_JITTER_MS = 0

    delay = GeminiLLMProvider._retry_delay_ms(
        FakeProviderException(status_code=429, retry_after=1.5), 0
    )

    assert delay == 1500


def test_rate_limit_exhaustion_keeps_safe_retry_diagnostics(settings, monkeypatch):
    settings.GEMINI_LLM_MAX_ATTEMPTS = 3
    settings.GEMINI_LLM_RETRY_INITIAL_BACKOFF_MS = 0
    settings.GEMINI_LLM_RETRY_MAX_BACKOFF_MS = 0
    settings.GEMINI_LLM_RETRY_JITTER_MS = 0
    monkeypatch.setattr("apps.orchestration.providers.gemini.time.sleep", lambda _: None)
    provider, client = provider_with_outcomes(
        settings,
        [
            FakeProviderException(status_code=429),
            FakeProviderException(status_code=429),
            FakeProviderException(status_code=429),
        ],
    )

    with pytest.raises(GeminiLLMProviderError) as exc_info:
        provider.generate(request={"contents": "safe"})

    assert exc_info.value.code == "rate_limited"
    assert exc_info.value.details == {
        "attempt_count": 3,
        "retry_count": 2,
        "total_retry_delay_ms": 0,
    }
    assert len(client.models.calls) == 3


def test_persistent_errors_do_not_retry(settings):
    settings.GEMINI_LLM_MAX_ATTEMPTS = 3
    provider, client = provider_with_outcomes(settings, [FakeProviderException(status_code=403)])

    with pytest.raises(GeminiLLMProviderError) as exc_info:
        provider.generate(request={"contents": "safe"})
    assert exc_info.value.code == "permission_denied"
    assert len(client.models.calls) == 1


@pytest.mark.parametrize(
    ("setting_name", "value"),
    [("GEMINI_LLM_TIMEOUT_MS", 0), ("GEMINI_LLM_MAX_ATTEMPTS", 4)],
)
def test_invalid_operational_settings_are_rejected_safely(settings, setting_name, value):
    settings.GEMINI_API_KEY = "test-secret-key"
    setattr(settings, setting_name, value)
    with pytest.raises(GeminiLLMProviderError) as exc_info:
        GeminiLLMProvider(client_factory=lambda api_key, timeout_ms: FakeClient([])).generate(
            request={"contents": "safe"}
        )
    assert exc_info.value.code == "invalid_request"
