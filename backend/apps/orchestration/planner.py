"""Deterministic, non-executing mapping from StructuredQuery to ToolPlan."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import ValidationError

from apps.orchestration.models import QueryRun
from apps.orchestration.services import QueryRunService
from apps.orchestration.structured_query import (
    RequestedOutput,
    StructuredQuery,
    StructuredQueryIntent,
)
from apps.orchestration.tool_plan import ToolPlan


class PlannerResultStatus(StrEnum):
    PLANNED = "planned"
    CLARIFICATION_REQUIRED = "clarification_required"
    UNPLANNABLE = "unplannable"


class PlannerReasonCode(StrEnum):
    INVALID_STRUCTURED_QUERY = "invalid_structured_query"
    MISSING_DOCUMENT_RETRIEVAL_QUERY = "missing_document_retrieval_query"
    MISSING_COMPENSATION_REFERENCE = "missing_compensation_reference"
    MISSING_SAFE_OPERATIONAL_REFERENCE = "missing_safe_operational_reference"
    UNSUPPORTED_REQUESTED_OUTPUT = "unsupported_requested_output"
    NO_SAFE_TOOL_MAPPING = "no_safe_tool_mapping"


_SUPPORTED_OUTPUTS = {
    StructuredQueryIntent.NETWORK_INVESTIGATION: frozenset(
        {
            RequestedOutput.SUMMARY,
            RequestedOutput.DETAILS,
            RequestedOutput.ROOT_CAUSE,
            RequestedOutput.EVIDENCE,
        }
    ),
    StructuredQueryIntent.OUTAGE_IMPACT: frozenset(
        {
            RequestedOutput.SUMMARY,
            RequestedOutput.DETAILS,
            RequestedOutput.IMPACT,
            RequestedOutput.ROOT_CAUSE,
            RequestedOutput.EVIDENCE,
        }
    ),
    StructuredQueryIntent.CUSTOMER_HISTORY: frozenset(
        {RequestedOutput.SUMMARY, RequestedOutput.DETAILS, RequestedOutput.IMPACT}
    ),
    StructuredQueryIntent.RULE_RETRIEVAL: frozenset(
        {RequestedOutput.SUMMARY, RequestedOutput.DETAILS, RequestedOutput.EVIDENCE}
    ),
    StructuredQueryIntent.RULE_EVIDENCE: frozenset(
        {RequestedOutput.SUMMARY, RequestedOutput.DETAILS, RequestedOutput.EVIDENCE}
    ),
    StructuredQueryIntent.COMPENSATION_EVALUATION: frozenset(
        {RequestedOutput.SUMMARY, RequestedOutput.ELIGIBILITY, RequestedOutput.EVIDENCE}
    ),
    StructuredQueryIntent.RULE_DOCUMENT_RETRIEVAL: frozenset(
        {RequestedOutput.SUMMARY, RequestedOutput.DETAILS, RequestedOutput.EVIDENCE}
    ),
}


@dataclass(frozen=True)
class PlannerResult:
    status: PlannerResultStatus
    tool_plan: ToolPlan | None = None
    reason_codes: tuple[str, ...] = ()

    @classmethod
    def planned(cls, tool_plan: ToolPlan) -> PlannerResult:
        return cls(status=PlannerResultStatus.PLANNED, tool_plan=tool_plan)

    @classmethod
    def clarification(cls, *reasons: str) -> PlannerResult:
        return cls(
            status=PlannerResultStatus.CLARIFICATION_REQUIRED,
            reason_codes=tuple(sorted(set(reasons))),
        )

    @classmethod
    def unplannable(cls, *reasons: str) -> PlannerResult:
        return cls(
            status=PlannerResultStatus.UNPLANNABLE,
            reason_codes=tuple(sorted(set(reasons))),
        )


class DeterministicToolPlanner:
    """Rule-based planner that emits only existing validated MCP calls."""

    def plan(self, structured_query: StructuredQuery | Mapping[str, Any]) -> PlannerResult:
        try:
            query = (
                structured_query
                if isinstance(structured_query, StructuredQuery)
                else StructuredQuery.model_validate(structured_query)
            )
        except ValidationError:
            return PlannerResult.unplannable(PlannerReasonCode.INVALID_STRUCTURED_QUERY.value)

        if query.clarification_required:
            return PlannerResult.clarification(
                *(reason.value for reason in query.clarification_reasons)
            )
        unsupported_outputs = set(query.requested_outputs) - _SUPPORTED_OUTPUTS[query.intent]
        if unsupported_outputs:
            return PlannerResult.unplannable(PlannerReasonCode.UNSUPPORTED_REQUESTED_OUTPUT.value)

        result = self._build_plan(query)
        if isinstance(result, PlannerResult):
            return result
        try:
            return PlannerResult.planned(ToolPlan.model_validate(result))
        except ValidationError:
            return PlannerResult.unplannable(PlannerReasonCode.NO_SAFE_TOOL_MAPPING.value)

    def plan_and_save(
        self,
        query_run: QueryRun,
        structured_query: StructuredQuery | Mapping[str, Any],
    ) -> PlannerResult:
        result = self.plan(structured_query)
        if result.status == PlannerResultStatus.PLANNED:
            QueryRunService().save_tool_plan(query_run, tool_plan=result.tool_plan)
        return result

    def _build_plan(self, query: StructuredQuery) -> dict[str, object] | PlannerResult:
        calls = self._calls_for_intent(query)
        if isinstance(calls, PlannerResult):
            return calls
        if not calls:
            return PlannerResult.unplannable(PlannerReasonCode.NO_SAFE_TOOL_MAPPING.value)
        return {
            "snapshot_identifier": query.snapshot_identifier,
            "structured_query_context": query.to_audit_dict(),
            "calls": calls,
        }

    def _calls_for_intent(self, query: StructuredQuery) -> list[dict[str, object]] | PlannerResult:
        if query.intent == StructuredQueryIntent.NETWORK_INVESTIGATION:
            return self._network_calls(query)
        if query.intent == StructuredQueryIntent.OUTAGE_IMPACT:
            return self._outage_impact_calls(query)
        if query.intent == StructuredQueryIntent.CUSTOMER_HISTORY:
            return self._customer_history_calls(query)
        if query.intent == StructuredQueryIntent.RULE_RETRIEVAL:
            return [self._call("rules", "rule", "search_rules", self._snapshot_args(query), 1)]
        if query.intent == StructuredQueryIntent.RULE_EVIDENCE:
            return self._evidence_calls(query, server="rule", tool_name="get_rule_evidence")
        if query.intent == StructuredQueryIntent.COMPENSATION_EVALUATION:
            return self._evidence_calls(
                query,
                server="compensation",
                tool_name="get_compensation_evidence",
                missing_reason=PlannerReasonCode.MISSING_COMPENSATION_REFERENCE,
            )
        if query.intent == StructuredQueryIntent.RULE_DOCUMENT_RETRIEVAL:
            return PlannerResult.clarification(
                PlannerReasonCode.MISSING_DOCUMENT_RETRIEVAL_QUERY.value
            )
        return PlannerResult.unplannable(PlannerReasonCode.NO_SAFE_TOOL_MAPPING.value)

    def _network_calls(self, query: StructuredQuery) -> list[dict[str, object]] | PlannerResult:
        if query.causal_event_code:
            return self._causal_analysis_calls(query)
        if query.outage_code:
            return [
                self._call(
                    "outage_details",
                    "network",
                    "get_outage_details",
                    self._snapshot_args(query, outage_code=query.outage_code),
                    1,
                ),
                self._call(
                    "root_cause",
                    "network",
                    "rank_root_cause_candidates",
                    self._snapshot_args(query, outage_code=query.outage_code),
                    2,
                    depends_on=["outage_details"],
                ),
            ]
        if query.incident_code:
            return self._incident_search_calls(query)
        return self._scoped_network_calls(query)

    def _outage_impact_calls(
        self, query: StructuredQuery
    ) -> list[dict[str, object]] | PlannerResult:
        if query.outage_code:
            return [
                self._call(
                    "outage_details",
                    "network",
                    "get_outage_details",
                    self._snapshot_args(query, outage_code=query.outage_code),
                    1,
                ),
                self._call(
                    "customer_impact",
                    "network",
                    "calculate_customer_impact",
                    self._snapshot_args(query, outage_code=query.outage_code),
                    2,
                    depends_on=["outage_details"],
                ),
            ]
        if query.causal_event_code:
            calls = self._causal_analysis_calls(query)
            calls.append(
                self._call(
                    "customer_history",
                    "customer",
                    "get_customer_outage_history",
                    self._snapshot_args(query, causal_event_code=query.causal_event_code),
                    2,
                    depends_on=["correlate", "root_cause"],
                )
            )
            return calls
        if query.incident_code:
            return self._incident_search_calls(query)
        return self._scoped_network_calls(query)

    def _customer_history_calls(
        self, query: StructuredQuery
    ) -> list[dict[str, object]] | PlannerResult:
        if query.causal_event_code:
            return [
                self._call(
                    "customer_history",
                    "customer",
                    "get_customer_outage_history",
                    self._snapshot_args(query, causal_event_code=query.causal_event_code),
                    1,
                )
            ]
        if query.location:
            return [
                self._call(
                    "customers_by_location",
                    "customer",
                    "list_customers_by_location",
                    self._snapshot_args(
                        query,
                        city=query.location.city,
                        district=query.location.district,
                        neighborhood=query.location.neighborhood,
                    ),
                    1,
                )
            ]
        return PlannerResult.clarification(
            PlannerReasonCode.MISSING_SAFE_OPERATIONAL_REFERENCE.value
        )

    def _evidence_calls(
        self,
        query: StructuredQuery,
        *,
        server: str,
        tool_name: str,
        missing_reason: PlannerReasonCode = PlannerReasonCode.MISSING_SAFE_OPERATIONAL_REFERENCE,
    ) -> list[dict[str, object]] | PlannerResult:
        if query.causal_event_code:
            arguments = self._snapshot_args(query, causal_event_code=query.causal_event_code)
        elif query.outage_code:
            arguments = self._snapshot_args(query, outage_code=query.outage_code)
        else:
            return PlannerResult.clarification(missing_reason.value)
        return [self._call("evidence", server, tool_name, arguments, 1)]

    def _causal_analysis_calls(self, query: StructuredQuery) -> list[dict[str, object]]:
        arguments = self._snapshot_args(query, causal_event_code=query.causal_event_code)
        return [
            self._call(
                "correlate",
                "network",
                "correlate_alarms",
                arguments,
                1,
                parallel_group="causal_analysis",
            ),
            self._call(
                "root_cause",
                "network",
                "rank_root_cause_candidates",
                arguments,
                1,
                parallel_group="causal_analysis",
            ),
        ]

    def _incident_search_calls(self, query: StructuredQuery) -> list[dict[str, object]]:
        arguments = self._snapshot_args(query, incident_code=query.incident_code)
        return [
            self._call(
                "incident_alarms",
                "network",
                "search_alarms",
                arguments,
                1,
                parallel_group="incident_scope",
            ),
            self._call(
                "incident_outages",
                "network",
                "search_outages",
                arguments,
                1,
                parallel_group="incident_scope",
            ),
        ]

    def _scoped_network_calls(
        self, query: StructuredQuery
    ) -> list[dict[str, object]] | PlannerResult:
        if not any((query.location, query.technology, query.time_window)):
            return PlannerResult.clarification(
                PlannerReasonCode.MISSING_SAFE_OPERATIONAL_REFERENCE.value
            )
        arguments = self._snapshot_args(query)
        if query.location:
            arguments.update(city=query.location.city, district=query.location.district)
        if query.technology:
            arguments["technology"] = query.technology.value
        if query.time_window:
            arguments.update(
                from_time=query.time_window.from_time,
                to_time=query.time_window.to_time,
            )
        return [self._call("scoped_outages", "network", "get_longest_outage", arguments, 1)]

    @staticmethod
    def _snapshot_args(query: StructuredQuery, **values: object) -> dict[str, object]:
        return {"snapshot_identifier": query.snapshot_identifier, **values}

    @staticmethod
    def _call(
        call_id: str,
        server: str,
        tool_name: str,
        arguments: dict[str, object],
        execution_order: int,
        *,
        depends_on: list[str] | None = None,
        parallel_group: str | None = None,
    ) -> dict[str, object]:
        return {
            "call_id": call_id,
            "server": server,
            "tool_name": tool_name,
            "arguments": arguments,
            "depends_on": depends_on or [],
            "execution_order": execution_order,
            "parallel_group": parallel_group,
        }
