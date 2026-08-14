from __future__ import annotations

import json
from collections.abc import Mapping

import pytest

from apps.geography.models import AreaProfileType, City, District
from apps.network.models import NetworkDevice, NetworkDeviceType
from apps.operations.tests.test_causal_models import create_causal_event
from apps.operations.tests.test_operations_models import create_snapshot
from apps.orchestration.natural_language_intake import (
    DETERMINISTIC_STRUCTURED_QUERY_PARSER_VERSION,
    STRUCTURED_QUERY_PARSER_PROMPT_VERSION,
    DeterministicStructuredQueryParser,
    LLMSemanticDecomposer,
    NaturalLanguageQueryParseError,
    NaturalLanguageStructuredQueryParser,
    query_requests_customer_impact,
)
from apps.orchestration.planner import DeterministicToolPlanner
from apps.orchestration.providers.base import LLMProvider
from apps.orchestration.providers.gemini import GeminiLLMProviderError
from apps.orchestration.structured_query import (
    AnalyticsSpecification,
    RequestedOutput,
    SemanticDimension,
    StructuredQuery,
)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("AGG-ANK-002 olayında kaç müşteri ve kaç abonelik etkilendi?", True),
        ("CE-MCR-0023 için kök alarm ve kök kaynak nedir?", False),
        ("müşteri etkisi doğrulandı mı?", True),
    ],
)
def test_customer_impact_intent_is_explicit_and_typed(query, expected):
    assert query_requests_customer_impact(query.casefold()) is expected


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


