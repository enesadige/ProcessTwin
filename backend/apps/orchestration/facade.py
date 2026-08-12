"""Thin synchronous composition of the validated orchestration layers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from apps.datasets.models import DataSnapshot
from apps.orchestration.executor import ExecutorResult, ToolExecutor
from apps.orchestration.models import QueryRun, QueryRunStatus
from apps.orchestration.natural_language_intake import (
    SEMANTIC_DECOMPOSITION_PROMPT_VERSION,
    DeterministicStructuredQueryParser,
    LLMSemanticDecomposer,
    NaturalLanguageQueryParseError,
)
from apps.orchestration.planner import (
    DeterministicToolPlanner,
    PlannerResultStatus,
)
from apps.orchestration.providers.registry import get_llm_descriptor
from apps.orchestration.response_builder import (
    ResponseGenerationMode,
    ValidatedNaturalLanguageResponse,
    ValidatedResponseBuilder,
)
from apps.orchestration.result_merge import ResultMergerValidator
from apps.orchestration.services import (
    QueryRunError,
    QueryRunIdempotencyConflictError,
    QueryRunService,
)
from apps.orchestration.structured_query import StructuredQuery
from apps.rag.providers.registry import get_embedding_descriptor


class OrchestrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    snapshot_identifier: str = Field(min_length=3, max_length=160)
    idempotency_key: str = Field(min_length=1, max_length=160)
    original_query: str = Field(min_length=1, max_length=10000)
    structured_query: StructuredQuery | None = None
    llm_provider: Literal["ollama", "gemini"] | None = None
    embedding_provider: Literal["ollama", "gemini"] | None = None
    response_mode: ResponseGenerationMode = ResponseGenerationMode.DETERMINISTIC

    @model_validator(mode="after")
    def validate_snapshot_context(self):
        if (
            self.structured_query
            and self.snapshot_identifier != self.structured_query.snapshot_identifier
        ):
            raise ValueError("request snapshot does not match structured query")
        if not self.idempotency_key.strip() or not self.original_query.strip():
            raise ValueError("request fields are invalid")
        return self


class OrchestrationError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    retry_requires_new_idempotency_key: bool = False


class OrchestrationClarification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    reasons: list[str]
    message: str


class OrchestrationEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_run_code: str | None = None
    status: str
    snapshot_identifier: str | None = None
    replayed: bool = False
    response: ValidatedNaturalLanguageResponse | None = None
    clarification: OrchestrationClarification | None = None
    error: OrchestrationError | None = None

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


@dataclass(frozen=True)
class OrchestrationOutcome:
    http_status: int
    envelope: OrchestrationEnvelope


class OrchestrationFacade:
    """Compose existing contracts without adding planner, execution, or LLM logic."""

    def __init__(
        self,
        *,
        planner: DeterministicToolPlanner | None = None,
        executor: ToolExecutor | None = None,
        merger: ResultMergerValidator | None = None,
        response_builder: ValidatedResponseBuilder | None = None,
        response_provider=None,
        intake_parser: DeterministicStructuredQueryParser | None = None,
    ) -> None:
        self._planner = planner or DeterministicToolPlanner()
        self._executor = executor or ToolExecutor()
        self._merger = merger or ResultMergerValidator()
        self._response_builder = response_builder or ValidatedResponseBuilder()
        self._response_provider = response_provider
        self._intake_parser = intake_parser or DeterministicStructuredQueryParser()
        self._query_run_service = QueryRunService()

    def execute(
        self,
        request: OrchestrationRequest | Mapping[str, Any],
        *,
        request_id: str,
        owner=None,
    ) -> OrchestrationOutcome:
        try:
            normalized_request = (
                request
                if isinstance(request, OrchestrationRequest)
                else OrchestrationRequest.model_validate(request)
            )
        except ValidationError:
            return self._error(400, "validation_error", "Request is invalid.")

        snapshot = self._snapshot(normalized_request.snapshot_identifier)
        if snapshot is None:
            return self._error(404, "snapshot_not_found", "Snapshot was not found.")
        try:
            query_run, created = self._query_run_service.create_or_get(
                data_snapshot=snapshot,
                idempotency_key=normalized_request.idempotency_key,
                original_query=normalized_request.original_query,
                request_id=request_id,
                owner=owner,
            )
        except QueryRunIdempotencyConflictError:
            return self._error(
                409, "idempotency_conflict", "Idempotency key conflicts with another run."
            )

        try:
            llm_descriptor = get_llm_descriptor(normalized_request.llm_provider)
            embedding_descriptor = get_embedding_descriptor(normalized_request.embedding_provider)
        except Exception:
            return self._error(400, "validation_error", "Requested provider is invalid.")

        structured_query = normalized_request.structured_query
        active_provider = self._response_provider
        if structured_query is None:
            try:
                parsed = self._intake_parser.parse(
                    original_query=normalized_request.original_query,
                    snapshot=snapshot,
                )
            except NaturalLanguageQueryParseError as exc:
                return self._error(
                    422 if exc.code in {"invalid_structured_query", "reference_not_found"} else 503,
                    exc.code,
                    "Query intake could not produce a safe structured query.",
                    query_run=query_run,
                )
            structured_query = parsed.structured_query
            parser_name = "deterministic"
            parser_version = parsed.prompt_version
            response_mode = ResponseGenerationMode.LLM_ASSISTED
            if active_provider is None:
                try:
                    active_provider = llm_descriptor.create_provider()
                except Exception:
                    active_provider = None
            if active_provider is not None:
                decomposition = LLMSemanticDecomposer(active_provider).merge(
                    original_query=normalized_request.original_query,
                    deterministic_query=structured_query,
                )
                structured_query = decomposition.structured_query
                if decomposition.accepted:
                    parser_version = f"{parser_version}+{SEMANTIC_DECOMPOSITION_PROMPT_VERSION}"
        else:
            parser_name = "replay"
            parser_version = "structured-query.v1"
            response_mode = normalized_request.response_mode
        structured_query = structured_query.model_copy(
            update={
                "embedding_provider": (
                    embedding_descriptor.provider
                    if embedding_descriptor.provider in {"ollama", "gemini"}
                    else None
                )
            }
        )
        if not created and query_run.structured_query != structured_query.to_audit_dict():
            persisted = StructuredQuery.model_validate(query_run.structured_query)
            incoming_audit = structured_query.to_audit_dict()
            persisted_audit = persisted.to_audit_dict()
            semantic_keys = {
                "semantic_dimensions",
                "semantic_decomposition_status",
                "semantic_decomposition_failure",
            }
            if {
                key: value for key, value in incoming_audit.items() if key not in semantic_keys
            } == {key: value for key, value in persisted_audit.items() if key not in semantic_keys}:
                structured_query = persisted
            else:
                return self._error(
                    409, "idempotency_conflict", "Idempotency key conflicts with another request."
                )

        if not created:
            replay = self._replay(query_run, structured_query, response_mode)
            if replay is not None:
                return replay

        try:
            if created:
                self._query_run_service.save_provider_provenance(
                    query_run,
                    requested_llm_provider=normalized_request.llm_provider,
                    resolved_llm_provider=llm_descriptor.provider,
                    resolved_llm_model=llm_descriptor.model,
                    requested_embedding_provider=normalized_request.embedding_provider,
                    resolved_embedding_provider=embedding_descriptor.provider,
                    resolved_embedding_model=embedding_descriptor.model,
                    embedding_prompt_version=embedding_descriptor.query_prompt_version,
                    structured_query_parser=parser_name,
                    structured_query_parser_version=parser_version,
                )
                self._query_run_service.save_structured_query(
                    query_run, structured_query=structured_query
                )
            planner_result = self._planner.plan_and_save(query_run, structured_query)
            if planner_result.status != PlannerResultStatus.PLANNED:
                return self._planner_outcome(
                    query_run, planner_result.status, planner_result.reason_codes
                )
            assert planner_result.tool_plan is not None
            execution_result = self._executor.execute(query_run, planner_result.tool_plan)
            validated = self._merger.validate_and_merge(
                query_run, planner_result.tool_plan, execution_result
            )
            finalized_run = self._merger.finalize_query_run(query_run, validated)
            if QueryRunStatus(finalized_run.status) == QueryRunStatus.FAILED:
                return self._failed_run_outcome(finalized_run, execution_result)
            self._query_run_service.save_response_audit(
                finalized_run,
                audit=self._pending_response_audit(
                    provider=active_provider,
                    fallback_provider=llm_descriptor,
                ),
            )
            response = self._response_builder.build(
                finalized_run,
                mode=response_mode,
                provider_name=llm_descriptor.provider,
                provider=active_provider,
            )
            self._query_run_service.save_response_audit(
                finalized_run, audit=self._response_audit(response)
            )
            return OrchestrationOutcome(
                http_status=200,
                envelope=OrchestrationEnvelope(
                    query_run_code=finalized_run.query_run_code,
                    status=QueryRunStatus.COMPLETED,
                    snapshot_identifier=snapshot.snapshot_key,
                    response=response,
                ),
            )
        except QueryRunError:
            return self._error(
                500, "orchestration_internal_error", "Orchestration could not be completed."
            )
        except Exception:
            return self._error(
                500, "orchestration_internal_error", "Orchestration could not be completed."
            )

    def _replay(
        self,
        query_run: QueryRun,
        structured_query: StructuredQuery,
        response_mode: ResponseGenerationMode,
    ) -> OrchestrationOutcome | None:
        status = QueryRunStatus(query_run.status)
        if status == QueryRunStatus.COMPLETED:
            try:
                self._query_run_service.save_response_audit(
                    query_run,
                    audit=self._pending_response_audit(
                        provider=self._response_provider,
                        fallback_provider=(
                            get_llm_descriptor(self._response_provider.provider_name)
                            if self._response_provider is not None
                            else None
                        ),
                    ),
                )
                response = self._response_builder.build(
                    query_run,
                    mode=response_mode,
                    provider=self._response_provider,
                )
                self._query_run_service.save_response_audit(
                    query_run, audit=self._response_audit(response)
                )
            except Exception:
                return self._error(
                    500, "orchestration_internal_error", "Response rendering failed."
                )
            return OrchestrationOutcome(
                http_status=200,
                envelope=OrchestrationEnvelope(
                    query_run_code=query_run.query_run_code,
                    status=status,
                    snapshot_identifier=query_run.data_snapshot.snapshot_key,
                    replayed=True,
                    response=response,
                ),
            )

        if status in {QueryRunStatus.PENDING, QueryRunStatus.EXECUTING}:
            return self._error(
                202,
                "run_in_progress",
                "QueryRun is already in progress.",
                query_run=query_run,
                replayed=True,
            )
        if status == QueryRunStatus.FAILED:
            return self._error(
                self._failed_status_code(query_run.error_code),
                query_run.error_code or "query_run_failed",
                "QueryRun failed and cannot be replayed.",
                query_run=query_run,
                replayed=True,
                retry_requires_new_idempotency_key=True,
            )
        if status == QueryRunStatus.PLANNED and not query_run.planned_tools:
            planner_result = self._planner.plan(structured_query)
            if planner_result.status != PlannerResultStatus.PLANNED:
                return self._planner_outcome(
                    query_run, planner_result.status, planner_result.reason_codes, replayed=True
                )
        return None

    @staticmethod
    def _pending_response_audit(*, provider, fallback_provider) -> dict[str, Any]:
        provider_name = getattr(provider, "provider_name", None) or getattr(
            fallback_provider, "provider", None
        )
        model = getattr(provider, "model_name", None) or getattr(
            fallback_provider, "model", None
        )
        return {
            "status": "pending",
            "provider": provider_name,
            "model": model,
            "generation_mode": "pending",
            "selected_statement_ids": [],
            "grounded_relationships": [],
            "warnings": [],
        }

    @staticmethod
    def _response_audit(response: ValidatedNaturalLanguageResponse) -> dict[str, Any]:
        audit = dict(response.statement_selection_audit)
        audit.update(
            {
                "generation_mode": response.generation_mode.value,
                "warnings": list(response.warnings),
                "selected_statement_ids": audit.get("selected_statement_ids", []),
                "grounded_relationships": list(response.grounded_relationships),
                "narrative_synthesis": dict(response.narrative_synthesis_audit),
            }
        )
        return audit

    @staticmethod
    def _snapshot(identifier: str) -> DataSnapshot | None:
        return (
            DataSnapshot.objects.select_related("dataset_version")
            .filter(snapshot_key=identifier)
            .first()
        )

    def _planner_outcome(
        self,
        query_run: QueryRun,
        status: PlannerResultStatus,
        reasons: tuple[str, ...],
        *,
        replayed: bool = False,
    ) -> OrchestrationOutcome:
        if status == PlannerResultStatus.CLARIFICATION_REQUIRED:
            candidates = DeterministicStructuredQueryParser.clarification_candidates(
                original_query=query_run.original_query,
                snapshot=query_run.data_snapshot,
            )
            message = "Additional safe query scope is required."
            if len(candidates) > 1:
                message = (
                    "Birden fazla uygun olay bulundu. "
                    + ", ".join(candidates)
                    + " arasından hangisini kastediyorsunuz?"
                )
            return OrchestrationOutcome(
                http_status=422,
                envelope=OrchestrationEnvelope(
                    query_run_code=query_run.query_run_code,
                    status=QueryRunStatus.PLANNED,
                    snapshot_identifier=query_run.data_snapshot.snapshot_key,
                    replayed=replayed,
                    clarification=OrchestrationClarification(
                        code="clarification_required",
                        reasons=sorted(reasons),
                        message=message,
                    ),
                ),
            )
        return self._error(
            422,
            "planner_unplannable",
            "Query cannot be mapped to safe tools.",
            query_run=query_run,
            replayed=replayed,
        )

    def _failed_run_outcome(
        self, query_run: QueryRun, execution_result: ExecutorResult
    ) -> OrchestrationOutcome:
        return self._error(
            self._failed_status_code(query_run.error_code, execution_result),
            query_run.error_code or "validation_failed",
            "Validated execution could not be completed.",
            query_run=query_run,
            retry_requires_new_idempotency_key=True,
        )

    @staticmethod
    def _failed_status_code(error_code: str, execution_result: ExecutorResult | None = None) -> int:
        if error_code in {"executor_transport_error", "timeout", "network_error"}:
            return 503
        if execution_result and any(
            result.error_code in {"executor_transport_error", "timeout", "network_error"}
            for result in execution_result.call_results
        ):
            return 503
        return 422

    @staticmethod
    def _error(
        status: int,
        code: str,
        message: str,
        *,
        query_run: QueryRun | None = None,
        replayed: bool = False,
        retry_requires_new_idempotency_key: bool = False,
    ) -> OrchestrationOutcome:
        return OrchestrationOutcome(
            http_status=status,
            envelope=OrchestrationEnvelope(
                query_run_code=None if query_run is None else query_run.query_run_code,
                status="failed" if query_run is None else query_run.status,
                snapshot_identifier=None
                if query_run is None
                else query_run.data_snapshot.snapshot_key,
                replayed=replayed,
                error=OrchestrationError(
                    code=code,
                    message=message,
                    retry_requires_new_idempotency_key=retry_requires_new_idempotency_key,
                ),
            ),
        )
