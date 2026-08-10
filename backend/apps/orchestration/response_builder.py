"""Render validated execution facts without changing QueryRun persistence."""

from __future__ import annotations

import json
from collections.abc import Mapping
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from apps.core.exceptions import ProcessTwinError
from apps.orchestration.models import QueryRun, QueryRunStatus
from apps.orchestration.providers.base import LLMProvider
from apps.orchestration.providers.gemini import GeminiLLMProviderError
from apps.orchestration.providers.registry import get_llm_descriptor
from apps.orchestration.result_merge import (
    ProvenanceEntry,
    ValidatedExecutionResult,
    ValidationStatus,
)

RESPONSE_PROMPT_VERSION = "closed-world-statement-selection-tr-v3"
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


class ResponseBuilderError(ProcessTwinError):
    """Stable response-builder precondition failure."""


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
        )
        if requested_mode == ResponseGenerationMode.DETERMINISTIC:
            return response

        active_provider = provider
        if active_provider is None:
            descriptor = get_llm_descriptor(provider_name)
            active_provider = descriptor.create_provider()
        response.provider = active_provider.provider_name
        response.model = active_provider.model_name
        contract = self._statement_contract(result)
        try:
            narrative = self._safe_statement_selection(active_provider, contract)
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
            return response

        response.response_text = narrative
        response.generation_mode = ResponseGenerationMode.LLM_ASSISTED
        return response

    @staticmethod
    def _statement_selection_failure_code(exc: Exception) -> str:
        """Return a bounded diagnostic category without exposing provider payloads."""
        if isinstance(exc, GeminiLLMProviderError):
            return f"provider_call_failed_{exc.code}"
        message = str(exc)
        if "not JSON" in message:
            return "statement_selection_parse_failed"
        if "unknown or duplicate" in message:
            return "unknown_or_duplicate_statement_id"
        if "critical statement missing" in message:
            return "statement_selection_missing_id"
        if "schema is invalid" in message:
            return "statement_selection_schema_invalid"
        if "provider response is invalid" in message:
            return "provider_response_invalid"
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
                if impact.affected_customer_count is not None:
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
                if impact.failover_protected == 0:
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
    def _statement_contract(result: ValidatedExecutionResult) -> tuple[str, dict[str, str]]:
        """Build immutable, privacy-safe sentences; the model may select IDs only."""
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
            if impact.affected_subscription_count is not None:
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
                if impact.failover_protected == 0:
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
            },
            "required": ["headline_id", "selected_statement_ids"],
            "additionalProperties": False,
        }
        prompt = (
            "Yalnız native schema nesnesini üret. Cümle yazma, cümleleri değiştirme, "
            "yeni ID üretme. Kritik tüm statement ID'lerini birer kez seç ve güvenli sırada diz.\n"
            "HEADLINES={'H1': 'Kesinti değerlendirmesi'}\nSTATEMENTS="
            + json.dumps(statements, ensure_ascii=False)
        )
        return prompt, {"schema": schema, "statements": statements}

    @classmethod
    def _safe_statement_selection(
        cls, provider: LLMProvider, contract: tuple[str, dict[str, object]]
    ) -> str:
        prompt, data = contract
        response = provider.generate(request={"contents": prompt, "format_schema": data["schema"]})
        if not isinstance(response, Mapping) or response.get("provider") != provider.provider_name:
            raise ValueError("provider response is invalid")
        if response.get("model") != provider.model_name or not isinstance(
            response.get("content"), str
        ):
            raise ValueError("provider response is invalid")
        try:
            selection = json.loads(response["content"])
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("native schema response is not JSON") from exc
        statements = data["statements"]
        if not isinstance(statements, Mapping):
            raise ValueError("statement contract is invalid")
        cls._validate_statement_selection(selection, statements)
        headline = "Kesinti değerlendirmesi" if selection["headline_id"] == "H1" else None
        lines = [headline] if headline else []
        selected = selection["selected_statement_ids"]
        # The model chooses a safe ordering only. Any omitted critical ID is
        # deterministically appended so semantic completeness never depends on
        # the model deciding to include every canonical statement.
        ordered_ids = [*selected, *(item for item in statements if item not in selected)]
        lines.extend(statements[statement_id] for statement_id in ordered_ids)
        return "\n".join(lines)

    @staticmethod
    def _validate_statement_selection(selection: object, statements: Mapping[str, str]) -> None:
        if not isinstance(selection, Mapping) or set(selection) != {
            "headline_id",
            "selected_statement_ids",
        }:
            raise ValueError("statement selection schema is invalid")
        if selection["headline_id"] not in {"H1", None}:
            raise ValueError("unknown headline ID")
        selected = selection["selected_statement_ids"]
        if not isinstance(selected, list) or not all(isinstance(item, str) for item in selected):
            raise ValueError("statement selection IDs are invalid")
        if len(selected) != len(set(selected)) or any(item not in statements for item in selected):
            raise ValueError("unknown or duplicate statement ID")

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