class SemanticProvider(RecordingProvider):
    def __init__(self, dimensions: object, *, fail: bool = False) -> None:
        super().__init__(fail=fail)
        self.dimensions = dimensions

    def generate(self, *, request: Mapping[str, object]) -> Mapping[str, object]:
        self.requests.append(request)
        if self.fail:
            raise RuntimeError("unavailable")
        return {
            "provider": self.provider_name,
            "model": self.model_name,
            "content": json.dumps({"dimensions": self.dimensions}),
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


def deterministic_query(snapshot_key: str) -> StructuredQuery:
    return StructuredQuery.model_validate(
        {
            "intent": "outage_impact",
            "requested_outputs": ["summary", "impact"],
            "snapshot_identifier": snapshot_key,
            "causal_event_code": "CE-INTAKE-001",
        }
    )


@pytest.mark.django_db
def test_semantic_decomposition_changes_real_requested_dimensions_without_overriding_anchor():
    snapshot = create_snapshot("intake-semantic-merge")
    create_causal_event(snapshot, code="CE-INTAKE-001")
    query = deterministic_query(snapshot.snapshot_key)
    result = LLMSemanticDecomposer(
        SemanticProvider(["outage_classification", "compensation_reason"])
    ).merge(
        original_query="CE-INTAKE-001 olayının sınıfı ve telafi nedeni nedir?",
        deterministic_query=query,
    )

    assert result.accepted is True
    assert result.structured_query.causal_event_code == "CE-INTAKE-001"
    assert result.structured_query.semantic_decomposition_status == "accepted"
    assert set(result.structured_query.semantic_dimensions) == {
        SemanticDimension.OUTAGE_CLASSIFICATION,
        SemanticDimension.COMPENSATION_REASON,
    }
    assert set(result.structured_query.requested_outputs) >= {
        RequestedOutput.DETAILS,
        RequestedOutput.EVIDENCE,
    }


@pytest.mark.django_db
def test_semantic_decomposition_normalizes_duplicates_and_rejects_unknown_dimensions():
    snapshot = create_snapshot("intake-semantic-validation")
    query = deterministic_query(snapshot.snapshot_key)
    duplicate = LLMSemanticDecomposer(
        SemanticProvider(["verified_customer_impact", "verified_customer_impact"])
    ).merge(original_query="CE-INTAKE-001 etkisi nedir?", deterministic_query=query)
    assert duplicate.accepted is True
    assert duplicate.structured_query.semantic_dimensions == [
        SemanticDimension.VERIFIED_CUSTOMER_IMPACT
    ]

    invalid = LLMSemanticDecomposer(SemanticProvider(["not_a_dimension"])).merge(
        original_query="CE-INTAKE-001 etkisi nedir?", deterministic_query=query
    )
    assert invalid.accepted is False
    assert invalid.structured_query.requested_outputs == query.requested_outputs
    assert invalid.structured_query.semantic_decomposition_status == "fallback"
    assert invalid.structured_query.semantic_decomposition_failure == "invalid_dimension"


@pytest.mark.django_db
def test_semantic_decomposition_provider_failure_preserves_deterministic_query():
    snapshot = create_snapshot("intake-semantic-fallback")
    query = deterministic_query(snapshot.snapshot_key)
    result = LLMSemanticDecomposer(SemanticProvider([], fail=True)).merge(
        original_query="CE-INTAKE-001 etkisi nedir?", deterministic_query=query
    )

    assert result.accepted is False
    assert result.structured_query.requested_outputs == query.requested_outputs
    assert result.structured_query.semantic_dimensions == []
    assert result.failure_code == "provider_unavailable"


def test_network_investigation_drops_semantic_dimension_without_safe_tool_output():
    query = StructuredQuery.model_validate(
        {
            "intent": "network_investigation",
            "requested_outputs": ["summary", "details", "root_cause", "evidence"],
            "snapshot_identifier": "intake-network-safe-output",
            "causal_event_code": "CE-INTAKE-001",
        }
    )

    result = LLMSemanticDecomposer(
        SemanticProvider(["alarm_correlation", "physical_root_cause"])
    ).merge(
        original_query="CE-INTAKE-001 alarmlarını kanıtlarıyla incele.",
        deterministic_query=query,
    )

    assert result.accepted is True
    assert SemanticDimension.ALARM_CORRELATION not in result.structured_query.semantic_dimensions
    assert SemanticDimension.PHYSICAL_ROOT_CAUSE in result.structured_query.semantic_dimensions
    assert RequestedOutput.CORRELATION not in result.structured_query.requested_outputs


def test_semantic_decomposition_skips_fully_deterministic_analytics_contract():
    query = StructuredQuery.model_validate(
        {
            "intent": "operational_analytics",
            "requested_outputs": ["summary", "impact"],
            "snapshot_identifier": "intake-analytics-contract",
            "analytics": AnalyticsSpecification(
                metric="affected_customers",
                aggregation="sum",
                group_by="city",
                comparison=True,
            ).model_dump(mode="json"),
        }
    )
    provider = SemanticProvider(["manual_review_reason"])

    result = LLMSemanticDecomposer(provider).merge(
        original_query="Haziran ve Temmuz arasında şehirleri müşteri etkisine göre sırala.",
        deterministic_query=query,
    )

    assert result.accepted is False
    assert result.failure_code is None
    assert result.structured_query == query
    assert result.structured_query.semantic_decomposition_status == "not_attempted"
    assert provider.requests == []


@pytest.mark.django_db
def test_semantic_decomposition_preserves_safe_gemini_provider_error_category():
    snapshot = create_snapshot("intake-semantic-gemini-error")
    query = deterministic_query(snapshot.snapshot_key)

    class GeminiFailureProvider(SemanticProvider):
        def generate(self, *, request: Mapping[str, object]) -> Mapping[str, object]:
            raise GeminiLLMProviderError(
                message="Gemini request is invalid.", code="invalid_request"
            )

    result = LLMSemanticDecomposer(GeminiFailureProvider([])).merge(
        original_query="CE-INTAKE-001 etkisi nedir?",
        deterministic_query=query,
    )

    assert result.accepted is False
    assert result.failure_code == "provider_call_failed_invalid_request"
    assert result.structured_query.semantic_decomposition_failure == (
        "provider_call_failed_invalid_request"
    )


@pytest.mark.django_db
def test_impact_evidence_gap_does_not_add_unavailable_rule_evidence_output():
    snapshot = create_snapshot("intake-impact-evidence-gap")
    query = StructuredQuery.model_validate(
        {
            "intent": "outage_impact",
            "requested_outputs": ["summary", "details", "impact"],
            "snapshot_identifier": snapshot.snapshot_key,
            "location": {"city": "İzmir", "district": "Konak"},
            "time_window": {
                "from_time": "2026-06-06T00:00:00Z",
                "to_time": "2026-06-06T23:59:59Z",
            },
        }
    )
    result = LLMSemanticDecomposer(SemanticProvider(["evidence_gap"])).merge(
        original_query="6 Haziran 2026 Konak etkisi ve kanıtı yetersiz kayıtlar",
        deterministic_query=query,
    )

    assert result.accepted is True
    assert RequestedOutput.EVIDENCE not in result.structured_query.requested_outputs
    assert RequestedOutput.IMPACT in result.structured_query.requested_outputs


@pytest.mark.django_db
def test_correlation_intent_ignores_broad_impact_dimension_from_semantic_decomposition():
    snapshot = create_snapshot("intake-correlation-dimension-noise")
    query = StructuredQuery.model_validate(
        {
            "intent": "alarm_correlation",
            "requested_outputs": ["summary", "correlation", "evidence"],
            "snapshot_identifier": snapshot.snapshot_key,
            "causal_event_code": "CE-INTAKE-001",
        }
    )

    result = LLMSemanticDecomposer(SemanticProvider(["evidence_gap"])).merge(
        original_query="CE-INTAKE-001 ile başka alarm arasında ilişki var mı?",
        deterministic_query=query,
    )

    assert result.accepted is True
    assert RequestedOutput.IMPACT not in result.structured_query.requested_outputs
    assert set(result.structured_query.requested_outputs) == {
        RequestedOutput.SUMMARY,
        RequestedOutput.CORRELATION,
        RequestedOutput.EVIDENCE,
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


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("prompt", "expected_intent"),
    [
        ("CE-INTAKE-001 olayinin kok nedeni nedir?", "network_investigation"),
        ("CE-INTAKE-001 icin failover ve yedek baglanti durumunu acikla.", "outage_impact"),
        (
            "CE-INTAKE-001 ve SUB-INTAKE-001 icin tazminat uygunlugu nedir?",
            "compensation_evaluation",
        ),
        ("CE-INTAKE-001 hangi kaynak ve section'a dayaniyor?", "rule_document_retrieval"),
        ("CE-INTAKE-001 icin kanit yetersiz mi, gercekten etkilendi mi?", "outage_impact"),
    ],
)
def test_deterministic_parser_extracts_supported_intents_without_provider(prompt, expected_intent):
    snapshot = create_snapshot("deterministic-intents")
    create_causal_event(snapshot, code="CE-INTAKE-001")
    from apps.customers.models import Subscription
    from apps.operations.tests.test_operations_models import (
        create_access_line,
        create_subscription_connection,
    )

    _, _, _, _, line = create_access_line(snapshot)
    connection = create_subscription_connection(snapshot, line)
    subscription = connection.subscription
    subscription.subscription_number = "SUB-INTAKE-001"
    subscription.save()

    parsed = DeterministicStructuredQueryParser().parse(original_query=prompt, snapshot=snapshot)

    assert parsed.prompt_version == DETERMINISTIC_STRUCTURED_QUERY_PARSER_VERSION
    assert parsed.structured_query.intent.value == expected_intent
    assert Subscription.objects.filter(pk=subscription.pk).exists()


@pytest.mark.django_db
def test_deterministic_parser_extracts_two_verified_events_and_a_bounded_correlation_window():
    snapshot = create_snapshot("cross-incident-intake")
    create_causal_event(snapshot, code="CE-CORR-001")
    create_causal_event(snapshot, code="CE-CORR-002")

    parsed = DeterministicStructuredQueryParser().parse(
        original_query=(
            "CE-CORR-001 ile CE-CORR-002 arasındaki alarm ilişkisi var mı? "
            "Bir saat önce başlayan olayları karşılaştır."
        ),
        snapshot=snapshot,
    )

    query = parsed.structured_query
    assert query.intent.value == "alarm_correlation"
    assert query.causal_event_code == "CE-CORR-001"
    assert query.comparison_causal_event_code == "CE-CORR-002"
    assert query.correlation_window_minutes == 60
    assert query.correlation_direction == "before"
    assert query.requested_outputs == [
        RequestedOutput.CORRELATION,
        RequestedOutput.EVIDENCE,
        RequestedOutput.SUMMARY,
    ]


@pytest.mark.django_db
def test_deterministic_parser_recognizes_folded_turkish_relation_question():
    snapshot = create_snapshot("cross-incident-folded-intake")
    create_causal_event(snapshot, code="CE-CORR-011")
    create_causal_event(snapshot, code="CE-CORR-012")

    parsed = DeterministicStructuredQueryParser().parse(
        original_query="CE-CORR-011 ile CE-CORR-012 olayları arasında ilişki var mı?",
        snapshot=snapshot,
    )

    assert parsed.structured_query.intent.value == "alarm_correlation"
    assert parsed.structured_query.comparison_causal_event_code == "CE-CORR-012"


@pytest.mark.django_db
def test_two_explicit_events_with_causal_direction_use_correlation_plan():
    snapshot = create_snapshot("two-event-causal-direction")
    create_causal_event(snapshot, code="CE-XREG-0001")
    create_causal_event(snapshot, code="CE-MCR-0023")

    parsed = DeterministicStructuredQueryParser().parse(
        original_query=(
            "CE-XREG-0001 ile CE-MCR-0023 arasında hangisinin diğerine neden "
            "olduğunu ve nedensel zincirin yönünü kesin olarak söyle."
        ),
        snapshot=snapshot,
    )

    query = parsed.structured_query
    assert query.intent.value == "alarm_correlation"
    assert query.causal_event_code == "CE-XREG-0001"
    assert query.comparison_causal_event_code == "CE-MCR-0023"


@pytest.mark.django_db
def test_same_event_alarm_investigation_uses_causal_alarm_tools():
    snapshot = create_snapshot("same-event-alarm-investigation")
    create_causal_event(snapshot, code="CE-MCR-0023")

    parsed = DeterministicStructuredQueryParser().parse(
        original_query=(
            "CE-MCR-0023 içindeki alarmlar arasında korelasyon var mı? "
            "Hangisi kök neden alarmı, hangileri semptom?"
        ),
        snapshot=snapshot,
    )

    query = parsed.structured_query
    assert query.intent.value == "network_investigation"
    assert query.comparison_causal_event_code is None
    plan = DeterministicToolPlanner().plan(query)
    assert [(call.server.value, call.tool_name) for call in plan.tool_plan.calls] == [
        ("network", "correlate_alarms"),
        ("network", "rank_root_cause_candidates"),
    ]


@pytest.mark.django_db
def test_deterministic_parser_recognizes_relation_question_with_modal_wording():
    snapshot = create_snapshot("cross-incident-modal-intake")
    create_causal_event(snapshot, code="CE-CORR-021")
    create_causal_event(snapshot, code="CE-CORR-022")

    parsed = DeterministicStructuredQueryParser().parse(
        original_query=(
            "CE-CORR-021 ile CE-CORR-022 yalnız zaman yakınlığı nedeniyle "
            "ilişkili sayılabilir mi?"
        ),
        snapshot=snapshot,
    )

    assert parsed.structured_query.intent.value == "alarm_correlation"


@pytest.mark.django_db
def test_deterministic_parser_resolves_explicit_alarm_pair_to_persisted_events():
    snapshot = create_snapshot("cross-incident-alarm-intake")
    first = create_causal_event(snapshot, code="CE-CORR-031")
    second = create_causal_event(snapshot, code="CE-CORR-032")
    from apps.operations.models import Alarm, AlarmStatus, Severity
    from apps.operations.tests.test_operations_models import create_alarm_type, create_maltepe_bng

    device = create_maltepe_bng(snapshot)
    alarm_type = create_alarm_type(snapshot, "ALARM_INTAKE")
    for alarm_id, event in (("ALM-CORR-031", first), ("ALM-CORR-032", second)):
        Alarm.objects.create(
            data_snapshot=snapshot,
            causal_event=event,
            alarm_id=alarm_id,
            alarm_type=alarm_type,
            device=device,
            severity=Severity.MAJOR,
            status=AlarmStatus.OPEN,
            detected_at=event.started_at,
        )

    parsed = DeterministicStructuredQueryParser().parse(
        original_query="ALM-CORR-031 ile ALM-CORR-032 ilişkili mi?",
        snapshot=snapshot,
    )

    assert parsed.structured_query.intent.value == "alarm_correlation"
    assert parsed.structured_query.causal_event_code == "CE-CORR-031"
    assert parsed.structured_query.comparison_causal_event_code == "CE-CORR-032"


@pytest.mark.django_db
def test_deterministic_parser_resolves_district_to_snapshot_parent_city_and_dates():
    snapshot = create_snapshot("deterministic-location")
    from apps.operations.tests.test_operations_models import create_maltepe_bng

    device = create_maltepe_bng(snapshot)
    parsed = DeterministicStructuredQueryParser().parse(
        original_query=(
            "2026-01-01 ile 2026-01-02 arasinda Maltepe ilcesinde kac kesinti oldu? "
            "Potansiyel kapsam ve failover ile korunanlari belirt."
        ),
        snapshot=snapshot,
    )

    assert parsed.structured_query.location is not None
    assert parsed.structured_query.location.city == device.city.name
    assert parsed.structured_query.location.district == "Maltepe"
    assert parsed.structured_query.time_window is not None
    assert parsed.missing_fields == ()


@pytest.mark.django_db
def test_deterministic_parser_uses_a_snapshot_device_code_as_operational_scope():
    snapshot = create_snapshot("deterministic-device-scope")
    from datetime import timedelta

    from django.utils import timezone

    from apps.operations.models import (
        Outage,
        OutageStatus,
        OutageType,
        RootCauseCategory,
        ServiceImpactClass,
    )
    from apps.operations.tests.test_operations_models import create_maltepe_bng

    device = create_maltepe_bng(snapshot, code="AGG-ANK-002")
    started_at = timezone.now() - timedelta(minutes=20)
    Outage.objects.create(
        data_snapshot=snapshot,
        outage_code="OUT-DEVICE-002",
        source_device=device,
        outage_type=OutageType.DEVICE,
        impact_type=ServiceImpactClass.FULL_OUTAGE,
        status=OutageStatus.RESOLVED,
        root_cause_category=RootCauseCategory.UNKNOWN,
        detected_at=started_at,
        started_at=started_at,
        ended_at=started_at + timedelta(minutes=10),
        resolved_at=started_at + timedelta(minutes=10),
    )

    parsed = DeterministicStructuredQueryParser().parse(
        original_query=(
            "AGG-ANK-002 cihazindaki kesintinin potansiyel kapsamini, "
            "dogrulanmis etkisini, failover durumunu ve kok nedenini acikla."
        ),
        snapshot=snapshot,
    )

    assert parsed.structured_query.device_code == "AGG-ANK-002"
    assert parsed.structured_query.outage_code == "OUT-DEVICE-002"
    assert parsed.structured_query.clarification_required is False
    assert parsed.missing_fields == ()


@pytest.mark.django_db
def test_device_impact_query_with_related_event_wording_is_not_alarm_correlation():
    snapshot = create_snapshot("deterministic-device-related-event")
    from apps.operations.tests.test_operations_models import create_maltepe_bng

    create_maltepe_bng(snapshot, code="AGG-ANK-002")

    parsed = DeterministicStructuredQueryParser().parse(
        original_query=(
            "AGG-ANK-002 için ilişkili olayı, kesinti sınıfını ve doğrulanmış "
            "müşteri/abonelik etkisini söyle. Müşteri etkisi bilinmiyorsa sıfır kabul etme; "
            "hangi kanıta dayandığını da belirt."
        ),
        snapshot=snapshot,
    )

    assert parsed.structured_query.intent.value == "outage_impact"
    assert parsed.structured_query.device_code == "AGG-ANK-002"
    assert "correlation" not in {
        requested_output.value for requested_output in parsed.structured_query.requested_outputs
    }


@pytest.mark.django_db
def test_device_impact_query_resolves_the_latest_equally_direct_outage():
    from datetime import timedelta

    from django.utils import timezone

    from apps.operations.models import (
        Outage,
        OutageStatus,
        OutageType,
        RootCauseCategory,
        ServiceImpactClass,
    )
    from apps.operations.tests.test_operations_models import create_maltepe_bng

    snapshot = create_snapshot("deterministic-device-latest-outage")
    device = create_maltepe_bng(snapshot, code="AGG-ANK-002")
    started_at = timezone.now() - timedelta(days=2)
    for outage_code, offset in (("OUT-DEVICE-OLD", 0), ("OUT-DEVICE-LATEST", 1)):
        Outage.objects.create(
            data_snapshot=snapshot,
            outage_code=outage_code,
            source_device=device,
            outage_type=OutageType.DEVICE,
            impact_type=ServiceImpactClass.FULL_OUTAGE,
            status=OutageStatus.RESOLVED,
            root_cause_category=RootCauseCategory.UNKNOWN,
            detected_at=started_at + timedelta(days=offset),
            started_at=started_at + timedelta(days=offset),
            ended_at=started_at + timedelta(days=offset, minutes=10),
            resolved_at=started_at + timedelta(days=offset, minutes=10),
        )

    parsed = DeterministicStructuredQueryParser().parse(
        original_query="AGG-ANK-002 için ilişkili olayı ve doğrulanmış müşteri etkisini söyle.",
        snapshot=snapshot,
    )

    assert parsed.structured_query.outage_code == "OUT-DEVICE-LATEST"
    assert parsed.structured_query.clarification_required is False


@pytest.mark.django_db
def test_deterministic_parser_does_not_match_a_device_code_prefix():
    snapshot = create_snapshot("deterministic-device-prefix")
    from apps.operations.tests.test_operations_models import create_maltepe_bng

    create_maltepe_bng(snapshot, code="AGG-ANK-002")

    parsed = DeterministicStructuredQueryParser().parse(
        original_query="AGG-ANK-0020 cihazindaki kesintiyi acikla.",
        snapshot=snapshot,
    )

    assert parsed.structured_query.device_code is None
    assert parsed.structured_query.clarification_required is True


@pytest.mark.django_db
def test_deterministic_parser_preserves_unicode_device_and_parses_turkish_date():
    snapshot = create_snapshot("deterministic-unicode-date")
    from apps.operations.tests.test_operations_models import create_maltepe_bng

    create_maltepe_bng(snapshot, code="AGG-İZM-002")
    device_query = DeterministicStructuredQueryParser().parse(
        original_query="AGG-İZM-002 cihazındaki olayın etkisini açıkla.",
        snapshot=snapshot,
    )
    date_query = DeterministicStructuredQueryParser().parse(
        original_query="6 Haziran 2026 tarihinde Maltepe ilçesinde kaç kesinti oldu?",
        snapshot=snapshot,
    )

    assert device_query.structured_query.device_code == "AGG-İZM-002"
    assert date_query.structured_query.time_window is not None
    assert date_query.structured_query.time_window.from_time.date().isoformat() == "2026-06-06"
    assert date_query.structured_query.intent.value == "operational_analytics"
    assert date_query.structured_query.analytics is not None
    assert date_query.structured_query.analytics.metric == "outage_count"
    assert date_query.structured_query.analytics.group_by is None


@pytest.mark.django_db
def test_device_resolution_prefers_reconciled_canonical_chain_over_history():
    from datetime import timedelta

    from django.utils import timezone

    from apps.operations.models import (
        Outage,
        OutageStatus,
        OutageType,
        RootCauseCategory,
        ServiceImpactClass,
    )
    from apps.operations.tests.test_operations_models import create_maltepe_bng

    snapshot = create_snapshot("deterministic-device-ranking")
    device = create_maltepe_bng(snapshot, code="AGG-ANK-002")
    started_at = timezone.now() - timedelta(hours=2)
    for code, metadata in (
        ("OUT-HISTORY-001", {}),
        ("OUT-CANONICAL-001", {"ground_truth_reconciled": True}),
    ):
        Outage.objects.create(
            data_snapshot=snapshot,
            outage_code=code,
            source_device=device,
            outage_type=OutageType.DEVICE,
            impact_type=ServiceImpactClass.FULL_OUTAGE,
            status=OutageStatus.RESOLVED,
            root_cause_category=RootCauseCategory.UNKNOWN,
            detected_at=started_at,
            started_at=started_at,
            ended_at=started_at + timedelta(minutes=10),
            resolved_at=started_at + timedelta(minutes=10),
            metadata=metadata,
        )

    parsed = DeterministicStructuredQueryParser().parse(
        original_query="AGG-ANK-002 cihazındaki kesintiyi açıkla.", snapshot=snapshot
    )

    assert parsed.structured_query.outage_code == "OUT-CANONICAL-001"
    assert parsed.missing_fields == ()


@pytest.mark.django_db
def test_analytics_ranking_is_a_typed_deterministic_query_without_an_anchor():
    snapshot = create_snapshot("analytics-query")

    parsed = DeterministicStructuredQueryParser().parse(
        original_query="Hangi şehirde en fazla tam hizmet kesintisi yaşandı?",
        snapshot=snapshot,
    )

    query = parsed.structured_query
    assert query.intent.value == "operational_analytics"
    assert query.analytics is not None
    assert query.analytics.metric == "full_outage_count"
    assert query.analytics.aggregation == "count"
    assert query.analytics.group_by == "city"
    assert query.analytics.limit == 1
    assert query.clarification_required is False


@pytest.mark.django_db
def test_count_metric_uses_count_when_ranked_highest_to_lowest():
    snapshot = create_snapshot("analytics-ranked-city-count")

    query = DeterministicStructuredQueryParser().parse(
        original_query=(
            "Mevcut veri setinde şehirleri tam hizmet kesintisi sayısına göre "
            "en yüksekten en düşüğe sırala."
        ),
        snapshot=snapshot,
    ).structured_query

    assert query.analytics is not None
    assert query.analytics.metric == "full_outage_count"
    assert query.analytics.aggregation == "count"
    assert query.analytics.direction == "desc"
    assert query.analytics.group_by == "city"


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("question", "expected_limit"),
    [
        ("Hangi şehirde en fazla tam hizmet kesintisi yaşandı?", 1),
        ("Temmuz 2026'da doğrulanmış müşteri etkisi en yüksek şehir hangisi?", 1),
        ("Tam hizmet kesintisine göre ilk 3 şehri sırala.", 3),
        ("Şehirleri tam hizmet kesintisine göre sırala.", None),
    ],
)
def test_analytics_ranking_limit_distinguishes_winner_from_exhaustive_list(
    question, expected_limit
):
    snapshot = create_snapshot("analytics-ranking-limit")

    query = DeterministicStructuredQueryParser().parse(
        original_query=question,
        snapshot=snapshot,
    ).structured_query

    assert query.analytics is not None
    assert query.analytics.group_by == "city"
    assert query.analytics.limit == expected_limit


