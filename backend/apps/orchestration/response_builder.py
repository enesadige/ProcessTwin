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
from apps.orchestration.providers.ollama import OllamaLLMProviderError
from apps.orchestration.providers.registry import get_llm_descriptor
from apps.orchestration.result_merge import (
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
_NARRATIVE_SYNTHESIS_KEYS = frozenset({"sentences"})
_NARRATIVE_SENTENCE_KEYS = frozenset({"text", "statement_ids", "relationship_ids"})
_NARRATIVE_DEBUG_MARKERS = ("->", "Nedensel ilişki:", "Sonuç ilişkisi:", "Belirsizlik ilişkisi:")
_NARRATIVE_ROLE_PREFIX_RE = re.compile(
    r"^\s*(?:details|evidence|summary|root_cause|impact|eligibility|correlation)\s*:\s*",
    re.IGNORECASE,
)
_NARRATIVE_INTERNAL_REASON_RE = re.compile(
    r"\b(?:root_cause_unverified|same_resource|temporal_propagation|evidence_gap)\b",
    re.IGNORECASE,
)
_NARRATIVE_INTERNAL_REASON_SEQUENCE_RE = re.compile(
    r"\b(?:root_cause_unverified|same_resource|temporal_propagation|evidence_gap)\b"
    r"(?:\s*,?\s*(?:ve\s*)?\b(?:root_cause_unverified|same_resource|temporal_propagation|evidence_gap)\b)+",
    re.IGNORECASE,
)
_NARRATIVE_DOMAIN_INTERPRETATION_RE = re.compile(
    r"\b(?:ortak kaynak|ortak kaynaklı|ortak arıza alanı|ortak arıza|aynı kaynak|"
    r"zamansal yayılım|bağımsızlık|bağımsız yollar|"
    r"shared[- ](?:source|failure|risk)|common[- ](?:cause|source|failure))\b",
    re.IGNORECASE,
)
_NARRATIVE_FACT_TOKEN_RE = re.compile(
    r"(?:\b\d+(?:[.,]\d+)?\b|\b[A-Z][A-Z0-9_:-]{3,}\b|\b[A-Z][A-Z0-9]+(?:-[A-Z0-9]+)+\b)"
)
_NARRATIVE_NUMBER_RE = re.compile(
    r"(?<![A-Za-zÇĞİÖŞÜçğıöşü0-9_-])\d+(?:[.,]\d+)?(?![A-Za-zÇĞİÖŞÜçğıöşü0-9_-])"
)

_TOPOLOGY_RELATION_NARRATIVE = {
    "same_resource": "Kaynaklar aynı doğrulanmış kaynak üzerinde yer alıyor.",
    "direct_parent_child": (
        "Kaynaklar arasında doğrulanmış doğrudan üst/alt topoloji bağlantısı bulunuyor."
    ),
    "same_bng_branch": "Kaynaklar aynı doğrulanmış upstream BNG dalında yer alıyor.",
    "shared_failure_domain": "Kaynaklar aynı doğrulanmış arıza alanında yer alıyor.",
}


def _topology_relation_narrative(relation: str | None) -> str | None:
    """Translate backend topology enums before they enter user-facing facts."""
    return _TOPOLOGY_RELATION_NARRATIVE.get(relation or "")


def _format_correlation_duration(seconds: int) -> str:
    """Render a verified correlation delta without exposing transport units by default."""
    if seconds < 60:
        return f"{seconds} saniye"
    minutes, remainder = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours and minutes:
        return f"{hours} saat {minutes} dakika"
    if hours:
        return f"{hours} saat"
    if remainder:
        return f"{minutes} dakika {remainder} saniye"
    return f"{minutes} dakika"


class ResponseBuilderError(ProcessTwinError):
    """Stable response-builder precondition failure."""


class StatementSelectionError(ValueError):
    """Safe structured diagnostics for a rejected closed-world selection."""

    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})


class NarrativeSynthesisError(ValueError):
    """Safe rejection for grounded natural-language synthesis."""

    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})


