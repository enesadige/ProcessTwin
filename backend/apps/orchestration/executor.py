"""Deterministic, audited execution of already validated MCP tool plans."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from time import monotonic
from typing import Any, Protocol

from django.conf import settings
from django.db import transaction
from mcp_servers.compensation.tools import CompensationMCPTools
from mcp_servers.customer.tools import CustomerMCPTools
from mcp_servers.network.tools import NetworkMCPTools
from mcp_servers.rules.tools import RuleMCPTools
from mcp_servers.shared.backend_client import InternalAPIClient, InternalAPIClientConfig
from mcp_servers.shared.contracts import MCPToolResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from apps.core.correlation import is_valid_correlation_id
from apps.orchestration.models import TERMINAL_QUERY_RUN_STATUSES, QueryRun, QueryRunStatus
from apps.orchestration.services import QueryRunError, QueryRunService, sanitize_text
from apps.orchestration.stdio_runner import StdioMCPToolRunner
from apps.orchestration.tool_plan import MCP_TOOL_REGISTRIES, MCPServer, ToolCall, ToolPlan

DEFAULT_MAX_ATTEMPTS = 2
MAX_EXECUTOR_ATTEMPTS = 3

# There is no retry metadata in the current MCP tool registry. This explicit,
# read-only subset is therefore deliberately narrow and reviewed with the plan.
RETRYABLE_TOOL_KEYS = frozenset(
    {
        (MCPServer.NETWORK, "aggregate_location_impact"),
        (MCPServer.NETWORK, "correlate_alarms"),
        (MCPServer.NETWORK, "correlate_causal_events"),
        (MCPServer.NETWORK, "rank_root_cause_candidates"),
        (MCPServer.NETWORK, "get_outage_details"),
        (MCPServer.NETWORK, "calculate_customer_impact"),
        (MCPServer.CUSTOMER, "get_customer_outage_history"),
        (MCPServer.RULE, "search_rules"),
        (MCPServer.RULE, "get_rule_evidence"),
        (MCPServer.RULE, "search_rule_documents"),
        (MCPServer.COMPENSATION, "get_compensation_evidence"),
    }
)

_SAFE_SUMMARY_KEYS = frozenset(
    {
        "causal_event_code",
        "code",
        "status",
        "reason_code",
        "reason_codes",
        "role_counts",
        "count",
        "counts",
        "total",
        "total_count",
        "eligible",
        "eligibility",
        "source",
        "source_version",
        "version",
        "schema_version",
        "deterministic",
        "snapshot_identifier",
        "root_resource_type",
        "root_cause_score",
        "root_cause_confidence",
    }
)
_FORBIDDEN_SUMMARY_PARTS = frozenset(
    {
        "authorization",
        "credential",
        "password",
        "secret",
        "token",
        "api_key",
        "header",
        "ip",
        "mac",
        "customer",
        "subscriber",
        "subscription",
        "raw_",
        "payload",
        "session",
    }
)


class ToolExecutionStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED_DEPENDENCY_FAILED = "skipped_dependency_failed"


class ExecutorStatus(StrEnum):
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"


class ToolExecutionResult(BaseModel):
    """Per-call runtime result; `normalized_response` is never persisted."""

    model_config = ConfigDict(extra="forbid")

    call_id: str
    server: MCPServer
    tool_name: str
    status: ToolExecutionStatus
    correlation_id: str
    attempt_count: int = Field(ge=0, le=MAX_EXECUTOR_ATTEMPTS)
    duration_ms: int = Field(ge=0)
    safe_result_summary: dict[str, Any] = Field(default_factory=dict)
    result_fingerprint: str | None = None
    error_code: str | None = None
    error_summary: str | None = None
    normalized_response: dict[str, Any] | None = None

    def to_audit_dict(self) -> dict[str, Any]:
        return self.model_dump(exclude={"normalized_response"}, exclude_none=True)


class ExecutorResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ExecutorStatus
    snapshot_identifier: str
    call_results: list[ToolExecutionResult]
    succeeded_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    skipped_count: int = Field(ge=0)


class MCPToolRunner(Protocol):
    def run(
        self, tool_name: str, arguments: dict[str, Any] | None
    ) -> MCPToolResponse[dict[str, Any]]: ...


@dataclass(frozen=True)
class _PreparedExecution:
    query_run: QueryRun
    existing_results: dict[str, ToolExecutionResult]


class ToolExecutor:
    """Run a persisted ToolPlan without merging or interpreting its results."""

    def __init__(
        self,
        *,
        tool_runners: Mapping[MCPServer, MCPToolRunner] | None = None,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> None:
        if not 1 <= max_attempts <= MAX_EXECUTOR_ATTEMPTS:
            raise ValueError("max_attempts must be between 1 and 3")
        self.max_attempts = max_attempts
        self._tool_runners = dict(tool_runners) if tool_runners is not None else None

    def execute(
        self,
        query_run: QueryRun,
        tool_plan: ToolPlan | Mapping[str, Any],
    ) -> ExecutorResult:
        plan = tool_plan if isinstance(tool_plan, ToolPlan) else ToolPlan.model_validate(tool_plan)
        prepared = self._prepare_execution(query_run=query_run, tool_plan=plan)
        # The facade retains its original instance for result finalization.
        query_run.refresh_from_db()
        results = dict(prepared.existing_results)

        for call in plan.calls:
            if call.call_id in results:
                continue
            dependency_results = [results[dependency] for dependency in call.depends_on]
            if any(result.status != ToolExecutionStatus.SUCCEEDED for result in dependency_results):
                result = self._skipped_dependency_result(prepared.query_run, call)
            else:
                result = self._execute_call(prepared.query_run, call)
            self._persist_result(query_run=prepared.query_run, result=result)
            results[call.call_id] = result

        ordered_results = [results[call.call_id] for call in plan.calls]
        return self._build_executor_result(plan.snapshot_identifier, ordered_results)

    def _prepare_execution(self, *, query_run: QueryRun, tool_plan: ToolPlan) -> _PreparedExecution:
        with transaction.atomic():
            locked_run = (
                QueryRun.objects.select_for_update()
                .select_related("data_snapshot")
                .get(pk=query_run.pk)
            )
            status = QueryRunStatus(locked_run.status)
            if status in TERMINAL_QUERY_RUN_STATUSES:
                raise QueryRunError(
                    message="Terminal QueryRun records cannot execute tools.",
                    code="query_run_execution_terminal",
                )
            if status not in {QueryRunStatus.PLANNED, QueryRunStatus.EXECUTING}:
                raise QueryRunError(
                    message="QueryRun must be planned before execution.",
                    code="query_run_execution_requires_planned",
                )
            self._validate_persisted_plan(locked_run, tool_plan)
            existing_results = self._parse_existing_results(locked_run, tool_plan)
            if status == QueryRunStatus.PLANNED and len(existing_results) < len(tool_plan.calls):
                QueryRunService().transition(locked_run, target_status=QueryRunStatus.EXECUTING)
            return _PreparedExecution(query_run=locked_run, existing_results=existing_results)

    @staticmethod
    def _validate_persisted_plan(query_run: QueryRun, tool_plan: ToolPlan) -> None:
        if tool_plan.snapshot_identifier != query_run.data_snapshot.snapshot_key:
            raise QueryRunError(
                message="Tool plan snapshot does not match QueryRun.",
                code="tool_plan_snapshot_mismatch",
            )
        if query_run.planned_tools != tool_plan.to_planned_tools():
            raise QueryRunError(
                message="Tool plan does not match QueryRun audit record.",
                code="query_run_tool_plan_mismatch",
            )
        for call in tool_plan.calls:
            definition = MCP_TOOL_REGISTRIES[call.server].get(call.tool_name)
            if definition is None:
                raise QueryRunError(
                    message="Tool is not allowed.", code="executor_tool_not_allowed"
                )
            try:
                definition.input_model.model_validate(dict(call.arguments))
            except ValidationError as exc:
                raise QueryRunError(
                    message="Tool arguments are invalid.", code="executor_tool_arguments_invalid"
                ) from exc

    @staticmethod
    def _parse_existing_results(
        query_run: QueryRun, tool_plan: ToolPlan
    ) -> dict[str, ToolExecutionResult]:
        calls_by_id = {call.call_id: call for call in tool_plan.calls}
        results: dict[str, ToolExecutionResult] = {}
        for record in query_run.executed_tools:
            try:
                result = ToolExecutionResult.model_validate(record)
            except ValidationError as exc:
                raise QueryRunError(
                    message="QueryRun execution audit is invalid.",
                    code="query_run_execution_audit_invalid",
                ) from exc
            call = calls_by_id.get(result.call_id)
            if call is None or (result.server, result.tool_name) != (call.server, call.tool_name):
                raise QueryRunError(
                    message="QueryRun execution audit does not match ToolPlan.",
                    code="query_run_execution_audit_mismatch",
                )
            if result.call_id in results:
                raise QueryRunError(
                    message="QueryRun execution audit contains duplicate calls.",
                    code="query_run_execution_audit_duplicate",
                )
            results[result.call_id] = result
        return results

    def _execute_call(self, query_run: QueryRun, call: ToolCall) -> ToolExecutionResult:
        correlation_id = self._correlation_id(query_run, call)
        arguments = dict(call.arguments)
        arguments["request_id"] = correlation_id
        definition = MCP_TOOL_REGISTRIES[call.server][call.tool_name]
        try:
            model = definition.input_model.model_validate(arguments)
        except ValidationError as exc:
            raise QueryRunError(
                message="Tool arguments are invalid.", code="executor_tool_arguments_invalid"
            ) from exc
        normalized_arguments = model.model_dump(mode="json", exclude_none=True)

        started = monotonic()
        response: MCPToolResponse[dict[str, Any]] | None = None
        attempts = 0
        for attempts in range(1, self.max_attempts + 1):
            try:
                response = self._runner_for(call.server).run(call.tool_name, normalized_arguments)
            except Exception:
                return self._failed_result(
                    call=call,
                    correlation_id=correlation_id,
                    attempt_count=attempts,
                    duration_ms=self._duration_ms(started),
                    error_code="executor_transport_error",
                    error_summary="MCP tool execution could not be completed.",
                )
            if response.success or not self._should_retry(call, response, attempts):
                break

        assert response is not None
        duration_ms = self._duration_ms(started)
        if not response.success:
            error = response.error
            return self._failed_result(
                call=call,
                correlation_id=correlation_id,
                attempt_count=attempts,
                duration_ms=duration_ms,
                error_code=(error.code.value if error else "mcp_tool_failed"),
                error_summary=(error.message if error else "MCP tool execution failed."),
            )

        normalized_response = response.model_dump(mode="json", exclude_none=True)
        summary = self._safe_result_summary(normalized_response)
        return ToolExecutionResult(
            call_id=call.call_id,
            server=call.server,
            tool_name=call.tool_name,
            status=ToolExecutionStatus.SUCCEEDED,
            correlation_id=correlation_id,
            attempt_count=attempts,
            duration_ms=duration_ms,
            safe_result_summary=summary,
            result_fingerprint=self._fingerprint(summary),
            normalized_response=normalized_response,
        )

    def _runner_for(self, server: MCPServer) -> MCPToolRunner:
        if self._tool_runners is None:
            if getattr(settings, "ORCHESTRATION_MCP_TRANSPORT", "direct") == "stdio":
                self._tool_runners = {item: StdioMCPToolRunner(item) for item in MCPServer}
                return self._tool_runners[server]
            config = InternalAPIClientConfig.from_env()
            client = InternalAPIClient(config=config)
            self._tool_runners = {
                MCPServer.NETWORK: NetworkMCPTools(client),
                MCPServer.CUSTOMER: CustomerMCPTools(client),
                MCPServer.RULE: RuleMCPTools(client),
                MCPServer.COMPENSATION: CompensationMCPTools(client),
            }
        runner = self._tool_runners.get(server)
        if runner is None:
            raise QueryRunError(
                message="MCP server runner is not configured.", code="executor_runner_unavailable"
            )
        return runner

    def _should_retry(
        self,
        call: ToolCall,
        response: MCPToolResponse[dict[str, Any]],
        attempts: int,
    ) -> bool:
        return bool(
            attempts < self.max_attempts
            and not response.success
            and response.error is not None
            and response.error.retryable
            and (call.server, call.tool_name) in RETRYABLE_TOOL_KEYS
        )

    @staticmethod
    def _correlation_id(query_run: QueryRun, call: ToolCall) -> str:
        base = (
            query_run.request_id
            if is_valid_correlation_id(query_run.request_id)
            else query_run.query_run_code
        )
        maximum_base_length = 128 - len(call.call_id) - 1
        correlation_id = f"{base[:maximum_base_length]}:{call.call_id}"
        if is_valid_correlation_id(correlation_id):
            return correlation_id
        digest = hashlib.sha256(f"{query_run.query_run_code}:{call.call_id}".encode()).hexdigest()
        return f"qr:{digest[:32]}:{call.call_id}"

    def _skipped_dependency_result(
        self, query_run: QueryRun, call: ToolCall
    ) -> ToolExecutionResult:
        return ToolExecutionResult(
            call_id=call.call_id,
            server=call.server,
            tool_name=call.tool_name,
            status=ToolExecutionStatus.SKIPPED_DEPENDENCY_FAILED,
            correlation_id=self._correlation_id(query_run, call),
            attempt_count=0,
            duration_ms=0,
            error_code="dependency_failed",
            error_summary="A required tool call did not succeed.",
        )

    @staticmethod
    def _failed_result(
        *,
        call: ToolCall,
        correlation_id: str,
        attempt_count: int,
        duration_ms: int,
        error_code: str,
        error_summary: str,
    ) -> ToolExecutionResult:
        return ToolExecutionResult(
            call_id=call.call_id,
            server=call.server,
            tool_name=call.tool_name,
            status=ToolExecutionStatus.FAILED,
            correlation_id=correlation_id,
            attempt_count=attempt_count,
            duration_ms=duration_ms,
            error_code=error_code,
            error_summary=sanitize_text(error_summary),
        )

    def _persist_result(self, *, query_run: QueryRun, result: ToolExecutionResult) -> None:
        QueryRunService().append_execution_record(query_run, record=result.to_audit_dict())

    @staticmethod
    def _safe_result_summary(response: Mapping[str, Any]) -> dict[str, Any]:
        data = response.get("data")
        summary = ToolExecutor._filter_safe_summary(data)
        metadata = response.get("metadata")
        if isinstance(metadata, Mapping):
            for key in ("schema_version", "snapshot_identifier", "deterministic", "tool_version"):
                value = metadata.get(key)
                if value is not None:
                    summary[key] = value
        return summary

    @staticmethod
    def _filter_safe_summary(value: Any) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            return {}
        summary: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = str(key).lower()
            if any(part in normalized_key for part in _FORBIDDEN_SUMMARY_PARTS):
                continue
            if normalized_key not in _SAFE_SUMMARY_KEYS:
                continue
            if isinstance(item, Mapping):
                nested = ToolExecutor._filter_safe_summary(item)
                if nested:
                    summary[str(key)] = nested
            elif isinstance(item, list):
                if all(isinstance(entry, (str, int, float, bool)) for entry in item):
                    summary[str(key)] = list(item)
            elif isinstance(item, (str, int, float, bool)) or item is None:
                summary[str(key)] = item
        return summary

    @staticmethod
    def _fingerprint(summary: Mapping[str, Any]) -> str:
        payload = json.dumps(summary, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()

    @staticmethod
    def _duration_ms(started: float) -> int:
        return max(0, round((monotonic() - started) * 1000))

    @staticmethod
    def _build_executor_result(
        snapshot_identifier: str, call_results: list[ToolExecutionResult]
    ) -> ExecutorResult:
        succeeded_count = sum(
            result.status == ToolExecutionStatus.SUCCEEDED for result in call_results
        )
        failed_count = sum(result.status == ToolExecutionStatus.FAILED for result in call_results)
        skipped_count = sum(
            result.status == ToolExecutionStatus.SKIPPED_DEPENDENCY_FAILED
            for result in call_results
        )
        status = (
            ExecutorStatus.SUCCEEDED
            if succeeded_count == len(call_results)
            else ExecutorStatus.FAILED
            if succeeded_count == 0
            else ExecutorStatus.PARTIAL
        )
        return ExecutorResult(
            status=status,
            snapshot_identifier=snapshot_identifier,
            call_results=call_results,
            succeeded_count=succeeded_count,
            failed_count=failed_count,
            skipped_count=skipped_count,
        )