@pytest.mark.django_db
def test_explicit_two_month_analytics_comparison_requires_no_operational_anchor():
    snapshot = create_snapshot("analytics-month-comparison")

    query = DeterministicStructuredQueryParser().parse(
        original_query=(
            "Haziran 2026 ile Temmuz 2026 aylarındaki doğrulanmış tam hizmet "
            "kesintisi sayılarını karşılaştır."
        ),
        snapshot=snapshot,
    ).structured_query

    assert query.intent.value == "operational_analytics"
    assert query.analytics is not None
    assert query.analytics.metric == "full_outage_count"
    assert query.analytics.aggregation == "count"
    assert query.analytics.group_by == "time_bucket"
    assert query.analytics.time_grain == "month"
    assert query.time_window is not None
    assert query.clarification_required is False


@pytest.mark.django_db
def test_grouped_month_comparison_preserves_city_dimension():
    snapshot = create_snapshot("analytics-city-month-comparison")

    query = DeterministicStructuredQueryParser().parse(
        original_query=(
            "Haziran 2026'dan Temmuz 2026'ya doğrulanmış müşteri etkisindeki "
            "değişime göre şehirleri sırala."
        ),
        snapshot=snapshot,
    ).structured_query

    assert query.analytics is not None
    assert query.analytics.group_by == "city"
    assert query.analytics.comparison is True
    assert query.analytics.time_grain == "month"
    assert query.analytics.limit is None


