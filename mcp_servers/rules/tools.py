from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from mcp_servers.rules import RULE_MCP_VERSION
from mcp_servers.rules.models import (
    DetectRuleConflictsInput,
    FindRelatedRulesInput,
    GetRuleInput,
    GetRulesEffectiveAtInput,
    RuleEvidenceInput,
    RuleVersionHistoryInput,
    SearchRuleDocumentsInput,
    SearchRulesInput,
)
from mcp_servers.shared.backend_client import InternalAPIClient, InternalAPIClientError
from mcp_servers.shared.contracts import (
    MCPError,
    MCPErrorCode,
    MCPEvidence,
    MCPMetadata,
    MCPToolResponse,
    MCPWarning,
)


class RuleToolDefinition:
    def __init__(
        self,
        *,
        name: str,
        description: str,
        input_model: type[BaseModel],
        method: str,
        path_builder: Callable[[BaseModel], str],
        params_builder: Callable[[BaseModel], dict[str, Any]],
        body_builder: Callable[[BaseModel], dict[str, Any]] | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.input_model = input_model
        self.method = method
        self.path_builder = path_builder
        self.params_builder = params_builder
        self.body_builder = body_builder


def _path(template: str, field_name: str | None = None):
    def build(model: BaseModel) -> str:
        if field_name is None:
            return template
        return template.format(value=getattr(model, field_name))

    return build


def _causal_evidence_path(model: BaseModel) -> str:
    code = getattr(model, "causal_event_code", None)
    if code:
        return f"/api/internal/v1/operations/causal-events/{code}/analysis/"
    return "/api/internal/v1/rules/evidence/"


def _params(model: BaseModel) -> dict[str, Any]:
    raw = model.model_dump(mode="json", exclude_none=True, exclude_defaults=True)
    raw.pop("request_id", None)
    return raw


def _params_without_path_rule_code(model: BaseModel) -> dict[str, Any]:
    raw = _params(model)
    raw.pop("rule_code", None)
    return raw


RULE_TOOL_DEFINITIONS: dict[str, RuleToolDefinition] = {
    "search_rules": RuleToolDefinition(
        name="search_rules",
        description=(
            "Search RuleSet, Rule, and RuleVersion summaries with explicit snapshot "
            "selection and stable pagination."
        ),
        input_model=SearchRulesInput,
        method="GET",
        path_builder=_path("/api/internal/v1/rules/"),
        params_builder=_params,
    ),
    "get_rule": RuleToolDefinition(
        name="get_rule",
        description=(
            "Return one rule and a deterministic version selection by version, "
            "event time, or unambiguous active version."
        ),
        input_model=GetRuleInput,
        method="GET",
        path_builder=_path("/api/internal/v1/rules/{value}/", "rule_code"),
        params_builder=_params_without_path_rule_code,
    ),
    "get_rules_effective_at": RuleToolDefinition(
        name="get_rules_effective_at",
        description=(
            "List RuleVersions effective at a timezone-aware event time without "
            "evaluating conditions."
        ),
        input_model=GetRulesEffectiveAtInput,
        method="GET",
        path_builder=_path("/api/internal/v1/rules/effective-at/"),
        params_builder=_params,
    ),
    "get_rule_version_history": RuleToolDefinition(
        name="get_rule_version_history",
        description="Return all versions for one rule in validity order.",
        input_model=RuleVersionHistoryInput,
        method="GET",
        path_builder=_path("/api/internal/v1/rules/{value}/versions/", "rule_code"),
        params_builder=_params_without_path_rule_code,
    ),
    "find_related_rules": RuleToolDefinition(
        name="find_related_rules",
        description=(
            "Find rules related by rule set, family, conflict group, action type, "
            "or price basis without natural-language search."
        ),
        input_model=FindRelatedRulesInput,
        method="GET",
        path_builder=_path("/api/internal/v1/rules/related/"),
        params_builder=_params,
    ),
    "detect_rule_conflicts": RuleToolDefinition(
        name="detect_rule_conflicts",
        description=(
            "Return conflict-group candidates and deterministic ordering hints "
            "without choosing a winning rule or calculating compensation."
        ),
        input_model=DetectRuleConflictsInput,
        method="GET",
        path_builder=_path("/api/internal/v1/rules/conflicts/"),
        params_builder=_params,
    ),
    "get_rule_evidence": RuleToolDefinition(
        name="get_rule_evidence",
        description=(
            "Read existing DecisionEvidence records by hash, evaluation, rule, "
            "rule set, outage, or subscription."
        ),
        input_model=RuleEvidenceInput,
        method="GET",
        path_builder=_causal_evidence_path,
        params_builder=_params,
    ),
    "search_rule_documents": RuleToolDefinition(
        name="search_rule_documents",
        description=(
            "Search rule and procedure source text with explicit snapshot and date "
            "filters; this tool does not make rule or compensation decisions."
        ),
        input_model=SearchRuleDocumentsInput,
        method="POST",
        path_builder=_path("/api/internal/v1/rag/search/"),
        params_builder=lambda _model: {},
        body_builder=_params,
    ),
}


class RuleMCPTools:
    def __init__(self, client: InternalAPIClient) -> None:
        self.client = client

    def run(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None,
    ) -> MCPToolResponse[dict[str, Any]]:
        definition = RULE_TOOL_DEFINITIONS.get(tool_name)
        if definition is None:
            return self._failure(
                tool_name=tool_name,
                request_id=None,
                snapshot_identifier=None,
                error=MCPError(
                    code=MCPErrorCode.NOT_FOUND,
                    message="Unknown Rule MCP tool.",
                    details={"tool_name": tool_name},
                ),
            )
        try:
            model = definition.input_model.model_validate(arguments or {})
        except ValidationError as exc:
            request_id = (arguments or {}).get("request_id")
            snapshot_identifier = (arguments or {}).get("snapshot_identifier")
            return self._failure(
                tool_name=tool_name,
                request_id=request_id,
                snapshot_identifier=snapshot_identifier,
                error=MCPError(
                    code=MCPErrorCode.VALIDATION_ERROR,
                    message="Invalid Rule MCP tool input.",
                    details={"errors": exc.errors(include_url=False)},
                ),
            )
        try:
            payload = self.client.request_json(
                definition.method,
                definition.path_builder(model),
                request_id=model.request_id,
                json=definition.body_builder(model) if definition.body_builder else None,
                params=definition.params_builder(model),
            )
        except InternalAPIClientError as exc:
            return self._failure(
                tool_name=tool_name,
                request_id=model.request_id,
                snapshot_identifier=model.snapshot_identifier,
                error=exc.mcp_error,
                evaluation_time=getattr(model, "evaluation_time", None),
            )
        return self._success(tool_name=tool_name, model=model, payload=payload)

    def _success(
        self,
        *,
        tool_name: str,
        model: BaseModel,
        payload: dict[str, Any],
    ) -> MCPToolResponse[dict[str, Any]]:
        backend_metadata = payload.get("metadata", {})
        data = self._response_data(tool_name, payload)
        snapshot_details = backend_metadata.get("snapshot", {}) or data.get("snapshot", {})
        metadata = MCPMetadata(
            tool_name=f"rules.{tool_name}",
            tool_version=RULE_MCP_VERSION,
            request_id=backend_metadata.get("correlation_id") or model.request_id or str(uuid4()),
            deterministic=True,
            snapshot_identifier=model.snapshot_identifier,
            reference_datetime=snapshot_details.get("reference_datetime"),
            evaluation_time=getattr(model, "evaluation_time", None),
            snapshot_details=snapshot_details,
        )
        return MCPToolResponse[dict[str, Any]](
            success=True,
            data=data,
            metadata=metadata,
            warnings=[
                MCPWarning.model_validate(warning) for warning in payload.get("warnings", [])
            ],
            evidence=[
                MCPEvidence.model_validate(evidence) for evidence in payload.get("evidence", [])
            ],
        )

    @staticmethod
    def _response_data(tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload.get("data", {}))
        if tool_name == "get_rule_evidence" and "causal_event" in data:
            impact = data.get("impact", {})
            compensation = data.get("compensation") or {}
            return {
                "causal_event_code": data["causal_event"].get("code"),
                "verified_impacted_count": impact.get("verified_impacted", 0),
                "selected_rule_version": compensation.get("selected_rule_version"),
                "baseline": compensation.get("baseline"),
                "candidate": compensation.get("candidate"),
                "difference_summary": compensation.get("difference_summary"),
                "eligible_count": compensation.get("eligible", 0),
                "ineligible_pending_count": compensation.get("ineligible_pending", 0),
                "reason_codes": impact.get("reason_codes", {}),
                "evidence": data.get("evidence"),
            }
        if tool_name != "search_rule_documents":
            return data

        embedding = data.pop("embedding", None) or {}
        data["embedding_provider"] = embedding.get("provider")
        data["embedding_model"] = embedding.get("model")
        data["embedding_dimensions"] = embedding.get("dimensions")
        data["embedding_version"] = embedding.get("embedding_version")
        data["document_prompt_version"] = embedding.get("document_prompt_version")
        data["query_prompt_version"] = embedding.get("query_prompt_version")
        data["correlation_id"] = payload.get("metadata", {}).get("correlation_id")
        data["results"] = [
            {
                key: value
                for key, value in result.items()
                if key not in {"embedding", "vector", "raw_embedding"}
            }
            for result in data.get("results", [])
        ]
        return data

    def _failure(
        self,
        *,
        tool_name: str,
        request_id: str | None,
        snapshot_identifier: str | None,
        error: MCPError,
        evaluation_time=None,
    ) -> MCPToolResponse[dict[str, Any]]:
        return MCPToolResponse[dict[str, Any]](
            success=False,
            error=error,
            metadata=MCPMetadata(
                tool_name=f"rules.{tool_name}",
                tool_version=RULE_MCP_VERSION,
                request_id=request_id or str(uuid4()),
                deterministic=True,
                snapshot_identifier=snapshot_identifier,
                evaluation_time=evaluation_time,
            ),
        )
