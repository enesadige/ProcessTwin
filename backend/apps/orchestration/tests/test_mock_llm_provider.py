import socket

import pytest
from django.core.exceptions import ImproperlyConfigured

from apps.orchestration.providers import MockLLMProvider, MockLLMProviderError, get_llm_descriptor
from apps.orchestration.providers.base import LLMProvider
from apps.orchestration.providers.mock import MOCK_LLM_MODEL


def test_mock_provider_implements_the_llm_contract_and_matches_its_descriptor(settings):
    settings.LLM_ALLOW_MOCK_PROVIDER = True

    provider = get_llm_descriptor("mock").create_provider()

    assert isinstance(provider, LLMProvider)
    assert isinstance(provider, MockLLMProvider)
    assert provider.metadata() == {
        "provider": "mock",
        "model": MOCK_LLM_MODEL,
        "supports_thinking": False,
        "thinking_enabled": False,
    }


def test_mock_success_is_deterministic_order_independent_and_does_not_mutate_input():
    provider = MockLLMProvider()
    request = {
        "mock_scenario": "deterministic_success",
        "messages": [{"role": "user", "content": "Kesinti özeti"}],
        "parameters": {"limit": 3},
    }
    reordered = {
        "parameters": {"limit": 3},
        "messages": [{"content": "Kesinti özeti", "role": "user"}],
        "mock_scenario": "deterministic_success",
    }
    original = {
        **request,
        "messages": [dict(request["messages"][0])],
        "parameters": dict(request["parameters"]),
    }

    first = provider.generate(request=request)
    second = provider.generate(request=reordered)

    assert first == second
    assert request == original
    assert first["content"].startswith("mock-response:")
    assert first["finish_reason"] == "stop"
    assert first["model"] == MOCK_LLM_MODEL
    assert first["provider"] == "mock"
    assert first["usage"]["total_tokens"] == (
        first["usage"]["input_tokens"] + first["usage"]["output_tokens"]
    )
    assert all(isinstance(value, int) for value in first["usage"].values())
    assert first["usage_is_mock_estimate"] is True


def test_mock_different_safe_input_has_a_different_deterministic_content():
    provider = MockLLMProvider()

    first = provider.generate(
        request={"query": "ilk", "mock_scenario": "deterministic_success"}
    )
    second = provider.generate(
        request={"query": "ikinci", "mock_scenario": "deterministic_success"}
    )

    assert first["content"] != second["content"]


def test_empty_and_controlled_failure_scenarios_are_safe_and_stable():
    provider = MockLLMProvider()

    empty = provider.generate(request={"mock_scenario": "deterministic_empty"})
    assert empty["content"] == ""
    assert empty["usage"]["output_tokens"] == 0

    with pytest.raises(MockLLMProviderError) as exc_info:
        provider.generate(
            request={
                "mock_scenario": "controlled_failure",
                "authorization": "Bearer secret-value",
                "raw_payload": {"ip": "192.0.2.10"},
            }
        )
    assert exc_info.value.code == "mock_llm_controlled_failure"
    assert "secret-value" not in str(exc_info.value)
    assert "192.0.2.10" not in str(exc_info.value)


@pytest.mark.parametrize("input_value", [[], "query", {"value": object()}])
def test_mock_rejects_invalid_requests_with_a_safe_stable_error(input_value):
    with pytest.raises(MockLLMProviderError) as exc_info:
        MockLLMProvider().generate(request=input_value)
    assert exc_info.value.code == "mock_llm_invalid_request"
    assert "object at" not in str(exc_info.value)


def test_mock_response_never_echoes_sensitive_or_raw_input_and_never_uses_network(monkeypatch):
    def fail_network(*args, **kwargs):
        raise AssertionError("Mock provider must not make network calls.")

    monkeypatch.setattr(socket, "create_connection", fail_network)
    response = MockLLMProvider().generate(
        request={
            "prompt": "Bearer secret-value 198.51.100.10 AA:BB:CC:DD:EE:FF",
            "customer_id": "CUST-001",
            "raw_mcp_response": {"session": "private"},
            "mock_scenario": "deterministic_success",
        }
    )
    serialized = str(response)

    for value in ("secret-value", "198.51.100.10", "AA:BB:CC:DD:EE:FF", "CUST-001", "private"):
        assert value not in serialized


def test_mock_selection_is_blocked_without_explicit_allowance(settings):
    settings.LLM_ALLOW_MOCK_PROVIDER = False

    with pytest.raises(ImproperlyConfigured, match="disabled outside tests"):
        get_llm_descriptor("mock")