@pytest.mark.django_db
def test_grouped_month_comparison_preserves_alarm_type_and_explicit_limit():
    snapshot = create_snapshot("analytics-alarm-month-comparison")

    query = DeterministicStructuredQueryParser().parse(
        original_query=(
            "Haziran 2026 ile Temmuz 2026 arasında doğrulanmış müşteri etkisi "
            "en fazla değişen ilk 5 alarm tipini sırala."
        ),
        snapshot=snapshot,
    ).structured_query

    assert query.analytics is not None
    assert query.analytics.group_by == "alarm_type"
    assert query.analytics.comparison is True
    assert query.analytics.time_grain == "month"
    assert query.analytics.limit == 5


@pytest.mark.django_db
def test_explicit_multi_month_analytics_trend_requires_no_operational_anchor():
    snapshot = create_snapshot("analytics-multi-month-trend")

    query = DeterministicStructuredQueryParser().parse(
        original_query="Ocak 2026, Şubat 2026 ve Mart 2026 aylarına göre olay sayılarını göster.",
        snapshot=snapshot,
    ).structured_query

    assert query.analytics is not None
    assert query.analytics.metric == "event_count"
    assert query.analytics.group_by == "time_bucket"
    assert query.analytics.time_grain == "month"
    assert query.clarification_required is False


