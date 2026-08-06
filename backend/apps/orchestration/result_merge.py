"""Typed, privacy-safe validation of fresh MCP execution results."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from apps.orchestration.executor import (
    ExecutorResult,
    ExecutorStatus,
    ToolExecutionStatus,
)
from apps.orchestration.models import QueryRun, QueryRunStatus
from apps.orchestration.services import QueryRunError, QueryRunService
from apps.orchestration.structured_query import (
    RequestedOutput,
    StructuredQuery,
    StructuredQueryIntent,
)
from apps.orchestration.tool_plan import MCPServer, ToolPlan


class ValidationStatus(StrEnum):
    VALID = "valid"
    INVALID = "invalid"


class EvidenceCategory(StrEnum):
    NETWORK_CAUSAL = "network_causal"
    CUSTOMER_IMPACT = "customer_impact"
    RULE_EVIDENCE = "rule_evidence"
    COMPENSATION = "compensation"
    DOCUMENT_RETRIEVAL = "document_retrieval"


class ValidationErrorItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    category: EvidenceCategory | None = None
    call_id: str | None = None


class CausalSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    causal_event_code: str | None = None
    outage_code: str | None = None
    root_resource_type: str | None = None
    root_resource_reference: str | None = None
    root_cause_reason_codes: list[str] = Field(default_factory=list)
    role_counts: dict[str, int] = Field(default_factory=dict)
    propagation_summary: str | None = None


class ImpactSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    potential: int | None = None
    verified_impacted: int | None = None
    verified_no_impact: int | None = None
    insufficient_evidence: int | None = None
    failover_protected: int | None = None
    reason_code_distribution: dict[str, int] = Field(default_factory=dict)


class RuleSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_codes: list[str] = Field(default_factory=list)
    rule_versions: list[str] = Field(default_factory=list)
    eligibility_status: str | None = None
    evidence_references: list[str] = Field(default_factory=list)
    baseline: str | None = None
    candidate: str | None = None
    difference_summary: str | None = None


class CompensationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str | None = None
    considered: int | None = None
    eligible: int | None = None
    ineligible_pending: int | None = None
    total_amount: str | None = None
    currency: str | None = None
    rule_versions: dict[str, int] = Field(default_factory=dict)
    evidence_references: list[str] = Field(default_factory=list)
    scope: str | None = None


class RetrievalSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_code: str
    version: int | None = None
    section: str | None = None
    source_kind: str | None = None


class ProvenanceEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call_id: str
    server: MCPServer
    tool_name: str
    correlation_id: str
    result_fingerprint: str | None = None
    category: EvidenceCategory | None = None


class ValidatedExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "validated-execution-result.v1"
    snapshot_identifier: str
    execution_status: ExecutorStatus
    validation_status: ValidationStatus
    causal_summary: CausalSummary | None = None
    impact_summary: ImpactSummary | None = None
    rule_summary: RuleSummary | None = None
    compensation_summary: CompensationSummary | None = None
    retrieval_sources: list[RetrievalSource] = Field(default_factory=list)
    provenance: list[ProvenanceEntry] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    validation_errors: list[ValidationErrorItem] = Field(default_factory=list)
    result_fingerprint: str | None = None

    def to_final_result(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class _ExtractedToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: EvidenceCategory
    causal: dict[str, Any] = Field(default_factory=dict)
    impact: dict[str, Any] = Field(default_factory=dict)
    rule: dict[str, Any] = Field(default_factory=dict)
    compensation: dict[str, Any] = Field(default_factory=dict)
    retrieval_sources: list[RetrievalSource] = Field(default_factory=list)


Normalizer = Callable[[Mapping[str, Any]], _ExtractedToolResult]


def _mapping(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _non_negative_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _optional_non_negative(data: Mapping[str, Any], field: str) -> int | None:
    if field not in data or data[field] is None:
        return None
    return _non_negative_int(data[field], field)


def _string(value: object, field: str, *, required: bool = False) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _string_list(value: object, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ValueError(f"{field} must be a list of strings")
    return sorted(set(item.strip() for item in value))


def _count_mapping(value: object, field: str) -> dict[str, int]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return {str(key): _non_negative_int(item, field) for key, item in sorted(value.items())}


def _network_causal(data: Mapping[str, Any]) -> _ExtractedToolResult:
    return _ExtractedToolResult(
        category=EvidenceCategory.NETWORK_CAUSAL,
        causal={
            "causal_event_code": _string(
                data.get("causal_event_code"), "causal_event_code", required=True
            ),
            "root_resource_type": _string(data.get("root_resource_type"), "root_resource_type"),
            "root_resource_reference": _string(
                data.get("root_resource_reference"), "root_resource_reference"
            ),
            "root_cause_reason_codes": _string_list(data.get("reason_codes"), "reason_codes"),
            "role_counts": _count_mapping(data.get("role_counts"), "role_counts"),
            "propagation_summary": _string(data.get("propagation_summary"), "propagation_summary"),
        },
    )


def _network_root_cause(data: Mapping[str, Any]) -> _ExtractedToolResult:
    if data.get("causal_event_code") is not None:
        return _network_causal(data)
    return _ExtractedToolResult(
        category=EvidenceCategory.NETWORK_CAUSAL,
        causal={
            "outage_code": _string(data.get("outage_code"), "outage_code", required=True),
            "root_resource_type": _string(data.get("root_resource_type"), "root_resource_type"),
            "root_resource_reference": _string(
                data.get("root_resource_reference"), "root_resource_reference"
            ),
            "root_cause_reason_codes": _string_list(data.get("reason_codes"), "reason_codes"),
            "role_counts": _count_mapping(data.get("role_counts"), "role_counts"),
            "propagation_summary": _string(data.get("propagation_summary"), "propagation_summary"),
        },
    )


def _customer_causal_impact(data: Mapping[str, Any]) -> _ExtractedToolResult:
    return _ExtractedToolResult(
        category=EvidenceCategory.CUSTOMER_IMPACT,
        causal={
            "causal_event_code": _string(
                data.get("causal_event_code"), "causal_event_code", required=True
            )
        },
        impact={
            "potential": _non_negative_int(
                data.get("potential_connection_count"), "potential_connection_count"
            ),
            "verified_impacted": _non_negative_int(
                data.get("verified_impacted_count"), "verified_impacted_count"
            ),
            "verified_no_impact": _non_negative_int(
                data.get("verified_no_impact_count"), "verified_no_impact_count"
            ),
            "insufficient_evidence": _non_negative_int(
                data.get("insufficient_evidence_count"), "insufficient_evidence_count"
            ),
            "failover_protected": _non_negative_int(
                data.get("failover_protected_count"), "failover_protected_count"
            ),
            "reason_code_distribution": _count_mapping(
                data.get("reason_code_distribution"), "reason_code_distribution"
            ),
        },
    )


def _network_outage_impact(data: Mapping[str, Any]) -> _ExtractedToolResult:
    return _ExtractedToolResult(
        category=EvidenceCategory.CUSTOMER_IMPACT,
        causal={"outage_code": _string(data.get("outage_code"), "outage_code", required=True)},
        impact={
            "potential": _non_negative_int(
                data.get("affected_subscription_count"), "affected_subscription_count"
            ),
            "failover_protected": _non_negative_int(
                (_mapping(data.get("protected_failover")) or {}).get("subscription_count", 0),
                "failover_protected_subscription_count",
            ),
        },
    )


def _network_outage_details(data: Mapping[str, Any]) -> _ExtractedToolResult:
    outage = _mapping(data.get("outage"))
    if outage is None:
        raise ValueError("outage must be an object")
    return _ExtractedToolResult(
        category=EvidenceCategory.NETWORK_CAUSAL,
        causal={"outage_code": _string(outage.get("outage_code"), "outage_code", required=True)},
    )


def _rule_evidence(data: Mapping[str, Any]) -> _ExtractedToolResult:
    evidence = _mapping(data.get("evidence"))
    reference = (
        None if evidence is None else _string(evidence.get("reference"), "evidence.reference")
    )
    return _ExtractedToolResult(
        category=EvidenceCategory.RULE_EVIDENCE,
        causal={
            "causal_event_code": _string(
                data.get("causal_event_code"), "causal_event_code", required=True
            )
        },
        rule={
            "rule_versions": _string_list(
                [data["selected_rule_version"]]
                if data.get("selected_rule_version") is not None
                else [],
                "selected_rule_version",
            ),
            "eligibility_status": _string(data.get("eligibility_status"), "eligibility_status"),
            "evidence_references": [reference] if reference else [],
            "baseline": _string(data.get("baseline"), "baseline"),
            "candidate": _string(data.get("candidate"), "candidate"),
            "difference_summary": _string(data.get("difference_summary"), "difference_summary"),
        },
    )


def _compensation_evidence(data: Mapping[str, Any]) -> _ExtractedToolResult:
    evidence = _mapping(data.get("evidence"))
    reference = (
        None if evidence is None else _string(evidence.get("reference"), "evidence.reference")
    )
    return _ExtractedToolResult(
        category=EvidenceCategory.COMPENSATION,
        causal={"causal_event_code": _string(data.get("causal_event_code"), "causal_event_code")},
        compensation={
            "status": _string(data.get("status"), "status", required=True),
            "considered": _optional_non_negative(data, "consideration_count"),
            "eligible": _optional_non_negative(data, "eligible"),
            "ineligible_pending": _optional_non_negative(data, "ineligible_pending"),
            "total_amount": _string(data.get("total_amount"), "total_amount"),
            "currency": _string(data.get("currency"), "currency"),
            "rule_versions": _count_mapping(data.get("rule_versions"), "rule_versions"),
            "evidence_references": [reference] if reference else [],
            # This source is generated by VerifiedImpactCompensationService.
            "scope": "verified_impact",
        },
    )


def _rule_search(data: Mapping[str, Any]) -> _ExtractedToolResult:
    rows = data.get("rules")
    if not isinstance(rows, list):
        raise ValueError("rules must be a list")
    codes: list[str] = []
    versions: list[str] = []
    for row in rows:
        rule = _mapping(row)
        rule_payload = None if rule is None else _mapping(rule.get("rule"))
        if rule_payload is None:
            raise ValueError("rule row is invalid")
        code = _string(rule_payload.get("code"), "rule.code", required=True)
        codes.append(code)
        version_payload = _mapping(rule.get("latest_version_summary")) or _mapping(
            rule.get("effective_version_summary")
        )
        if version_payload and version_payload.get("version") is not None:
            versions.append(f"{code}:v{_non_negative_int(version_payload['version'], 'version')}")
    return _ExtractedToolResult(
        category=EvidenceCategory.RULE_EVIDENCE,
        rule={"rule_codes": sorted(set(codes)), "rule_versions": sorted(set(versions))},
    )


def _document_retrieval(data: Mapping[str, Any]) -> _ExtractedToolResult:
    rows = data.get("results")
    if not isinstance(rows, list):
        raise ValueError("results must be a list")
    sources: list[RetrievalSource] = []
    for row in rows:
        item = _mapping(row)
        if item is None:
            raise ValueError("retrieval source is invalid")
        sources.append(
            RetrievalSource(
                source_code=_string(item.get("document_code"), "document_code", required=True),
                version=_optional_non_negative(item, "document_version"),
                section=_string(item.get("heading"), "heading"),
                source_kind=_string(data.get("source_kind"), "source_kind"),
            )
        )
    return _ExtractedToolResult(
        category=EvidenceCategory.DOCUMENT_RETRIEVAL, retrieval_sources=sources
    )


NORMALIZERS: dict[tuple[MCPServer, str], Normalizer] = {
    (MCPServer.NETWORK, "correlate_alarms"): _network_causal,
    (MCPServer.NETWORK, "rank_root_cause_candidates"): _network_root_cause,
    (MCPServer.NETWORK, "get_outage_details"): _network_outage_details,
    (MCPServer.NETWORK, "calculate_customer_impact"): _network_outage_impact,
    (MCPServer.CUSTOMER, "get_customer_outage_history"): _customer_causal_impact,
    (MCPServer.RULE, "get_rule_evidence"): _rule_evidence,
    (MCPServer.RULE, "search_rules"): _rule_search,
    (MCPServer.RULE, "search_rule_documents"): _document_retrieval,
    (MCPServer.COMPENSATION, "get_compensation_evidence"): _compensation_evidence,
}


class ResultMergerValidator:
    """Merge only known MCP response contracts; never recalculate domain facts."""

    def validate_and_merge(
        self,
        query_run: QueryRun,
        tool_plan: ToolPlan,
        executor_result: ExecutorResult,
    ) -> ValidatedExecutionResult:
        errors: list[ValidationErrorItem] = []
        warnings: list[str] = []
        if QueryRunStatus(query_run.status) != QueryRunStatus.EXECUTING:
            raise QueryRunError(
                message="QueryRun must be executing before result validation.",
                code="query_run_validation_requires_execution",
            )
        if not self._snapshots_match(query_run, tool_plan, executor_result):
            return self._invalid_result(tool_plan, executor_result, ["snapshot_mismatch"])
        if query_run.planned_tools != tool_plan.to_planned_tools():
            return self._invalid_result(tool_plan, executor_result, ["validation_failed"])

        calls_by_id = {call.call_id: call for call in tool_plan.calls}
        results_by_id = {result.call_id: result for result in executor_result.call_results}
        if len(results_by_id) != len(executor_result.call_results) or set(results_by_id) != set(
            calls_by_id
        ):
            return self._invalid_result(tool_plan, executor_result, ["runtime_result_unavailable"])

        required = self.required_categories(tool_plan.structured_query_context)
        category_results: dict[EvidenceCategory, list[_ExtractedToolResult]] = {}
        provenance: list[ProvenanceEntry] = []
        for call in tool_plan.calls:
            result = results_by_id[call.call_id]
            category = self._category_for_call(call.server, call.tool_name)
            if result.status != ToolExecutionStatus.SUCCEEDED:
                if category in required:
                    errors.append(
                        ValidationErrorItem(
                            code="required_tool_failed", category=category, call_id=call.call_id
                        )
                    )
                else:
                    warnings.append(f"optional_tool_{result.status.value}:{call.call_id}")
                continue
            if result.normalized_response is None:
                errors.append(
                    ValidationErrorItem(
                        code="runtime_result_unavailable", category=category, call_id=call.call_id
                    )
                )
                continue
            normalizer = NORMALIZERS.get((call.server, call.tool_name))
            if normalizer is None:
                errors.append(
                    ValidationErrorItem(
                        code="invalid_response_contract", category=category, call_id=call.call_id
                    )
                )
                continue
            try:
                data = _mapping(result.normalized_response.get("data"))
                if data is None:
                    raise ValueError("response data must be an object")
                extracted = normalizer(data)
            except (TypeError, ValueError):
                errors.append(
                    ValidationErrorItem(
                        code="invalid_response_contract", category=category, call_id=call.call_id
                    )
                )
                continue
            category_results.setdefault(extracted.category, []).append(extracted)
            provenance.append(
                ProvenanceEntry(
                    call_id=call.call_id,
                    server=call.server,
                    tool_name=call.tool_name,
                    correlation_id=result.correlation_id,
                    result_fingerprint=result.result_fingerprint,
                    category=extracted.category,
                )
            )

        for category in sorted(required, key=str):
            if not category_results.get(category):
                errors.append(
                    ValidationErrorItem(code="required_evidence_missing", category=category)
                )

        causal, impact, rule, compensation, sources, merge_errors = self._merge_sections(
            category_results
        )
        errors.extend(merge_errors)
        errors.extend(self._validate_cross_tool(tool_plan, causal, impact, compensation))
        result = ValidatedExecutionResult(
            snapshot_identifier=tool_plan.snapshot_identifier,
            execution_status=executor_result.status,
            validation_status=ValidationStatus.INVALID if errors else ValidationStatus.VALID,
            causal_summary=CausalSummary(**causal) if causal else None,
            impact_summary=ImpactSummary(**impact) if impact else None,
            rule_summary=RuleSummary(**rule) if rule else None,
            compensation_summary=CompensationSummary(**compensation) if compensation else None,
            retrieval_sources=sources,
            provenance=sorted(provenance, key=lambda item: item.call_id),
            warnings=sorted(set(warnings)),
            validation_errors=sorted(
                errors, key=lambda item: (item.code, str(item.category), item.call_id or "")
            ),
        )
        result.result_fingerprint = self._fingerprint(result)
        return result

    def finalize_query_run(
        self, query_run: QueryRun, validated_result: ValidatedExecutionResult
    ) -> QueryRun:
        if QueryRunStatus(query_run.status) != QueryRunStatus.EXECUTING:
            raise QueryRunError(
                message="QueryRun must be executing before finalization.",
                code="query_run_finalization_requires_execution",
            )
        service = QueryRunService()
        if validated_result.validation_status == ValidationStatus.VALID:
            return service.complete(query_run, final_result=validated_result.to_final_result())
        priority = (
            "required_tool_failed",
            "required_evidence_missing",
            "runtime_result_unavailable",
            "snapshot_mismatch",
            "invalid_response_contract",
            "public_reference_conflict",
            "conflicting_fact",
            "impact_invariant_failed",
            "compensation_scope_mismatch",
            "validation_failed",
        )
        codes = {item.code for item in validated_result.validation_errors}
        primary_code = next((code for code in priority if code in codes), "validation_failed")
        return service.fail(
            query_run,
            error_code=primary_code,
            error_summary="Tool result validation failed.",
        )

    @staticmethod
    def required_categories(query: StructuredQuery) -> frozenset[EvidenceCategory]:
        categories: set[EvidenceCategory] = set()
        outputs = set(query.requested_outputs)
        if RequestedOutput.ROOT_CAUSE in outputs:
            categories.add(EvidenceCategory.NETWORK_CAUSAL)
        if RequestedOutput.IMPACT in outputs:
            categories.add(EvidenceCategory.CUSTOMER_IMPACT)
        if query.intent == StructuredQueryIntent.OUTAGE_IMPACT:
            categories.add(EvidenceCategory.CUSTOMER_IMPACT)
        if query.intent in {
            StructuredQueryIntent.RULE_RETRIEVAL,
            StructuredQueryIntent.RULE_EVIDENCE,
        }:
            categories.add(EvidenceCategory.RULE_EVIDENCE)
        if (
            RequestedOutput.EVIDENCE in outputs
            and query.intent
            not in {
                StructuredQueryIntent.COMPENSATION_EVALUATION,
                StructuredQueryIntent.RULE_DOCUMENT_RETRIEVAL,
            }
        ):
            categories.add(EvidenceCategory.RULE_EVIDENCE)
        if (
            query.intent == StructuredQueryIntent.COMPENSATION_EVALUATION
            or RequestedOutput.COMPENSATION_AMOUNT in outputs
        ):
            categories.add(EvidenceCategory.COMPENSATION)
        if query.intent == StructuredQueryIntent.RULE_DOCUMENT_RETRIEVAL:
            categories.add(EvidenceCategory.DOCUMENT_RETRIEVAL)
        return frozenset(categories)

    @staticmethod
    def _category_for_call(server: MCPServer, tool_name: str) -> EvidenceCategory | None:
        if (server, tool_name) in {
            (MCPServer.NETWORK, "correlate_alarms"),
            (MCPServer.NETWORK, "rank_root_cause_candidates"),
            (MCPServer.NETWORK, "get_outage_details"),
        }:
            return EvidenceCategory.NETWORK_CAUSAL
        if (server, tool_name) in {
            (MCPServer.CUSTOMER, "get_customer_outage_history"),
            (MCPServer.NETWORK, "calculate_customer_impact"),
        }:
            return EvidenceCategory.CUSTOMER_IMPACT
        if server == MCPServer.RULE and tool_name == "search_rule_documents":
            return EvidenceCategory.DOCUMENT_RETRIEVAL
        if server == MCPServer.RULE:
            return EvidenceCategory.RULE_EVIDENCE
        if server == MCPServer.COMPENSATION:
            return EvidenceCategory.COMPENSATION
        return None

    @staticmethod
    def _snapshots_match(query_run: QueryRun, plan: ToolPlan, result: ExecutorResult) -> bool:
        return (
            query_run.data_snapshot.snapshot_key
            == plan.snapshot_identifier
            == result.snapshot_identifier
        )

    def _invalid_result(
        self, plan: ToolPlan, result: ExecutorResult, codes: list[str]
    ) -> ValidatedExecutionResult:
        merged = ValidatedExecutionResult(
            snapshot_identifier=plan.snapshot_identifier,
            execution_status=result.status,
            validation_status=ValidationStatus.INVALID,
            validation_errors=[ValidationErrorItem(code=code) for code in sorted(set(codes))],
        )
        merged.result_fingerprint = self._fingerprint(merged)
        return merged

    @staticmethod
    def _merge_sections(
        category_results: Mapping[EvidenceCategory, list[_ExtractedToolResult]],
    ) -> tuple[
        dict[str, Any],
        dict[str, Any],
        dict[str, Any],
        dict[str, Any],
        list[RetrievalSource],
        list[ValidationErrorItem],
    ]:
        causal: dict[str, Any] = {}
        impact: dict[str, Any] = {}
        rule: dict[str, Any] = {}
        compensation: dict[str, Any] = {}
        sources: dict[tuple[str, int | None, str | None], RetrievalSource] = {}
        errors: list[ValidationErrorItem] = []
        for results in category_results.values():
            for extracted in results:
                for target, incoming in (
                    (causal, extracted.causal),
                    (impact, extracted.impact),
                    (rule, extracted.rule),
                    (compensation, extracted.compensation),
                ):
                    for key, value in incoming.items():
                        if value in (None, [], {}):
                            continue
                        if key in target and target[key] != value:
                            errors.append(ValidationErrorItem(code="conflicting_fact"))
                        else:
                            target[key] = value
                for source in extracted.retrieval_sources:
                    key = (source.source_code, source.version, source.section)
                    if key in sources and sources[key] != source:
                        errors.append(ValidationErrorItem(code="conflicting_fact"))
                    else:
                        sources[key] = source
        for section in (causal, impact, rule, compensation):
            for key, value in list(section.items()):
                if isinstance(value, list):
                    section[key] = sorted(set(value))
        return (
            causal,
            impact,
            rule,
            compensation,
            sorted(
                sources.values(),
                key=lambda item: (item.source_code, item.version or -1, item.section or ""),
            ),
            errors,
        )

    @staticmethod
    def _validate_cross_tool(
        plan: ToolPlan,
        causal: Mapping[str, Any],
        impact: Mapping[str, Any],
        compensation: Mapping[str, Any],
    ) -> list[ValidationErrorItem]:
        errors: list[ValidationErrorItem] = []
        query = plan.structured_query_context
        planned_reference = query.causal_event_code or query.outage_code
        actual_reference = causal.get("causal_event_code") or causal.get("outage_code")
        if planned_reference and actual_reference and planned_reference != actual_reference:
            errors.append(ValidationErrorItem(code="public_reference_conflict"))
        potential = impact.get("potential")
        verified = impact.get("verified_impacted")
        protected = impact.get("failover_protected")
        if potential is not None and verified is not None and verified > potential:
            errors.append(ValidationErrorItem(code="impact_invariant_failed"))
        if potential is not None and verified is not None and protected is not None:
            if verified + protected > potential:
                errors.append(ValidationErrorItem(code="impact_invariant_failed"))
        considered = compensation.get("considered")
        if compensation and compensation.get("scope") != "verified_impact":
            errors.append(ValidationErrorItem(code="compensation_scope_mismatch"))
        if considered is not None and verified is not None and considered > verified:
            errors.append(ValidationErrorItem(code="compensation_scope_mismatch"))
        return errors

    @staticmethod
    def _fingerprint(result: ValidatedExecutionResult) -> str:
        payload = result.model_dump(mode="json", exclude={"result_fingerprint"}, exclude_none=True)
        serialized = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode()).hexdigest()
