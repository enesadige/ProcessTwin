"""Render validated execution facts without changing QueryRun persistence."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from apps.core.exceptions import ProcessTwinError
from apps.orchestration.models import QueryRun, QueryRunStatus
from apps.orchestration.providers.base import LLMProvider
from apps.orchestration.providers.gemini import GeminiLLMProviderError
from apps.orchestration.providers.registry import get_llm_descriptor
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

RESPONSE_PROMPT_VERSION = "grounded-semantic-statement-selection-tr-v4"
_NARRATIVE_KEYS = frozenset(
    {
        "summary",
        "root_cause",
        "impact_status",
        "impact_numbers",
        "failover_status",
        "decision",
        "references",
        "citations",
        "uncertainty",
    }
)
_IMPACT_STATUSES = frozenset(
    {"potential_scope", "verified_impacted", "verified_no_impact", "insufficient_evidence"}
)
_FAILOVER_PRIMARY_DOWN_BACKUP_HEALTHY = "primary_down_backup_healthy"
_UNCERTAINTY_STATEMENT = "Yeterli doğrulanmış bilgi yok."
_RELATION_TYPES = frozenset({"cause", "contrast", "consequence", "uncertainty", "evidence_gap"})


class ResponseBuilderError(ProcessTwinError):
    """Stable response-builder precondition failure."""


class StatementSelectionError(ValueError):
    """Safe structured diagnostics for a rejected closed-world selection."""

    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})


class ResponseGenerationMode(StrEnum):
    DETERMINISTIC = "deterministic"
    LLM_ASSISTED = "llm_assisted"
    DETERMINISTIC_FALLBACK = "deterministic_fallback"


class ResponseCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference_code: str
    reference_kind: str
    version: int | None = None
    section: str | None = None


class StructuredVerifiedResult(BaseModel):
    """Safe, already-validated facts exposed to the application client."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "structured-verified-result.v1"
    causal_summary: CausalSummary | None = None
    impact_summary: ImpactSummary | None = None
    rule_summary: RuleSummary | None = None
    compensation_summary: CompensationSummary | None = None
    retrieval_sources: list[RetrievalSource] = Field(default_factory=list)