@pytest.mark.django_db
def test_analytics_comparison_without_period_remains_clarification_required():
    snapshot = create_snapshot("analytics-comparison-missing-period")

    query = DeterministicStructuredQueryParser().parse(
        original_query="Tam hizmet kesintisi sayılarını karşılaştır.",
        snapshot=snapshot,
    ).structured_query

    assert query.analytics is not None
    assert query.clarification_required is True
    assert [reason.value for reason in query.clarification_reasons] == ["missing_scope_filter"]


@pytest.mark.django_db
def test_analytics_city_month_alarm_type_scope_survives_deterministic_intake():
    snapshot = create_snapshot("analytics-city-month-scope")
    city = City.objects.create(name="İzmir", plate_code="35")
    district = District.objects.create(
        city=city,
        name="Konak",
        profile_type=AreaProfileType.MIXED,
    )
    NetworkDevice.objects.create(
        data_snapshot=snapshot,
        code="AGG-IZM-TEST-001",
        name="Analytics scope device",
        device_type=NetworkDeviceType.BNG,
        city=city,
        district=district,
    )

    query = DeterministicStructuredQueryParser().parse(
        original_query=(
            "Haziran 2026’da İzmir’de gerçekleşen olayları doğrulanmış müşteri etkisine "
            "göre en yüksekten en düşüğe sırala. En yüksek etkili ilk 3 alarm tipini belirt."
        ),
        snapshot=snapshot,
    ).structured_query

    assert query.location is not None
    assert query.location.city == "İzmir"
    assert query.time_window is not None
    assert query.analytics is not None
    assert query.analytics.aggregation == "sum"
    assert query.analytics.group_by == "alarm_type"
    assert query.analytics.limit == 3

    plan = DeterministicToolPlanner().plan(query)
    assert plan.tool_plan is not None
    assert plan.tool_plan.calls[0].arguments == {
        "snapshot_identifier": snapshot.snapshot_key,
        "metric": "affected_customers",
        "aggregation": "sum",
        "group_by": "alarm_type",
        "direction": "desc",
        "limit": 3,
        "from_time": query.time_window.from_time.isoformat().replace("+00:00", "Z"),
        "to_time": query.time_window.to_time.isoformat().replace("+00:00", "Z"),
        "city": "İzmir",
    }


