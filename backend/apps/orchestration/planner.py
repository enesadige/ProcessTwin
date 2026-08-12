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
    requires_customer_impact_evidence,
    requires_documentary_evidence,
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
    StructuredQueryIntent.ALARM_CORRELATION: frozenset(
        {RequestedOutput.SUMMARY, RequestedOutput.CORRELATION, RequestedOutput.EVIDENCE}
    ),
    StructuredQueryIntent.NETWORK_INVESTIGATION: frozenset(
        {
            RequestedOutput.SUMMARY,
            RequestedOutput.DETAILS,
            RequestedOutput.IMPACT,
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
            RequestedOutput.ELIGIBILITY,
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
        if query.intent == StructuredQueryIntent.ALARM_CORRELATION:
            return self._cross_incident_correlation_calls(query)
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
            if not query.retrieval_query:
                return PlannerResult.clarification(
                    PlannerReasonCode.MISSING_DOCUMENT_RETRIEVAL_QUERY.value
                )
            calls = [
                self._call(
                    "rule_documents",
                    "rule",
                    "search_rule_documents",
                    self._snapshot_args(
                        query,
                        query=query.retrieval_query,
                        search_mode="hybrid",
                        top_k=5,
                        include_scores=True,
                        embedding_provider=query.embedding_provider,
                    ),
                    1,
                    parallel_group="rule_document_context",
                )
            ]
            if query.causal_event_code:
                calls.append(
                    self._call(
                        "rule_evidence",
                        "rule",
                        "get_rule_evidence",
                        self._snapshot_args(query, causal_event_code=query.causal_event_code),
                        1,
                        parallel_group="rule_document_context",
                    )
                )
                calls.append(
                    self._call(
                        "compensation_evidence",
                        "compensation",
                        "get_compensation_evidence",
                        (
                            self._snapshot_args(
                                query, subscription_number=query.subscription_reference
                            )
                            if query.subscription_reference
                            else self._snapshot_args(
                                query, causal_event_code=query.causal_event_code
                            )
                        ),
                        1,
                        parallel_group="rule_document_context",
                    )
                )
            return calls
        return PlannerResult.unplannable(PlannerReasonCode.NO_SAFE_TOOL_MAPPING.value)

    def _cross_incident_correlation_calls(
        self, query: StructuredQuery
    ) -> list[dict[str, object]] | PlannerResult:
        if not query.causal_event_code:
            return PlannerResult.clarification(
                PlannerReasonCode.MISSING_SAFE_OPERATIONAL_REFERENCE.value
            )
        return [
            self._call(
                "cross_incident_correlation",
                "network",
                "correlate_causal_events",
                self._snapshot_args(
                    query,
                    causal_event_code=query.causal_event_code,
                    candidate_causal_event_code=query.comparison_causal_event_code,
                    window_minutes=query.correlation_window_minutes or 60,
                    direction=query.correlation_direction,
                    other_region_only=query.correlation_other_region_only,
                ),
                1,
            )
        ]

    def _network_calls(self, query: StructuredQuery) -> list[dict[str, object]] | PlannerResult:
        if query.causal_event_code:
            calls = self._causal_analysis_calls(query)
            self._append_rule_evidence_if_requested(query, calls)
            return calls
        if query.outage_code:
            calls = [
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
            self._append_rule_evidence_if_requested(query, calls)
            return calls
        if query.incident_code:
            return self._incident_search_calls(query)
        return self._scoped_network_calls(query)

    def _outage_impact_calls(
        self, query: StructuredQuery
    ) -> list[dict[str, object]] | PlannerResult:
        if query.outage_code:
            calls = [
                self._call(
                    "outage_details",
                    "network",
                    "get_outage_details",
                    self._snapshot_args(query, outage_code=query.outage_code),
                    1,
                )
            ]
            if requires_customer_impact_evidence(query):
                calls.append(
                    self._call(
                        "customer_impact",
                        "network",
                        "calculate_customer_impact",
                        self._snapshot_args(query, outage_code=query.outage_code),
                        2,
                        depends_on=["outage_details"],
                    )
                )
            if RequestedOutput.ROOT_CAUSE in query.requested_outputs:
                calls.append(
                    self._call(
                        "root_cause",
                        "network",
                        "rank_root_cause_candidates",
                        self._snapshot_args(query, outage_code=query.outage_code),
                        2 if not requires_customer_impact_evidence(query) else 3,
                        depends_on=[
                            "customer_impact"
                            if requires_customer_impact_evidence(query)
                            else "outage_details"
                        ],
                    )
                )
            self._append_rule_evidence_if_requested(query, calls)
            self._append_compensation_if_requested(query, calls)
            return calls
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
            self._append_rule_evidence_if_requested(query, calls)
            self._append_compensation_if_requested(query, calls)
            return calls
        if query.device_code:
            return [
                self._call(
                    "device_details",
                    "network",
                    "get_device_details",
                    self._snapshot_args(query, device_code=query.device_code),
                    1,
                ),
                self._call(
                    "customers_by_device",
                    "customer",
                    "list_customers_by_device",
                    self._snapshot_args(query, device_code=query.device_code),
                    2,
                    depends_on=["device_details"],
                ),
            ]
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
            if tool_name == "get_compensation_evidence" and query.subscription_reference:
                # The MCP contract deliberately accepts either a causal event or a
                # public subscription reference. Prefer the latter when supplied.
                arguments = self._snapshot_args(
                    query, subscription_number=query.subscription_reference
                )
            else:
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

    def _append_rule_evidence_if_requested(
        self, query: StructuredQuery, calls: list[dict[str, object]]
    ) -> None:
        if (
            RequestedOutput.EVIDENCE not in query.requested_outputs
            or not requires_documentary_evidence(query)
        ):
            return
        if query.outage_code and not query.causal_event_code:
            calls.append(
                self._call(
                    "rule_evidence",
                    "rule",
                    "get_rule_evidence",
                    self._snapshot_args(query, outage_code=query.outage_code),
                    max((int(call["execution_order"]) for call in calls), default=0) + 1,
                    depends_on=[str(calls[-1]["call_id"])] if calls else None,
                )
            )
            return
        calls.append(
            self._call(
                "rule_evidence",
                "rule",
                "get_rule_evidence",
                (
                    self._snapshot_args(query, causal_event_code=query.causal_event_code)
                    if query.causal_event_code
                    else self._snapshot_args(query, outage_code=query.outage_code)
                ),
                1,
                parallel_group="causal_analysis",
            )
        )

    def _append_compensation_if_requested(
        self, query: StructuredQuery, calls: list[dict[str, object]]
    ) -> None:
        rule_only_compensation = (
            RequestedOutput.EVIDENCE in query.requested_outputs
            and query.decision_type == "compensation"
        )
        if (
            RequestedOutput.ELIGIBILITY not in query.requested_outputs
            and not rule_only_compensation
        ):
            return
        arguments = self._snapshot_args(
            query,
            subscription_number=query.subscription_reference,
            outage_code=query.outage_code,
            causal_event_code=query.causal_event_code,
        )
        calls.append(
            self._call(
                "compensation_evidence",
                "compensation",
                "get_compensation_evidence",
                {key: value for key, value in arguments.items() if value is not None},
                max((int(call["execution_order"]) for call in calls), default=0) + 1,
                depends_on=[str(calls[-1]["call_id"])] if calls else None,
            )
        )

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
        if query.location and query.time_window:
            return [
                self._call(
                    "aggregate_location_impact",
                    "network",
                    "aggregate_location_impact",
                    arguments,
                    1,
                )
            ]
        return [self._call("scoped_outages", "network", "get_longest_outage", arguments, 1)]

    @staticmethod
    def _snapshot_args(structured_query: StructuredQuery, **values: object) -> dict[str, object]:
        return {"snapshot_identifier": structured_query.snapshot_identifier, **values}

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