class NarrativeGroundingValidationError(ValueError):
    """Safe sentence-level grounding rejection details."""

    def __init__(
        self,
        rule: str,
        message: str,
        *,
        sentence_index: int = -1,
        sentence: Mapping[str, Any] | None = None,
    ):
        sentence = sentence or {}
        self.rule = rule
        self.details = {
            "exact_validation_rule": rule,
            "rejected_sentence_index": sentence_index,
            "rejected_sentence_text": sentence.get("text")
            if isinstance(sentence.get("text"), str)
            else "",
            "rejected_statement_ids": [
                str(item) for item in sentence.get("statement_ids", []) if isinstance(item, str)
            ],
            "rejected_relationship_ids": [
                str(item) for item in sentence.get("relationship_ids", []) if isinstance(item, str)
            ],
            "safe_failure_detail": message,
        }
        super().__init__(message)


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
    cross_incident_correlation_summary: CrossIncidentCorrelationSummary | None = None
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
    narrative_synthesis_audit: dict[str, Any] = Field(default_factory=dict)
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
        verified_anchors = self._verified_narrative_anchors(result, query_run.structured_query)
        narrative = deterministic_text
        try:
            selection = self._deterministic_answer_plan(contract[1], query_run.structured_query)
            response.semantic_concepts = selection["concepts"]
            response.grounded_relationships = selection["relationships"]
            response.statement_selection_audit = selection["audit"]
            if getattr(active_provider, "supports_grounded_narrative", False):
                narrative, synthesis_audit = self._safe_grounded_narrative(
                    active_provider,
                    original_query=query_run.original_query,
                    selected_statements={
                        statement_id: contract[1]["statements"][statement_id]
                        for statement_id in selection["selected_statement_ids"]
                    },
                    statement_concepts={
                        statement_id: contract[1]
                        .get("statement_concepts", {})
                        .get(statement_id, [])
                        for statement_id in selection["selected_statement_ids"]
                    },
                    relationships=selection["relationships"],
                    verified_anchors=verified_anchors,
                    requested_outputs=selection["audit"]["selection_reason"]["requested_outputs"],
                )
                narrative, coverage_fill_count = self._ensure_requested_narrative_coverage(
                    narrative,
                    original_query=query_run.original_query,
                    selected_statements={
                        statement_id: contract[1]["statements"][statement_id]
                        for statement_id in selection["selected_statement_ids"]
                    },
                    statement_concepts={
                        statement_id: contract[1]
                        .get("statement_concepts", {})
                        .get(statement_id, [])
                        for statement_id in selection["selected_statement_ids"]
                    },
                )
                synthesis_audit["deterministic_fill_count"] = coverage_fill_count
                response.narrative_synthesis_audit = synthesis_audit
            else:
                response.generation_mode = ResponseGenerationMode.DETERMINISTIC_FALLBACK
                response.warnings = sorted(
                    {
                        *response.warnings,
                        "llm_narrative_fallback",
                        "llm_narrative_synthesis_not_supported",
                    }
                )
                response.narrative_synthesis_audit = {
                    "status": "skipped",
                    "reason": "provider_does_not_advertise_grounded_narrative",
                }
        except Exception as exc:
            response.generation_mode = ResponseGenerationMode.DETERMINISTIC_FALLBACK
            synthesis_failure = isinstance(exc, NarrativeSynthesisError)
            failure_code = f"narrative_synthesis_{exc.code}" if synthesis_failure else str(exc)
            failure_warnings = [
                *response.warnings,
                "llm_narrative_fallback",
            ]
            if synthesis_failure:
                failure_warnings.extend(
                    [
                        "llm_narrative_synthesis_attempted",
                        "llm_narrative_synthesis_failure:" + failure_code,
                    ]
                )
            response.warnings = sorted(set(failure_warnings))
            details = getattr(exc, "details", {})
            if synthesis_failure:
                response.narrative_synthesis_audit = {
                    "status": "rejected",
                    "provider": active_provider.provider_name,
                    "model": active_provider.model_name,
                    "failure_code": failure_code,
                    **details,
                }
            else:
                response.statement_selection_audit = {
                    "status": "rejected",
                    "mode": "deterministic",
                    "failure_code": failure_code,
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

    @classmethod
    def _ensure_requested_narrative_coverage(
        cls,
        narrative: str,
        *,
        original_query: str,
        selected_statements: Mapping[str, str],
        statement_concepts: Mapping[str, list[str]],
    ) -> tuple[str, int]:
        """Add only explicitly requested verified facts omitted by the provider."""
        query = original_query.casefold()
        requested_roles: set[str] = set()
        if any(term in query for term in ("kaç abonelik", "kac abonelik", "abonelik")):
            requested_roles.add("verified_subscription_impact")
        if any(term in query for term in ("kaç müşteri", "kac musteri", "müşteri", "musteri")):
            requested_roles.add("verified_customer_impact")
        if any(term in query for term in ("tazminat", "telafi", "tutar", "amount")):
            requested_roles.add("compensation_amount")
        if any(term in query for term in ("uygulanan kural", "ruleversion", "rule version")):
            requested_roles.add("rule_version")
        if any(
            term in query for term in ("decisionevidence", "decision evidence", "kararın dayandığı")
        ):
            requested_roles.add("decision_evidence")
        if any(term in query for term in ("tam hizmet", "tam kesinti", "full outage")):
            requested_roles.add("outage_classification")
        if any(term in query for term in ("kök kaynak", "kok kaynak", "root resource")):
            requested_roles.add("root_resource")
        if any(
            term in query for term in ("detaylı analiz", "detayli analiz", "analiz et", "analyze")
        ):
            requested_roles.add("root_resource")
        if "failover" in query and any(
            term in query for term in ("neden", "başarılı olmadı", "basarili olmadi")
        ):
            requested_roles.add("failover_explanation")
            requested_roles.add("physical_root_cause")
        if any(
            term in query
            for term in (
                "zaman farkı",
                "zaman farki",
                "zaman",
                "zamansal kanıt",
                "zamansal kanit",
                "ne kadar süre",
                "ne kadar sure",
                "ne kadar sonra",
                "ne kadar önce",
                "ne kadar once",
            )
        ):
            requested_roles.add("correlation_temporal_evidence")

        text = narrative
        fill_count = 0
        for role in requested_roles:
            candidates = [
                (statement_id, statement_text)
                for statement_id, statement_text in selected_statements.items()
                if role in set(statement_concepts.get(statement_id, []))
            ]
            if not candidates:
                continue
            supported_tokens = {
                token.casefold()
                for _, statement_text in candidates
                for token in _NARRATIVE_FACT_TOKEN_RE.findall(statement_text)
            }
            combined_candidate_text = " ".join(
                statement_text for _, statement_text in candidates
            ).casefold()
            lower_text = text.casefold()
            role_present = (
                (role == "outage_classification" and "tam hizmet kesintisi" in lower_text)
                or (
                    role in {"verified_customer_impact", "verified_subscription_impact"}
                    and any(token in lower_text for token in supported_tokens)
                )
                or (
                    role == "root_resource"
                    and any(token in lower_text for token in supported_tokens)
                )
                or (
                    role == "failover_explanation"
                    and "failover" in lower_text
                    and any(token in lower_text for token in supported_tokens)
                )
                or (
                    role == "physical_root_cause"
                    and ("kök neden" in lower_text or "fiziksel" in lower_text)
                )
                or (
                    role in {"compensation_amount", "rule_version", "decision_evidence"}
                    and any(token in lower_text for token in supported_tokens)
                )
                or (
                    role == "correlation_temporal_evidence"
                    and any(token in lower_text for token in supported_tokens)
                )
                or (combined_candidate_text and combined_candidate_text in lower_text)
            )
            if supported_tokens and not role_present:
                appended = _NARRATIVE_ROLE_PREFIX_RE.sub("", candidates[0][1], count=1).strip()
                appended = _NARRATIVE_INTERNAL_REASON_RE.sub(
                    "doğrulanmamış teknik gerekçe", appended
                ).strip()
                text = f"{text.rstrip()} {appended}"
                fill_count += 1
        return text, fill_count

    @staticmethod
    def _deterministic_answer_plan(
        data: Mapping[str, Any], structured_query: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        """Select verified statements and relationships without an LLM call."""
        statements = data.get("statements", {})
        concepts = data.get("statement_concepts", {})
        relationships = data.get("validated_relationships", [])
        if not isinstance(statements, Mapping) or not isinstance(concepts, Mapping):
            raise ResponseBuilderError("answer plan contract is invalid")

        requested = set()
        dimensions = set()
        intent = ""
        if isinstance(structured_query, Mapping):
            requested = {str(value) for value in structured_query.get("requested_outputs", [])}
            dimensions = {str(value) for value in structured_query.get("semantic_dimensions", [])}
            intent = str(structured_query.get("intent", ""))

        all_roles = {
            "alarm_correlation",
            "outage_classification",
            "root_cause",
            "primary_backup_state",
            "potential_scope",
            "verified_customer_impact",
            "verified_no_impact",
            "insufficient_evidence",
            "failover_explanation",
            "compensation_status",
            "compensation_reason",
            "evidence",
            "verified_subscription_impact",
            "compensation_amount",
            "rule_version",
            "decision_evidence",
            "physical_root_cause",
            "root_resource",
        }
        relevant_roles = set()
        if not requested and not dimensions:
            relevant_roles = all_roles
        if (
            requested & {"correlation"}
            or dimensions & {"alarm_correlation"}
            or intent == "alarm_correlation"
        ):
            relevant_roles |= {"alarm_correlation"}
        if requested & {"impact", "summary", "details"} or dimensions & {
            "verified_customer_impact",
            "verified_subscription_impact",
            "potential_scope",
        }:
            relevant_roles |= {
                "outage_classification",
                "potential_scope",
                "verified_customer_impact",
                "verified_no_impact",
                "insufficient_evidence",
            }
        if requested & {"root_cause"} or dimensions & {
            "root_resource",
            "physical_root_cause",
            "outage_classification",
        }:
            relevant_roles |= {"root_cause", "outage_classification"}
        if dimensions & {"failover_status", "failover_protection"}:
            relevant_roles |= {
                "primary_backup_state",
                "failover_explanation",
                "insufficient_evidence",
            }
        if (
            requested & {"eligibility", "compensation_amount", "evidence"}
            or dimensions
            & {
                "compensation_result",
                "compensation_reason",
                "rule_version",
                "decision_evidence",
                "rag_evidence",
                "source_version_section",
                "evidence_gap",
            }
            or intent in {"compensation_evaluation", "rule_evidence", "rule_document_retrieval"}
        ):
            relevant_roles |= {
                "compensation_status",
                "compensation_reason",
                "compensation_amount",
                "rule_version",
                "decision_evidence",
                "evidence",
                "insufficient_evidence",
            }
        if not relevant_roles:
            relevant_roles = all_roles

        selected_ids = [
            statement_id
            for statement_id, statement_text in statements.items()
            if relevant_roles.intersection(concepts.get(statement_id, []))
            or not concepts.get(statement_id)
        ]
        if not selected_ids:
            selected_ids = list(statements)
        selected_set = set(selected_ids)
        selected_relationships = [
            relation
            for relation in relationships
            if isinstance(relation, Mapping)
            and relation.get("from_statement_id") in selected_set
            and relation.get("to_statement_id") in selected_set
        ]
        derived_concepts = []
        for statement_id in selected_ids:
            for concept in concepts.get(statement_id, []):
                if concept not in derived_concepts:
                    derived_concepts.append(concept)
        audit = {
            "status": "completed",
            "mode": "deterministic",
            "answer_plan_mode": "deterministic",
            "selected_statement_ids": selected_ids,
            "selected_relationship_ids": [
                f"R{index}" for index, _ in enumerate(selected_relationships, 1)
            ],
            "effective_statement_ids": selected_ids,
            "selection_reason": {
                "intent": intent,
                "requested_outputs": sorted(requested),
                "semantic_dimensions": sorted(dimensions),
                "semantic_roles": sorted(relevant_roles),
            },
            "derived_concepts": derived_concepts or ["explanation_requested"],
            "relationship_references": selected_relationships,
            "validation_status": "valid",
        }
        return {
            "selected_statement_ids": selected_ids,
            "relationships": selected_relationships,
            "concepts": derived_concepts or ["explanation_requested"],
            "audit": audit,
        }

    @staticmethod
    def _public_structured_result(
        result: ValidatedExecutionResult,
    ) -> StructuredVerifiedResult:
        """Expose validated summaries without raw calls, prompts, or internal IDs."""
        return StructuredVerifiedResult(
            causal_summary=result.causal_summary,
            cross_incident_correlation_summary=result.cross_incident_correlation_summary,
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

        correlation = result.cross_incident_correlation_summary
        if correlation:
            if correlation.candidate_event_code:
                sections.append(
                    "Karşılaştırılan olaylar: "
                    f"{correlation.anchor_event_code} ve {correlation.candidate_event_code}."
                )
            if correlation.correlation_status == "verified_relation":
                sections.append("Olaylar arasında doğrulanmış operasyonel ilişki bulunuyor.")
            elif correlation.correlation_status == "insufficient_evidence":
                sections.append("Olaylar arasında ilişkiyi doğrulamak için mevcut kanıt yetersiz.")
            else:
                sections.append("Olaylar arasında doğrulanmış operasyonel ilişki bulunmuyor.")
            if correlation.time_difference_seconds is not None:
                sections.append(
                    "Olaylar arasındaki zaman farkı: "
                    f"{_format_correlation_duration(correlation.time_difference_seconds)}."
                )
            topology_narrative = _topology_relation_narrative(correlation.topology_relation)
            if topology_narrative:
                sections.append(topology_narrative)
            if correlation.root_symptom_status == "not_verified":
                sections.append("Olaylar arasında kök/belirti yönü kesin olarak doğrulanmadı.")
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
        if result.cross_incident_correlation_summary:
            add(result.cross_incident_correlation_summary.anchor_event_code, "causal_event")
            add(result.cross_incident_correlation_summary.candidate_event_code, "causal_event")
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
        correlation = result.cross_incident_correlation_summary
        if correlation:
            if correlation.candidate_event_code:
                add(
                    "Karşılaştırılan olaylar: "
                    f"{correlation.anchor_event_code} ve {correlation.candidate_event_code}."
                )
            if correlation.correlation_status == "verified_relation":
                add("Olaylar arasında doğrulanmış operasyonel ilişki bulunuyor.")
            elif correlation.correlation_status == "insufficient_evidence":
                add("Olaylar arasında ilişkiyi doğrulamak için mevcut kanıt yetersiz.")
            else:
                add("Olaylar arasında doğrulanmış operasyonel ilişki bulunmuyor.")
            if correlation.time_difference_seconds is not None:
                add(
                    "Olaylar arasındaki zaman farkı: "
                    f"{_format_correlation_duration(correlation.time_difference_seconds)}."
                )
            topology_narrative = _topology_relation_narrative(correlation.topology_relation)
            if topology_narrative:
                add(topology_narrative)
            if correlation.root_symptom_status == "not_verified":
                add("Olaylar arasında kök/belirti yönü kesin olarak doğrulanmadı.")
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
        if compensation and compensation.total_amount and compensation.currency:
            add(
                f"Doğrulanmış tazminat tutarı: {compensation.total_amount} {compensation.currency}."
            )
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
        validated_relationships = ValidatedResponseBuilder._backend_relationship_candidates(
            statements
        )
        prompt = (
            "Yalnız native schema nesnesini üret. Cümle yazma, cümleleri değiştirme, "
            "yeni ID veya gerçek üretme. concepts alanı üretme; kavramlar backend tarafından "
            "seçilen statement ID'lerinden türetilecektir. "
            "relationships yalnız aşağıdaki backend-doğrulanmış adaylardan seçilebilir; yeni "
            "ilişki üretme. Aday listesi boşsa relationships boş bırakılmalıdır. "
            "Kullanıcı sorusundaki doğrulanmış ankorlar redakte edilmiştir.\n"
            "USER_SEMANTIC_QUERY="
            + safe_query
            + "\nHEADLINES={'H1': 'Kesinti değerlendirmesi'}\nSTATEMENTS="
            + json.dumps(statements, ensure_ascii=False)
            + "\nSTATEMENT_CONCEPTS="
            + json.dumps(statement_concepts, ensure_ascii=False)
            + "\nBACKEND_VALIDATED_RELATIONSHIPS="
            + json.dumps(validated_relationships, ensure_ascii=False, sort_keys=True)
        )
        return prompt, {
            "schema": schema,
            "statements": statements,
            "statement_concepts": statement_concepts,
            "validated_relationships": validated_relationships,
        }

    @staticmethod
    def _verified_narrative_anchors(
        result: ValidatedExecutionResult,
        structured_query: Mapping[str, Any] | None,
    ) -> dict[str, str]:
        """Return only deterministic anchors resolved for this QueryRun."""
        anchors: dict[str, str] = {}

        def add(value: object, source: str) -> None:
            if isinstance(value, str) and value.strip():
                anchors[value.strip()] = source

        if isinstance(structured_query, Mapping):
            for field in (
                "causal_event_code",
                "comparison_causal_event_code",
                "incident_code",
                "outage_code",
                "device_code",
                "subscription_reference",
            ):
                add(structured_query.get(field), "verified_anchor")
        causal = result.causal_summary
        if causal:
            add(causal.causal_event_code, "verified_anchor")
            add(causal.outage_code, "verified_anchor")
            add(causal.root_resource_reference, "verified_anchor")
            for alarm in causal.root_alarm_types:
                add(alarm, "verified_anchor")
            for alarm in causal.symptom_alarm_types:
                add(alarm, "verified_anchor")
        return anchors

    @staticmethod
    def _backend_relationship_candidates(
        statements: Mapping[str, str],
    ) -> list[dict[str, str]]:
        """Build only explainable, backend-owned relationships for this result set."""
        candidates: list[dict[str, str]] = []

        def add(
            relationship_type: str,
            source: str,
            target: str,
            provenance: str,
            semantics: str,
        ) -> None:
            candidates.append(
                {
                    "type": relationship_type,
                    "from_statement_id": source,
                    "to_statement_id": target,
                    "provenance": provenance,
                    "narrative_semantics": semantics,
                }
            )

        ids = list(statements)
        for source in ids:
            source_text = statements[source].casefold()
            for target in ids:
                if source == target:
                    continue
                target_text = statements[target].casefold()
                if (
                    "down" in source_text
                    and "active" in source_text
                    and "tam hizmet kesintisi: hayır" in target_text
                ):
                    add(
                        "consequence",
                        source,
                        target,
                        "deterministic_outage_classification",
                        "causal",
                    )
                    add(
                        "contrast",
                        source,
                        target,
                        "deterministic_outage_classification",
                        "contrast",
                    )
                if "potansiyel kapsam" in source_text and "doğrulanmış etki" in target_text:
                    add("consequence", source, target, "deterministic_impact_scope", "causal")
                if (
                    "müşteri etkisi" in source_text
                    and "kesin doğrulanmadı" in source_text
                    and "telafi durumu" in target_text
                ):
                    add(
                        "consequence",
                        source,
                        target,
                        "deterministic_compensation_pending",
                        "causal",
                    )
                if (
                    "müşteri etkisi" in source_text
                    and "kesin doğrulanmadı" in source_text
                    and "tazminat kararı" in target_text
                ):
                    add(
                        "consequence",
                        source,
                        target,
                        "deterministic_compensation_evaluation",
                        "causal",
                    )
        return candidates

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
            ("compensation_amount", ("tazminat tutarı", "telafi tutarı")),
            ("compensation_reason", ("kararı", "doğrulanmış etki üzerinden")),
            ("root_cause", ("kök neden", "Kök kaynak")),
            (
                "alarm_correlation",
                (
                    "Karşılaştırılan olaylar",
                    "operasyonel ilişki",
                    "topoloji ilişkisi",
                    "zaman farkı",
                ),
            ),
            ("correlation_temporal_evidence", ("Zaman farkı:",)),
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
        statements = data.get("statements")
        if not isinstance(statements, Mapping):
            raise StatementSelectionError(
                "statement_contract_invalid",
                "statement contract is invalid",
                details={"allowed_statement_ids": []},
            )
        statement_concepts = data.get("statement_concepts", {})
        allowed_ids = sorted(str(key) for key in statements)
        allowed_concepts = (
            sorted(
                str(concept)
                for concepts in statement_concepts.values()
                if isinstance(concepts, list)
                for concept in concepts
            )
            if isinstance(statement_concepts, Mapping)
            else []
        )
        base_details = {
            "allowed_statement_ids": allowed_ids,
            "allowed_statement_concepts": allowed_concepts,
            "allowed_relationship_endpoints": allowed_ids,
            "returned_keys": [],
            "returned_statement_ids": [],
            "returned_concepts": [],
            "normalized_concepts": [],
            "relationship_references": [],
        }
        try:
            response = provider.generate(
                request={"contents": prompt, "format_schema": data["schema"]}
            )
        except Exception as exc:
            provider_code = getattr(exc, "code", None)
            safe_detail = type(exc).__name__
            if isinstance(provider_code, str) and provider_code:
                safe_detail = f"{safe_detail}:{provider_code}"
            raise StatementSelectionError(
                "provider_request_failed",
                "provider request failed",
                details={
                    **base_details,
                    "provider_error_code": provider_code,
                    "failure_detail": safe_detail,
                },
            ) from exc
        if not isinstance(response, Mapping) or response.get("provider") != provider.provider_name:
            raise StatementSelectionError(
                "provider_response_invalid",
                "provider response is invalid",
                details={**base_details, "failure_detail": "provider_metadata_invalid"},
            )
        if response.get("model") != provider.model_name or not isinstance(
            response.get("content"), str
        ):
            raise StatementSelectionError(
                "provider_response_invalid",
                "provider response is invalid",
                details={**base_details, "failure_detail": "provider_content_invalid"},
            )
        retry = response.get("retry", {})
        if not isinstance(retry, Mapping):
            raise StatementSelectionError(
                "provider_response_invalid",
                "provider response is invalid",
                details={**base_details, "failure_detail": "retry_metadata_invalid"},
            )
        try:
            selection = json.loads(response["content"])
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise StatementSelectionError(
                "structured_output_invalid_json",
                "native schema response is not JSON",
                details={**base_details, "failure_detail": "invalid_json"},
            ) from exc
        if not isinstance(statement_concepts, Mapping) or any(
            statement_id not in statements for statement_id in statement_concepts
        ):
            raise StatementSelectionError(
                "statement_contract_inconsistent",
                "statement contract references an unavailable statement",
                details={
                    **base_details,
                    "failure_detail": "statement_concepts_reference_unavailable_id",
                },
            )
        try:
            cls._validate_statement_selection(
                selection,
                statements,
                statement_concepts,
                data.get("validated_relationships", []),
            )
        except ValueError as exc:
            returned_ids = (
                selection.get("selected_statement_ids") if isinstance(selection, Mapping) else None
            )
            relationships = (
                selection.get("relationships") if isinstance(selection, Mapping) else None
            )
            details = {
                **base_details,
                "returned_keys": (
                    sorted(str(key) for key in selection) if isinstance(selection, Mapping) else []
                ),
                "returned_statement_ids": (
                    [str(value) for value in returned_ids] if isinstance(returned_ids, list) else []
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
                    if isinstance(relationships, list)
                    else []
                ),
                "failure_detail": str(exc),
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
        candidate_map = {
            (
                item["type"],
                item["from_statement_id"],
                item["to_statement_id"],
            ): item
            for item in data.get("validated_relationships", [])
            if isinstance(item, Mapping)
        }
        selected_relationships = [
            candidate_map[(item["type"], item["from_statement_id"], item["to_statement_id"])]
            for item in selection["relationships"]
        ]
        selection = {**selection, "relationships": selected_relationships}
        audit = {
            "status": "accepted",
            "provider": provider.provider_name,
            "model": provider.model_name,
            "allowed_statement_ids": sorted(str(key) for key in statements),
            "selected_statement_ids": [str(value) for value in selected],
            "derived_concepts": derived_concepts,
            "relationship_references": selected_relationships,
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
        validated_relationships: list[dict[str, str]] | None = None,
    ) -> None:
        if (
            not isinstance(selection, Mapping)
            or not {"headline_id", "selected_statement_ids", "relationships"}.issubset(selection)
            or set(selection)
            - {"headline_id", "concepts", "selected_statement_ids", "relationships"}
        ):
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
        candidate_keys = {
            (item.get("type"), item.get("from_statement_id"), item.get("to_statement_id"))
            for item in (validated_relationships or [])
            if isinstance(item, Mapping)
        }
        for relation in relationships:
            if not isinstance(relation, Mapping) or set(relation) != {
                "type",
                "from_statement_id",
                "to_statement_id",
            }:
                raise ValueError("statement relationships are invalid")
            if (
                relation["type"] not in _RELATION_TYPES
                or relation["from_statement_id"] not in statements
                or relation["to_statement_id"] not in statements
                or relation["from_statement_id"] == relation["to_statement_id"]
                or (
                    validated_relationships is not None
                    and (
                        relation["type"],
                        relation["from_statement_id"],
                        relation["to_statement_id"],
                    )
                    not in candidate_keys
                )
            ):
                raise ValueError("statement relationships are invalid")

    @classmethod
    def _safe_grounded_narrative(
        cls,
        provider: LLMProvider,
        *,
        original_query: str,
        selected_statements: Mapping[str, str],
        relationships: list[dict[str, str]],
        verified_anchors: Mapping[str, str] | None = None,
        requested_outputs: list[str] | None = None,
        statement_concepts: Mapping[str, list[str]] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        relationship_map = {
            f"R{index}": relationship
            for index, relationship in enumerate(
                (
                    relationship
                    for relationship in relationships
                    if relationship.get("from_statement_id") in selected_statements
                    and relationship.get("to_statement_id") in selected_statements
                ),
                start=1,
            )
        }
        prompt = (
            "Doğrulanmış telecom gerçeklerini kullanarak doğal Türkçe paragraflar yaz. "
            "Yalnız aşağıdaki gerçeklerde bulunan sayı, kimlik, durum ve nedenleri kullan. "
            "Bilinmeyenleri sıfıra çevirme; bağımsız kanıt boşluklarını nedensel bağlama. "
            "4-8 kısa cümleyle tüm istenen noktaları kapsa. details:, evidence:, summary:, "
            "root_cause:, impact: veya eligibility: gibi iç rol etiketleriyle başlama. "
            "root_cause_unverified, same_resource, temporal_propagation veya evidence_gap "
            "gibi iç reason code'larını da gösterme; desteklenen anlamı doğal Türkçeyle ifade et. "
            "JSON, ID, madde imi veya debug ilişkisi üretme.\n"
            "Sorgunun aşağıdaki istenen çıktılarını ayrı ayrı yanıtla; mevcut bir "
            "doğrulanmış değer varsa atlama: REQUESTED_OUTPUTS="
            + json.dumps(requested_outputs or [], ensure_ascii=False)
            + "\n"
            "USER_QUERY="
            + original_query.strip()
            + "\nVERIFIED_FACTS="
            + json.dumps(selected_statements, ensure_ascii=False, sort_keys=True)
            + "\nVERIFIED_ANCHORS="
            + json.dumps(dict(verified_anchors or {}), ensure_ascii=False, sort_keys=True)
            + "\nVALID_RELATIONSHIPS="
            + json.dumps(relationship_map, ensure_ascii=False, sort_keys=True)
        )
        if provider.provider_name == "gemini":
            prompt += (
                "\nKök kaynak doğrulanmış, fiziksel kök neden doğrulanmamışsa yalnızca "
                "'kök kaynak X olarak doğrulanmıştır' de; X'in olaya neden olduğunu söyleme. "
                "Failover başarısızlığı doğrulanmış ancak fiziksel nedeni doğrulanmamışsa bunu "
                "'Failover başarısızlığı doğrulanmıştır; ancak başarısızlığın fiziksel nedeni "
                "mevcut kanıtlarla kesin olarak doğrulanmamıştır.' çizgisinde ifade et. "
                "Mevcut AnswerPlan'da açıkça desteklenmiyorsa path/source independence, "
                "shared failure domain veya ortak kaynak iddiası kurma."
            )
        request: dict[str, Any] = {"contents": prompt}
        if getattr(provider, "supports_request_unload", False):
            request["release_after"] = True
        try:
            response = provider.generate(request=request)
        except Exception as exc:
            provider_code = None
            if isinstance(exc, (OllamaLLMProviderError, GeminiLLMProviderError)):
                provider_code = exc.code
            safe_code = (
                f"provider_call_failed:{provider_code}"
                if isinstance(provider_code, str) and provider_code
                else "provider_call_failed"
            )
            raise NarrativeSynthesisError(
                safe_code,
                "narrative provider request failed",
                details={"failure_detail": type(exc).__name__},
            ) from exc
        if not isinstance(response, Mapping) or response.get("provider") != provider.provider_name:
            raise NarrativeSynthesisError(
                "provider_response_invalid", "provider response is invalid"
            )
        if response.get("model") != provider.model_name:
            raise NarrativeSynthesisError(
                "provider_response_invalid", "provider metadata is invalid"
            )
        content = response.get("content", "")
        narrative, removed_sentences = cls._free_text_narrative(
            content, selected_statements, relationship_map, verified_anchors, statement_concepts
        )
        if not narrative["sentences"]:
            removal_details = removed_sentences[0] if removed_sentences else {}
            raise NarrativeSynthesisError(
                "unsupported_narrative",
                "no grounded narrative sentence remained",
                details={
                    "removed_sentence_count": len(removed_sentences),
                    "removed_sentence_reasons": removed_sentences,
                    "deterministic_fill_count": 0,
                    "exact_validation_rule": removal_details.get("failure_code", ""),
                    "rejected_sentence_index": 0,
                    "rejected_sentence_text": removal_details.get("text", ""),
                    "safe_failure_detail": removal_details.get("safe_failure_detail", ""),
                },
            )
        try:
            cls._validate_grounded_narrative(
                narrative,
                selected_statements,
                relationships,
                verified_anchors=verified_anchors,
            )
        except NarrativeGroundingValidationError as exc:
            raise NarrativeSynthesisError(
                "grounding_validation_failed",
                str(exc),
                details={
                    "selected_statement_ids": sorted(selected_statements),
                    "narrative_support_references": cls._narrative_support_references(narrative),
                    **exc.details,
                },
            ) from exc
        except ValueError as exc:
            raise NarrativeSynthesisError(
                "grounding_validation_failed",
                str(exc),
                details={
                    "selected_statement_ids": sorted(selected_statements),
                    "narrative_support_references": cls._narrative_support_references(narrative),
                    "exact_validation_rule": "narrative_schema_invalid",
                    "rejected_sentence_index": -1,
                    "rejected_sentence_text": "",
                    "rejected_statement_ids": [],
                    "rejected_relationship_ids": [],
                    "safe_failure_detail": str(exc),
                },
            ) from exc
        audit = {
            "status": "accepted",
            "provider": provider.provider_name,
            "model": provider.model_name,
            "sentence_count": len(narrative["sentences"]),
            "narrative_support_references": cls._narrative_support_references(narrative),
            "narrative_sentence_support": cls._narrative_sentence_support(
                narrative, relationship_map, verified_anchors, selected_statements
            ),
            "verified_narrative_anchors": dict(verified_anchors or {}),
            "removed_sentence_count": len(removed_sentences),
            "removed_sentence_reasons": removed_sentences,
            "deterministic_fill_count": 0,
            "validation_status": "valid",
        }
        return cls._render_grounded_narrative(narrative), audit

    @classmethod
    def _free_text_narrative(
        cls,
        content: object,
        selected_statements: Mapping[str, str],
        relationship_map: Mapping[str, Mapping[str, str]],
        verified_anchors: Mapping[str, str] | None = None,
        statement_concepts: Mapping[str, list[str]] | None = None,
    ) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, str]]]:
        if not isinstance(content, str) or not content.strip():
            return {"sentences": []}, []
        sentences = re.split(r"(?<=[.!?])\s+|\n+", content.strip())
        result: list[dict[str, Any]] = []
        removed: list[dict[str, str]] = []
        for text in (part.strip() for part in sentences):
            if not text:
                continue
            text = cls._sanitize_narrative_text(text)
            if not text:
                continue
            if cls._contains_unsupported_domain_interpretation(
                text, selected_statements, relationship_map
            ):
                removed.append(
                    {
                        "text": text,
                        "reason": "unsupported domain interpretation",
                        "failure_code": "unsupported_domain_interpretation",
                        "safe_failure_detail": (
                            "current-query evidence does not support the domain interpretation"
                        ),
                    }
                )
                continue
            # The AnswerPlan is the closed-world support universe. A sentence
            # may paraphrase or combine facts without repeating canonical text.
            support = list(selected_statements)
            relationships = cls._sentence_relationships(
                text, support, selected_statements, relationship_map
            )
            candidate = {
                "text": text,
                "statement_ids": support,
                "relationship_ids": relationships,
            }
            try:
                cls._validate_grounded_narrative(
                    {"sentences": [candidate]},
                    selected_statements,
                    list(relationship_map.values()),
                    verified_anchors=verified_anchors,
                )
            except (ValueError, NarrativeGroundingValidationError) as exc:
                detail = {
                    "text": text,
                    "reason": str(exc),
                }
                if isinstance(exc, NarrativeGroundingValidationError):
                    detail.update(
                        {
                            "failure_code": exc.rule,
                            "safe_failure_detail": str(exc),
                        }
                    )
                removed.append(detail)
                continue
            result.append(candidate)
        return {"sentences": result}, removed

    @staticmethod
    def _sanitize_narrative_text(text: str) -> str:
        text = _NARRATIVE_ROLE_PREFIX_RE.sub("", text, count=1).strip()
        if _NARRATIVE_INTERNAL_REASON_RE.search(text):
            text = _NARRATIVE_INTERNAL_REASON_SEQUENCE_RE.sub("doğrulanmamış teknik gerekçe", text)
            text = _NARRATIVE_INTERNAL_REASON_RE.sub("", text)
            text = re.sub(r"\s*,\s*(?:ve\s*)?", " ", text)
            text = re.sub(r"\s{2,}", " ", text)
            text = text.replace("gerekçeleriyle", "mevcut kanıtlarla")
            text = text.replace("gerekçeleri", "mevcut kanıtlar")
        return text.strip(" ,")

    @staticmethod
    def _contains_unsupported_domain_interpretation(
        text: str,
        statements: Mapping[str, str],
        relationships: Mapping[str, Mapping[str, str]],
    ) -> bool:
        if not _NARRATIVE_DOMAIN_INTERPRETATION_RE.search(text):
            return False
        relationship_text = " ".join(
            json.dumps(value, ensure_ascii=False) for value in relationships.values()
        ).casefold()
        return not any(
            marker in relationship_text
            for marker in ("ortak kaynak", "ortak arıza", "bağımsız", "shared", "common")
        )

    @staticmethod
    def _sentence_support(text: str, statements: Mapping[str, str]) -> list[str]:
        # Kept as a small public helper for audit/tests. Support is intentionally
        # not inferred from lexical similarity; the deterministic AnswerPlan is
        # the authoritative support set for the whole narrative.
        return list(statements)

    @staticmethod
    def _sentence_relationships(
        text: str,
        support: list[str],
        statements: Mapping[str, str],
        relationships: Mapping[str, Mapping[str, str]],
    ) -> list[str]:
        lowered = text.casefold()
        causal = any(
            phrase in lowered
            for phrase in (
                "nedeniyle",
                "sebebiyle",
                "bu yüzden",
                "sonucunda",
                "dolayısıyla",
                "yol açtı",
                "tetikledi",
                "kaynaklandı",
                "olduğu için",
                "olmadığı için",
            )
        )
        if not causal:
            return []
        selected: list[str] = []
        for relationship_id, relationship in relationships.items():
            if relationship.get("narrative_semantics") != "causal":
                continue
            source = statements.get(relationship.get("from_statement_id"), "")
            target = statements.get(relationship.get("to_statement_id"), "")
            source_tokens = {
                token.casefold()
                for token in re.findall(r"[A-Za-zÇĞİÖŞÜçğıöşü][\wÇĞİÖŞÜçğıöşü-]{3,}", source)
                if len(token) >= 5
            }
            target_tokens = {
                token.casefold()
                for token in re.findall(r"[A-Za-zÇĞİÖŞÜçğıöşü][\wÇĞİÖŞÜçğıöşü-]{3,}", target)
                if len(token) >= 5
            }
            lowered = text.casefold()
            text_tokens = {
                token.casefold()
                for token in re.findall(r"[A-Za-zÇĞİÖŞÜçğıöşü][\wÇĞİÖŞÜçğıöşü-]{3,}", lowered)
            }
            if (
                source_tokens
                and target_tokens
                and (
                    any(
                        any(
                            candidate.startswith(token[:5]) or token.startswith(candidate[:5])
                            for candidate in text_tokens
                        )
                        for token in source_tokens
                    )
                    and any(
                        any(
                            candidate.startswith(token[:5]) or token.startswith(candidate[:5])
                            for candidate in text_tokens
                        )
                        for token in target_tokens
                    )
                )
            ):
                selected.append(relationship_id)
        return selected

    @staticmethod
    def _parse_tagged_narrative(content: object) -> dict[str, list[dict[str, Any]]]:
        if not isinstance(content, str) or not content.strip():
            raise ValueError("tagged narrative is empty")
        sentences: list[dict[str, Any]] = []
        pattern = re.compile(r"^\[S:([^|]+)\|R:([^\]]*)\]\s+(.+)$")
        lines = [line.strip() for line in content.strip().splitlines()]
        lines = [line for line in lines if line not in {"```", "```text", "```plaintext"}]
        for line in lines:
            line = re.sub(r"^(?:[-*]\s+|\d+[.)]\s+)", "", line)
            match = pattern.fullmatch(line)
            if not match:
                raise ValueError("tagged narrative line is invalid")
            statement_ids = [value.strip() for value in match.group(1).split(",")]
            relationship_ids = (
                []
                if not match.group(2).strip()
                else [value.strip() for value in match.group(2).split(",")]
            )
            if any(not re.fullmatch(r"S\d+", value) for value in statement_ids):
                raise ValueError("tagged narrative statement IDs are invalid")
            if any(not re.fullmatch(r"R\d+", value) for value in relationship_ids):
                raise ValueError("tagged narrative relationship IDs are invalid")
            sentences.append(
                {
                    "text": match.group(3).strip(),
                    "statement_ids": statement_ids,
                    "relationship_ids": relationship_ids,
                }
            )
        if not sentences or len(sentences) > 5:
            raise ValueError("tagged narrative sentence count is invalid")
        return {"sentences": sentences}

    @staticmethod
    def _narrative_support_references(narrative: object) -> list[str]:
        if not isinstance(narrative, Mapping) or not isinstance(narrative.get("sentences"), list):
            return []
        refs: list[str] = []
        for sentence in narrative["sentences"]:
            if isinstance(sentence, Mapping) and isinstance(sentence.get("statement_ids"), list):
                refs.extend(str(item) for item in sentence["statement_ids"])
        return list(dict.fromkeys(refs))

    @staticmethod
    def _narrative_sentence_support(
        narrative: object,
        relationship_map: Mapping[str, Mapping[str, str]] | None = None,
        verified_anchors: Mapping[str, str] | None = None,
        selected_statements: Mapping[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        if not isinstance(narrative, Mapping) or not isinstance(narrative.get("sentences"), list):
            return []
        support: list[dict[str, Any]] = []
        for sentence in narrative["sentences"]:
            if not isinstance(sentence, Mapping):
                continue
            explicit_ids = [str(item) for item in sentence.get("statement_ids", [])]
            relationship_ids = [str(item) for item in sentence.get("relationship_ids", [])]
            effective_ids = list(explicit_ids)
            for relationship_id in relationship_ids:
                relationship = (relationship_map or {}).get(relationship_id)
                if relationship:
                    for endpoint in (
                        relationship.get("from_statement_id"),
                        relationship.get("to_statement_id"),
                    ):
                        if endpoint and endpoint not in effective_ids:
                            effective_ids.append(endpoint)
            identifier_values = re.findall(
                r"\b[A-ZÇĞİÖŞÜ][A-ZÇĞİÖŞÜ0-9_-]{2,}\b",
                str(sentence.get("text", "")),
            )
            statement_text = " ".join(
                (selected_statements or {}).get(statement_id, "") for statement_id in effective_ids
            )
            supported_identifiers = set(
                re.findall(r"\b[A-ZÇĞİÖŞÜ][A-ZÇĞİÖŞÜ0-9_-]{2,}\b", statement_text)
            )
            support.append(
                {
                    "model_explicit_statement_ids": explicit_ids,
                    "backend_effective_statement_ids": effective_ids,
                    "relationship_ids": relationship_ids,
                    "identifier_validation_sources": {
                        value: (
                            "verified_anchorstatement_support"
                            if value in supported_identifiers
                            else "verified_anchor"
                        )
                        for value in identifier_values
                        if value in (supported_identifiers | set(verified_anchors or {}))
                    },
                }
            )
        return support

    @classmethod
    def _validate_grounded_narrative(
        cls,
        narrative: object,
        selected_statements: Mapping[str, str],
        relationships: list[dict[str, str]],
        *,
        verified_anchors: Mapping[str, str] | None = None,
    ) -> None:
        if not isinstance(narrative, Mapping) or set(narrative) != _NARRATIVE_SYNTHESIS_KEYS:
            raise ValueError("narrative schema is invalid")
        sentences = narrative["sentences"]
        if not isinstance(sentences, list) or not sentences or len(sentences) > 8:
            raise ValueError("narrative sentences are invalid")
        relationship_map = {
            f"R{index}": relationship
            for index, relationship in enumerate(
                (
                    relationship
                    for relationship in relationships
                    if relationship.get("from_statement_id") in selected_statements
                    and relationship.get("to_statement_id") in selected_statements
                ),
                start=1,
            )
        }
        for sentence_index, sentence in enumerate(sentences):
            if not isinstance(sentence, Mapping) or set(sentence) != _NARRATIVE_SENTENCE_KEYS:
                raise NarrativeGroundingValidationError(
                    "sentence_schema_invalid",
                    "narrative sentence schema is invalid",
                    sentence_index=sentence_index,
                    sentence=sentence if isinstance(sentence, Mapping) else None,
                )
            text = sentence["text"]
            refs = sentence["statement_ids"]
            declared = sentence["relationship_ids"]
            if not isinstance(text, str) or not text.strip():
                raise NarrativeGroundingValidationError(
                    "empty_sentence_support",
                    "narrative sentence text is invalid",
                    sentence_index=sentence_index,
                    sentence=sentence,
                )
            if not isinstance(refs, list) or not refs:
                raise NarrativeGroundingValidationError(
                    "empty_sentence_support",
                    "narrative sentence support is invalid",
                    sentence_index=sentence_index,
                    sentence=sentence,
                )
            if len(refs) != len(set(refs)) or any(
                not isinstance(ref, str) or ref not in selected_statements for ref in refs
            ):
                raise NarrativeGroundingValidationError(
                    "unsupported_statement_id",
                    "narrative references an unselected statement",
                    sentence_index=sentence_index,
                    sentence=sentence,
                )
            if not isinstance(declared, list) or len(declared) > 3:
                raise NarrativeGroundingValidationError(
                    "sentence_schema_invalid",
                    "narrative sentence relationships are invalid",
                    sentence_index=sentence_index,
                    sentence=sentence,
                )
            if len(declared) != len(set(declared)) or any(
                not isinstance(item, str) or item not in relationship_map for item in declared
            ):
                raise NarrativeGroundingValidationError(
                    "unsupported_relationship_id",
                    "narrative references an invalid relationship ID",
                    sentence_index=sentence_index,
                    sentence=sentence,
                )
            for relationship_id in declared:
                relationship = relationship_map[relationship_id]
            effective_refs = list(refs)
            for relationship_id in declared:
                relationship = relationship_map[relationship_id]
                for endpoint in (
                    relationship["from_statement_id"],
                    relationship["to_statement_id"],
                ):
                    if endpoint not in effective_refs:
                        effective_refs.append(endpoint)
            if any(marker in text for marker in _NARRATIVE_DEBUG_MARKERS):
                raise NarrativeGroundingValidationError(
                    "debug_marker_detected",
                    "narrative contains relationship debug output",
                    sentence_index=sentence_index,
                    sentence=sentence,
                )
            numbers = set(_NARRATIVE_NUMBER_RE.findall(text))
            effective_text = " ".join(
                selected_statements[statement_id]
                for statement_id in effective_refs
                if statement_id in selected_statements
            )
            effective_numbers = set(_NARRATIVE_NUMBER_RE.findall(effective_text))
            effective_codes = set(
                re.findall(r"\b[A-ZÇĞİÖŞÜ][A-ZÇĞİÖŞÜ0-9_-]{2,}\b", effective_text)
            )
            effective_codes.update(verified_anchors or {})
            if not numbers <= effective_numbers:
                raise NarrativeGroundingValidationError(
                    "unsupported_number",
                    "narrative contains an unsupported number",
                    sentence_index=sentence_index,
                    sentence=sentence,
                )
            codes = set(re.findall(r"\b[A-ZÇĞİÖŞÜ][A-ZÇĞİÖŞÜ0-9_-]{2,}\b", text))
            if not codes <= effective_codes:
                raise NarrativeGroundingValidationError(
                    "unsupported_identifier",
                    "narrative contains an unsupported identifier",
                    sentence_index=sentence_index,
                    sentence=sentence,
                )
            relational_language = (
                "çünkü",
                "nedeniyle",
                "bu yüzden",
                "dolayısıyla",
                "sonucunda",
                "yol açtı",
                "tetikledi",
                "sebep oldu",
                "buna bağlı olarak",
                "bu belirsizlik nedeniyle",
                "bu nedenle",
                "bunun sonucu olarak",
                "doğrulanmadığı için",
                "olduğu için",
                "olmadığı için",
                "olmadığından",
            )
            has_relational_language = any(
                phrase in text.casefold() for phrase in relational_language
            )
            grounded_manual_review = (
                "manuel inceleme" in text.casefold()
                and "root_cause_unverified" in effective_text.casefold()
            )
            if grounded_manual_review:
                has_relational_language = False
            if has_relational_language and not declared:
                raise NarrativeGroundingValidationError(
                    "causal_language_without_relationship",
                    "narrative contains an unsupported causal relation",
                    sentence_index=sentence_index,
                    sentence=sentence,
                )
            if has_relational_language and not any(
                relationship_map[relationship_id].get("narrative_semantics") == "causal"
                for relationship_id in declared
            ):
                raise NarrativeGroundingValidationError(
                    "relationship_semantics_not_permitted",
                    "relationship semantics do not permit causal wording",
                    sentence_index=sentence_index,
                    sentence=sentence,
                )

    @staticmethod
    def _render_grounded_narrative(narrative: Mapping[str, Any]) -> str:
        return " ".join(str(sentence["text"]).strip() for sentence in narrative["sentences"])

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