@pytest.mark.django_db
def test_analytics_parser_supports_generic_potential_scope_and_event_count_metrics():
    snapshot = create_snapshot("analytics-generic-metrics")

    potential_scope = DeterministicStructuredQueryParser().parse(
        original_query="Potansiyel abonelik kapsamını şehirlere göre sırala.",
        snapshot=snapshot,
    ).structured_query
    event_count = DeterministicStructuredQueryParser().parse(
        original_query="Şehirlere göre olay sayısını göster.",
        snapshot=snapshot,
    ).structured_query

    assert potential_scope.analytics is not None
    assert potential_scope.analytics.metric == "potential_subscriptions"
    assert event_count.analytics is not None
    assert event_count.analytics.metric == "event_count"


@pytest.mark.django_db
def test_filtered_total_impact_does_not_group_by_incidental_event_wording():
    snapshot = create_snapshot("analytics-filtered-total")

    query = DeterministicStructuredQueryParser().parse(
        original_query=(
            "Failed failover olaylarında toplam kaç müşteri etkilendi? "
            "Yalnızca doğrulanmış müşteri etkisini kullan; bilinmeyenleri sıfır sayma."
        ),
        snapshot=snapshot,
    ).structured_query

    assert query.analytics is not None
    assert query.analytics.metric == "affected_customers"
    assert query.analytics.aggregation == "sum"
    assert query.analytics.group_by is None
    assert query.analytics.failed_failover is True


