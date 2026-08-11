from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import pytest

from apps.operations.tests.test_operations_models import create_snapshot
from apps.orchestration.executor import ExecutorStatus
from apps.orchestration.models import QueryRunStatus
from apps.orchestration.providers.base import LLMProvider
from apps.orchestration.providers.mock import MockLLMProvider
from apps.orchestration.response_builder import (
    ResponseBuilderError,
    ResponseGenerationMode,
    ValidatedResponseBuilder,
)
from apps.orchestration.result_merge import (
    CausalSummary,
    CompensationSummary,
    ImpactSummary,
    ProvenanceEntry,
    RetrievalSource,
    RuleSummary,
    ValidatedExecutionResult,
    ValidationStatus,
)
from apps.orchestration.services import QueryRunService
from apps.orchestration.tool_plan import MCPServer


class RecordingProvider(LLMProvider):
    provider_name = "recording"
    model_name = "recording-v1"
    supports_thinking = False
    thinking_enabled = False

    def __init__(self, content: str | None = None) -> None:
        self.content = content
        self.requests: list[Mapping[str, Any]] = []

    def generate(self, *, request: Mapping[str, Any]) -> Mapping[str, Any]:
        self.requests.append(dict(request))
        content = self.content
        if content is None:
            statement_ids = request["format_schema"]["properties"]["selected_statement_ids"][
                "items"
            ]["enum"]
            concepts = request["format_schema"]["properties"]["concepts"]["items"]["enum"]
            content = json.dumps(
                {
                    "headline_id": "H1",
                    "concepts": concepts[:2],
                    "selected_statement_ids": statement_ids,
                    "relationships": [],
                }
            )
        return {
            "content": content,
            "finish_reason": "stop",
            "provider": self.provider_name,
            "model": self.model_name,
            "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        }


class RelationshipProvider(RecordingProvider):
    def generate(self, *, request: Mapping[str, Any]) -> Mapping[str, Any]:
        self.requests.append(dict(request))
        schema = request["format_schema"]
        statement_ids = schema["properties"]["selected_statement_ids"]["items"]["enum"]
        concepts = schema["properties"]["concepts"]["items"]["enum"]
        content = json.dumps(
            {
                "headline_id": "H1",
                "concepts": ["primary_backup_state", "failover_explanation"],
                "selected_statement_ids": statement_ids,
                "relationships": (
                    []
                    if len(statement_ids) < 2
                    else [
                        {
                            "type": "contrast",
                            "from_statement_id": statement_ids[0],
                            "to_statement_id": statement_ids[1],
                        }
                    ]
                ),
            }
        )
        assert "primary_backup_state" in concepts
        return {
            "content": content,
            "provider": self.provider_name,
            "model": self.model_name,
            "retry": {},
        }


class DuplicateConceptProvider(RecordingProvider):
    def generate(self, *, request: Mapping[str, Any]) -> Mapping[str, Any]:
        schema = request["format_schema"]
        statement_ids = schema["properties"]["selected_statement_ids"]["items"]["enum"]
        return {
            "content": json.dumps(
                {
                    "headline_id": "H1",
                    "concepts": ["verified_customer_impact", "verified_customer_impact"],
                    "selected_statement_ids": statement_ids,
                    "relationships": [],
                }
            ),
            "provider": self.provider_name,
            "model": self.model_name,
            "retry": {},
        }


def valid_result(snapshot_identifier: str, *, warnings: list[str] | None = None):
    return ValidatedExecutionResult(
        snapshot_identifier=snapshot_identifier,
        execution_status=ExecutorStatus.PARTIAL if warnings else ExecutorStatus.SUCCEEDED,
        validation_status=ValidationStatus.VALID,
        causal_summary=CausalSummary(
            causal_event_code="CE-GPON-001",
            root_resource_type="device",
            root_resource_reference="OLT-001",
            root_cause_reason_codes=["shared_upstream"],
            propagation_summary="Üst katman etkisi doğrulandı.",
            root_cause_summary="OLT_UNREACHABLE",
            root_alarm_types=["OLT_UNREACHABLE"],
            symptom_alarm_types=["ONT_DISCONNECT_SURGE"],
            dying_gasp_classification="symptom",
            device_not_active_classification="not_observed",
            primary_status="down",
            backup_status="active",
            full_outage=False,
        ),
        impact_summary=ImpactSummary(
            outage_count=3,
            potential=5,
            verified_impacted=2,
            verified_no_impact=1,
            insufficient_evidence=1,
            failover_protected=1,
            assessment_record_count=0,
            missing_evidence_categories=["customer_impact_assessment"],
        ),
        rule_summary=RuleSummary(
            rule_codes=["REFUND-001"],
            rule_versions=["REFUND-001:v2"],
            eligibility_status="eligible",
            evidence_references=["EVIDENCE-001"],
        ),
        compensation_summary=CompensationSummary(
            status="available",
            considered=2,
            eligible=1,
            ineligible_pending=1,
            total_amount="10.00",
            currency="TRY",
            evidence_references=["EVIDENCE-001"],
            scope="verified_impact",
        ),
        retrieval_sources=[
            RetrievalSource(source_code="SYN-COMP-2026", version=2, section="Uygunluk koşulları")
        ],
        provenance=[
            ProvenanceEntry(
                call_id="rule_evidence",
                server=MCPServer.RULE,
                tool_name="get_rule_evidence",
                correlation_id="request:rule_evidence",
            )
        ],
        warnings=warnings or [],
    )


def completed_run(
    seed: str,
    *,
    result: ValidatedExecutionResult | None = None,
    snapshot=None,
    original_query: str = "Müşteri CUST-001 için 198.51.100.10 etkisini açıkla.",
):
    snapshot = snapshot or create_snapshot(seed)
    result = result or valid_result(snapshot.snapshot_key)
    service = QueryRunService()
    run, _ = service.create_or_get(
        data_snapshot=snapshot,
        idempotency_key=f"response-{snapshot.snapshot_key}",
        original_query=original_query,
    )
    service.transition(run, target_status=QueryRunStatus.PLANNED)
    service.transition(run, target_status=QueryRunStatus.EXECUTING)
    return service.complete(run, final_result=result.to_final_result())


@pytest.mark.django_db
def test_deterministic_response_renders_validated_sections_and_keeps_run_unchanged():
    run = completed_run("response-deterministic")
    original_final_result = dict(run.final_result)

    response = ValidatedResponseBuilder().build(run)

    assert response.generation_mode == ResponseGenerationMode.DETERMINISTIC
    assert response.provider is None
    assert response.structured_result is not None
    assert response.structured_result.impact_summary is not None
    assert response.structured_result.impact_summary.verified_impacted == 2
    assert response.structured_result.impact_summary.verified_no_impact == 1
    assert response.structured_result.impact_summary.potential == 5
    assert response.structured_result.compensation_summary is not None
    assert response.structured_result.compensation_summary.total_amount == "10.00"
    assert "Potansiyel etki: 5 bağlantı." in response.response_text
    assert "Doğrulanmış etki: 2 bağlantı." in response.response_text
    assert "Etkilenmediği doğrulanan: 1 bağlantı." in response.response_text
    assert "Kanıtı yetersiz: 1 bağlantı." in response.response_text
    assert (
        "Failover ile korunan: 1 bağlantı tam hizmet kesintisi değildir." in response.response_text
    )
    assert "Doğrulanmış ana kök neden: OLT_UNREACHABLE." in response.response_text
    assert "Dying Gasp alarmı kök neden değil, belirtidir." in response.response_text
    assert "Tam hizmet kesintisi: Hayır." in response.response_text
    assert "CustomerImpactAssessment kanıtı yok." in response.response_text
    assert "Toplam telafi tutarı: 10.00 TRY." in response.response_text
    assert "Doküman sonuçları karar değil" in response.response_text
    assert {citation.reference_kind for citation in response.citations} >= {
        "causal_event",
        "rule_version",
        "decision_evidence",
        "retrieval_source",
    }
    run.refresh_from_db()
    assert run.status == QueryRunStatus.COMPLETED
    assert run.final_result == original_final_result


@pytest.mark.django_db
def test_builder_rejects_noncompleted_invalid_and_snapshot_mismatched_runs():
    snapshot = create_snapshot("response-rejected")
    service = QueryRunService()
    planned, _ = service.create_or_get(
        data_snapshot=snapshot,
        idempotency_key=f"response-planned-{snapshot.snapshot_key}",
        original_query="safe",
    )
    with pytest.raises(ResponseBuilderError) as exc_info:
        ValidatedResponseBuilder().build(planned)
    assert exc_info.value.code == "response_requires_completed_query_run"

    invalid = valid_result(snapshot.snapshot_key).model_copy(
        update={"validation_status": ValidationStatus.INVALID}
    )
    completed = completed_run("response-invalid", result=invalid)
    with pytest.raises(ResponseBuilderError) as exc_info:
        ValidatedResponseBuilder().build(completed)
    assert exc_info.value.code == "response_requires_validated_result"

    mismatched = valid_result("other-snapshot-001")
    completed = completed_run("response-snapshot", result=mismatched)
    with pytest.raises(ResponseBuilderError) as exc_info:
        ValidatedResponseBuilder().build(completed)
    assert exc_info.value.code == "response_snapshot_mismatch"


@pytest.mark.django_db
def test_llm_assisted_mode_uses_only_safe_fact_sheet_and_preserves_deterministic_blocks():
    run = completed_run("response-assisted")
    provider = RecordingProvider()

    response = ValidatedResponseBuilder().build(
        run,
        mode=ResponseGenerationMode.LLM_ASSISTED,
        provider=provider,
    )

    assert response.generation_mode == ResponseGenerationMode.LLM_ASSISTED
    assert response.provider == "recording"
    assert response.model == "recording-v1"
    assert response.response_text.startswith("Kesinti değerlendirmesi")
    assert "Kesinti sayısı: 3." in response.response_text
    assert "Potansiyel kapsam: 5 bağlantı." in response.response_text
    prompt = provider.requests[0]["contents"]
    for value in ("CUST-001", "198.51.100.10", "original_query", "raw_payload", "token"):
        assert value not in prompt


@pytest.mark.django_db
def test_compensation_rule_is_authoritative_over_unrelated_rule_tool_candidate():
    snapshot = create_snapshot("response-compensation-authority")
    result = valid_result(snapshot.snapshot_key).model_copy(
        update={
            "rule_summary": RuleSummary(
                rule_codes=["UNRELATED-RULE"],
                rule_versions=["UNRELATED-RULE:v9"],
                evidence_references=["UNRELATED-EVIDENCE"],
            ),
            "compensation_summary": CompensationSummary(
                status="available",
                considered=1,
                eligible=1,
                ineligible_pending=0,
                total_amount="48.00",
                currency="TRY",
                rule_versions={"APPLIED-RULE:v1": 1},
                evidence_references=["APPLIED-EVIDENCE"],
                scope="verified_impact",
            ),
        }
    )
    response = ValidatedResponseBuilder().build(
        completed_run("response-compensation-authority-run", result=result, snapshot=snapshot)
    )

    assert "APPLIED-RULE:v1" in response.response_text
    assert "APPLIED-EVIDENCE" in response.response_text
    assert "UNRELATED-RULE:v9" not in response.response_text
    assert "UNRELATED-EVIDENCE" not in response.response_text


@pytest.mark.django_db
@pytest.mark.parametrize(
    "content",
    [
        "999 bağlantı etkilendi.",
        '{"headline_id":"H2","concepts":["root_cause"],"selected_statement_ids":["S1"],"relationships":[]}',
        '{"headline_id":"H1","concepts":["root_cause"],"selected_statement_ids":["S1","S1"],"relationships":[]}',
    ],
)
def test_unsupported_llm_facts_use_deterministic_fallback(content):
    run = completed_run(f"response-fallback-{len(content)}-{content[:3].lower()}")

    response = ValidatedResponseBuilder().build(
        run,
        mode=ResponseGenerationMode.LLM_ASSISTED,
        provider=RecordingProvider(content),
    )

    assert response.generation_mode == ResponseGenerationMode.DETERMINISTIC_FALLBACK
    assert "llm_narrative_fallback" in response.warnings
    assert "llm_statement_selection_attempted" in response.warnings
    assert any(
        warning.startswith("llm_statement_selection_failure:") for warning in response.warnings
    )
    assert content not in response.response_text
    assert "Doğrulanmış etki: 2 bağlantı." in response.response_text


@pytest.mark.django_db
def test_provider_failure_and_nonstructured_mock_narrative_are_safe_and_deterministic():
    run = completed_run("response-mock")

    mock_response = ValidatedResponseBuilder().build(
        run,
        mode=ResponseGenerationMode.LLM_ASSISTED,
        provider=MockLLMProvider(),
    )
    assert mock_response.generation_mode == ResponseGenerationMode.DETERMINISTIC_FALLBACK
    assert "mock-response:" not in mock_response.response_text

    fallback = ValidatedResponseBuilder().build(
        run,
        mode=ResponseGenerationMode.LLM_ASSISTED,
        provider=RecordingProvider(""),
    )
    assert fallback.generation_mode == ResponseGenerationMode.DETERMINISTIC_FALLBACK


@pytest.mark.django_db
def test_statement_selection_rejects_unknown_or_duplicate_canonical_ids():
    run = completed_run("response-semantic-guard")
    partial = json.dumps(
        {
            "headline_id": "H1",
            "concepts": ["root_cause"],
            "selected_statement_ids": ["S1"],
            "relationships": [],
        }
    )
    full_outage = json.dumps(
        {
            "headline_id": "H1",
            "concepts": ["root_cause"],
            "selected_statement_ids": [
                "S1",
                "S2",
                "S3",
                "S4",
                "S5",
                "S6",
                "S7",
                "S8",
                "S9",
                "S999",
            ],
            "relationships": [],
        }
    )
    response = ValidatedResponseBuilder().build(
        run, mode=ResponseGenerationMode.LLM_ASSISTED, provider=RecordingProvider(partial)
    )
    assert response.generation_mode == ResponseGenerationMode.LLM_ASSISTED
    assert "Doğrulanmış etki: 2 bağlantı." in response.response_text
    for content in (full_outage,):
        response = ValidatedResponseBuilder().build(
            run, mode=ResponseGenerationMode.LLM_ASSISTED, provider=RecordingProvider(content)
        )
    assert response.generation_mode == ResponseGenerationMode.DETERMINISTIC_FALLBACK


@pytest.mark.django_db
def test_semantic_decomposition_and_grounded_relationships_change_safe_answer_order():
    run = completed_run(
        "response-semantic-decomposition",
        original_query=(
            "Ana bağlantı down ve yedek bağlantı active; bu neden tam kesinti değil, "
            "failover ne yaptı ve telafi değerlendirmesi nasıl etkileniyor?"
        ),
    )
    provider = RelationshipProvider()

    response = ValidatedResponseBuilder().build(
        run, mode=ResponseGenerationMode.LLM_ASSISTED, provider=provider
    )

    assert response.generation_mode == ResponseGenerationMode.LLM_ASSISTED
    assert "Karşıtlık ilişkisi: " in response.response_text
    assert "Tam hizmet kesintisi: Hayır." in response.response_text
    assert "CUST-001" not in provider.requests[0]["contents"]
    assert "198.51.100.10" not in provider.requests[0]["contents"]
    assert "concepts" in provider.requests[0]["format_schema"]["properties"]
    assert "relationships" in provider.requests[0]["format_schema"]["properties"]


@pytest.mark.django_db
def test_simple_date_location_selection_normalizes_repeated_allowlisted_concept():
    run = completed_run(
        "response-simple-location",
        original_query=(
            "6 Haziran 2026 tarihinde Konak ilçesinde kaç kesinti oldu ve "
            "doğrulanmış müşteri etkisi nedir?"
        ),
    )
    response = ValidatedResponseBuilder().build(
        run,
        mode=ResponseGenerationMode.LLM_ASSISTED,
        provider=DuplicateConceptProvider(),
    )

    assert response.generation_mode == ResponseGenerationMode.LLM_ASSISTED
    assert response.semantic_concepts == ["verified_customer_impact"]
    assert "Doğrulanmış etki: 2 bağlantı." in response.response_text


@pytest.mark.django_db
def test_invalid_semantic_decomposition_keeps_deterministic_fallback_safe():
    run = completed_run("response-invalid-semantic-decomposition")
    invalid = json.dumps(
        {
            "headline_id": "H1",
            "concepts": ["invented_concept"],
            "selected_statement_ids": [],
            "relationships": [],
        }
    )

    response = ValidatedResponseBuilder().build(
        run,
        mode=ResponseGenerationMode.LLM_ASSISTED,
        provider=RecordingProvider(invalid),
    )

    assert response.generation_mode == ResponseGenerationMode.DETERMINISTIC_FALLBACK
    assert "invented_concept" not in response.response_text
    assert "Doğrulanmış etki: 2 bağlantı." in response.response_text


@pytest.mark.django_db
def test_partial_result_warning_and_empty_summaries_do_not_invent_values():
    snapshot = create_snapshot("response-partial")
    result = valid_result(snapshot.snapshot_key, warnings=["optional_tool_failed:documents"])
    result.impact_summary = ImpactSummary(verified_impacted=0)
    result.compensation_summary = None
    run = completed_run("response-partial-run", result=result, snapshot=snapshot)

    response = ValidatedResponseBuilder().build(run)

    assert "İsteğe bağlı kanıt uyarısı: optional_tool_failed:documents." in response.response_text
    assert "Doğrulanmış etki: 0 bağlantı." in response.response_text
    assert "Potansiyel etki:" not in response.response_text
    assert "Telafi sonucu" not in response.response_text
    assert response.structured_result is not None
    assert response.structured_result.impact_summary is not None
    assert response.structured_result.impact_summary.verified_impacted == 0
    assert response.structured_result.impact_summary.potential is None
    assert response.structured_result.compensation_summary is None