class ValidatedNaturalLanguageResponse(BaseModel):
    """In-memory user response with deterministic facts and safe metadata."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "validated-natural-language-response.v1"
    language: str = "tr"
    response_text: str
    generation_mode: ResponseGenerationMode
    citations: list[ResponseCitation] = Field(default_factory=list)
    provenance: list[ProvenanceEntry] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    provider: str | None = None
    model: str | None = None
    prompt_version: str = RESPONSE_PROMPT_VERSION
    validation_status: ValidationStatus
    semantic_concepts: list[str] = Field(default_factory=list)
    grounded_relationships: list[dict[str, str]] = Field(default_factory=list)
    statement_selection_audit: dict[str, Any] = Field(default_factory=dict)
    structured_result: StructuredVerifiedResult | None = None


class ValidatedResponseBuilder:
    """Build an immutable response from an already completed validated QueryRun."""

    def build(
        self,
        query_run: QueryRun,
        *,
        mode: ResponseGenerationMode | str = ResponseGenerationMode.DETERMINISTIC,
        provider_name: str | None = None,
        provider: LLMProvider | None = None,
    ) -> ValidatedNaturalLanguageResponse:
        requested_mode = ResponseGenerationMode(mode)
        result = self._validated_result(query_run)
        deterministic_text = self._render_deterministic(result)
        citations = self._citations(result)
        warnings = list(result.warnings)
        response = ValidatedNaturalLanguageResponse(
            response_text=deterministic_text,
            generation_mode=ResponseGenerationMode.DETERMINISTIC,
            citations=citations,
            provenance=sorted(result.provenance, key=lambda item: item.call_id),
            warnings=sorted(set(warnings)),
            validation_status=result.validation_status,
            structured_result=self._public_structured_result(result),
        )
        if requested_mode == ResponseGenerationMode.DETERMINISTIC:
            return response

        active_provider = provider
        if active_provider is None:
            descriptor = get_llm_descriptor(provider_name)
            active_provider = descriptor.create_provider()
        response.provider = active_provider.provider_name
        response.model = active_provider.model_name
        contract = self._statement_contract(
            result,
            original_query=query_run.original_query,
            structured_query=query_run.structured_query,
        )
        try:
            narrative, retry, selection = self._safe_statement_selection(active_provider, contract)
            response.semantic_concepts = selection["concepts"]
            response.grounded_relationships = selection["relationships"]
            response.statement_selection_audit = selection["audit"]
            if retry.get("retry_count", 0):
                response.warnings = [
                    *response.warnings,
                    f"llm_statement_selection_retry_count:{retry['retry_count']}",
                    f"llm_statement_selection_retry_delay_ms:{retry['total_retry_delay_ms']}",
                ]
        except Exception as exc:
            response.generation_mode = ResponseGenerationMode.DETERMINISTIC_FALLBACK
            response.warnings = sorted(
                set(
                    [
                        *response.warnings,
                        "llm_narrative_fallback",
                        "llm_statement_selection_attempted",
                        "llm_statement_selection_failure:"
                        + self._statement_selection_failure_code(exc),
                    ]
                )
            )
            details = getattr(exc, "details", {})
            response.statement_selection_audit = {
                "status": "rejected",
                "provider": active_provider.provider_name,
                "model": active_provider.model_name,
                "failure_code": self._statement_selection_failure_code(exc),
                **details,
            }
            if isinstance(details, Mapping):
                for key in (
                    "allowed_statement_ids",
                    "allowed_statement_concepts",
                    "allowed_relationship_endpoints",
                    "returned_keys",
                    "returned_statement_ids",
                    "returned_concepts",
                    "normalized_concepts",
                    "relationship_references",
                ):
                    value = details.get(key)
                    if isinstance(value, (list, dict)):
                        response.warnings.append(
                            "llm_statement_selection_"
                            f"{key}:{json.dumps(value, ensure_ascii=True, sort_keys=True)}"
                        )
                for key in ("attempt_count", "retry_count", "total_retry_delay_ms"):
                    if isinstance(details.get(key), int):
                        response.warnings.append(f"llm_statement_selection_{key}:{details[key]}")
                response.warnings = sorted(set(response.warnings))
            return response

        response.response_text = narrative
        response.generation_mode = ResponseGenerationMode.LLM_ASSISTED
        return response

    @staticmethod
    def _public_structured_result(
        result: ValidatedExecutionResult,
    ) -> StructuredVerifiedResult:
        """Expose validated summaries without raw calls, prompts, or internal IDs."""
        return StructuredVerifiedResult(
            causal_summary=result.causal_summary,
            impact_summary=result.impact_summary,
            rule_summary=result.rule_summary,
            compensation_summary=result.compensation_summary,
            retrieval_sources=result.retrieval_sources,
        )

    @staticmethod
    def _statement_selection_failure_code(exc: Exception) -> str:
        """Return a bounded diagnostic category without exposing provider payloads."""
        if isinstance(exc, StatementSelectionError):
            return exc.code
        if isinstance(exc, GeminiLLMProviderError):
            return f"provider_call_failed_{exc.code}"
        message = str(exc)
        if "not JSON" in message:
            return "statement_selection_parse_failed"
        if "unknown or duplicate" in message:
            return "unknown_or_duplicate_statement_id"
        if "semantic decomposition is invalid" in message:
            return "semantic_concept_validation_failed"
        if "statement relationships are invalid" in message:
            return "relationship_validation_failed"
        if "statement selection IDs are invalid" in message:
            return "statement_selection_ids_invalid"
        if "critical statement missing" in message:
            return "statement_selection_missing_id"
        if "schema is invalid" in message:
            return "statement_selection_schema_invalid"
        if "provider response is invalid" in message:
            return "provider_response_invalid"
        if isinstance(exc, KeyError):
            return "statement_selection_missing_contract_key"
        if isinstance(exc, (TypeError, IndexError)):
            return "statement_selection_normalization_failed"
        if "selection" in message:
            return "statement_selection_validation_failed"
        return "statement_selection_failed"

    @staticmethod
    def _validated_result(query_run: QueryRun) -> ValidatedExecutionResult:
        if QueryRunStatus(query_run.status) != QueryRunStatus.COMPLETED:
            raise ResponseBuilderError(
                message="A completed QueryRun is required for response rendering.",
                code="response_requires_completed_query_run",
            )
        if not isinstance(query_run.final_result, Mapping):
            raise ResponseBuilderError(
                message="QueryRun final result is unavailable.",
                code="response_final_result_unavailable",
            )
        try:
            result = ValidatedExecutionResult.model_validate(query_run.final_result)
        except (TypeError, ValueError) as exc:
            raise ResponseBuilderError(
                message="QueryRun final result is invalid.", code="response_final_result_invalid"
            ) from exc
        if result.validation_status != ValidationStatus.VALID:
            raise ResponseBuilderError(
                message="Only valid execution results can be rendered.",
                code="response_requires_validated_result",
            )
        if result.snapshot_identifier != query_run.data_snapshot.snapshot_key:
            raise ResponseBuilderError(
                message="QueryRun result snapshot does not match.",
                code="response_snapshot_mismatch",
            )
        return result

    @staticmethod
    def _render_deterministic(result: ValidatedExecutionResult) -> str:
        sections = ["Genel sonuç"]
        if result.causal_summary:
            reference = result.causal_summary.causal_event_code or result.causal_summary.outage_code
            if reference:
                sections.append(f"Doğrulanan operasyon referansı: {reference}.")

        causal = result.causal_summary
        if causal and any(
            (
                causal.root_resource_reference,
                causal.root_cause_reason_codes,
                causal.propagation_summary,
            )
        ):
            sections.extend(["", "Kök neden"])
            if causal.root_resource_reference:
                resource = causal.root_resource_type or "kaynak"
                sections.append(f"Kök kaynak: {resource} {causal.root_resource_reference}.")
            if (
                causal.root_cause_summary
                and causal.root_cause_summary != causal.root_resource_reference
            ):
                sections.append(f"Doğrulanmış ana kök neden: {causal.root_cause_summary}.")
            elif causal.root_cause_summary == causal.root_resource_reference:
                sections.append(
                    "Kök kaynak doğrulanmış, ancak fiziksel kök neden gerekçesi "
                    "ayrıca doğrulanmadı."
                )
            if "root_cause_unverified" in causal.root_cause_reason_codes:
                sections.append(
                    "Kök neden kesin olarak doğrulanmadı; eksik kanıt nedeniyle "
                    "manuel inceleme gerekir."
                )
            if causal.root_alarm_types:
                sections.append("Kök neden alarmı: " + ", ".join(causal.root_alarm_types) + ".")
            if causal.dying_gasp_classification == "symptom":
                sections.append("Dying Gasp alarmı kök neden değil, belirtidir.")
            elif causal.dying_gasp_classification == "not_observed":
                sections.append("Dying Gasp için bu olayda doğrulanmış alarm kaydı yok.")
            if causal.device_not_active_classification == "symptom":
                sections.append("Device Not Active alarmı kök neden değil, belirtidir.")
            if causal.device_not_active_classification == "not_observed":
                sections.append("Device Not Active için bu olayda doğrulanmış alarm kaydı yok.")
            if causal.full_outage is not None:
                sections.append(
                    f"Tam hizmet kesintisi: {'Evet' if causal.full_outage else 'Hayır'}."
                )
            if causal.primary_status or causal.backup_status:
                sections.append(
                    "Bağlantı durumu: ana bağlantı "
                    f"{causal.primary_status or 'doğrulanmadı'}, yedek bağlantı "
                    f"{causal.backup_status or 'doğrulanmadı'}."
                )
            if causal.root_cause_reason_codes:
                sections.append(
                    "Gerekçe kodları: " + ", ".join(causal.root_cause_reason_codes) + "."
                )
            if causal.propagation_summary:
                sections.append(f"Yayılım özeti: {causal.propagation_summary}")

        impact = result.impact_summary
        if impact:
            sections.extend(["", "Müşteri etkisi"])
            if impact.outage_count is not None:
                sections.append(f"Kesinti sayısı: {impact.outage_count}.")
            if impact.potential is not None:
                if impact.affected_subscription_count is not None:
                    sections.append(f"Potansiyel kapsam: {impact.potential} abonelik.")
                else:
                    sections.append(f"Potansiyel etki: {impact.potential} bağlantı.")
            if impact.verified_impacted is not None:
                if (
                    impact.affected_subscription_count is not None
                    and impact.affected_customer_count is not None
                ):
                    sections.append(
                        "Doğrulanmış etki: "
                        f"{impact.affected_subscription_count} abonelik / "
                        f"{impact.affected_customer_count} müşteri."
                    )
                else:
                    sections.append(f"Doğrulanmış etki: {impact.verified_impacted} bağlantı.")
            if impact.verified_no_impact is not None:
                sections.append(f"Etkilenmediği doğrulanan: {impact.verified_no_impact} bağlantı.")
            if impact.insufficient_evidence is not None:
                sections.append(f"Kanıtı yetersiz: {impact.insufficient_evidence} bağlantı.")
            if impact.failover_protected is not None:
                suffix = (
                    " tam hizmet kesintisi değildir."
                    if causal and causal.full_outage is False
                    else "."
                )
                sections.append(
                    f"Failover ile korunan: {impact.failover_protected} bağlantı{suffix}"
                )
                if causal and causal.full_outage is True and impact.failover_protected > 0:
                    sections.append(
                        "Failover bazı bağlantıları korusa da bu olayda tam hizmet kesintisini "
                        "önleyemedi."
                    )
            if impact.failover_path_diversity_counts.get("shared_risk", 0) > 0:
                sections.append(
                    "Ana ve yedek yollar ortak arıza alanı taşıyor; bağımsızlık doğrulanamadı "
                    "ve manuel inceleme gerekir."
                )
            if impact.assessment_record_count == 0 and "customer_impact_assessment" in (
                impact.missing_evidence_categories
            ):
                sections.append(
                    "Gerçek müşteri etkisi kesin doğrulanmadı; CustomerImpactAssessment kanıtı yok."
                )
                if impact.failover_protected is None:
                    sections.append(
                        "Failover ile korunan bağlantı sayısı için doğrulanmış sayısal kayıt yok."
                    )

        compensation = result.compensation_summary
        # A compensation evaluation is the authoritative rule/evidence source
        # for that decision. Retrieval/rule-tool candidates must not be rendered
        # as if they were the applied rule for the same answer.
        rule = None if compensation and compensation.rule_versions else result.rule_summary
        if rule and any(
            (rule.rule_codes, rule.rule_versions, rule.eligibility_status, rule.evidence_references)
        ):
            sections.extend(["", "Kural ve kanıt"])
            if rule.rule_codes:
                sections.append("Kural: " + ", ".join(rule.rule_codes) + ".")
            if rule.rule_versions:
                sections.append("Kural sürümü: " + ", ".join(rule.rule_versions) + ".")
            if rule.eligibility_status:
                sections.append(f"Uygunluk durumu: {rule.eligibility_status}.")
            if rule.evidence_references:
                sections.append("Kanıt referansı: " + ", ".join(rule.evidence_references) + ".")

        if compensation:
            sections.extend(["", "Telafi sonucu"])
            if compensation.status:
                sections.append(f"Telafi durumu: {compensation.status}.")
            if compensation.considered is not None:
                sections.append(f"Değerlendirilen doğrulanmış etki: {compensation.considered}.")
            if compensation.eligible is not None:
                sections.append(f"Uygun kayıt: {compensation.eligible}.")
            if compensation.ineligible_pending is not None:
                sections.append(f"Uygun olmayan/bekleyen kayıt: {compensation.ineligible_pending}.")
                if compensation.ineligible_pending > 0:
                    sections.append("Karar: eksik doğrulama nedeniyle manuel inceleme bekleniyor.")
            if compensation.total_amount and compensation.currency:
                sections.append(
                    f"Toplam telafi tutarı: {compensation.total_amount} {compensation.currency}."
                )
            if compensation.rule_versions:
                sections.append(
                    "Doğrulanmış RuleVersion: "
                    + ", ".join(sorted(compensation.rule_versions))
                    + "."
                )
            if compensation.evidence_references:
                sections.append(
                    "Doğrulanmış DecisionEvidence: "
                    + ", ".join(compensation.evidence_references)
                    + "."
                )
            if compensation.scope == "verified_impact":
                sections.append(
                    "Tazminat kararı yalnız doğrulanmış etki üzerinden değerlendirilmiştir."
                )

        if result.retrieval_sources:
            sections.extend(["", "Kaynaklar"])
            sections.append("Doküman sonuçları karar değil, kaynak/citation niteliğindedir.")
            for source in result.retrieval_sources:
                version = f" v{source.version}" if source.version is not None else ""
                section = f" / {source.section}" if source.section else ""
                sections.append(f"{source.source_code}{version}{section}")

        if result.warnings:
            sections.extend(["", "Uyarılar"])
            for warning in sorted(set(result.warnings)):
                sections.append(f"İsteğe bağlı kanıt uyarısı: {warning}.")
        return "\n".join(sections)

    @staticmethod
    def _citations(result: ValidatedExecutionResult) -> list[ResponseCitation]:
        citations: dict[tuple[str, str, int | None, str | None], ResponseCitation] = {}

        def add(
            code: str | None, kind: str, *, version: int | None = None, section: str | None = None
        ):
            if code:
                citations[(code, kind, version, section)] = ResponseCitation(
                    reference_code=code,
                    reference_kind=kind,
                    version=version,
                    section=section,
                )

        if result.causal_summary:
            add(result.causal_summary.causal_event_code, "causal_event")
            add(result.causal_summary.outage_code, "outage")
        if result.rule_summary:
            for code in result.rule_summary.rule_codes:
                add(code, "rule")
            for version in result.rule_summary.rule_versions:
                add(version, "rule_version")
            for reference in result.rule_summary.evidence_references:
                add(reference, "decision_evidence")
        if result.compensation_summary:
            for reference in result.compensation_summary.evidence_references:
                add(reference, "decision_evidence")
        for source in result.retrieval_sources:
            add(
                source.source_code,
                "retrieval_source",
                version=source.version,
                section=source.section,
            )
        return sorted(
            citations.values(), key=lambda item: (item.reference_kind, item.reference_code)
        )

    @staticmethod
    def _statement_contract(
        result: ValidatedExecutionResult,
        *,
        original_query: str = "",
        structured_query: Mapping[str, Any] | None = None,
    ) -> tuple[str, dict[str, object]]:
        """Build a closed-world contract for decomposition, relations and ordering."""
        statements: dict[str, str] = {}

        def add(text: str) -> None:
            statements[f"S{len(statements) + 1}"] = text

        causal = result.causal_summary
        if causal:
            if (
                causal.root_cause_summary
                and causal.root_cause_summary != causal.root_resource_reference
            ):
                add(f"Doğrulanmış ana kök neden: {causal.root_cause_summary}.")
            elif causal.root_cause_summary == causal.root_resource_reference:
                add(
                    "Kök kaynak doğrulanmış, ancak fiziksel kök neden gerekçesi "
                    "ayrıca doğrulanmadı."
                )
            if "root_cause_unverified" in causal.root_cause_reason_codes:
                add(
                    "Kök neden kesin olarak doğrulanmadı; eksik kanıt nedeniyle "
                    "manuel inceleme gerekir."
                )
            if causal.root_resource_reference:
                resource_type = causal.root_resource_type or "kaynak"
                add(f"Doğrulanmış kök kaynak: {resource_type} {causal.root_resource_reference}.")
            if causal.root_alarm_types:
                add("Kök neden alarmı: " + ", ".join(causal.root_alarm_types) + ".")
            if causal.dying_gasp_classification == "symptom":
                add("Dying Gasp alarmı kök neden değil, belirtidir.")
            elif causal.dying_gasp_classification == "not_observed":
                add("Dying Gasp için bu olayda doğrulanmış alarm kaydı yok.")
            if causal.device_not_active_classification == "symptom":
                add("Device Not Active alarmı kök neden değil, belirtidir.")
            elif causal.device_not_active_classification == "not_observed":
                add("Device Not Active için bu olayda doğrulanmış alarm kaydı yok.")
            if causal.full_outage is not None:
                full_outage = "Evet" if causal.full_outage else "Hayır"
                add(f"Tam hizmet kesintisi: {full_outage}.")
            if causal.primary_status or causal.backup_status:
                add(
                    "Bağlantı durumu: ana bağlantı "
                    f"{causal.primary_status or 'doğrulanmadı'}, yedek bağlantı "
                    f"{causal.backup_status or 'doğrulanmadı'}."
                )
            if causal.root_cause_reason_codes:
                add("Kök neden gerekçesi: " + ", ".join(causal.root_cause_reason_codes) + ".")
                if "shared_failure_domain" in causal.root_cause_reason_codes:
                    add(
                        "Ana ve yedek yollar aynı arıza alanını paylaştığı için "
                        "bağımsızlık doğrulanamadı; manuel inceleme gerekir."
                    )
        impact = result.impact_summary
        if impact:
            if impact.outage_count is not None:
                add(f"Kesinti sayısı: {impact.outage_count}.")
            if (
                impact.affected_subscription_count is not None
                and impact.affected_customer_count is not None
            ):
                add(f"Potansiyel kapsam: {impact.potential} abonelik.")
                add(
                    "Doğrulanmış etki: "
                    f"{impact.affected_subscription_count} abonelik / "
                    f"{impact.affected_customer_count} müşteri."
                )
            else:
                for label, value in (
                    ("Potansiyel kapsam", impact.potential),
                    ("Doğrulanmış etki", impact.verified_impacted),
                    ("Doğrulanmış etkisizlik", impact.verified_no_impact),
                    ("Kanıt yetersiz", impact.insufficient_evidence),
                ):
                    if value is not None:
                        add(f"{label}: {value} bağlantı.")
            if impact.failover_protected is not None:
                suffix = (
                    " tam hizmet kesintisi değildir."
                    if causal and causal.full_outage is False
                    else "."
                )
                add(f"Failover ile korunan: {impact.failover_protected} bağlantı{suffix}")
                if causal and causal.full_outage is True and impact.failover_protected > 0:
                    add(
                        "Failover bazı bağlantıları korusa da bu olayda tam hizmet kesintisini "
                        "önleyemedi."
                    )
            if impact.failover_path_diversity_counts.get("shared_risk", 0) > 0:
                add(
                    "Ana ve yedek yollar ortak arıza alanı taşıyor; bağımsızlık doğrulanamadı "
                    "ve manuel inceleme gerekir."
                )
            if impact.assessment_record_count == 0 and "customer_impact_assessment" in (
                impact.missing_evidence_categories
            ):
                add(
                    "Gerçek müşteri etkisi kesin doğrulanmadı; CustomerImpactAssessment kanıtı yok."
                )
                if impact.failover_protected is None:
                    add("Failover ile korunan bağlantı sayısı için doğrulanmış sayısal kayıt yok.")
        compensation = result.compensation_summary
        rule = None if compensation and compensation.rule_versions else result.rule_summary
        if rule and rule.rule_versions:
            add("Doğrulanmış kural sürümü: " + ", ".join(rule.rule_versions) + ".")
        if rule and rule.evidence_references:
            add("Doğrulanmış karar kanıtı: " + ", ".join(rule.evidence_references) + ".")
        if compensation and compensation.status:
            add(f"Telafi durumu: {compensation.status}.")
        if compensation and compensation.considered is not None:
            add(f"Telafi değerlendirmesi yapılan: {compensation.considered} kayıt.")
        if compensation and compensation.eligible is not None:
            add(f"Tazminata uygun: {compensation.eligible} kayıt.")
        if compensation and compensation.ineligible_pending is not None:
            add(f"Uygun olmayan veya bekleyen: {compensation.ineligible_pending} kayıt.")
            if compensation.ineligible_pending > 0:
                add("Karar: eksik doğrulama nedeniyle manuel inceleme bekleniyor.")
        if compensation and compensation.rule_versions:
            add("Doğrulanmış RuleVersion: " + ", ".join(sorted(compensation.rule_versions)) + ".")
        if compensation and compensation.evidence_references:
            add(
                "Doğrulanmış DecisionEvidence: " + ", ".join(compensation.evidence_references) + "."
            )
        if compensation and compensation.scope == "verified_impact":
            add("Tazminat kararı yalnız doğrulanmış etki üzerinden değerlendirilmiştir.")
        if result.retrieval_sources:
            source_labels = []
            for source in result.retrieval_sources:
                version = f" v{source.version}" if source.version is not None else ""
                section = f" / {source.section}" if source.section else ""
                source_labels.append(f"{source.source_code}{version}{section}")
            add("Doğrulanmış kaynaklar: " + "; ".join(source_labels) + ".")
        if not statements:
            add(_UNCERTAINTY_STATEMENT)
        statement_concepts = {
            statement_id: ValidatedResponseBuilder._statement_concepts(text)
            for statement_id, text in statements.items()
        }
        schema = {
            "type": "object",
            "properties": {
                "headline_id": {"type": ["string", "null"], "enum": ["H1", None]},
                "selected_statement_ids": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(statements)},
                    "uniqueItems": True,
                    "maxItems": len(statements),
                },
                "relationships": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "enum": sorted(_RELATION_TYPES)},
                            "from_statement_id": {"type": "string", "enum": list(statements)},
                            "to_statement_id": {"type": "string", "enum": list(statements)},
                        },
                        "required": ["type", "from_statement_id", "to_statement_id"],
                        "additionalProperties": False,
                    },
                    "maxItems": 8,
                },
            },
            "required": ["headline_id", "selected_statement_ids", "relationships"],
            "additionalProperties": False,
        }
        safe_query = original_query
        for value in (structured_query or {}).values():
            if isinstance(value, str) and value.strip():
                safe_query = safe_query.replace(value, "[doğrulanmış-ankor]")
        if isinstance(structured_query, Mapping):
            location = structured_query.get("location")
            if isinstance(location, Mapping):
                for value in location.values():
                    if isinstance(value, str) and value.strip():
                        safe_query = safe_query.replace(value, "[doğrulanmış-konum]")
        safe_query = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "[redakte-adres]", safe_query)
        safe_query = re.sub(
            r"\b(?:CUST|SUB|AGG|OLT|BNG|DSLAM|AN|CE|INC|OUT)-[A-Z0-9İÇŞĞÜÖ_-]+\b",
            "[redakte-referans]",
            safe_query,
            flags=re.IGNORECASE,
        )
        prompt = (
            "Yalnız native schema nesnesini üret. Cümle yazma, cümleleri değiştirme, "
            "yeni ID veya gerçek üretme. concepts alanı üretme; kavramlar backend tarafından "
            "seçilen statement ID'lerinden türetilecektir. "
            "relationships yalnız verilen statement ID'leri arasında kurulabilir. "
            "Kullanıcı sorusundaki doğrulanmış ankorlar redakte edilmiştir.\n"
            "USER_SEMANTIC_QUERY="
            + safe_query
            + "\nHEADLINES={'H1': 'Kesinti değerlendirmesi'}\nSTATEMENTS="
            + json.dumps(statements, ensure_ascii=False)
            + "\nSTATEMENT_CONCEPTS="
            + json.dumps(statement_concepts, ensure_ascii=False)
        )
        return prompt, {
            "schema": schema,
            "statements": statements,
            "statement_concepts": statement_concepts,
        }

    @staticmethod
    def _statement_concepts(text: str) -> list[str]:
        concepts: list[str] = []
        checks = (
            ("outage_classification", ("kesinti", "Tam hizmet")),
            ("potential_scope", ("Potansiyel kapsam",)),
            ("verified_customer_impact", ("Doğrulanmış etki", "müşteri etkisi")),
            ("verified_no_impact", ("etkilenmediği",)),
            ("insufficient_evidence", ("kanıt", "doğrulanmadı", "manuel inceleme")),
            ("primary_backup_state", ("ana bağlantı", "yedek bağlantı")),
            ("failover_explanation", ("Failover", "yedek yollar")),
            ("compensation_status", ("Telafi", "Tazminat")),
            ("compensation_reason", ("kararı", "doğrulanmış etki üzerinden")),
            ("root_cause", ("kök neden", "Kök kaynak")),
            ("evidence", ("Kaynaklar", "DecisionEvidence", "RuleVersion")),
        )
        lowered = text.casefold()
        for concept, needles in checks:
            if any(needle.casefold() in lowered for needle in needles):
                concepts.append(concept)
        return concepts or ["explanation_requested"]

    @classmethod
    def _safe_statement_selection(
        cls, provider: LLMProvider, contract: tuple[str, dict[str, object]]
    ) -> tuple[str, Mapping[str, Any], Mapping[str, Any]]:
        prompt, data = contract
        response = provider.generate(request={"contents": prompt, "format_schema": data["schema"]})
        if not isinstance(response, Mapping) or response.get("provider") != provider.provider_name:
            raise ValueError("provider response is invalid")
        if response.get("model") != provider.model_name or not isinstance(
            response.get("content"), str
        ):
            raise ValueError("provider response is invalid")
        retry = response.get("retry", {})
        if not isinstance(retry, Mapping):
            raise ValueError("provider response is invalid")
        try:
            selection = json.loads(response["content"])
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("native schema response is not JSON") from exc
        statements = data["statements"]
        if not isinstance(statements, Mapping):
            raise ValueError("statement contract is invalid")
        statement_concepts = data.get("statement_concepts", {})
        if not isinstance(statement_concepts, Mapping) or any(
            statement_id not in statements for statement_id in statement_concepts
        ):
            raise StatementSelectionError(
                "statement_contract_inconsistent",
                "statement contract references an unavailable statement",
                details={
                    "allowed_statement_ids": sorted(str(key) for key in statements),
                    "allowed_statement_concepts": sorted(
                        str(concept)
                        for concepts in statement_concepts.values()
                        if isinstance(concepts, list)
                        for concept in concepts
                    )
                    if isinstance(statement_concepts, Mapping)
                    else [],
                },
            )
        try:
            cls._validate_statement_selection(selection, statements, statement_concepts)
        except ValueError as exc:
            returned_ids = (
                selection.get("selected_statement_ids") if isinstance(selection, Mapping) else None
            )
            relationships = (
                selection.get("relationships") if isinstance(selection, Mapping) else None
            )
            details = {
                "allowed_statement_ids": sorted(str(key) for key in statements),
                "allowed_relationship_endpoints": sorted(str(key) for key in statements),
                "allowed_statement_concepts": sorted(
                    str(concept)
                    for concepts in statement_concepts.values()
                    if isinstance(concepts, list)
                    for concept in concepts
                ),
                "returned_keys": (
                    sorted(str(key) for key in selection)
                    if isinstance(selection, Mapping)
                    else []
                ),
                "returned_statement_ids": (
                    [str(value) for value in returned_ids]
                    if isinstance(returned_ids, list) else []
                ),
                "returned_concepts": [],
                "normalized_concepts": [],
                "relationship_references": (
                    [
                        {
                            "from": str(item.get("from_statement_id")),
                            "to": str(item.get("to_statement_id")),
                            "type": str(item.get("type")),
                        }
                        for item in relationships
                        if isinstance(item, Mapping)
                    ]
                    if isinstance(relationships, list) else []
                ),
            }
            code = cls._statement_selection_failure_code(exc)
            raise StatementSelectionError(code, str(exc), details=details) from exc
        selected = selection["selected_statement_ids"]
        derived_concepts: list[str] = []
        for statement_id in selected:
            for concept in statement_concepts.get(statement_id, []):
                if concept not in derived_concepts:
                    derived_concepts.append(concept)
        if not derived_concepts:
            derived_concepts = ["explanation_requested"]
        audit = {
            "status": "accepted",
            "provider": provider.provider_name,
            "model": provider.model_name,
            "allowed_statement_ids": sorted(str(key) for key in statements),
            "selected_statement_ids": [str(value) for value in selected],
            "derived_concepts": derived_concepts,
            "relationship_references": selection["relationships"],
            "validation_status": "valid",
        }
        selection = {**selection, "concepts": derived_concepts, "audit": audit}
        headline = "Kesinti değerlendirmesi" if selection["headline_id"] == "H1" else None
        lines = [headline] if headline else []
        concepts = selection["concepts"]
        concept_rank = {concept: index for index, concept in enumerate(concepts)}
        selected_position = {statement_id: index for index, statement_id in enumerate(selected)}
        ordered_selected = sorted(
            selected,
            key=lambda statement_id: (
                min(
                    (
                        concept_rank.get(concept, len(concepts))
                        for concept in statement_concepts.get(statement_id, [])
                    ),
                    default=len(concepts),
                ),
                selected_position[statement_id],
            ),
        )
        # Omitted critical IDs are appended deterministically.
        ordered_ids = [
            *ordered_selected,
            *(item for item in statements if item not in selected),
        ]
        lines.extend(statements[statement_id] for statement_id in ordered_ids)
        relation_labels = {
            "cause": "Nedensel ilişki",
            "contrast": "Karşıtlık ilişkisi",
            "consequence": "Sonuç ilişkisi",
            "uncertainty": "Belirsizlik ilişkisi",
            "evidence_gap": "Kanıt boşluğu ilişkisi",
        }
        for relation in selection["relationships"]:
            lines.append(
                f"{relation_labels[relation['type']]}: "
                f"{statements[relation['from_statement_id']]} -> "
                f"{statements[relation['to_statement_id']]}"
            )
        return "\n".join(lines), retry, selection

    @staticmethod
    def _validate_statement_selection(
        selection: object,
        statements: Mapping[str, str],
        statement_concepts: Mapping[str, object] | None = None,
    ) -> None:
        if not isinstance(selection, Mapping) or not {
            "headline_id", "selected_statement_ids", "relationships"
        }.issubset(selection) or set(selection) - {
            "headline_id", "concepts", "selected_statement_ids", "relationships"
        }:
            raise ValueError("statement selection schema is invalid")
        if selection["headline_id"] not in {"H1", None}:
            raise ValueError("unknown headline ID")
        selected = selection["selected_statement_ids"]
        if not isinstance(selected, list) or not all(isinstance(item, str) for item in selected):
            raise ValueError("statement selection IDs are invalid")
        if len(selected) != len(set(selected)) or any(item not in statements for item in selected):
            raise ValueError("unknown or duplicate statement ID")
        relationships = selection["relationships"]
        if not isinstance(relationships, list) or len(relationships) > 8:
            raise ValueError("statement relationships are invalid")
        for relation in relationships:
            if not isinstance(relation, Mapping) or set(relation) != {
                "type", "from_statement_id", "to_statement_id"
            }:
                raise ValueError("statement relationships are invalid")
            if (
                relation["type"] not in _RELATION_TYPES
                or relation["from_statement_id"] not in statements
                or relation["to_statement_id"] not in statements
                or relation["from_statement_id"] == relation["to_statement_id"]
            ):
                raise ValueError("statement relationships are invalid")

    @staticmethod
    def _narrative_contract(result: ValidatedExecutionResult) -> str:
        """Return the closed-world prompt and the only values an LLM may select.

        This is deliberately a JSON contract instead of a prose fact sheet: an
        LLM response is never rendered verbatim, and each selected value is
        checked against these per-run allowlists before deterministic rendering.
        """
        causal = result.causal_summary
        impact = result.impact_summary
        rule = result.rule_summary
        compensation = result.compensation_summary
        numbers = []
        impact_statuses = []
        impact_numbers_by_status: dict[str, list[int]] = {}
        if impact:
            for status, value in (
                ("potential_scope", impact.potential),
                ("verified_impacted", impact.verified_impacted),
                ("verified_no_impact", impact.verified_no_impact),
                ("insufficient_evidence", impact.insufficient_evidence),
            ):
                if value is not None:
                    impact_statuses.append(status)
                    numbers.append(value)
                    impact_numbers_by_status[status] = [value]
            if impact.failover_protected is not None:
                numbers.append(impact.failover_protected)
        references = []
        if causal:
            references.extend(
                value for value in (causal.causal_event_code, causal.outage_code) if value
            )
        if rule:
            references.extend([*rule.rule_codes, *rule.rule_versions, *rule.evidence_references])
        if compensation:
            references.extend(compensation.evidence_references)
        citations = []
        for source in result.retrieval_sources:
            version = source.version if source.version is not None else ""
            citations.append(f"{source.source_code}@{version}:{source.section or ''}")
        root_causes = (
            []
            if causal is None
            else [
                *causal.root_cause_reason_codes,
                *([causal.propagation_summary] if causal.propagation_summary else []),
            ]
        )
        decisions = []
        if rule and rule.eligibility_status:
            decisions.append(rule.eligibility_status)
        if compensation and compensation.status:
            decisions.append(compensation.status)
        failover_statuses = (
            [_FAILOVER_PRIMARY_DOWN_BACKUP_HEALTHY]
            if impact and impact.failover_protected is not None and impact.failover_protected > 0
            else []
        )
        contract = {
            "prompt_version": RESPONSE_PROMPT_VERSION,
            "ALLOWED_NUMBERS": sorted(set(numbers)),
            "ALLOWED_PUBLIC_REFERENCES": sorted(set(references)),
            "ALLOWED_DECISIONS": sorted(set(decisions)),
            "ALLOWED_ROOT_CAUSES": sorted(set(root_causes)),
            "ALLOWED_IMPACT_STATUSES": sorted(set(impact_statuses)),
            "ALLOWED_IMPACT_NUMBERS_BY_STATUS": impact_numbers_by_status,
            "ALLOWED_FAILOVER_STATUSES": failover_statuses,
            "ALLOWED_CITATIONS": sorted(set(citations)),
            "ALLOWED_UNCERTAINTY_STATEMENTS": [_UNCERTAINTY_STATEMENT],
        }
        instructions = (
            "Yalnız aşağıdaki JSON nesnesini üret; Markdown veya başka metin üretme. "
            "Anahtarlar tam olarak summary, root_cause, impact_status, impact_numbers, "
            "failover_status, decision, references, citations, uncertainty olmalıdır. "
            "Her string değer ilgili ALLOWED listesinden karakter karakter kopyalanmalı; "
            "bilinmeyen alan için null, liste için [] kullan. Yeni sayı, doküman, standart, "
            "politika, kayıt, kaynak, karar veya durum üretme. 'Kayıtlara göre', 'ilgili "
            "standart kapsamında' ve 'sistem verilerine göre' gibi dayanak cümleleri yasaktır. "
            "Potential scope verified impact değildir. primary_down_backup_healthy tam kesinti, "
            "tüm müşteriler etkilendi veya hizmet tamamen kesildi anlamına gelmez. Kaynak listesi "
            "boşsa references ve citations [] olmalıdır. Hatalı örnek: "
            '{"impact_status":"verified_impacted"} (allowlist yalnız potential_scope iken). '
            'Olumlu örnek: {"summary":null,"root_cause":null,'
            '"impact_status":null,"impact_numbers":[],"failover_status":null,"decision":null,'
            '"references":[],"citations":[],"uncertainty":null}.\nCLOSED_WORLD_ALLOWLIST='
        )
        return instructions + json.dumps(contract, ensure_ascii=False, sort_keys=True)

    @classmethod
    def _safe_narrative(cls, provider: LLMProvider, contract: str) -> str:
        response = provider.generate(request={"contents": contract})
        if not isinstance(response, Mapping):
            raise ValueError("provider response is invalid")
        content = response.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("provider response content is invalid")
        if (
            response.get("provider") != provider.provider_name
            or response.get("model") != provider.model_name
        ):
            raise ValueError("provider metadata is invalid")
        if not isinstance(response.get("finish_reason"), str):
            raise ValueError("provider finish reason is invalid")
        usage = response.get("usage")
        if not isinstance(usage, Mapping) or not all(
            isinstance(usage.get(field), int) and not isinstance(usage.get(field), bool)
            for field in ("input_tokens", "output_tokens", "total_tokens")
        ):
            raise ValueError("provider usage is invalid")
        try:
            allowlists = json.loads(contract.rsplit("CLOSED_WORLD_ALLOWLIST=", 1)[1])
            narrative = json.loads(content)
        except (IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("provider narrative is not valid structured JSON") from exc
        cls._validate_structured_narrative(narrative, allowlists)
        return cls._render_structured_narrative(narrative)

    @staticmethod
    def _validate_structured_narrative(narrative: object, allowlists: Mapping[str, object]) -> None:
        if not isinstance(narrative, Mapping) or set(narrative) != _NARRATIVE_KEYS:
            raise ValueError("provider narrative schema is invalid")
        for field, allowlist in (
            ("root_cause", "ALLOWED_ROOT_CAUSES"),
            ("impact_status", "ALLOWED_IMPACT_STATUSES"),
            ("failover_status", "ALLOWED_FAILOVER_STATUSES"),
            ("decision", "ALLOWED_DECISIONS"),
            ("uncertainty", "ALLOWED_UNCERTAINTY_STATEMENTS"),
        ):
            value = narrative[field]
            if value is not None and (
                not isinstance(value, str) or value not in allowlists[allowlist]
            ):
                raise ValueError(f"provider narrative has unsupported {field}")
        for field, allowlist in (
            ("references", "ALLOWED_PUBLIC_REFERENCES"),
            ("citations", "ALLOWED_CITATIONS"),
        ):
            value = narrative[field]
            if not isinstance(value, list) or not all(
                isinstance(item, str) and item in allowlists[allowlist] for item in value
            ):
                raise ValueError(f"provider narrative has unsupported {field}")
        numbers = narrative["impact_numbers"]
        if not isinstance(numbers, list) or not all(
            isinstance(item, int)
            and not isinstance(item, bool)
            and item in allowlists["ALLOWED_NUMBERS"]
            for item in numbers
        ):
            raise ValueError("provider narrative has unsupported impact number")
        if narrative["summary"] is not None:
            raise ValueError("provider narrative summary must be null")
        # Canonical status values are never transformed into a different impact class.
        status = narrative["impact_status"]
        if status is not None and status not in _IMPACT_STATUSES:
            raise ValueError("provider narrative has invalid impact status")
        if status is None and numbers:
            raise ValueError("provider narrative has unclassified impact number")
        if status is not None and any(
            number not in allowlists["ALLOWED_IMPACT_NUMBERS_BY_STATUS"].get(status, [])
            for number in numbers
        ):
            raise ValueError("provider narrative transforms an impact status")

    @staticmethod
    def _render_structured_narrative(narrative: Mapping[str, object]) -> str:
        """Render only fixed Turkish labels plus validated allowlist values."""
        lines = []
        if narrative["root_cause"]:
            lines.append(f"Kök neden: {narrative['root_cause']}.")
        if narrative["impact_status"]:
            labels = {
                "potential_scope": "Potansiyel kapsam",
                "verified_impacted": "Doğrulanmış etki",
                "verified_no_impact": "Doğrulanmış etkisizlik",
                "insufficient_evidence": "Kanıt yetersiz",
            }
            values = ", ".join(str(value) for value in narrative["impact_numbers"])
            lines.append(
                f"{labels[narrative['impact_status']]}: {values}."
                if values
                else f"{labels[narrative['impact_status']]}."
            )
        if narrative["failover_status"]:
            lines.append(
                "Failover durumu: birincil yol aşağıda, yedek yol sağlıklı/aktif; "
                "tam kesinti değildir."
            )
        if narrative["decision"]:
            lines.append(f"Doğrulanmış karar durumu: {narrative['decision']}.")
        if narrative["uncertainty"]:
            lines.append(str(narrative["uncertainty"]))
        return "\n".join(lines) or _UNCERTAINTY_STATEMENT