@pytest.mark.django_db
def test_exact_event_compensation_total_is_not_misclassified_as_dataset_analytics():
    snapshot = create_snapshot("anchored-compensation-total")
    create_causal_event(snapshot, code="CE-INTAKE-001")

    query = DeterministicStructuredQueryParser().parse(
        original_query=(
            "CE-INTAKE-001 için telafi uygunluğu nedir; hangi kural sürümü uygulandı ve "
            "DecisionEvidence kaydını belirt."
        ),
        snapshot=snapshot,
    ).structured_query

    assert query.intent.value == "compensation_evaluation"
    assert query.analytics is None
    assert query.clarification_required is False
    assert {item.value for item in query.requested_outputs} >= {
        "summary",
        "eligibility",
        "evidence",
    }


@pytest.mark.django_db
@pytest.mark.parametrize(
    "query",
    [
        "Çorum'da bu ay kaç kesinti oldu?",
        "Çorum şehrinde bu ay kaç kesinti oldu?",
        "Çorum'da bu ay kaç kesinti oldu?",
    ],
)
def test_unresolved_explicit_city_never_widens_an_analytics_scope(query):
    snapshot = create_snapshot("analytics-unresolved-city")

    parsed = DeterministicStructuredQueryParser().parse(
        original_query=query,
        snapshot=snapshot,
    ).structured_query

    assert parsed.clarification_required is True
    assert [reason.value for reason in parsed.clarification_reasons] == ["missing_scope_filter"]


