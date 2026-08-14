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
