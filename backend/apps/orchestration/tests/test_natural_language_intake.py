from __future__ import annotations

import json
from collections.abc import Mapping

import pytest

from apps.operations.tests.test_causal_models import create_causal_event
from apps.operations.tests.test_operations_models import create_snapshot
from apps.orchestration.natural_language_intake import (
    STRUCTURED_QUERY_PARSER_PROMPT_VERSION,
    NaturalLanguageQueryParseError,
    NaturalLanguageStructuredQueryParser,
)
from apps.orchestration.providers.base import LLMProvider


class RecordingProvider(LLMProvider):
    provider_name = "ollama"
    model_name = "gemma4:12b-it-qat"
    supports_thinking = True
    thinking_enabled = False

    def __init__(self, payload: Mapping[str, object] | None = None, *, fail: bool = False) -> None:
        self.payload = payload
        self.fail = fail
        self.requests: list[Mapping[str, object]] = []

    def generate(self, *, request: Mapping[str, object]) -> Mapping[str, object]:
        self.requests.append(request)
        if self.fail:
            raise RuntimeError("unavailable")
        return {
            "provider": self.provider_name,
            "model": self.model_name,
            "content": json.dumps(self.payload),
        }


def candidate(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "intent": "network_investigation",
        "requested_outputs": ["summary", "root_cause"],
        "causal_event_code": "CE-INTAKE-001",
        "outage_code": None,
        "subscription_reference": None,
        "decision_type": None,
        "location_city": None,
        "location_district": None,
        "date_start": None,
        "date_end": None,
        "retrieval_query": None,
        "missing_fields": [],
        "assumptions": [],
    }
    payload.update(overrides)
    return payload


@pytest.mark.django_db
def test_parser_uses_native_schema_and_returns_validated_structured_query():
    snapshot = create_snapshot("intake-valid")
    create_causal_event(snapshot, code="CE-INTAKE-001")
    provider = RecordingProvider(candidate())

    parsed = NaturalLanguageStructuredQueryParser(provider=provider).parse(
        original_query="CE-INTAKE-001 olayinin kok nedeni nedir?", snapshot=snapshot
    )

    assert parsed.prompt_version == STRUCTURED_QUERY_PARSER_PROMPT_VERSION
    assert parsed.structured_query.causal_event_code == "CE-INTAKE-001"
    assert parsed.structured_query.intent.value == "network_investigation"
    assert provider.requests[0]["format_schema"]["additionalProperties"] is False
    assert "structured-query-parser-tr-v1" in provider.requests[0]["contents"]


@pytest.mark.django_db
def test_parser_rejects_invented_reference_date_and_location():
    snapshot = create_snapshot("intake-invented")
    create_causal_event(snapshot, code="CE-INTAKE-001")
    provider = RecordingProvider(
        candidate(
            location_city="Istanbul",
            date_start="2026-01-01",
            date_end="2026-01-02",
        )
    )

    with pytest.raises(NaturalLanguageQueryParseError) as exc_info:
        NaturalLanguageStructuredQueryParser(provider=provider).parse(
            original_query="CE-INTAKE-001 olayini incele.", snapshot=snapshot
        )

    assert exc_info.value.code == "invalid_structured_query"


@pytest.mark.django_db
def test_parser_returns_explicit_clarification_query_for_missing_scope():
    snapshot = create_snapshot("intake-clarification")
    provider = RecordingProvider(
        candidate(
            causal_event_code=None,
            requested_outputs=[],
            missing_fields=["operational_reference", "requested_output"],
        )
    )

    parsed = NaturalLanguageStructuredQueryParser(provider=provider).parse(
        original_query="Buna bakar misin?", snapshot=snapshot
    )

    assert parsed.structured_query.clarification_required is True
    assert {reason.value for reason in parsed.structured_query.clarification_reasons} == {
        "missing_operational_anchor",
        "missing_requested_output",
    }


@pytest.mark.django_db
@pytest.mark.parametrize(
    "provider",
    [RecordingProvider(fail=True), RecordingProvider({"intent": "network_investigation"})],
)
def test_parser_provider_and_schema_failures_are_safe(provider):
    snapshot = create_snapshot("intake-parser-failure")
    with pytest.raises(NaturalLanguageQueryParseError) as exc_info:
        NaturalLanguageStructuredQueryParser(provider=provider).parse(
            original_query="Kok neden nedir?", snapshot=snapshot
        )
    assert exc_info.value.code in {"query_parse_unavailable", "invalid_structured_query"}


@pytest.mark.django_db
def test_parser_rejects_public_reference_not_found_in_snapshot():
    snapshot = create_snapshot("intake-not-found")
    provider = RecordingProvider(candidate(causal_event_code="CE-UNKNOWN-001"))
    with pytest.raises(NaturalLanguageQueryParseError) as exc_info:
        NaturalLanguageStructuredQueryParser(provider=provider).parse(
            original_query="CE-UNKNOWN-001 olayini incele.", snapshot=snapshot
        )
    assert exc_info.value.code == "reference_not_found"