@pytest.mark.django_db
def test_known_city_with_locative_suffix_keeps_the_existing_analytics_scope():
    snapshot = create_snapshot("analytics-known-locative-city")
    city = City.objects.create(name="Ankara", plate_code="06")
    district = District.objects.create(
        city=city,
        name="Çankaya",
        profile_type=AreaProfileType.MIXED,
    )
    NetworkDevice.objects.create(
        data_snapshot=snapshot,
        code="AGG-ANK-LOCATIVE-001",
        name="Known location device",
        device_type=NetworkDeviceType.BNG,
        city=city,
        district=district,
    )

    parsed = DeterministicStructuredQueryParser().parse(
        original_query="Ankara'da bu ay kaç kesinti oldu?",
        snapshot=snapshot,
    ).structured_query

    assert parsed.clarification_required is False
    assert [item.model_dump(exclude_none=True) for item in parsed.analytics_locations] == [
        {"city": "Ankara"}
    ]


@pytest.mark.django_db
def test_document_meaning_query_does_not_require_operational_anchor():
    snapshot = create_snapshot("document-intent-without-anchor")

    query = DeterministicStructuredQueryParser().parse(
        original_query=(
            "Dokümana göre FAILOVER_UNSUCCESSFUL ne anlama gelir? Kaynak ve bölüm belirt."
        ),
        snapshot=snapshot,
    ).structured_query

    assert query.intent.value == "rule_document_retrieval"
    assert query.retrieval_query is not None
    assert query.clarification_required is False


@pytest.mark.django_db
def test_document_semantic_dimensions_cannot_expand_into_operational_impact_output():
    snapshot = create_snapshot("document-semantic-boundary")
    query = DeterministicStructuredQueryParser().parse(
        original_query="Dokümana göre FAILOVER_UNSUCCESSFUL ne anlama gelir?",
        snapshot=snapshot,
    ).structured_query

    result = LLMSemanticDecomposer(
        SemanticProvider(["failover_status", "source_version_section", "summary"])
    ).merge(original_query="Dokümana göre anlamı nedir?", deterministic_query=query)

    assert result.accepted is True
    assert RequestedOutput.IMPACT not in result.structured_query.requested_outputs
    assert set(result.structured_query.requested_outputs) == {
        RequestedOutput.SUMMARY,
        RequestedOutput.DETAILS,
        RequestedOutput.EVIDENCE,
    }
