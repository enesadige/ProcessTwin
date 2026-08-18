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
from apps.orchestration.providers.ollama import OllamaLLMProviderError
from apps.orchestration.response_builder import (
    ResponseBuilderError,
    ResponseGenerationMode,
    ValidatedResponseBuilder,
)
from apps.orchestration.result_merge import (
    AnalyticsSummary,
    CausalSummary,
    CompensationSummary,
    CrossIncidentCorrelationSummary,
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
    supports_grounded_narrative = True

    def __init__(self, content: str | None = None) -> None:
        self.content = content
        self.requests: list[Mapping[str, Any]] = []

    def generate(self, *, request: Mapping[str, Any]) -> Mapping[str, Any]:
        self.requests.append(dict(request))
        content = self.content or (
            "Doğrulanmış operasyon kayıtlarına dayalı doğal bir değerlendirme."
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
        return super().generate(request=request)


class DuplicateConceptProvider(RecordingProvider):
    def generate(self, *, request: Mapping[str, Any]) -> Mapping[str, Any]:
        return super().generate(request=request)


class GroundedNarrativeProvider(RecordingProvider):
    supports_grounded_narrative = True

    def __init__(self, narrative: str | dict[str, Any] | None = None) -> None:
        super().__init__(narrative)
        self.narrative = narrative

    def generate(self, *, request: Mapping[str, Any]) -> Mapping[str, Any]:
        self.requests.append(dict(request))
        if isinstance(self.narrative, dict):
            content = " ".join(
                str(sentence.get("text", ""))
                for sentence in self.narrative.get("sentences", [])
                if isinstance(sentence, Mapping)
            )
        else:
            content = self.narrative or (
                "Bu değerlendirme doğrulanmış operasyon kayıtlarına dayanıyor."
            )
        return {
            "content": content,
            "provider": self.provider_name,
            "model": self.model_name,
            "retry": {},
            "finish_reason": "stop",
            "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        }


class StructuredAnalyticsClaimPlanProvider(RecordingProvider):
    def __init__(self, claims: list[dict[str, str]] | None = None) -> None:
        super().__init__()
        self.claims = claims or []

    def generate(self, *, request: Mapping[str, Any]) -> Mapping[str, Any]:
        self.requests.append(dict(request))
        return {
            "content": json.dumps({"claims": self.claims}),
            "provider": self.provider_name,
            "model": self.model_name,
            "retry": {},
            "finish_reason": "stop",
            "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        }


class NarrativeFailureProvider(GroundedNarrativeProvider):
    def generate(self, *, request: Mapping[str, Any]) -> Mapping[str, Any]:
        call_number = len(self.requests) + 1
        self.requests.append(dict(request))
        if call_number == 1:
            raise OllamaLLMProviderError(message="Ollama request timed out.", code="timeout")
        return super().generate(request=request)


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
            RetrievalSource(
                source_code="SYN-COMP-2026",
                version=2,
                section="Uygunluk koşulları",
                section_path="Telafi / Uygunluk koşulları",
                score=0.812,
                score_source="hybrid_score",
            )
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
    assert response.structured_result.retrieval_sources[0].source_code == "SYN-COMP-2026"
    assert (
        response.structured_result.retrieval_sources[0].section_path
        == "Telafi / Uygunluk koşulları"
    )
    assert response.structured_result.retrieval_sources[0].score == pytest.approx(0.812)
    assert response.structured_result.retrieval_sources[0].score_source == "hybrid_score"
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
    assert "doğrulanmış müşteri etkisi değerlendirme kaydı yok." in response.response_text
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
    assert response.response_text == (
        "Doğrulanmış operasyon kayıtlarına dayalı doğal bir değerlendirme. "
        "Doğrulanmış etki: 2 bağlantı."
    )
    assert response.narrative_synthesis_audit["deterministic_fill_count"] == 1
    assert response.statement_selection_audit["mode"] == "deterministic"
    assert response.statement_selection_audit["status"] == "completed"
    prompt = provider.requests[0]["contents"]
    for value in ("198.51.100.10", "raw_payload", "token"):
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
@pytest.mark.skip(reason="obsolete: Phase 1A model selection and tagged narrative were removed")
def test_unsupported_llm_facts_use_deterministic_fallback(content):
    run = completed_run(f"response-fallback-{len(content)}-{content[:3].lower()}")

    response = ValidatedResponseBuilder().build(
        run,
        mode=ResponseGenerationMode.LLM_ASSISTED,
        provider=RecordingProvider(content),
    )

    assert response.generation_mode == ResponseGenerationMode.LLM_ASSISTED
    assert response.narrative_synthesis_audit["removed_sentence_count"] >= 0


@pytest.mark.django_db
def test_provider_failure_and_nonstructured_mock_narrative_are_safe_and_deterministic():
    run = completed_run("response-mock")

    mock_response = ValidatedResponseBuilder().build(
        run,
        mode=ResponseGenerationMode.LLM_ASSISTED,
        provider=MockLLMProvider(),
    )
    assert mock_response.generation_mode == ResponseGenerationMode.LLM_ASSISTED
    assert "mock-response:" not in mock_response.response_text

    fallback = ValidatedResponseBuilder().build(
        run,
        mode=ResponseGenerationMode.LLM_ASSISTED,
        provider=RecordingProvider(" "),
    )
    assert fallback.generation_mode == ResponseGenerationMode.DETERMINISTIC_FALLBACK


@pytest.mark.django_db
@pytest.mark.skip(
    reason="obsolete: Phase 1A model selection was replaced by deterministic AnswerPlan"
)
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
    for content in (full_outage,):
        response = ValidatedResponseBuilder().build(
            run, mode=ResponseGenerationMode.LLM_ASSISTED, provider=RecordingProvider(content)
        )
    assert response.generation_mode == ResponseGenerationMode.LLM_ASSISTED


@pytest.mark.django_db
@pytest.mark.skip(
    reason="obsolete: Phase 1A model selection was replaced by deterministic AnswerPlan"
)
def test_statement_selection_normalizes_phase_two_semantic_aliases():
    run = completed_run("response-phase2-aliases")
    content = json.dumps(
        {
            "headline_id": "H1",
            "concepts": ["failover_status", "evidence_gap", "compensation_result"],
            "selected_statement_ids": ["S1"],
            "relationships": [],
        }
    )

    response = ValidatedResponseBuilder().build(
        run,
        mode=ResponseGenerationMode.LLM_ASSISTED,
        provider=RecordingProvider(content),
    )

    assert response.generation_mode == ResponseGenerationMode.LLM_ASSISTED
    assert response.semantic_concepts == ["root_cause"]


@pytest.mark.django_db
@pytest.mark.skip(
    reason="obsolete: Phase 1A model selection was replaced by deterministic AnswerPlan"
)
def test_statement_selection_normalizes_common_allowlisted_concept_variants():
    run = completed_run("response-concept-variants")
    content = json.dumps(
        {
            "headline_id": "H1",
            "concepts": ["impact", "failover", "compensation_evaluation"],
            "selected_statement_ids": ["S1"],
            "relationships": [],
        }
    )

    response = ValidatedResponseBuilder().build(
        run,
        mode=ResponseGenerationMode.LLM_ASSISTED,
        provider=RecordingProvider(content),
    )

    assert response.generation_mode == ResponseGenerationMode.LLM_ASSISTED
    assert response.semantic_concepts == ["root_cause"]


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
    assert "Sonuç ilişkisi: " not in response.response_text
    assert "->" not in response.response_text
    assert "CUST-001" not in provider.requests[0]["contents"]
    assert "198.51.100.10" not in provider.requests[0]["contents"]
    assert "format_schema" not in provider.requests[0]
    assert response.statement_selection_audit["status"] == "completed"
    assert response.statement_selection_audit["selected_statement_ids"]
    assert response.statement_selection_audit["derived_concepts"] == response.semantic_concepts


@pytest.mark.django_db
def test_phase1b_synthesizes_grounded_natural_language_and_records_support():
    run = completed_run("response-grounded-narrative")
    provider = GroundedNarrativeProvider()

    response = ValidatedResponseBuilder().build(
        run, mode=ResponseGenerationMode.LLM_ASSISTED, provider=provider
    )

    assert response.generation_mode == ResponseGenerationMode.LLM_ASSISTED
    assert response.narrative_synthesis_audit["status"] == "accepted"
    assert response.narrative_synthesis_audit["narrative_support_references"]
    assert "Nedensel ilişki:" not in response.response_text
    assert "->" not in response.response_text
    assert len(provider.requests) == 1
    assert "JSON" in provider.requests[0]["contents"]
    prompt = provider.requests[0]["contents"]
    assert "kök kaynak X olarak doğrulanmıştır" not in prompt
    assert response.narrative_synthesis_audit["removed_sentence_count"] == 0


@pytest.mark.django_db
def test_phase1b_keeps_extended_root_cause_prose_instructions_for_gemini_only():
    run = completed_run("response-grounded-narrative-gemini")
    provider = GroundedNarrativeProvider()
    provider.provider_name = "gemini"
    provider.model_name = "gemini-test"

    ValidatedResponseBuilder().build(
        run, mode=ResponseGenerationMode.LLM_ASSISTED, provider=provider
    )

    prompt = provider.requests[0]["contents"]
    assert "kök kaynak X olarak doğrulanmıştır" in prompt
    assert "Failover başarısızlığı doğrulanmıştır" in prompt
    assert "shared failure domain" in prompt


@pytest.mark.django_db
def test_phase1b_rejects_unselected_statement_reference_and_falls_back():
    run = completed_run("response-invalid-grounded-narrative")
    provider = GroundedNarrativeProvider(narrative="Bu olayda 99 alarm doğrulandı.")

    response = ValidatedResponseBuilder().build(
        run, mode=ResponseGenerationMode.LLM_ASSISTED, provider=provider
    )

    assert response.generation_mode == ResponseGenerationMode.DETERMINISTIC_FALLBACK
    assert (
        "llm_narrative_synthesis_failure:narrative_synthesis_unsupported_narrative"
        in response.warnings
    )


@pytest.mark.django_db
def test_phase1b_grounding_failure_persists_exact_sentence_diagnostics():
    run = completed_run("response-grounding-diagnostics")
    provider = GroundedNarrativeProvider(narrative="Bu olayda 99 alarm doğrulandı.")

    response = ValidatedResponseBuilder().build(
        run, mode=ResponseGenerationMode.LLM_ASSISTED, provider=provider
    )

    audit = response.narrative_synthesis_audit
    assert audit["failure_code"] == "narrative_synthesis_unsupported_narrative"
    assert audit["exact_validation_rule"] == "unsupported_number"
    assert audit["rejected_sentence_index"] == 0
    assert audit["rejected_sentence_text"] == "Bu olayda 99 alarm doğrulandı."
    assert audit["removed_sentence_count"] == 1
    assert audit["removed_sentence_reasons"][0]["failure_code"] == "unsupported_number"
    assert audit["safe_failure_detail"] == "narrative contains an unsupported number"


@pytest.mark.django_db
def test_phase1b_provider_failure_keeps_accepted_phase1a_audit():
    run = completed_run("response-phase1b-provider-failure")
    response = ValidatedResponseBuilder().build(
        run,
        mode=ResponseGenerationMode.LLM_ASSISTED,
        provider=NarrativeFailureProvider(),
    )

    assert response.generation_mode == ResponseGenerationMode.DETERMINISTIC_FALLBACK
    assert response.statement_selection_audit["status"] == "completed"
    assert response.statement_selection_audit["selected_statement_ids"]
    assert response.narrative_synthesis_audit["failure_code"] == (
        "narrative_synthesis_provider_call_failed:timeout"
    )


@pytest.mark.parametrize(
    "text",
    [
        "SUB-MCR-00011 PRIMARY_PATH_DOWN alarmını tetikledi.",
        "Dying Gasp ve Device Not Active kayıtları olmadığı için failover doğrulanamadı.",
        "CustomerImpactAssessment kaydı olmadığı için failover sayısı bilinmiyor.",
    ],
)
def test_sentence_grounding_rejects_unvalidated_causal_claims(text):
    statements = {
        "S1": "Doğrulanmış kök kaynak subscription_connection SUB-MCR-00011.",
        "S2": "Doğrulanmış kök alarm PRIMARY_PATH_DOWN.",
        "S3": "Dying Gasp ve Device Not Active için doğrulanmış kayıt yok.",
        "S4": "CustomerImpactAssessment kanıtı yok.",
        "S5": "Failover ile korunan bağlantı sayısı bilinmiyor.",
    }
    narrative = {
        "sentences": [
            {
                "text": text,
                "statement_ids": ["S1", "S2", "S3", "S4", "S5"],
                "relationship_ids": [],
            }
        ]
    }

    with pytest.raises(ValueError, match="unsupported causal relation"):
        ValidatedResponseBuilder._validate_grounded_narrative(narrative, statements, [])


def test_sentence_grounding_accepts_only_the_exact_declared_relationship():
    statements = {
        "S1": "Ana bağlantı down, yedek bağlantı active.",
        "S2": "Tam hizmet kesintisi: Hayır.",
    }
    relationship = {
        "type": "consequence",
        "from_statement_id": "S1",
        "to_statement_id": "S2",
        "provenance": "deterministic_outage_classification",
        "narrative_semantics": "causal",
    }
    narrative = {
        "sentences": [
            {
                "text": (
                    "Ana bağlantı down olmasına rağmen yedek bağlantı active olduğu "
                    "için tam kesinti değildir."
                ),
                "statement_ids": ["S1", "S2"],
                "relationship_ids": ["R1"],
            }
        ]
    }

    ValidatedResponseBuilder._validate_grounded_narrative(narrative, statements, [relationship])


def test_causal_sentence_may_include_additional_valid_noncausal_support():
    statements = {
        "S1": "Ana bağlantı down, yedek bağlantı active.",
        "S2": "Tam hizmet kesintisi: Hayır.",
    }
    relationships = [
        {
            "type": "consequence",
            "from_statement_id": "S1",
            "to_statement_id": "S2",
            "provenance": "deterministic_outage_classification",
            "narrative_semantics": "causal",
        },
        {
            "type": "contrast",
            "from_statement_id": "S1",
            "to_statement_id": "S2",
            "provenance": "deterministic_outage_classification",
            "narrative_semantics": "contrast",
        },
    ]
    narrative = {
        "sentences": [
            {
                "text": "Ana bağlantı down olduğu için olay tam hizmet kesintisi değildir.",
                "statement_ids": ["S2"],
                "relationship_ids": ["R1", "R2"],
            }
        ]
    }

    ValidatedResponseBuilder._validate_grounded_narrative(narrative, statements, relationships)


def test_relationship_endpoints_become_effective_support_without_model_duplication():
    statements = {
        "S3": "Kesinti sırasında 572 abonelik etkilendi.",
        "S6": "Kesinti sırasında 495 müşteri etkilendi.",
    }
    relationship = {
        "type": "consequence",
        "from_statement_id": "S3",
        "to_statement_id": "S6",
        "provenance": "deterministic_customer_impact",
        "narrative_semantics": "causal",
    }
    narrative = {
        "sentences": [
            {
                "text": "Kesinti sonucunda 572 abonelik ve 495 müşteri etkilendi.",
                "statement_ids": ["S6"],
                "relationship_ids": ["R1"],
            }
        ]
    }

    ValidatedResponseBuilder._validate_grounded_narrative(narrative, statements, [relationship])


def test_backend_relationship_candidates_keep_independent_evidence_gaps_separate():
    statements = {
        "S7": "Gerçek müşteri etkisi kesin doğrulanmadı; CustomerImpactAssessment kanıtı yok.",
        "S8": "Failover ile korunan bağlantı sayısı için doğrulanmış sayısal kayıt yok.",
    }

    assert ValidatedResponseBuilder._backend_relationship_candidates(statements) == []


def test_uncertainty_relationship_cannot_support_causal_wording():
    statements = {
        "S1": "Müşteri etkisi kesin doğrulanmadı.",
        "S2": "Failover ile korunan miktar bilinmiyor.",
    }
    relationship = {
        "type": "uncertainty",
        "from_statement_id": "S1",
        "to_statement_id": "S2",
        "provenance": "generic_uncertainty_pairing",
        "narrative_semantics": "uncertainty",
    }
    narrative = {
        "sentences": [
            {
                "text": "Müşteri etkisi doğrulanmadığı için failover miktarı bilinmiyor.",
                "statement_ids": ["S1", "S2"],
                "relationship_ids": ["R1"],
            }
        ]
    }

    with pytest.raises(ValueError, match="semantics do not permit"):
        ValidatedResponseBuilder._validate_grounded_narrative(narrative, statements, [relationship])


@pytest.mark.parametrize(
    ("relationship_ids", "message"),
    [
        (["R9"], "invalid relationship ID"),
        ([], "unsupported causal relation"),
    ],
)
def test_compact_narrative_requires_valid_relationship_support(relationship_ids, message):
    statements = {
        "S1": "Ana bağlantı down, yedek bağlantı active.",
        "S2": "Tam hizmet kesintisi: Hayır.",
    }
    narrative = {
        "sentences": [
            {
                "text": "Ana bağlantı down olduğu için tam hizmet kesintisi değildir.",
                "statement_ids": ["S1", "S2"],
                "relationship_ids": relationship_ids,
            }
        ]
    }
    relationship = {
        "type": "consequence",
        "from_statement_id": "S1",
        "to_statement_id": "S2",
    }

    with pytest.raises(ValueError, match=message):
        ValidatedResponseBuilder._validate_grounded_narrative(narrative, statements, [relationship])


def test_compact_narrative_rejects_unsupported_numeric_claim():
    statements = {"R1": "Doğrulanmış alarm kaydı mevcut."}
    narrative = {
        "sentences": [
            {
                "text": "Bu olayda 99 alarm doğrulandı.",
                "statement_ids": ["R1"],
                "relationship_ids": [],
            }
        ]
    }

    with pytest.raises(ValueError, match="unsupported number"):
        ValidatedResponseBuilder._validate_grounded_narrative(narrative, statements, [])


def test_narrative_identifier_digits_are_not_treated_as_numeric_claims():
    statements = {"S1": "Doğrulanmış kök kaynak device AGG-ANK-002."}
    narrative = {
        "sentences": [
            {
                "text": "AGG-ANK-002 cihazı olayın doğrulanmış kök kaynağıdır.",
                "statement_ids": ["S1"],
                "relationship_ids": [],
            }
        ]
    }

    ValidatedResponseBuilder._validate_grounded_narrative(narrative, statements, [])


def test_verified_anchor_is_allowed_when_not_repeated_in_statement_support():
    statements = {"S1": "Tam hizmet kesintisi: Evet."}
    narrative = {
        "sentences": [
            {
                "text": "AGG-ANK-002 cihazındaki kesinti tam hizmet kesintisidir.",
                "statement_ids": ["S1"],
                "relationship_ids": [],
            }
        ]
    }

    ValidatedResponseBuilder._validate_grounded_narrative(
        narrative, statements, [], verified_anchors={"AGG-ANK-002": "verified_anchor"}
    )


def test_tagged_narrative_protocol_parses_multiple_lines_and_strips_tags():
    narrative = ValidatedResponseBuilder._parse_tagged_narrative(
        "[S:S1,S2|R:R1] Ana bağlantı down olsa da yedek bağlantı active.\n"
        "[S:S3|R:] Müşteri etkisi doğrulanmamıştır."
    )

    assert narrative["sentences"][0]["statement_ids"] == ["S1", "S2"]
    assert narrative["sentences"][0]["relationship_ids"] == ["R1"]
    assert ValidatedResponseBuilder._render_grounded_narrative(narrative) == (
        "Ana bağlantı down olsa da yedek bağlantı active. Müşteri etkisi doğrulanmamıştır."
    )


def test_tagged_narrative_parser_allows_safe_whitespace_and_code_fences():
    narrative = ValidatedResponseBuilder._parse_tagged_narrative(
        "```text\n- [S:S1, S2|R:R1] Doğrulanmış açıklama.\n```"
    )

    assert narrative["sentences"][0]["statement_ids"] == ["S1", "S2"]


@pytest.mark.parametrize(
    "content",
    [
        "[S:S999|R:] Desteksiz.",
        "[S:S1|R:R999] Desteksiz ilişki.",
        "JSON değil.",
    ],
)
def test_tagged_narrative_protocol_rejects_invalid_tags(content):
    if "S999" in content or "R999" in content:
        parsed = ValidatedResponseBuilder._parse_tagged_narrative(content)
        statements = {"S1": "Doğrulanmış bilgi."}
        with pytest.raises(ValueError):
            ValidatedResponseBuilder._validate_grounded_narrative(parsed, statements, [])
    else:
        with pytest.raises(ValueError):
            ValidatedResponseBuilder._parse_tagged_narrative(content)


def test_unresolved_anchor_is_rejected_even_when_present_in_the_question():
    statements = {"S1": "Tam hizmet kesintisi: Evet."}
    narrative = {
        "sentences": [
            {
                "text": "AGG-ANK-999 cihazındaki kesinti tam hizmet kesintisidir.",
                "statement_ids": ["S1"],
                "relationship_ids": [],
            }
        ]
    }

    with pytest.raises(ValueError, match="unsupported identifier"):
        ValidatedResponseBuilder._validate_grounded_narrative(
            narrative, statements, [], verified_anchors={"AGG-ANK-002": "verified_anchor"}
        )


@pytest.mark.django_db
@pytest.mark.skip(
    reason="obsolete: Phase 1A model selection was replaced by deterministic AnswerPlan"
)
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
    assert "verified_customer_impact" in response.semantic_concepts
    assert len(response.semantic_concepts) == len(set(response.semantic_concepts))
    assert "Doğrulanmış etki: 2 bağlantı." in response.response_text


@pytest.mark.django_db
@pytest.mark.skip(
    reason="obsolete: AnswerPlan selection is deterministic; providers synthesize only narratives"
)
def test_invalid_semantic_decomposition_keeps_deterministic_fallback_safe():
    run = completed_run("response-invalid-semantic-decomposition")
    invalid = json.dumps(
        {
            "headline_id": "H1",
            "concepts": ["invented_concept"],
            "selected_statement_ids": ["S999"],
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
@pytest.mark.skip(reason="obsolete: Phase 1A provider diagnostics are no longer on the main path")
def test_statement_selection_failure_persists_safe_structured_diagnostics():
    run = completed_run("response-selection-diagnostics")
    invalid = json.dumps(
        {
            "headline_id": "H1",
            "concepts": ["invented_concept"],
            "selected_statement_ids": ["S999"],
            "relationships": [
                {
                    "type": "cause",
                    "from_statement_id": "S999",
                    "to_statement_id": "S1",
                }
            ],
        }
    )

    response = ValidatedResponseBuilder().build(
        run,
        mode=ResponseGenerationMode.LLM_ASSISTED,
        provider=RecordingProvider(invalid),
    )

    assert response.generation_mode == ResponseGenerationMode.DETERMINISTIC_FALLBACK
    assert "llm_statement_selection_failure:unknown_or_duplicate_statement_id" in response.warnings
    assert any(
        warning.startswith("llm_statement_selection_allowed_statement_ids:")
        for warning in response.warnings
    )
    assert any(
        warning.startswith("llm_statement_selection_returned_statement_ids:")
        for warning in response.warnings
    )
    assert any(
        warning.startswith("llm_statement_selection_returned_concepts:")
        for warning in response.warnings
    )


@pytest.mark.django_db
@pytest.mark.skip(reason="obsolete: Phase 1A provider diagnostics are no longer on the main path")
@pytest.mark.parametrize(
    ("content", "failure_code", "failure_detail"),
    [
        ("not-json", "structured_output_invalid_json", "invalid_json"),
        (
            json.dumps({"headline_id": "H1", "relationships": []}),
            "statement_selection_schema_invalid",
            "statement selection schema is invalid",
        ),
    ],
)
def test_statement_selection_source_failure_always_keeps_safe_contract_diagnostics(
    content, failure_code, failure_detail
):
    run = completed_run("response-source-selection-diagnostics-" + failure_code)
    response = ValidatedResponseBuilder().build(
        run,
        mode=ResponseGenerationMode.LLM_ASSISTED,
        provider=RecordingProvider(content),
    )

    diagnostics = response.statement_selection_audit
    assert diagnostics["failure_code"] == failure_code
    assert diagnostics["failure_detail"] == failure_detail
    assert diagnostics["allowed_statement_ids"]
    assert diagnostics["returned_statement_ids"] == []
    assert diagnostics["returned_keys"] == (
        [] if failure_code.endswith("invalid_json") else ["headline_id", "relationships"]
    )


def test_grounded_narrative_contract_is_generic_for_unrelated_statement_vocabulary():
    statements = {
        "R1": "Bölge raporu 14:00 itibarıyla doğrulandı.",
        "R2": "İnceleme sahibi ekip operasyon kontrolünü tamamladı.",
    }
    narrative = {
        "sentences": [
            {
                "text": "Bölge raporu doğrulandı ve operasyon kontrolü tamamlandı.",
                "statement_ids": ["R1", "R2"],
                "relationship_ids": [],
            }
        ]
    }

    ValidatedResponseBuilder._validate_grounded_narrative(narrative, statements, [])


@pytest.mark.django_db
@pytest.mark.skip(reason="obsolete: Phase 1A provider selection was removed from orchestration")
def test_statement_selection_rejects_relationship_reference_outside_current_allowlist():
    run = completed_run("response-relationship-diagnostics")
    invalid = json.dumps(
        {
            "headline_id": "H1",
            "concepts": ["root_cause"],
            "selected_statement_ids": ["S1"],
            "relationships": [
                {
                    "type": "cause",
                    "from_statement_id": "S1",
                    "to_statement_id": "S999",
                }
            ],
        }
    )

    response = ValidatedResponseBuilder().build(
        run,
        mode=ResponseGenerationMode.LLM_ASSISTED,
        provider=RecordingProvider(invalid),
    )

    assert response.generation_mode == ResponseGenerationMode.DETERMINISTIC_FALLBACK
    assert "llm_statement_selection_failure:relationship_validation_failed" in response.warnings
    assert any(
        warning.startswith("llm_statement_selection_relationship_references:")
        for warning in response.warnings
    )


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


def test_free_text_narrative_accepts_natural_paraphrase_without_sentence_repair():
    statements = {
        "S1": "Ana bağlantı down, yedek bağlantı active.",
        "S2": "Tam hizmet kesintisi: Hayır.",
    }
    narrative, removed = ValidatedResponseBuilder._free_text_narrative(
        (
            "Ana hat devre dışı kalsa da yedek hat çalışır durumda olduğu için "
            "olay tam kesinti değildir."
        ),
        statements,
        {
            "R1": {
                "type": "consequence",
                "from_statement_id": "S1",
                "to_statement_id": "S2",
                "narrative_semantics": "causal",
            }
        },
    )

    assert [sentence["text"] for sentence in narrative["sentences"]] == [
        (
            "Ana hat devre dışı kalsa da yedek hat çalışır durumda olduğu için "
            "olay tam kesinti değildir."
        )
    ]
    assert removed == []


def test_free_text_narrative_strips_only_known_internal_role_prefixes():
    statements = {"S1": "Ana bağlantı down, yedek bağlantı active."}
    narrative, removed = ValidatedResponseBuilder._free_text_narrative(
        "analytics: Ana bağlantı down, yedek bağlantı active. "
        "evidence: Bilgi doğrulandı. correlation: İlişki doğrulandı.",
        statements,
        {},
    )

    assert removed == []
    assert [sentence["text"] for sentence in narrative["sentences"]] == [
        "Ana bağlantı down, yedek bağlantı active.",
        "Bilgi doğrulandı.",
        "İlişki doğrulandı.",
    ]


def test_free_text_narrative_strips_markdown_role_prefix_and_internal_support_labels():
    narrative, removed = ValidatedResponseBuilder._free_text_narrative(
        "**Summary** (S2) Ana bağlantı down, yedek bağlantı active.",
        {"S1": "Ana bağlantı down, yedek bağlantı active."},
        {},
    )

    assert removed == []
    assert narrative["sentences"][0]["text"] == (
        "Ana bağlantı down, yedek bağlantı active."
    )


def test_free_text_narrative_strips_standalone_internal_support_labels():
    narrative, removed = ValidatedResponseBuilder._free_text_narrative(
        (
            "S3 bölümü ana bağlantının aktif olduğunu, S1’deki kayıt ise yedeğin aktif "
            "olduğunu gösterir."
        ),
        {"S1": "Ana bağlantı down, yedek bağlantı active."},
        {},
    )

    assert removed == []
    assert "S3" not in narrative["sentences"][0]["text"]
    assert "S1" not in narrative["sentences"][0]["text"]


def test_free_text_narrative_normalizes_verified_thousands_separators():
    narrative, removed = ValidatedResponseBuilder._free_text_narrative(
        "Doğrulanmış müşteri etkisi 11\u202f477, toplam etki 5.921 müşteridir.",
        {
            "S1": "Doğrulanmış müşteri etkisi 11477.",
            "S2": "Toplam doğrulanmış müşteri etkisi 5921.",
        },
        {},
    )

    assert removed == []
    assert "11477" in narrative["sentences"][0]["text"]
    assert "5921" in narrative["sentences"][0]["text"]


def test_free_text_narrative_strips_turkish_markdown_role_prefix():
    narrative, removed = ValidatedResponseBuilder._free_text_narrative(
        "**Analiz** Doğrulanmış müşteri etkisi 5921 müşteridir.",
        {"S1": "Doğrulanmış müşteri etkisi 5921 müşteridir."},
        {},
    )

    assert removed == []
    assert narrative["sentences"][0]["text"] == (
        "Doğrulanmış müşteri etkisi 5921 müşteridir."
    )


def test_analytics_unknown_exclusion_and_failed_failover_filter_are_verified_support():
    result = valid_result("response-analytics-unknown").model_copy(
        update={
            "analytics_summary": AnalyticsSummary(
                metric="affected_customers",
                aggregation="sum",
                group_by="event",
                ranking_direction="desc",
                filters={"failed_failover": True},
                rows=[],
                included_event_count=0,
                excluded_unknown_count=2,
                deduplication_grain="causal_event",
            )
        }
    )

    deterministic = ValidatedResponseBuilder._render_deterministic(result)
    _prompt, contract = ValidatedResponseBuilder._statement_contract(result)

    assert "Başarısız failover filtresi uygulandı." in deterministic
    assert "0 müşteri" not in deterministic
    assert any(
        statement == "Başarısız failover filtresi uygulandı."
        for statement in contract["statements"].values()
    )
    assert any(
        "2 olay, doğrulanmış etki kanıtı olmadığı" in statement
        for statement in contract["statements"].values()
    )


def test_analytics_included_event_count_is_first_class_verified_support():
    result = valid_result("response-analytics-included").model_copy(
        update={
            "analytics_summary": AnalyticsSummary(
                metric="affected_customers",
                aggregation="sum",
                group_by="time_bucket",
                ranking_direction="desc",
                rows=[
                    {"label": "2026-06", "value": 12, "event_count": 2},
                    {"label": "2026-07", "value": 8, "event_count": 3},
                ],
                included_event_count=5,
                excluded_unknown_count=1,
                deduplication_grain="causal_event",
            )
        }
    )

    _prompt, contract = ValidatedResponseBuilder._statement_contract(result)

    assert "Hesaba dahil edilen olay sayısı: 5." in contract["statements"].values()


def test_compositional_analytics_contract_keeps_scope_and_total_projections():
    total_alarm = AnalyticsSummary(
        metric="alarm_count",
        aggregation="count",
        ranking_direction="desc",
        filters={"city": "Ankara", "district": "Çankaya"},
        scope_label="Çankaya",
        rows=[{"label": "Toplam", "value": 11, "event_count": 2}],
        included_event_count=2,
        excluded_unknown_count=0,
        deduplication_grain="causal_event",
    )
    breakdown = total_alarm.model_copy(
        update={
            "group_by": "alarm_type",
            "rows": [
                {"label": "UPLINK_DOWN", "value": 6, "event_count": 1},
                {"label": "ACCESS_NODE_UNREACHABLE", "value": 5, "event_count": 1},
            ],
            "deduplication_grain": "alarm_occurrence",
        }
    )
    result = valid_result("response-compositional-contract").model_copy(
        update={"analytics_summary": total_alarm, "analytics_summaries": [total_alarm, breakdown]}
    )

    deterministic = ValidatedResponseBuilder._render_deterministic(result)
    _prompt, contract = ValidatedResponseBuilder._statement_contract(result)

    assert "Alarm sayısı: Çankaya: 11." in deterministic
    assert "UPLINK_DOWN: 6" in deterministic
    assert any("Çankaya: 11 alarm." in statement for statement in contract["statements"].values())
    assert any(
        "UPLINK_DOWN: 6 alarm." in statement
        for statement in contract["statements"].values()
    )


def test_global_comparison_contract_has_period_specific_evidence_counts():
    result = valid_result("response-global-comparison-period-counts").model_copy(
        update={
            "analytics_summary": AnalyticsSummary(
                metric="affected_customers",
                aggregation="sum",
                group_by="time_bucket",
                ranking_direction="desc",
                comparison=True,
                rows=[
                    {
                        "label": "2026-06",
                        "value": 11477,
                        "event_count": 38,
                        "included_event_count": 38,
                        "excluded_unknown_count": 8,
                    },
                    {
                        "label": "2026-07",
                        "value": 10719,
                        "event_count": 39,
                        "included_event_count": 39,
                        "excluded_unknown_count": 9,
                        "absolute_change": 758,
                        "signed_change": -758,
                        "trend_direction": "decrease",
                    },
                ],
                included_event_count=77,
                excluded_unknown_count=17,
                deduplication_grain="causal_event",
            )
        }
    )

    _prompt, contract = ValidatedResponseBuilder._statement_contract(result)
    statements = list(contract["statements"].values())

    assert any(
        "2026-06: 11477 doğrulanmış müşteri etkisi (38 dahil, 8 hariç)." in statement
        for statement in statements
    )
    assert any(
        "2026-07: 10719 doğrulanmış müşteri etkisi (39 dahil, 9 hariç)." in statement
        for statement in statements
    )
    assert any("mutlak değişim 758; yön azalış" in statement for statement in statements)


def test_free_text_narrative_preserves_colon_identifiers_and_natural_text():
    statements = {"S1": "RuleVersion BB-DEGRADATION-QUALITY:v1 uygulandı."}
    narrative, removed = ValidatedResponseBuilder._free_text_narrative(
        "RuleVersion BB-DEGRADATION-QUALITY:v1 uygulandı.",
        statements,
        {},
    )

    assert removed == []
    assert narrative["sentences"][0]["text"] == "RuleVersion BB-DEGRADATION-QUALITY:v1 uygulandı."


def test_free_text_narrative_hides_internal_reason_codes_without_changing_ids():
    narrative, removed = ValidatedResponseBuilder._free_text_narrative(
        (
            "Kök neden root_cause_unverified, same_resource ve temporal_propagation "
            "kodlarıyla işaretlendi."
        ),
        {"S1": "Kök neden doğrulanmamıştır."},
        {},
    )

    assert removed == []
    assert "root_cause_unverified" not in narrative["sentences"][0]["text"]
    assert "same_resource" not in narrative["sentences"][0]["text"]
    assert "temporal_propagation" not in narrative["sentences"][0]["text"]


def test_deterministic_fallback_uses_explicit_device_anchor_and_hides_internal_causal_fields():
    result = valid_result("response-device-anchor").model_copy(
        update={
            "causal_summary": CausalSummary(
                causal_event_code="CE-UNRELATED-001",
                root_resource_type="device",
                root_resource_reference="AGG-TEST-002",
                root_cause_reason_codes=["root_cause_unverified", "same_resource"],
                propagation_summary="Candidate matches the causal event physical root resource.",
                full_outage=True,
            )
        }
    )

    text = ValidatedResponseBuilder._render_deterministic(
        result, {"device_code": "AGG-TEST-002"}
    )

    assert "Doğrulanan operasyon referansı: AGG-TEST-002." in text
    assert "CE-UNRELATED-001" not in text
    assert "root_cause_unverified" not in text
    assert "same_resource" not in text
    assert "Candidate matches" not in text
    assert result.causal_summary.root_cause_reason_codes == [
        "root_cause_unverified",
        "same_resource",
    ]
    assert result.causal_summary.propagation_summary == (
        "Candidate matches the causal event physical root resource."
    )


def test_deterministic_fallback_keeps_explicit_causal_event_anchor():
    result = valid_result("response-causal-anchor")

    text = ValidatedResponseBuilder._render_deterministic(
        result, {"causal_event_code": "CE-GPON-001"}
    )

    assert "Doğrulanan operasyon referansı: CE-GPON-001." in text


def test_deterministic_fallback_allows_second_verified_root_resource_identifier():
    result = valid_result("response-second-anchor")

    text = ValidatedResponseBuilder._render_deterministic(
        result, {"causal_event_code": "CE-GPON-001"}
    )

    assert "Doğrulanan operasyon referansı: CE-GPON-001." in text
    assert "Kök kaynak: device OLT-001." in text


def test_answer_plan_keeps_resolved_event_identity_and_excludes_scenario_from_root_cause():
    result = valid_result("response-device-event-identity")
    result.causal_summary.causal_event_code = "CE-MCR-0049"
    result.causal_summary.outage_code = "OUT-MCR-0049"
    result.causal_summary.root_resource_reference = "AGG-ANK-002"
    result.causal_summary.root_cause_summary = "SCN-BNG-DOWN-001"

    _prompt, contract = ValidatedResponseBuilder._statement_contract(
        result,
        original_query="AGG-ANK-002 için ilişkili olayı ve müşteri etkisini söyle.",
        structured_query={"requested_outputs": ["summary", "details", "impact"]},
    )
    statements = contract["statements"]

    assert "İlişkili olay kaydı: CE-MCR-0049; kesinti kaydı: OUT-MCR-0049." in statements.values()
    assert "Doğrulanmış ana kök neden: SCN-BNG-DOWN-001." not in statements.values()
    assert (
        "Kök kaynak doğrulanmış, ancak fiziksel kök neden gerekçesi ayrıca doğrulanmadı."
        in statements.values()
    )


def test_answer_plan_does_not_render_an_unconfirmed_root_candidate_as_root_cause():
    result = valid_result("response-unconfirmed-root-candidate")
    result.causal_summary.root_resource_type = "failure_domain"
    result.causal_summary.root_resource_reference = "FD-SITE-459"
    result.causal_summary.root_cause_summary = "OLT-ETI-002"
    result.causal_summary.propagation_summary = (
        "Candidate is retained as causal-chain evidence, not a confirmed root."
    )

    _prompt, contract = ValidatedResponseBuilder._statement_contract(
        result,
        original_query="CE-MCR-0023 içindeki alarmları incele.",
        structured_query={"requested_outputs": ["summary", "root_cause"]},
    )

    assert "Doğrulanmış ana kök neden: OLT-ETI-002." not in contract["statements"].values()
    assert "Doğrulanmış kök kaynak: failure_domain FD-SITE-459." in contract["statements"].values()


@pytest.mark.parametrize(
    "claim",
    [
        "Kesinti müşteri memnuniyetini olumsuz etkiledi.",
        "Müşteriler alternatif çözümler aramak zorunda kaldı.",
        "Kesinti iş sürekliliğini olumsuz etkiledi.",
        "Bu düşüş hizmet kalitesinde bir gerilemeye işaret edebilir.",
        "Olay ticari etki yarattı.",
    ],
)
def test_free_text_narrative_rejects_unsupported_qualitative_impact_claim(claim):
    narrative, removed = ValidatedResponseBuilder._free_text_narrative(
        claim,
        {"S1": "Doğrulanmış müşteri etkisi 495 müşteridir."},
        {},
    )

    assert narrative["sentences"] == []
    assert removed[0]["failure_code"] == "unsupported_domain_interpretation"


def test_free_text_narrative_rejects_backup_inference_from_zero_protected_count():
    narrative, removed = ValidatedResponseBuilder._free_text_narrative(
        "Failover ile korunan bağlantı sayısı 0 olduğu için yedek bağlantı devreye girmedi.",
        {"S1": "Failover ile korunan: 0 bağlantı."},
        {},
    )

    assert narrative["sentences"] == []
    assert removed[0]["failure_code"] == "unsupported_domain_interpretation"


@pytest.mark.parametrize(
    "claim",
    [
        "Yedek cihaz arızalandığı için backup devreye girmedi.",
        "Device Not Active sinyali dağıtım kablosu arızasından kaynaklandı.",
        "Fiziksel kök neden kesin olarak belirlendi.",
    ],
)
def test_free_text_narrative_rejects_indirect_physical_causality(claim):
    narrative, removed = ValidatedResponseBuilder._free_text_narrative(
        claim,
        {
            "S1": "Failover ile korunan: 0 bağlantı.",
            "S2": "Kök kaynak doğrulanmış, ancak fiziksel kök neden gerekçesi ayrıca doğrulanmadı.",
            "S3": "Device Not Active için bu olayda doğrulanmış alarm kaydı yok.",
        },
        {},
    )

    assert narrative["sentences"] == []
    assert removed[0]["failure_code"] == "unsupported_domain_interpretation"


def test_same_event_alarm_query_requires_root_and_symptom_evidence():
    statements = {
        "S1": "Kök neden alarmı: DISTRIBUTION_CABLE_DOWN.",
        "S2": "Dying Gasp alarmı kök neden değil, belirtidir.",
    }
    concepts = {
        statement_id: ValidatedResponseBuilder._statement_concepts(statement)
        for statement_id, statement in statements.items()
    }

    text, fill_count = ValidatedResponseBuilder._ensure_requested_narrative_coverage(
        "Olaydaki alarmlar incelendi.",
        original_query=(
            "CE-MCR-0023 olayındaki alarmları incele. Hangisi root cause, "
            "hangileri semptom?"
        ),
        selected_statements=statements,
        statement_concepts=concepts,
    )

    assert "Kök neden alarmı: DISTRIBUTION_CABLE_DOWN." in text
    assert "Dying Gasp alarmı kök neden değil, belirtidir." in text
    assert fill_count == 2


def test_free_text_narrative_rejects_unverified_independence_claim():
    narrative, removed = ValidatedResponseBuilder._free_text_narrative(
        "Alarmlar kesin bağımsızdır ve birbirini etkilemedi.",
        {"S1": "Olaylar arasında doğrulanmış ilişki bulunmadı."},
        {},
    )

    assert narrative["sentences"] == []
    assert removed[0]["failure_code"] == "unsupported_domain_interpretation"


def test_unverified_causality_uses_deterministic_response_without_provider_attempt():
    statements = {
        "S1": "Kök kaynak doğrulanmış, ancak fiziksel kök neden gerekçesi ayrıca doğrulanmadı.",
        "S2": "Failover ile korunan: 0 bağlantı.",
    }

    assert ValidatedResponseBuilder._requires_deterministic_uncertainty_response(
        "Backup neden devreye girmedi ve fiziksel arıza nedeni ne?",
        statements,
    )


@pytest.mark.django_db
def test_builder_skips_provider_for_only_unverified_requested_causality():
    snapshot = create_snapshot("response-unverified-causality-skip")
    result = valid_result(snapshot.snapshot_key)
    result.causal_summary.root_cause_summary = "SCN-BNG-DOWN-001"
    result.causal_summary.propagation_summary = (
        "Candidate is retained as causal-chain evidence, not a confirmed root."
    )
    run = completed_run(
        "response-unverified-causality-skip",
        snapshot=snapshot,
        result=result,
        original_query="Backup neden devreye girmedi ve fiziksel arıza nedeni ne?",
    )
    run.structured_query = {
        "intent": "outage_impact",
        "requested_outputs": ["summary", "details", "root_cause"],
    }
    run.save(update_fields=["structured_query"])
    provider = RecordingProvider()

    response = ValidatedResponseBuilder().build(
        run,
        mode=ResponseGenerationMode.LLM_ASSISTED,
        provider=provider,
    )

    assert provider.requests == []
    assert response.generation_mode == ResponseGenerationMode.DETERMINISTIC
    assert response.warnings == []
    assert response.narrative_synthesis_audit["status"] == "skipped"


def test_free_text_narrative_rejects_positive_relation_and_time_proximity_without_relation():
    narrative, removed = ValidatedResponseBuilder._free_text_narrative(
        "İki olay arasında korelasyon olduğu ve yakın zamanda gerçekleştiği görülüyor.",
        {
            "S1": "Olaylar arasında doğrulanmış ilişki bulunmadı.",
            "S2": "Olaylar arasındaki zaman farkı: 1161 saat 46 dakika.",
        },
        {},
    )

    assert narrative["sentences"] == []
    assert removed[0]["failure_code"] == "unsupported_domain_interpretation"


def test_no_relation_card_fact_skips_provider_narrative_synthesis():
    assert ValidatedResponseBuilder._requires_deterministic_uncertainty_response(
        "İki olay arasındaki nedensel zincirin yönünü söyle.",
        {
            "S1": "Korelasyon: İlişki bulunmadı.",
            "S2": "Olaylar arasındaki zaman farkı: 1161 saat 46 dakika.",
            "S3": "Olaylar arasında kök/belirti yönü kesin olarak doğrulanmadı.",
        },
    )


@pytest.mark.django_db
def test_builder_skips_provider_for_canonical_no_relation_result():
    snapshot = create_snapshot("response-no-relation-skip")
    result = valid_result(snapshot.snapshot_key)
    result.cross_incident_correlation_summary = CrossIncidentCorrelationSummary(
        anchor_event_code="CE-XREG-0001",
        candidate_event_code="CE-MCR-0023",
        correlation_status="no_relation",
        time_difference_seconds=4_182_360,
        root_symptom_status="not_verified",
    )
    run = completed_run(
        "response-no-relation-skip",
        snapshot=snapshot,
        result=result,
        original_query="CE-XREG-0001 ile CE-MCR-0023 arasındaki nedensel yön nedir?",
    )
    run.structured_query = {
        "intent": "alarm_correlation",
        "requested_outputs": ["summary", "correlation", "evidence"],
    }
    run.save(update_fields=["structured_query"])
    provider = RecordingProvider()

    response = ValidatedResponseBuilder().build(
        run,
        mode=ResponseGenerationMode.LLM_ASSISTED,
        provider=provider,
    )

    assert provider.requests == []
    assert response.generation_mode == ResponseGenerationMode.DETERMINISTIC
    assert "Olaylar arasında doğrulanmış ilişki bulunmadı." in response.response_text
    assert "yakın zaman" not in response.response_text.casefold()
    assert "verified_anchor" not in response.response_text


@pytest.mark.django_db
def test_builder_skips_provider_when_scoped_analytics_has_no_matching_records():
    snapshot = create_snapshot("response-empty-analytics-skip")
    result = valid_result(snapshot.snapshot_key).model_copy(
        update={
            "analytics_summary": AnalyticsSummary(
                metric="outage_count",
                aggregation="count",
                ranking_direction="desc",
                filters={"city": "İzmir", "district": "Konak"},
                rows=[],
                included_event_count=0,
                excluded_unknown_count=0,
                deduplication_grain="causal_event",
            )
        }
    )
    run = completed_run(
        "response-empty-analytics-skip",
        snapshot=snapshot,
        result=result,
        original_query="6 Haziran 2026 tarihinde Konak ilçesinde kaç kesinti yaşandı?",
    )
    run.structured_query = {
        "intent": "operational_analytics",
        "requested_outputs": ["summary", "analytics"],
    }
    run.save(update_fields=["structured_query"])
    provider = RecordingProvider()

    response = ValidatedResponseBuilder().build(
        run,
        mode=ResponseGenerationMode.LLM_ASSISTED,
        provider=provider,
    )

    assert provider.requests == []
    assert response.generation_mode == ResponseGenerationMode.DETERMINISTIC
    assert "eşleşen kayıt bulunmuyor" in response.response_text
    assert response.narrative_synthesis_audit["reason"] == "no_matching_analytics_records"


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("metric", "value", "label"),
    [
        ("outage_count", 13, "kesinti"),
        ("alarm_count", 21, "alarm"),
    ],
)
def test_direct_analytics_count_coverage_restores_selected_canonical_fact(metric, value, label):
    text, fill_count = ValidatedResponseBuilder._ensure_requested_narrative_coverage(
        "Kayıtlar değerlendirildi.",
        original_query=f"2026 yılında İzmir şehrinde kaç {label} yaşandı?",
        selected_statements={"S1": f"1. İzmir: {value} {label}."},
        statement_concepts={"S1": ["analytics_direct_count"]},
        structured_query={
            "intent": "operational_analytics",
            "requested_outputs": ["summary", "analytics"],
            "analytics": {
                "metric": metric,
                "aggregation": "count",
                "group_by": None,
                "comparison": False,
            },
        },
    )

    assert f"İzmir: {value} {label}." in text
    assert fill_count == 1


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("metric", "value", "expected"),
    [
        ("outage_count", 13, "2026 yılında İzmir şehrinde 13 kesinti yaşandı."),
        ("alarm_count", 88, "2026 yılında İzmir şehrinde 88 alarm oluştu."),
    ],
)
def test_single_direct_analytics_count_uses_concise_deterministic_presentation(
    metric, value, expected
):
    snapshot = create_snapshot(f"response-concise-count-{metric}")
    result = valid_result(snapshot.snapshot_key).model_copy(
        update={
            "analytics_summary": AnalyticsSummary(
                metric=metric,
                aggregation="count",
                ranking_direction="desc",
                filters={"city": "İzmir"},
                scope_label="İzmir",
                rows=[{"label": "Toplam", "value": value, "event_count": value}],
                included_event_count=value,
                excluded_unknown_count=0,
                deduplication_grain="causal_event",
            )
        }
    )
    run = completed_run(
        f"response-concise-count-{metric}",
        snapshot=snapshot,
        result=result,
        original_query="2026 yılında İzmir şehrinde kaç kayıt oluştu?",
    )
    run.structured_query = {
        "intent": "operational_analytics",
        "requested_outputs": ["summary", "analytics"],
        "analytics": {
            "metric": metric,
            "aggregation": "count",
            "group_by": None,
            "comparison": False,
        },
        "analytics_specs": [
            {
                "metric": metric,
                "aggregation": "count",
                "group_by": None,
                "comparison": False,
            }
        ],
        "time_window": {
            "from_time": "2026-01-01T00:00:00+00:00",
            "to_time": "2026-12-31T23:59:59+00:00",
        },
    }
    run.save(update_fields=["structured_query"])
    provider = RecordingProvider("Bu prose kullanılmamalı.")

    response = ValidatedResponseBuilder().build(
        run, mode=ResponseGenerationMode.LLM_ASSISTED, provider=provider
    )

    assert response.response_text == expected
    assert response.generation_mode == ResponseGenerationMode.DETERMINISTIC
    assert provider.requests == []
    assert response.narrative_synthesis_audit == {
        "status": "skipped",
        "reason": "single_direct_analytics_count",
    }


def _analytics_structured_query(snapshot_identifier, *, specifications, locations):
    return {
        "snapshot_identifier": snapshot_identifier,
        "intent": "operational_analytics",
        "requested_outputs": ["summary", "analytics"],
        "analytics": specifications[0],
        "analytics_specs": specifications,
        "analytics_locations": locations,
        "time_window": {
            "from_time": "2026-01-01T00:00:00+00:00",
            "to_time": "2026-12-31T23:59:59+00:00",
        },
    }


def _failover_structured_query(snapshot_identifier):
    return {
        "snapshot_identifier": snapshot_identifier,
        "intent": "outage_impact",
        "requested_outputs": ["details", "impact", "summary"],
        "semantic_dimensions": ["failover_status", "outage_classification"],
    }


def _failover_result(snapshot_identifier, *, full_outage):
    base = valid_result(snapshot_identifier)
    return base.model_copy(
        update={
            "causal_summary": base.causal_summary.model_copy(
                update={"full_outage": full_outage}
            ),
            "impact_summary": None,
        }
    )


def _failover_run(snapshot, *, full_outage):
    run = completed_run(
        f"response-structured-failover-{full_outage}",
        snapshot=snapshot,
        result=_failover_result(snapshot.snapshot_key, full_outage=full_outage),
        original_query=(
            "CE-MCR-0010 olayında ana bağlantı down ve yedek bağlantı active. "
            "Bu tam kesinti mi?"
        ),
    )
    run.structured_query = _failover_structured_query(snapshot.snapshot_key)
    run.save(update_fields=["structured_query"])
    return run


def _compensation_structured_query(snapshot_identifier):
    return {
        "snapshot_identifier": snapshot_identifier,
        "intent": "compensation_evaluation",
        "requested_outputs": ["eligibility", "evidence", "summary"],
        "semantic_dimensions": ["decision_evidence", "rule_version", "summary"],
    }


def _compensation_run(snapshot, *, result=None):
    run = completed_run(
        "response-structured-compensation",
        snapshot=snapshot,
        result=result or valid_result(snapshot.snapshot_key),
        original_query=(
            "Kesinti için telafi değerlendirmesi nedir, hangi RuleVersion uygulandı "
            "ve DecisionEvidence kaydını göster."
        ),
    )
    run.structured_query = _compensation_structured_query(snapshot.snapshot_key)
    run.save(update_fields=["structured_query"])
    return run


def _compensation_required_ids(run):
    result = ValidatedExecutionResult.model_validate(run.final_result)
    _prompt, contract = ValidatedResponseBuilder._statement_contract(
        result,
        original_query=run.original_query,
        structured_query=run.structured_query,
    )
    selection = ValidatedResponseBuilder._deterministic_answer_plan(
        contract,
        run.structured_query,
    )
    selected_statements = {
        statement_id: contract["statements"][statement_id]
        for statement_id in selection["selected_statement_ids"]
    }
    required_ids = ValidatedResponseBuilder._required_compensation_statement_ids(
        selected_statements,
        contract["compensation_statement_ids"],
        run.structured_query,
    )
    return contract, selected_statements, required_ids


def _customer_impact_structured_query(snapshot_identifier, *, dimensions=None):
    return {
        "snapshot_identifier": snapshot_identifier,
        "intent": "outage_impact",
        "requested_outputs": ["impact"],
        "semantic_dimensions": dimensions
        or ["verified_customer_impact", "verified_subscription_impact"],
        "customer_impact_requested": True,
    }


def _customer_impact_result(snapshot_identifier):
    base = valid_result(snapshot_identifier)
    impact = base.impact_summary.model_copy(
        update={
            "potential": 572,
            "verified_impacted": 429,
            "affected_subscription_count": 429,
            "affected_customer_count": 393,
            "verified_no_impact": 0,
            "insufficient_evidence": 143,
            "failover_protected": 0,
        }
    )
    return base.model_copy(update={"impact_summary": impact})


def _customer_impact_run(snapshot, *, result=None, dimensions=None):
    result = (
        result if result is not None else _customer_impact_result(snapshot.snapshot_key)
    )
    run = completed_run(
        "response-structured-customer-impact",
        snapshot=snapshot,
        result=result,
        original_query="Kesintiden kaç müşteri ve kaç abonelik gerçekten etkilendi?",
    )
    run.structured_query = _customer_impact_structured_query(
        snapshot.snapshot_key,
        dimensions=dimensions,
    )
    run.save(update_fields=["structured_query"])
    return run


def _customer_impact_claims(run):
    result = ValidatedExecutionResult.model_validate(run.final_result)
    _prompt, contract = ValidatedResponseBuilder._statement_contract(
        result,
        original_query=run.original_query,
        structured_query=run.structured_query,
    )
    selection = ValidatedResponseBuilder._deterministic_answer_plan(
        contract,
        run.structured_query,
    )
    selected_statements = {
        statement_id: contract["statements"][statement_id]
        for statement_id in selection["selected_statement_ids"]
    }
    claims = ValidatedResponseBuilder._customer_impact_claim_statements(
        selected_statements,
        contract["customer_impact_statement_ids"],
    )
    required_ids = ValidatedResponseBuilder._required_customer_impact_statement_ids(
        claims,
        contract["customer_impact_statement_ids"],
        run.structured_query,
    )
    return contract, selected_statements, claims, required_ids


@pytest.mark.django_db
def test_explicit_failover_uses_structured_claim_plan_without_impact_prose():
    snapshot = create_snapshot("response-structured-failover-true")
    run = _failover_run(snapshot, full_outage=True)
    result = ValidatedExecutionResult.model_validate(run.final_result)
    _prompt, contract = ValidatedResponseBuilder._statement_contract(
        result,
        original_query=run.original_query,
        structured_query=run.structured_query,
    )
    required_id = contract["outage_classification_statement_ids"][0]
    provider = StructuredAnalyticsClaimPlanProvider(
        [{"statement_id": required_id, "role": "primary"}]
    )

    response = ValidatedResponseBuilder().build(
        run, mode=ResponseGenerationMode.LLM_ASSISTED, provider=provider
    )

    assert len(provider.requests) == 1
    assert response.response_text == "Tam hizmet kesintisi: Evet."
    assert response.narrative_synthesis_audit["mode"] == "structured_claim_plan"
    assert response.narrative_synthesis_audit["required_statement_ids"] == [required_id]
    assert response.narrative_synthesis_audit["deterministic_fill_count"] == 0
    assert "müşteri" not in response.response_text.casefold()
    assert "performans" not in response.response_text.casefold()


@pytest.mark.django_db
def test_explicit_failover_completes_only_missing_outage_classification():
    snapshot = create_snapshot("response-structured-failover-completeness")
    run = _failover_run(snapshot, full_outage=True)
    result = ValidatedExecutionResult.model_validate(run.final_result)
    _prompt, contract = ValidatedResponseBuilder._statement_contract(
        result,
        original_query=run.original_query,
        structured_query=run.structured_query,
    )
    required_id = contract["outage_classification_statement_ids"][0]
    optional_id = next(
        statement_id for statement_id in contract["statements"] if statement_id != required_id
    )
    provider = StructuredAnalyticsClaimPlanProvider(
        [{"statement_id": optional_id, "role": "primary"}]
    )

    response = ValidatedResponseBuilder().build(
        run, mode=ResponseGenerationMode.LLM_ASSISTED, provider=provider
    )

    assert response.narrative_synthesis_audit["missing_required_statement_ids"] == [required_id]
    assert response.narrative_synthesis_audit["deterministic_fill_statement_ids"] == [required_id]
    assert response.narrative_synthesis_audit["deterministic_fill_count"] == 1
    assert response.response_text.endswith("Tam hizmet kesintisi: Evet.")


@pytest.mark.django_db
def test_explicit_failover_rejects_unknown_claim_ids_with_canonical_fallback():
    snapshot = create_snapshot("response-structured-failover-unknown-id")
    run = _failover_run(snapshot, full_outage=True)
    provider = StructuredAnalyticsClaimPlanProvider(
        [{"statement_id": "S999", "role": "primary"}]
    )

    response = ValidatedResponseBuilder().build(
        run, mode=ResponseGenerationMode.LLM_ASSISTED, provider=provider
    )

    audit = response.narrative_synthesis_audit
    assert audit["fallback_used"] is True
    assert audit["rejected_statement_ids"] == ["S999"]
    assert "Tam hizmet kesintisi: Evet." in response.response_text
    assert "kullanıcı" not in response.response_text.casefold()


@pytest.mark.django_db
def test_explicit_failover_renders_false_without_hard_coding_true():
    snapshot = create_snapshot("response-structured-failover-false")
    run = _failover_run(snapshot, full_outage=False)
    result = ValidatedExecutionResult.model_validate(run.final_result)
    _prompt, contract = ValidatedResponseBuilder._statement_contract(
        result,
        original_query=run.original_query,
        structured_query=run.structured_query,
    )
    required_id = contract["outage_classification_statement_ids"][0]
    provider = StructuredAnalyticsClaimPlanProvider(
        [{"statement_id": required_id, "role": "primary"}]
    )

    response = ValidatedResponseBuilder().build(
        run, mode=ResponseGenerationMode.LLM_ASSISTED, provider=provider
    )

    assert response.response_text == "Tam hizmet kesintisi: Hayır."


@pytest.mark.django_db
def test_unknown_failover_classification_does_not_enable_structured_failover_claims():
    snapshot = create_snapshot("response-structured-failover-unknown")
    run = _failover_run(snapshot, full_outage=None)
    result = ValidatedExecutionResult.model_validate(run.final_result)
    _prompt, contract = ValidatedResponseBuilder._statement_contract(
        result,
        original_query=run.original_query,
        structured_query=run.structured_query,
    )

    assert contract["outage_classification_statement_ids"] == []
    assert not ValidatedResponseBuilder._uses_structured_failover_claim_plan(
        contract,
        run.structured_query,
    )


@pytest.mark.django_db
def test_compensation_uses_structured_claim_plan_for_requested_canonical_facts():
    snapshot = create_snapshot("response-structured-compensation-eligible")
    run = _compensation_run(snapshot)
    _contract, _selected, required_ids = _compensation_required_ids(run)
    provider = StructuredAnalyticsClaimPlanProvider(
        [{"statement_id": statement_id, "role": "primary"} for statement_id in required_ids]
    )

    response = ValidatedResponseBuilder().build(
        run, mode=ResponseGenerationMode.LLM_ASSISTED, provider=provider
    )

    assert len(provider.requests) == 1
    assert response.narrative_synthesis_audit["mode"] == "structured_claim_plan"
    assert response.narrative_synthesis_audit["fallback_used"] is False
    assert response.narrative_synthesis_audit["deterministic_fill_count"] == 0
    assert "Tazminata uygun: 1 kayıt." in response.response_text
    assert "Doğrulanmış tazminat tutarı: 10.00 TRY." in response.response_text
    assert "Doğrulanmış kural sürümü: REFUND-001:v2." in response.response_text
    assert "Doğrulanmış karar kanıtı: EVIDENCE-001." in response.response_text
    assert "başka kayıt" not in response.response_text.casefold()
    assert "uygulanabilir" not in response.response_text.casefold()


@pytest.mark.django_db
def test_compensation_completes_only_omitted_required_amount():
    snapshot = create_snapshot("response-structured-compensation-amount")
    run = _compensation_run(snapshot)
    contract, _selected, required_ids = _compensation_required_ids(run)
    amount_id = contract["compensation_statement_ids"]["compensation_amount"][0]
    provider = StructuredAnalyticsClaimPlanProvider(
        [
            {"statement_id": statement_id, "role": "primary"}
            for statement_id in required_ids
            if statement_id != amount_id
        ]
    )

    response = ValidatedResponseBuilder().build(
        run, mode=ResponseGenerationMode.LLM_ASSISTED, provider=provider
    )

    audit = response.narrative_synthesis_audit
    assert audit["missing_required_statement_ids"] == [amount_id]
    assert audit["deterministic_fill_statement_ids"] == [amount_id]
    assert audit["deterministic_fill_count"] == 1
    assert response.response_text.endswith("Doğrulanmış tazminat tutarı: 10.00 TRY.")


@pytest.mark.django_db
def test_compensation_completes_explicit_rule_and_decision_evidence():
    snapshot = create_snapshot("response-structured-compensation-rule-evidence")
    run = _compensation_run(snapshot)
    contract, _selected, required_ids = _compensation_required_ids(run)
    rule_id = contract["compensation_statement_ids"]["rule_version"][0]
    evidence_id = contract["compensation_statement_ids"]["decision_evidence"][0]
    provider = StructuredAnalyticsClaimPlanProvider(
        [
            {"statement_id": statement_id, "role": "primary"}
            for statement_id in required_ids
            if statement_id not in {rule_id, evidence_id}
        ]
    )

    response = ValidatedResponseBuilder().build(
        run, mode=ResponseGenerationMode.LLM_ASSISTED, provider=provider
    )

    audit = response.narrative_synthesis_audit
    assert audit["missing_required_statement_ids"] == [rule_id, evidence_id]
    assert "REFUND-001:v2" in response.response_text
    assert "EVIDENCE-001" in response.response_text


@pytest.mark.django_db
def test_compensation_rejects_unknown_claim_ids_with_canonical_fallback():
    snapshot = create_snapshot("response-structured-compensation-unknown")
    run = _compensation_run(snapshot)
    provider = StructuredAnalyticsClaimPlanProvider([{"statement_id": "S999", "role": "primary"}])

    response = ValidatedResponseBuilder().build(
        run, mode=ResponseGenerationMode.LLM_ASSISTED, provider=provider
    )

    audit = response.narrative_synthesis_audit
    assert audit["fallback_used"] is True
    assert audit["rejected_statement_ids"] == ["S999"]
    assert "Doğrulanmış tazminat tutarı: 10.00 TRY." in response.response_text
    assert "başka kayıt" not in response.response_text.casefold()


@pytest.mark.django_db
def test_compensation_preserves_pending_manual_review_without_zero_amount():
    snapshot = create_snapshot("response-structured-compensation-pending")
    base = valid_result(snapshot.snapshot_key)
    pending = base.compensation_summary.model_copy(
        update={
            "status": "pending",
            "considered": None,
            "eligible": None,
            "ineligible_pending": 1,
            "total_amount": None,
            "currency": None,
            "evidence_references": [],
        }
    )
    run = _compensation_run(
        snapshot,
        result=base.model_copy(update={"compensation_summary": pending}),
    )
    _contract, _selected, required_ids = _compensation_required_ids(run)
    provider = StructuredAnalyticsClaimPlanProvider(
        [{"statement_id": statement_id, "role": "primary"} for statement_id in required_ids]
    )

    response = ValidatedResponseBuilder().build(
        run, mode=ResponseGenerationMode.LLM_ASSISTED, provider=provider
    )

    assert "Telafi durumu: pending." in response.response_text
    assert "manuel inceleme bekleniyor" in response.response_text
    assert "0.00 TRY" not in response.response_text


@pytest.mark.django_db
def test_compensation_keeps_decision_evidence_distinct_from_rule_evidence():
    snapshot = create_snapshot("response-structured-compensation-evidence-distinction")
    base = valid_result(snapshot.snapshot_key)
    compensation = base.compensation_summary.model_copy(
        update={
            "rule_versions": {"COMPENSATION-RULE:v1": 1},
            "evidence_references": ["COMPENSATION-EVIDENCE-HASH"],
        }
    )
    run = _compensation_run(
        snapshot,
        result=base.model_copy(update={"compensation_summary": compensation}),
    )
    _contract, _selected, required_ids = _compensation_required_ids(run)
    provider = StructuredAnalyticsClaimPlanProvider(
        [{"statement_id": statement_id, "role": "primary"} for statement_id in required_ids]
    )

    response = ValidatedResponseBuilder().build(
        run, mode=ResponseGenerationMode.LLM_ASSISTED, provider=provider
    )

    assert "COMPENSATION-RULE:v1" in response.response_text
    assert "COMPENSATION-EVIDENCE-HASH" in response.response_text
    assert "EVIDENCE-001" not in response.response_text


@pytest.mark.django_db
def test_rule_evidence_uses_structured_claims_only_with_deterministic_claims():
    snapshot = create_snapshot("response-structured-rule-evidence")
    run = _compensation_run(snapshot)
    run.structured_query = {
        "snapshot_identifier": snapshot.snapshot_key,
        "intent": "rule_evidence",
        "requested_outputs": ["evidence"],
        "semantic_dimensions": ["rule_version", "decision_evidence"],
    }
    run.save(update_fields=["structured_query"])
    contract, _selected, required_ids = _compensation_required_ids(run)
    provider = StructuredAnalyticsClaimPlanProvider(
        [{"statement_id": statement_id, "role": "primary"} for statement_id in required_ids]
    )

    response = ValidatedResponseBuilder().build(
        run, mode=ResponseGenerationMode.LLM_ASSISTED, provider=provider
    )

    assert ValidatedResponseBuilder._uses_structured_compensation_claim_plan(
        contract, run.structured_query
    )
    assert "REFUND-001:v2" in response.response_text
    assert "EVIDENCE-001" in response.response_text


def test_rule_document_retrieval_does_not_enable_structured_compensation_claims():
    assert not ValidatedResponseBuilder._uses_structured_compensation_claim_plan(
        {"compensation_statement_ids": {"rule_version": ["S1"]}},
        {
            "intent": "rule_document_retrieval",
            "semantic_dimensions": ["rule_version"],
        },
    )


@pytest.mark.django_db
def test_customer_impact_uses_structured_claims_for_verified_metrics_only():
    snapshot = create_snapshot("response-structured-ci")
    run = _customer_impact_run(snapshot)
    contract, _selected, claims, required_ids = _customer_impact_claims(run)
    provider = StructuredAnalyticsClaimPlanProvider(
        [{"statement_id": statement_id, "role": "primary"} for statement_id in required_ids]
    )

    response = ValidatedResponseBuilder().build(
        run, mode=ResponseGenerationMode.LLM_ASSISTED, provider=provider
    )

    assert len(provider.requests) == 1
    assert response.narrative_synthesis_audit["mode"] == "structured_claim_plan"
    assert response.narrative_synthesis_audit["fallback_used"] is False
    assert response.narrative_synthesis_audit["deterministic_fill_count"] == 0
    assert response.response_text == "Doğrulanmış etki: 429 abonelik / 393 müşteri."
    assert "572" not in response.response_text
    assert "143" not in response.response_text
    assert "sınırlı" not in response.response_text.casefold()
    assert contract["customer_impact_statement_ids"]["potential_scope"] != required_ids
    assert set(claims) == {
        *contract["customer_impact_statement_ids"]["potential_scope"],
        *contract["customer_impact_statement_ids"]["verified_customer_impact"],
        *contract["customer_impact_statement_ids"]["insufficient_evidence"],
        *contract["customer_impact_statement_ids"]["failover_protected"],
    }


@pytest.mark.django_db
def test_customer_impact_completes_missing_verified_statement_only():
    snapshot = create_snapshot("response-structured-ci-completeness")
    run = _customer_impact_run(snapshot)
    _contract, _selected, claims, required_ids = _customer_impact_claims(run)
    optional_id = next(statement_id for statement_id in claims if statement_id not in required_ids)
    provider = StructuredAnalyticsClaimPlanProvider(
        [{"statement_id": optional_id, "role": "primary"}]
    )

    response = ValidatedResponseBuilder().build(
        run, mode=ResponseGenerationMode.LLM_ASSISTED, provider=provider
    )

    audit = response.narrative_synthesis_audit
    assert audit["missing_required_statement_ids"] == required_ids
    assert audit["deterministic_fill_statement_ids"] == required_ids
    assert audit["deterministic_fill_count"] == 1
    assert response.response_text.endswith("Doğrulanmış etki: 429 abonelik / 393 müşteri.")
    assert "143" not in response.response_text


@pytest.mark.django_db
def test_customer_impact_exposes_insufficient_evidence_only_when_explicitly_requested():
    snapshot = create_snapshot("response-structured-ci-unknown")
    run = _customer_impact_run(
        snapshot,
        dimensions=["verified_customer_impact", "evidence_gap"],
    )
    contract, _selected, claims, required_ids = _customer_impact_claims(run)
    insufficient_id = contract["customer_impact_statement_ids"]["insufficient_evidence"][0]
    provider = StructuredAnalyticsClaimPlanProvider(
        [{"statement_id": insufficient_id, "role": "primary"}]
    )

    response = ValidatedResponseBuilder().build(
        run, mode=ResponseGenerationMode.LLM_ASSISTED, provider=provider
    )

    assert insufficient_id in required_ids
    assert "Kanıt yetersiz: 143 bağlantı." in response.response_text
    assert "143 abonelik" not in response.response_text
    assert "0 bağlantı" not in response.response_text
    assert "Doğrulanmış etki: 429 abonelik / 393 müşteri." in response.response_text
    assert set(claims) >= {insufficient_id}


@pytest.mark.django_db
def test_customer_impact_renders_canonical_verified_no_impact_without_verified_impact():
    snapshot = create_snapshot("response-structured-ci-protected")
    result = _customer_impact_result(snapshot.snapshot_key)
    impact = result.impact_summary.model_copy(
        update={
            "affected_subscription_count": None,
            "affected_customer_count": None,
            "verified_impacted": None,
            "verified_no_impact": 4,
            "insufficient_evidence": None,
        }
    )
    run = _customer_impact_run(
        snapshot,
        result=result.model_copy(update={"impact_summary": impact}),
        dimensions=["verified_no_impact"],
    )
    contract, _selected, _claims, required_ids = _customer_impact_claims(run)
    protected_id = contract["customer_impact_statement_ids"]["verified_no_impact"][0]
    provider = StructuredAnalyticsClaimPlanProvider(
        [{"statement_id": protected_id, "role": "primary"}]
    )

    response = ValidatedResponseBuilder().build(
        run, mode=ResponseGenerationMode.LLM_ASSISTED, provider=provider
    )

    assert required_ids == [protected_id]
    assert response.response_text == "Doğrulanmış etkisizlik: 4 bağlantı."
    assert "429 abonelik" not in response.response_text
    assert response.narrative_synthesis_audit["deterministic_fill_count"] == 0


@pytest.mark.django_db
def test_customer_impact_rejects_unrelated_outage_statement_ids():
    snapshot = create_snapshot("response-structured-ci-unrelated")
    run = _customer_impact_run(snapshot)
    contract, selected_statements, _claims, required_ids = _customer_impact_claims(run)
    unrelated_id = next(
        statement_id
        for statement_id in selected_statements
        if statement_id not in contract["customer_impact_statement_ids"]["verified_customer_impact"]
        and statement_id not in contract["customer_impact_statement_ids"]["potential_scope"]
        and statement_id not in contract["customer_impact_statement_ids"]["insufficient_evidence"]
        and statement_id not in contract["customer_impact_statement_ids"]["failover_protected"]
    )
    provider = StructuredAnalyticsClaimPlanProvider(
        [{"statement_id": unrelated_id, "role": "primary"}]
    )

    response = ValidatedResponseBuilder().build(
        run, mode=ResponseGenerationMode.LLM_ASSISTED, provider=provider
    )

    audit = response.narrative_synthesis_audit
    assert audit["fallback_used"] is True
    assert audit["rejected_statement_ids"] == [unrelated_id]
    assert audit["required_statement_ids"] == required_ids
    assert "kök neden" not in response.response_text.casefold()
    assert "AGG-ANK" not in response.response_text


@pytest.mark.django_db
def test_customer_impact_gate_does_not_override_explicit_failover_gate():
    snapshot = create_snapshot("response-structured-ci-failover")
    run = _customer_impact_run(
        snapshot,
        dimensions=[
            "verified_customer_impact",
            "failover_status",
            "outage_classification",
        ],
    )
    result = ValidatedExecutionResult.model_validate(run.final_result)
    _prompt, contract = ValidatedResponseBuilder._statement_contract(
        result,
        original_query=run.original_query,
        structured_query=run.structured_query,
    )

    assert not ValidatedResponseBuilder._uses_structured_customer_impact_claim_plan(
        contract,
        run.structured_query,
    )


@pytest.mark.django_db
def test_ranking_uses_requested_canonical_support_before_provider_synthesis():
    snapshot = create_snapshot("response-analytics-ranking-support")
    ranking = AnalyticsSummary(
        metric="alarm_count",
        aggregation="count",
        group_by="alarm_type",
        ranking_direction="desc",
        limit=1,
        filters={
            "city": "İzmir",
            "from_time": "2026-01-01T00:00:00+00:00",
            "to_time": "2026-12-31T23:59:59+00:00",
        },
        rows=[{"label": "FAILOVER_UNSUCCESSFUL", "value": 17, "event_count": 7}],
        included_event_count=7,
        excluded_unknown_count=0,
        deduplication_grain="alarm_occurrence",
    )
    result = valid_result(snapshot.snapshot_key).model_copy(
        update={"analytics_summary": ranking, "analytics_summaries": [ranking]}
    )
    query = _analytics_structured_query(
        snapshot.snapshot_key,
        specifications=[
            {
                "metric": "alarm_count",
                "aggregation": "count",
                "group_by": "alarm_type",
                "direction": "desc",
                "limit": 1,
                "comparison": False,
            }
        ],
        locations=[{"city": "İzmir"}],
    )
    run = completed_run(
        "response-analytics-ranking-support",
        snapshot=snapshot,
        result=result,
        original_query="2026 yılında İzmir şehrinde en çok görülen alarm tipi nedir?",
    )
    run.structured_query = query
    run.save(update_fields=["structured_query"])

    _prompt, contract = ValidatedResponseBuilder._statement_contract(
        result,
        original_query=run.original_query,
        structured_query=query,
    )
    support = contract["analytics_answer_support"]
    assert len(support) == 1
    support_statement_id = contract["analytics_requested_statement_ids"][0]
    support_statement = (support_statement_id, contract["statements"][support_statement_id])
    assert "FAILOVER_UNSUCCESSFUL" in support_statement[1]
    assert "17 alarm" in support_statement[1]
    assert support[support_statement_id]["kind"] == "canonical"

    provider = StructuredAnalyticsClaimPlanProvider(
        [{"statement_id": support_statement_id, "role": "primary"}]
    )
    response = ValidatedResponseBuilder().build(
        run,
        mode=ResponseGenerationMode.LLM_ASSISTED,
        provider=provider,
    )

    assert len(provider.requests) == 1
    assert response.narrative_synthesis_audit["status"] == "accepted"
    assert response.narrative_synthesis_audit["status"] != "skipped"
    assert response.narrative_synthesis_audit["mode"] == "structured_claim_plan"
    assert response.narrative_synthesis_audit["required_statement_ids"] == [support_statement_id]
    assert response.narrative_synthesis_audit["deterministic_fill_count"] == 0
    assert "FAILOVER_UNSUCCESSFUL" in response.response_text
    assert "17 alarm" in response.response_text


@pytest.mark.django_db
def test_requested_total_supports_constituents_and_derived_total_before_provider():
    snapshot = create_snapshot("response-analytics-total-support")

    def summary(city, value):
        return AnalyticsSummary(
            metric="alarm_count",
            aggregation="count",
            group_by="city",
            ranking_direction="desc",
            filters={
                "city": city,
                "from_time": "2026-01-01T00:00:00+00:00",
                "to_time": "2026-12-31T23:59:59+00:00",
            },
            scope_label=city,
            rows=[{"label": city, "value": value, "event_count": value}],
            included_event_count=value,
            excluded_unknown_count=0,
            deduplication_grain="causal_event",
        )

    istanbul, izmir, ankara = summary("İstanbul", 72), summary("İzmir", 88), summary("Ankara", 99)
    result = valid_result(snapshot.snapshot_key).model_copy(
        update={"analytics_summary": istanbul, "analytics_summaries": [istanbul, izmir, ankara]}
    )
    query = _analytics_structured_query(
        snapshot.snapshot_key,
        specifications=[
            {
                "metric": "alarm_count",
                "aggregation": "count",
                "group_by": "city",
                "direction": "desc",
                "comparison": False,
            }
        ],
        locations=[{"city": "İstanbul"}, {"city": "İzmir"}],
    )
    run = completed_run(
        "response-analytics-total-support",
        snapshot=snapshot,
        result=result,
        original_query="2026 yılında İzmir ve İstanbul şehirlerinde toplam kaç alarm oluştu?",
    )
    run.structured_query = query
    run.save(update_fields=["structured_query"])

    _prompt, contract = ValidatedResponseBuilder._statement_contract(
        result,
        original_query=run.original_query,
        structured_query=query,
    )
    support_text = [
        contract["statements"][statement_id]
        for statement_id in contract["analytics_requested_statement_ids"]
    ]
    assert any("72 alarm" in item for item in support_text)
    assert any("88 alarm" in item for item in support_text)
    assert any("160" in item for item in support_text)
    assert all("99" not in item and "Ankara" not in item for item in support_text)
    derived_support = [
        item for item in contract["analytics_answer_support"].values() if item["kind"] == "derived"
    ]
    assert derived_support[0]["canonical_source_refs"] == [
        "analytics_summary[0].rows[0]",
        "analytics_summary[1].rows[0]",
    ]

    provider = StructuredAnalyticsClaimPlanProvider(
        [
            {"statement_id": statement_id, "role": "primary" if index == 0 else "support"}
            for index, statement_id in enumerate(contract["analytics_requested_statement_ids"][:2])
        ]
    )
    response = ValidatedResponseBuilder().build(
        run,
        mode=ResponseGenerationMode.LLM_ASSISTED,
        provider=provider,
    )

    assert len(provider.requests) == 1
    provider_facts = provider.requests[0]["contents"]
    assert "72 alarm" in provider_facts
    assert "88 alarm" in provider_facts
    assert "160" in provider_facts
    assert "Ankara" not in provider_facts
    assert response.narrative_synthesis_audit["status"] == "accepted"
    assert response.narrative_synthesis_audit["mode"] == "structured_claim_plan"
    assert response.narrative_synthesis_audit["deterministic_fill_count"] == 1
    assert response.narrative_synthesis_audit["missing_required_statement_ids"] == [
        contract["analytics_requested_statement_ids"][2]
    ]
    assert "160" in response.response_text


def test_unknown_typed_analytics_fact_does_not_expose_zero_as_provider_support():
    analytics = AnalyticsSummary(
        metric="alarm_count",
        aggregation="count",
        ranking_direction="desc",
        filters={
            "city": "İzmir",
            "from_time": "2026-01-01T00:00:00+00:00",
            "to_time": "2026-12-31T23:59:59+00:00",
        },
        rows=[{"label": "Toplam", "value": 0, "event_count": 0}],
        included_event_count=0,
        excluded_unknown_count=1,
        deduplication_grain="causal_event",
    )
    query = _analytics_structured_query(
        "response-analytics-unknown-support",
        specifications=[
            {
                "metric": "alarm_count",
                "aggregation": "count",
                "group_by": None,
                "direction": "desc",
                "comparison": False,
            }
        ],
        locations=[{"city": "İzmir"}],
    )
    _prompt, contract = ValidatedResponseBuilder._statement_contract(
        valid_result(query["snapshot_identifier"]).model_copy(
            update={"analytics_summary": analytics, "analytics_summaries": [analytics]}
        ),
        original_query="2026 yılında İzmir şehrinde kaç alarm oluştu?",
        structured_query=query,
    )
    selection = ValidatedResponseBuilder._deterministic_answer_plan(contract, query)

    assert contract["analytics_has_typed_requirements"] is True
    assert contract["analytics_requested_statement_ids"] == []
    assert selection["selected_statement_ids"] == []


@pytest.mark.django_db
def test_multi_metric_provider_support_excludes_unrequested_sibling_metric():
    snapshot = create_snapshot("response-analytics-multi-support")

    def summary(metric, value):
        return AnalyticsSummary(
            metric=metric,
            aggregation="count",
            ranking_direction="desc",
            filters={
                "city": "İzmir",
                "from_time": "2026-01-01T00:00:00+00:00",
                "to_time": "2026-12-31T23:59:59+00:00",
            },
            rows=[{"label": "Toplam", "value": value, "event_count": value}],
            included_event_count=value,
            excluded_unknown_count=0,
            deduplication_grain="causal_event",
        )

    alarm, outage, event = (
        summary("alarm_count", 88),
        summary("outage_count", 13),
        summary("event_count", 101),
    )
    result = valid_result(snapshot.snapshot_key).model_copy(
        update={"analytics_summary": alarm, "analytics_summaries": [alarm, outage, event]}
    )
    query = _analytics_structured_query(
        snapshot.snapshot_key,
        specifications=[
            {
                "metric": "alarm_count",
                "aggregation": "count",
                "group_by": None,
                "direction": "desc",
                "comparison": False,
            },
            {
                "metric": "outage_count",
                "aggregation": "count",
                "group_by": None,
                "direction": "desc",
                "comparison": False,
            },
        ],
        locations=[{"city": "İzmir"}],
    )
    run = completed_run(
        "response-analytics-multi-support",
        snapshot=snapshot,
        result=result,
        original_query="2026 yılında İzmir şehrinde kaç alarm ve kaç kesinti yaşandı?",
    )
    run.structured_query = query
    run.save(update_fields=["structured_query"])
    _prompt, contract = ValidatedResponseBuilder._statement_contract(
        result,
        original_query=run.original_query,
        structured_query=query,
    )
    provider = StructuredAnalyticsClaimPlanProvider(
        [
            {"statement_id": statement_id, "role": "primary" if index == 0 else "support"}
            for index, statement_id in enumerate(contract["analytics_requested_statement_ids"])
        ]
    )

    response = ValidatedResponseBuilder().build(
        run,
        mode=ResponseGenerationMode.LLM_ASSISTED,
        provider=provider,
    )

    assert len(provider.requests) == 1
    assert "101" not in provider.requests[0]["contents"]
    assert response.narrative_synthesis_audit["status"] == "accepted"


@pytest.mark.django_db
def test_supported_comparison_uses_provider_without_derived_delta():
    snapshot = create_snapshot("response-analytics-comparison-support")
    comparison = AnalyticsSummary(
        metric="outage_count",
        aggregation="count",
        group_by="time_bucket",
        ranking_direction="desc",
        time_grain="month",
        comparison=True,
        filters={
            "from_time": "2026-01-01T00:00:00+00:00",
            "to_time": "2026-12-31T23:59:59+00:00",
        },
        rows=[
            {"label": "2026-06", "value": 13, "event_count": 13},
            {"label": "2026-07", "value": 11, "event_count": 11},
        ],
        included_event_count=24,
        excluded_unknown_count=0,
        deduplication_grain="causal_event",
    )
    result = valid_result(snapshot.snapshot_key).model_copy(
        update={"analytics_summary": comparison, "analytics_summaries": [comparison]}
    )
    query = _analytics_structured_query(
        snapshot.snapshot_key,
        specifications=[
            {
                "metric": "outage_count",
                "aggregation": "count",
                "group_by": "time_bucket",
                "direction": "desc",
                "time_grain": "month",
                "comparison": True,
            }
        ],
        locations=[],
    )
    run = completed_run(
        "response-analytics-comparison-support",
        snapshot=snapshot,
        result=result,
        original_query="Haziran 2026 ile Temmuz 2026 kesinti sayılarını karşılaştır.",
    )
    run.structured_query = query
    run.save(update_fields=["structured_query"])
    _prompt, contract = ValidatedResponseBuilder._statement_contract(
        result,
        original_query=run.original_query,
        structured_query=query,
    )
    provider = StructuredAnalyticsClaimPlanProvider(
        [
            {"statement_id": statement_id, "role": "primary" if index == 0 else "support"}
            for index, statement_id in enumerate(contract["analytics_requested_statement_ids"])
        ]
    )

    response = ValidatedResponseBuilder().build(
        run,
        mode=ResponseGenerationMode.LLM_ASSISTED,
        provider=provider,
    )

    assert len(provider.requests) == 1
    assert response.narrative_synthesis_audit["status"] == "accepted"
    assert response.narrative_synthesis_audit["deterministic_fill_count"] == 0
    assert response.response_text == "2026-06: 13 kesinti. 2026-07: 11 kesinti."


def test_structured_analytics_claim_plan_rejects_unknown_ids_without_rendering_them():
    provider = StructuredAnalyticsClaimPlanProvider(
        [{"statement_id": "S999", "role": "primary"}]
    )

    text, audit = ValidatedResponseBuilder._structured_analytics_claim_narrative(
        provider,
        original_query="En çok görülen alarm tipi nedir?",
        selected_statements={
            "S1": "2026 yılında İzmir'de en yüksek alarm tipi: FAILOVER_UNSUCCESSFUL (17 alarm)."
        },
        analytics_support={"S1": {"requirement_kind": "ranking_winner"}},
    )

    assert len(provider.requests) == 1
    assert text == "2026 yılında İzmir'de en yüksek alarm tipi: FAILOVER_UNSUCCESSFUL (17 alarm)."
    assert audit["status"] == "fallback"
    assert audit["rejected_statement_ids"] == ["S999"]
    assert audit["backend_effective_statement_ids"] == ["S1"]
    assert "failover mekanizması" not in text.casefold()
    assert "diğer alarm tipleri" not in text.casefold()


def test_structured_analytics_claim_plan_rejects_provider_fact_channels_outside_ids():
    provider = StructuredAnalyticsClaimPlanProvider(
        [{"statement_id": "S1", "role": "primary", "value": 999}]
    )

    text, audit = ValidatedResponseBuilder._structured_analytics_claim_narrative(
        provider,
        original_query="En çok görülen alarm tipi nedir?",
        selected_statements={"S1": "FAILOVER_UNSUCCESSFUL alarmı 17 kez görüldü."},
        analytics_support={"S1": {"requirement_kind": "ranking_winner"}},
    )

    assert len(provider.requests) == 1
    assert text == "FAILOVER_UNSUCCESSFUL alarmı 17 kez görüldü."
    assert audit["status"] == "fallback"
    assert audit["fallback_reason"] == "invalid_structured_claim_plan"
    assert "999" not in text


def test_structured_analytics_claim_plan_renders_only_provider_selected_fact_order():
    selected_statements = {
        "S1": "2026 yılında İstanbul'de 72 alarm.",
        "S2": "2026 yılında İzmir'de 88 alarm.",
        "S3": "2026 yılında İstanbul ve İzmir toplam alarm: 160.",
    }
    support = {
        "S1": {"requirement_kind": "aggregate_total_request"},
        "S2": {"requirement_kind": "aggregate_total_request"},
        "S3": {"requirement_kind": "aggregate_total_request"},
    }
    provider = StructuredAnalyticsClaimPlanProvider(
        [
            {"statement_id": "S3", "role": "primary"},
            {"statement_id": "S2", "role": "support"},
            {"statement_id": "S1", "role": "support"},
        ]
    )

    text, audit = ValidatedResponseBuilder._structured_analytics_claim_narrative(
        provider,
        original_query="İzmir ve İstanbul'da toplam kaç alarm oluştu?",
        selected_statements=selected_statements,
        analytics_support=support,
    )

    assert len(provider.requests) == 1
    assert text == " ".join(
        (selected_statements["S3"], selected_statements["S2"], selected_statements["S1"])
    )
    assert audit["status"] == "accepted"
    assert audit["backend_effective_statement_ids"] == ["S3", "S2", "S1"]
    assert audit["rendered_fact_types"] == ["aggregate_total_request"] * 3
    assert "veri bütünlüğü" not in text.casefold()
    assert "yoğunluk" not in text.casefold()


def test_structured_analytics_claim_plan_preserves_unknown_without_zero_rendering():
    provider = StructuredAnalyticsClaimPlanProvider([])

    text, audit = ValidatedResponseBuilder._structured_analytics_claim_narrative(
        provider,
        original_query="İzmir'de kaç alarm oluştu?",
        selected_statements={},
        analytics_support={},
    )

    assert provider.requests == []
    assert text == "Yeterli doğrulanmış bilgi yok."
    assert audit["fallback_reason"] == "no_supported_analytics_claims"
    assert "0" not in text


def test_typed_analytics_completeness_restores_only_missing_aggregate_total():
    selected_statements = {
        "S1": "İstanbul 72 alarm.",
        "S2": "İzmir 88 alarm.",
        "S3": "Toplam 160 alarm.",
    }
    support = {
        "S1": {"kind": "canonical", "requirement_kind": "aggregate_total_request"},
        "S2": {"kind": "canonical", "requirement_kind": "aggregate_total_request"},
        "S3": {"kind": "derived", "requirement_kind": "aggregate_total_request"},
    }

    effective_ids, missing_ids = ValidatedResponseBuilder._complete_structured_analytics_claims(
        ["S1", "S2"],
        selected_statements=selected_statements,
        analytics_support=support,
    )

    assert effective_ids == ["S1", "S2", "S3"]
    assert missing_ids == ["S3"]


def test_typed_analytics_completeness_does_not_overfill_total_constituents():
    selected_statements = {
        "S1": "İstanbul 72 alarm.",
        "S2": "İzmir 88 alarm.",
        "S3": "Toplam 160 alarm.",
    }
    support = {
        "S1": {"kind": "canonical", "requirement_kind": "aggregate_total_request"},
        "S2": {"kind": "canonical", "requirement_kind": "aggregate_total_request"},
        "S3": {"kind": "derived", "requirement_kind": "aggregate_total_request"},
    }

    effective_ids, missing_ids = ValidatedResponseBuilder._complete_structured_analytics_claims(
        ["S3"],
        selected_statements=selected_statements,
        analytics_support=support,
    )

    assert effective_ids == ["S3"]
    assert missing_ids == []


def test_typed_analytics_completeness_restores_ranking_and_multimetric_requirements():
    selected_statements = {
        "S1": "FAILOVER_UNSUCCESSFUL alarmı 17 kez görüldü.",
        "S2": "İzmir'de 88 alarm oluştu.",
        "S3": "İzmir'de 13 kesinti yaşandı.",
    }
    support = {
        "S1": {"kind": "canonical", "requirement_kind": "ranking_winner"},
        "S2": {"kind": "canonical", "requirement_kind": "direct_value"},
        "S3": {"kind": "canonical", "requirement_kind": "direct_value"},
    }

    ranking_ids, ranking_missing = ValidatedResponseBuilder._complete_structured_analytics_claims(
        [],
        selected_statements={"S1": selected_statements["S1"]},
        analytics_support={"S1": support["S1"]},
    )
    multi_metric_ids, multi_metric_missing = (
        ValidatedResponseBuilder._complete_structured_analytics_claims(
            ["S2"],
            selected_statements={"S2": selected_statements["S2"], "S3": selected_statements["S3"]},
            analytics_support={"S2": support["S2"], "S3": support["S3"]},
        )
    )

    assert ranking_ids == ["S1"]
    assert ranking_missing == ["S1"]
    assert multi_metric_ids == ["S2", "S3"]
    assert multi_metric_missing == ["S3"]


def test_typed_analytics_completeness_does_not_fill_unknown_or_unrequested_rows():
    effective_ids, missing_ids = ValidatedResponseBuilder._complete_structured_analytics_claims(
        [],
        selected_statements={},
        analytics_support={},
    )

    assert effective_ids == []
    assert missing_ids == []


def test_free_text_narrative_allows_qualitative_impact_only_when_current_plan_supports_it():
    narrative, removed = ValidatedResponseBuilder._free_text_narrative(
        "Müşteri memnuniyeti olumsuz etkilendi.",
        {"S1": "Doğrulanmış müşteri memnuniyeti olumsuz etkilendi."},
        {},
    )

    assert removed == []
    assert narrative["sentences"][0]["text"] == "Müşteri memnuniyeti olumsuz etkilendi."


def test_requested_narrative_coverage_adds_only_missing_verified_fact():
    text, fill_count = ValidatedResponseBuilder._ensure_requested_narrative_coverage(
        "Olay tam hizmet kesintisidir.",
        original_query="Uygulanan kural ve tazminat tutarı nedir?",
        selected_statements={
            "S1": "Doğrulanmış tazminat tutarı: 839.99 TRY.",
            "S2": "Uygulanan RuleVersion: ME-FAILED-FAILOVER:v1.",
        },
        statement_concepts={
            "S1": ["compensation_amount"],
            "S2": ["rule_version"],
        },
    )

    assert fill_count == 2
    assert "839.99" in text
    assert "ME-FAILED-FAILOVER:v1" in text


def test_requested_comparison_coverage_adds_verified_periods_change_and_direction():
    text, fill_count = ValidatedResponseBuilder._ensure_requested_narrative_coverage(
        "Haziran ayından Temmuz ayına azalış görülmüştür.",
        original_query=(
            "Haziran ile Temmuz değerlerini karşılaştır; iki değeri, farkı ve yönü yaz."
        ),
        selected_statements={
            "S1": (
                "Dönem karşılaştırması: 2026-06 11477, 2026-07 10719; "
                "mutlak değişim 758; yön azalış."
            )
        },
        statement_concepts={"S1": ["analytics_comparison"]},
    )

    assert fill_count == 1
    assert "2026-06 11477" in text
    assert "2026-07 10719" in text
    assert "758" in text


def test_grouped_comparison_coverage_adds_each_missing_period_pair():
    text, fill_count = ValidatedResponseBuilder._ensure_requested_narrative_coverage(
        "İzmir -10, Ankara 5 değişim kaydetti.",
        original_query="Şehirleri iki dönem arasındaki değişime göre karşılaştır.",
        selected_statements={
            "S1": "İzmir: 2026-06 30, 2026-07 20; mutlak değişim 10; yön azalış.",
            "S2": "Ankara: 2026-06 10, 2026-07 15; mutlak değişim 5; yön artış.",
        },
        statement_concepts={
            "S1": ["analytics_comparison"],
            "S2": ["analytics_comparison"],
        },
    )

    assert fill_count == 2
    assert "2026-06 30" in text
    assert "2026-07 15" in text


def test_grouped_comparison_contract_has_period_evidence_without_fake_global_summary():
    result = valid_result("response-grouped-comparison").model_copy(
        update={
            "analytics_summary": AnalyticsSummary(
                metric="affected_customers",
                aggregation="sum",
                group_by="city",
                ranking_direction="desc",
                comparison=True,
                rows=[
                    {
                        "label": "İzmir",
                        "value": -10,
                        "absolute_change": 10,
                        "signed_change": -10,
                        "trend_direction": "decrease",
                        "event_count": 3,
                        "period_values": [
                            {
                                "label": "2026-06",
                                "value": 30,
                                "event_count": 2,
                                "included_event_count": 2,
                                "excluded_unknown_count": 1,
                            },
                            {
                                "label": "2026-07",
                                "value": 20,
                                "event_count": 1,
                                "included_event_count": 1,
                                "excluded_unknown_count": 0,
                            },
                        ],
                    }
                ],
                included_event_count=3,
                excluded_unknown_count=1,
                deduplication_grain="causal_event",
            )
        }
    )

    _prompt, contract = ValidatedResponseBuilder._statement_contract(result)
    statements = list(contract["statements"].values())

    assert any("2026-06 30 (2 dahil, 1 hariç)" in statement for statement in statements)
    assert not any(statement.startswith("Dönem karşılaştırması:") for statement in statements)


def test_city_comparison_contract_grounds_extrema_and_rejects_unknown_as_no_impact():
    result = valid_result("response-city-comparison-extrema").model_copy(
        update={
            "analytics_summary": AnalyticsSummary(
                metric="affected_customers",
                aggregation="sum",
                group_by="city",
                ranking_direction="desc",
                comparison=True,
                rows=[
                    {
                        "label": "İstanbul",
                        "value": 664,
                        "signed_change": 664,
                        "absolute_change": 664,
                        "trend_direction": "increase",
                        "event_count": 11,
                        "period_values": [
                            {
                                "label": "2026-06",
                                "value": 435,
                                "event_count": 4,
                                "included_event_count": 4,
                                "excluded_unknown_count": 2,
                            },
                            {
                                "label": "2026-07",
                                "value": 1099,
                                "event_count": 7,
                                "included_event_count": 7,
                                "excluded_unknown_count": 2,
                            },
                        ],
                    },
                    {
                        "label": "Ankara",
                        "value": 13,
                        "signed_change": 13,
                        "absolute_change": 13,
                        "trend_direction": "increase",
                        "event_count": 13,
                    },
                ],
                included_event_count=24,
                excluded_unknown_count=4,
                deduplication_grain="causal_event",
            )
        }
    )

    _prompt, contract = ValidatedResponseBuilder._statement_contract(result)
    statements = contract["statements"]
    assert "En yüksek artış: İstanbul, 664 müşteri." in statements.values()
    assert any("2026-06 435 (4 dahil, 2 hariç)" in statement for statement in statements.values())
    assert any(
        "analytics_period_evidence" in concepts
        for concepts in contract["statement_concepts"].values()
    )

    narrative, removed = ValidatedResponseBuilder._free_text_narrative(
        "4 olay etkisiz olarak dışarıda bırakıldı. En çok artan şehir Ankara oldu.",
        statements,
        {},
    )

    assert narrative["sentences"] == []
    assert len(removed) == 2


def test_requested_unknown_exclusion_coverage_preserves_verified_zero():
    text, fill_count = ValidatedResponseBuilder._ensure_requested_narrative_coverage(
        "Başarısız failover olaylarında doğrulanmış müşteri etkisi hesaplandı.",
        original_query="Kaç olayın hariç kaldığını da belirt.",
        selected_statements={
            "S1": (
                "0 olay, doğrulanmış etki kanıtı olmadığı için hesaplamaya dahil edilmedi."
            )
        },
        statement_concepts={"S1": ["unknown_exclusion"]},
    )

    assert fill_count == 1
    assert "0 olay" in text


def test_requested_unknown_exclusion_coverage_does_not_repeat_equivalent_prose():
    text, fill_count = ValidatedResponseBuilder._ensure_requested_narrative_coverage(
        "Doğrulanmış etki kanıtı bulunmadığı için 17 olay hesaplamadan çıkarıldı.",
        original_query="Kaç olayın hariç kaldığını da belirt.",
        selected_statements={
            "S1": "17 olay, doğrulanmış etki kanıtı olmadığı için hesaplamaya dahil edilmedi."
        },
        statement_concepts={"S1": ["unknown_exclusion"]},
    )

    assert fill_count == 0
    assert text.count("17 olay") == 1


def test_requested_included_count_coverage_accepts_equivalent_count_prose():
    text, fill_count = ValidatedResponseBuilder._ensure_requested_narrative_coverage(
        "Hesaba dahil edilen toplam olay sayısı 77'dir.",
        original_query="Hesaba dahil edilen olay sayısını belirt.",
        selected_statements={"S1": "Hesaba dahil edilen olay sayısı: 77."},
        statement_concepts={"S1": ["analytics_included_count"]},
    )

    assert fill_count == 0


def test_correlation_temporal_coverage_adds_verified_minutes_only_when_requested():
    text, fill_count = ValidatedResponseBuilder._ensure_requested_narrative_coverage(
        "İki olay arasında doğrulanmış operasyonel ilişki bulunuyor.",
        original_query="Hangi zaman farkı ve topoloji kanıtları ilişkiyi destekliyor?",
        selected_statements={"S1": "Olaylar arasındaki zaman farkı: 37 dakika."},
        statement_concepts={"S1": ["correlation_temporal_evidence"]},
    )

    assert fill_count == 1
    assert "37 dakika" in text


def test_correlation_temporal_coverage_does_not_fill_when_time_is_not_requested():
    text, fill_count = ValidatedResponseBuilder._ensure_requested_narrative_coverage(
        "İki olay arasında doğrulanmış operasyonel ilişki bulunuyor.",
        original_query="İki olay ilişkili mi?",
        selected_statements={"S1": "Olaylar arasındaki zaman farkı: 37 dakika."},
        statement_concepts={"S1": ["correlation_temporal_evidence"]},
    )

    assert fill_count == 0
    assert text == "İki olay arasında doğrulanmış operasyonel ilişki bulunuyor."


def test_structured_result_exposes_verified_correlation_summary():
    result = valid_result("correlation-structured")
    result.cross_incident_correlation_summary = CrossIncidentCorrelationSummary(
        anchor_event_code="CE-XREG-0001",
        candidate_event_code="CE-XREG-0002",
        correlation_status="verified_relation",
        time_difference_seconds=2220,
        topology_relation="direct_parent_child",
        root_symptom_status="not_verified",
    )

    structured = ValidatedResponseBuilder._public_structured_result(result)
    assert structured.snapshot_identifier == result.snapshot_identifier

    assert structured.cross_incident_correlation_summary is not None
    assert structured.cross_incident_correlation_summary.time_difference_seconds == 2220


def test_free_text_narrative_accepts_eight_short_grounded_sentences():
    statements = {f"S{index}": f"Doğrulanmış bilgi {index}." for index in range(1, 9)}
    narrative, removed = ValidatedResponseBuilder._free_text_narrative(
        " ".join(f"Doğrulanmış bilgi {index}." for index in range(1, 9)),
        statements,
        {},
    )

    assert len(narrative["sentences"]) == 8
    assert removed == []


def test_analytics_ranking_facts_remain_grounded_in_natural_ordered_prose():
    statements = {
        "S1": "1. CE-RANK-300: 300 doğrulanmış müşteri etkisi.",
        "S2": "2. CE-RANK-200: 200 doğrulanmış müşteri etkisi.",
        "S3": "3. CE-RANK-100: 100 doğrulanmış müşteri etkisi.",
        "S4": "3 olay hesaplamaya dahil edildi.",
        "S5": "2 olay, doğrulanmış etki kanıtı olmadığı için hesaplamaya dahil edilmedi.",
    }
    content = (
        "En yüksek doğrulanmış müşteri etkisi sıralaması hazırdır. "
        "CE-RANK-300 ilk sırada 300 müşteri etkisiyle yer alır. "
        "CE-RANK-200 ikinci sırada 200 müşteri etkisiyle yer alır. "
        "CE-RANK-100 üçüncü sırada 100 müşteri etkisiyle yer alır. "
        "Bu sıralama yalnız doğrulanmış müşteri etkisini kullanır. "
        "Üç olay hesaplamaya dahil edilmiştir. "
        "Yetersiz etki kanıtı bulunan iki olay hariç tutulmuştur. "
        "Eksik etki kayıtları sıfır müşteri etkisi olarak yorumlanmaz. "
        "Sonuçlar mevcut veri seti kapsamındadır."
    )

    narrative, removed = ValidatedResponseBuilder._free_text_narrative(content, statements, {})

    assert removed == []
    assert len(narrative["sentences"]) == 9
    ValidatedResponseBuilder._validate_grounded_narrative(narrative, statements, [])


def test_free_text_narrative_keeps_independent_facts_and_unknown_wording():
    statements = {
        "S1": "Gerçek müşteri etkisi kesin doğrulanmadı.",
        "S2": "Failover ile korunan bağlantı sayısı için doğrulanmış sayısal kayıt yok.",
    }
    narrative, removed = ValidatedResponseBuilder._free_text_narrative(
        "Müşteri etkisi kesin olarak doğrulanamadı. Ayrıca korunan bağlantı sayısı bilinmiyor.",
        statements,
        {},
    )

    assert len(narrative["sentences"]) == 2
    assert removed == []


def test_free_text_narrative_removes_only_fabricated_sentence_and_records_reason():
    statements = {
        "S1": "Doğrulanmış müşteri etkisi 495 müşteridir.",
        "S2": "Tam hizmet kesintisi: Evet.",
    }
    narrative, removed = ValidatedResponseBuilder._free_text_narrative(
        "495 müşteri etkilendi. 999 müşteri etkilendi.",
        statements,
        {},
    )

    assert [sentence["text"] for sentence in narrative["sentences"]] == ["495 müşteri etkilendi."]
    assert removed[0]["failure_code"] == "unsupported_number"


@pytest.mark.django_db
def test_deterministic_answer_plan_is_the_only_selection_stage():
    run = completed_run("response-deterministic-answer-plan")
    provider = RecordingProvider("Doğrulanmış gerçekler değerlendirilmiştir.")
    response = ValidatedResponseBuilder().build(
        run, mode=ResponseGenerationMode.LLM_ASSISTED, provider=provider
    )

    assert response.statement_selection_audit["mode"] == "deterministic"
    assert response.statement_selection_audit["status"] == "completed"
    assert len(provider.requests) == 1
    assert "format_schema" not in provider.requests[0]


@pytest.mark.django_db
def test_unknown_impact_quantities_are_not_rendered_as_zero():
    snapshot = create_snapshot("response-unknown-impact")
    result = valid_result(snapshot.snapshot_key).model_copy(
        update={
            "causal_summary": CausalSummary(
                causal_event_code="CE-MCR-0010",
                root_resource_type="subscription_connection",
                root_resource_reference="SUB-MCR-00011",
                primary_status="down",
                backup_status="active",
                full_outage=False,
            ),
            "impact_summary": ImpactSummary(
                assessment_record_count=0,
                missing_evidence_categories=["customer_impact_assessment"],
            ),
            "compensation_summary": CompensationSummary(status="pending", scope="verified_impact"),
        }
    )
    response = ValidatedResponseBuilder().build(
        completed_run("response-unknown-impact-run", result=result, snapshot=snapshot)
    )

    assert "Failover ile korunan: 0" not in response.response_text
    assert "Potansiyel etki: 0" not in response.response_text
    assert "Doğrulanmış etki: 0" not in response.response_text
    assert "Kanıtı yetersiz: 0" not in response.response_text
    assert "doğrulanmış sayısal kayıt yok" in response.response_text
    structured = response.structured_result
    assert structured is not None and structured.impact_summary is not None
    assert structured.impact_summary.failover_protected is None
    assert structured.impact_summary.potential is None
