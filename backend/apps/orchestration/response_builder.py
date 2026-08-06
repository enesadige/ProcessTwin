"""Render validated execution facts without changing QueryRun persistence."""

from __future__ import annotations

import re
from collections.abc import Mapping
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from apps.core.exceptions import ProcessTwinError
from apps.orchestration.models import QueryRun, QueryRunStatus
from apps.orchestration.providers.base import LLMProvider
from apps.orchestration.providers.registry import get_llm_descriptor
from apps.orchestration.result_merge import (
    ProvenanceEntry,
    ValidatedExecutionResult,
    ValidationStatus,
)

RESPONSE_PROMPT_VERSION = "validated-response-builder-tr-v1"
_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9._-])\d+(?:[.,]\d+)?(?![A-Za-z0-9._-])")
_PUBLIC_REFERENCE_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,15}(?:-[A-Z0-9][A-Z0-9_-]{0,63})+\b")
_DECISION_WORD_RE = re.compile(
    r"\b(eligible|ineligible|eligibility|compensation|uygun|uygun değil|telafi)\b",
    re.IGNORECASE,
)


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
        try:
            narrative = self._safe_narrative(active_provider, self._fact_sheet(result))
        except Exception:
            response.generation_mode = ResponseGenerationMode.DETERMINISTIC_FALLBACK
            response.warnings = sorted(set([*response.warnings, "llm_narrative_fallback"]))
            return response

        response.response_text = f"{narrative}\n\n{deterministic_text}"
        response.generation_mode = ResponseGenerationMode.LLM_ASSISTED
        response.provider = active_provider.provider_name
        response.model = active_provider.model_name
        return response

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
            if causal.root_cause_reason_codes:
                sections.append(
                    "Gerekçe kodları: " + ", ".join(causal.root_cause_reason_codes) + "."
                )
            if causal.propagation_summary:
                sections.append(f"Yayılım özeti: {causal.propagation_summary}")

        impact = result.impact_summary
        if impact:
            sections.extend(["", "Müşteri etkisi"])
            if impact.potential is not None:
                sections.append(f"Potansiyel etki: {impact.potential} bağlantı.")
            if impact.verified_impacted is not None:
                sections.append(f"Doğrulanmış etki: {impact.verified_impacted} bağlantı.")
            if impact.verified_no_impact is not None:
                sections.append(f"Etkilenmediği doğrulanan: {impact.verified_no_impact} bağlantı.")
            if impact.insufficient_evidence is not None:
                sections.append(f"Kanıtı yetersiz: {impact.insufficient_evidence} bağlantı.")
            if impact.failover_protected is not None:
                sections.append(
                    f"Failover ile korunan: {impact.failover_protected} bağlantı; "
                    "tam kesinti sayılmaz."
                )

        rule = result.rule_summary
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

        compensation = result.compensation_summary
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
            if compensation.total_amount and compensation.currency:
                sections.append(
                    f"Toplam telafi tutarı: {compensation.total_amount} {compensation.currency}."
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
    def _fact_sheet(result: ValidatedExecutionResult) -> str:
        """A minimal, already-safe prompt input; no query text or raw runtime data."""
        safe = {
            "causal_summary": None
            if result.causal_summary is None
            else result.causal_summary.model_dump(),
            "impact_summary": None
            if result.impact_summary is None
            else result.impact_summary.model_dump(),
            "rule_summary": None
            if result.rule_summary is None
            else result.rule_summary.model_dump(),
            "compensation_summary": (
                None
                if result.compensation_summary is None
                else result.compensation_summary.model_dump()
            ),
            "warnings": sorted(set(result.warnings)),
        }
        return (
            "Yalnız kısa Türkçe açıklama yaz. Yeni sayı, tutar, karar, public referans veya "
            "kaynak ekleme. Potansiyel etkiyi doğrulanmış etki gibi, failover korumasını "
            "tam kesinti gibi ve retrieval kaynağını karar gibi anlatma.\n"
            f"DOĞRULANMIŞ_FACT_SHEET={safe!r}"
        )

    @classmethod
    def _safe_narrative(cls, provider: LLMProvider, fact_sheet: str) -> str:
        response = provider.generate(request={"contents": fact_sheet})
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
        narrative = content.strip()
        if (
            _NUMBER_RE.search(narrative)
            or _PUBLIC_REFERENCE_RE.search(narrative)
            or _DECISION_WORD_RE.search(narrative)
        ):
            raise ValueError("provider narrative contains unsupported facts")
        return narrative
