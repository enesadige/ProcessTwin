from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from mcp_servers.compensation import COMPENSATION_MCP_VERSION
from mcp_servers.compensation.models import (
    CampaignEligibilityInput,
    CompensationEvidenceInput,
    CompensationOptionsInput,
    RankCompensationOptionsInput,
    RefundAmountInput,
    RefundEligibilityInput,
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


class CompensationToolDefinition:
    def __init__(
        self,
        *,
        name: str,
        description: str,
        input_model: type[BaseModel],
        method: str,
        path_builder: Callable[[BaseModel], str],
        payload_builder: Callable[[BaseModel], dict[str, Any]],
    ) -> None:
        self.name = name
        self.description = description
        self.input_model = input_model
        self.method = method
        self.path_builder = path_builder
        self.payload_builder = payload_builder


def _path(path: str):
    def build(_model: BaseModel) -> str:
        return path

    return build


def _causal_evidence_path(model: BaseModel) -> str:
    code = getattr(model, "causal_event_code", None)
    if code:
        return f"/api/internal/v1/operations/causal-events/{code}/analysis/"
    return "/api/internal/v1/compensation/evidence/"


def _payload(model: BaseModel) -> dict[str, Any]:
    raw = model.model_dump(mode="json", exclude_none=True, exclude_defaults=True)
    raw.pop("request_id", None)
    return raw


COMPENSATION_TOOL_DEFINITIONS: dict[str, CompensationToolDefinition] = {
    "evaluate_refund_eligibility": CompensationToolDefinition(
        name="evaluate_refund_eligibility",
        description=(
            "Evaluate refund eligibility without calculating amount or writing "
            "CompensationEvaluation/DecisionEvidence records."
        ),
        input_model=RefundEligibilityInput,
        method="POST",
        path_builder=_path("/api/internal/v1/compensation/eligibility/"),
        payload_builder=_payload,
    ),
    "calculate_refund_amount": CompensationToolDefinition(
        name="calculate_refund_amount",
        description=(
            "Calculate deterministic compensation amount; persist only when "
            "persist=true and the outage is finalizable."
        ),
        input_model=RefundAmountInput,
        method="POST",
        path_builder=_path("/api/internal/v1/compensation/amount/"),
        payload_builder=_payload,
    ),
    "evaluate_compensation_options": CompensationToolDefinition(
        name="evaluate_compensation_options",
        description="Return deterministic rule-set compensation options without persisting.",
        input_model=CompensationOptionsInput,
        method="POST",
        path_builder=_path("/api/internal/v1/compensation/options/"),
        payload_builder=_payload,
    ),
    "check_campaign_eligibility": CompensationToolDefinition(
        name="check_campaign_eligibility",
        description="Read campaign enrollment/applicability summary without mutating prices.",
        input_model=CampaignEligibilityInput,
        method="POST",
        path_builder=_path("/api/internal/v1/compensation/campaigns/check/"),
        payload_builder=_payload,
    ),
    "rank_compensation_options": CompensationToolDefinition(
        name="rank_compensation_options",
        description="Rank rule-set options using existing priority/conflict ordering only.",
        input_model=RankCompensationOptionsInput,
        method="POST",
        path_builder=_path("/api/internal/v1/compensation/options/rank/"),
        payload_builder=_payload,
    ),
    "get_compensation_evidence": CompensationToolDefinition(
        name="get_compensation_evidence",
        description="Read existing CompensationEvaluation and DecisionEvidence records.",
        input_model=CompensationEvidenceInput,
        method="GET",
        path_builder=_causal_evidence_path,
        payload_builder=_payload,
    ),
}


class CompensationMCPTools:
    def __init__(self, client: InternalAPIClient) -> None:
        self.client = client

    def run(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None,
    ) -> MCPToolResponse[dict[str, Any]]:
        definition = COMPENSATION_TOOL_DEFINITIONS.get(tool_name)
        if definition is None:
            return self._failure(
                tool_name=tool_name,
                request_id=None,
                snapshot_identifier=None,
                error=MCPError(
                    code=MCPErrorCode.NOT_FOUND,
                    message="Unknown Compensation MCP tool.",
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
                    message="Invalid Compensation MCP tool input.",
                    details={"errors": exc.errors(include_url=False)},
                ),
            )
        try:
            payload = definition.payload_builder(model)
            response = self.client.request_json(
                definition.method,
                definition.path_builder(model),
                request_id=model.request_id,
                json=payload if definition.method == "POST" else None,
                params=payload if definition.method == "GET" else None,
            )
        except InternalAPIClientError as exc:
            return self._failure(
                tool_name=tool_name,
                request_id=model.request_id,
                snapshot_identifier=model.snapshot_identifier,
                error=exc.mcp_error,
                evaluation_time=getattr(model, "evaluation_time", None),
            )
        return self._success(tool_name=tool_name, model=model, payload=response)

    def _success(
        self,
        *,
        tool_name: str,
        model: BaseModel,
        payload: dict[str, Any],
    ) -> MCPToolResponse[dict[str, Any]]:
        backend_metadata = payload.get("metadata", {})
        snapshot_details = backend_metadata.get("snapshot", {})
        if not isinstance(snapshot_details, dict):
            snapshot_details = {"snapshot_key": snapshot_details}
        metadata = MCPMetadata(
            tool_name=f"compensation.{tool_name}",
            tool_version=COMPENSATION_MCP_VERSION,
            request_id=backend_metadata.get("correlation_id") or model.request_id or str(uuid4()),
            deterministic=True,
            snapshot_identifier=model.snapshot_identifier,
            reference_datetime=snapshot_details.get("reference_datetime"),
            evaluation_time=getattr(model, "evaluation_time", None),
            snapshot_details=snapshot_details,
        )
        data = payload.get("data", {})
        if tool_name == "get_compensation_evidence" and "causal_event" in data:
            compensation = data.get("compensation")
            if compensation is None:
                data = {"status": "pending", "consideration_count": None}
            else:
                data = {
                    "causal_event_code": data["causal_event"].get("code"),
                    **compensation,
                    "evidence": data.get("evidence"),
                }
        elif tool_name == "get_compensation_evidence":
            evaluations = data.get("evaluations", [])
            evidence_rows = data.get("decision_evidence", [])
            evaluation = evaluations[0] if isinstance(evaluations, list) and evaluations else {}
            evidence = evidence_rows[0] if isinstance(evidence_rows, list) and evidence_rows else {}
            data = {
                "status": evaluation.get("status", "pending"),
                "consideration_count": 1 if evaluation else None,
                "eligible": 1 if evaluation.get("result_type") == "eligible" else None,
                "ineligible_pending": (
                    0 if evaluation.get("result_type") == "eligible" else None
                ),
                "total_amount": evaluation.get("proposed_amount"),
                "currency": evaluation.get("currency"),
                "rule_versions": (
                    {f"{evaluation.get('rule_code')}:v{evaluation.get('rule_version')}": 1}
                    if evaluation.get("rule_code") and evaluation.get("rule_version") is not None
                    else {}
                ),
                "evidence": {"reference": evidence.get("evidence_hash", "")[:12]}
                if evidence.get("evidence_hash")
                else None,
            }
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
                tool_name=f"compensation.{tool_name}",
                tool_version=COMPENSATION_MCP_VERSION,
                request_id=request_id or str(uuid4()),
                deterministic=True,
                snapshot_identifier=snapshot_identifier,
                evaluation_time=evaluation_time,
            ),
        )
