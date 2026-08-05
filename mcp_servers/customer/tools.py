from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from mcp_servers.customer import CUSTOMER_MCP_VERSION
from mcp_servers.customer.models import (
    CustomerCompensationHistoryInput,
    CustomerOutageHistoryInput,
    CustomerPaymentStatusInput,
    CustomerProfileInput,
    CustomerSubscriptionInput,
    ListCustomersByDeviceInput,
    ListCustomersByLocationInput,
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


class CustomerToolDefinition:
    def __init__(
        self,
        *,
        name: str,
        description: str,
        input_model: type[BaseModel],
        method: str,
        path_builder: Callable[[BaseModel], str],
        params_builder: Callable[[BaseModel], dict[str, Any]],
    ) -> None:
        self.name = name
        self.description = description
        self.input_model = input_model
        self.method = method
        self.path_builder = path_builder
        self.params_builder = params_builder


def _path(template: str, field_name: str | None = None):
    def build(model: BaseModel) -> str:
        if field_name is None:
            return template
        return template.format(value=getattr(model, field_name))

    return build


def _params(model: BaseModel) -> dict[str, Any]:
    raw = model.model_dump(mode="json", exclude_none=True)
    raw.pop("request_id", None)
    return raw


def _history_path(model: BaseModel) -> str:
    if getattr(model, "causal_event_code", None):
        return f"/api/internal/v1/operations/causal-events/{model.causal_event_code}/analysis/"
    return "/api/internal/v1/customer/outages/history/"


CUSTOMER_TOOL_DEFINITIONS: dict[str, CustomerToolDefinition] = {
    "get_customer_profile": CustomerToolDefinition(
        name="get_customer_profile",
        description=(
            "Return one customer's masked profile, segment, priority, location, "
            "and optional compact subscription summaries."
        ),
        input_model=CustomerProfileInput,
        method="GET",
        path_builder=_path(
            "/api/internal/v1/customer/customers/{value}/profile/",
            "customer_number",
        ),
        params_builder=_params,
    ),
    "get_customer_subscription": CustomerToolDefinition(
        name="get_customer_subscription",
        description=(
            "Return subscription package, SLA, status, and controlled connection "
            "summaries for one customer or subscription."
        ),
        input_model=CustomerSubscriptionInput,
        method="GET",
        path_builder=_path("/api/internal/v1/customer/subscriptions/"),
        params_builder=_params,
    ),
    "get_customer_payment_status": CustomerToolDefinition(
        name="get_customer_payment_status",
        description=(
            "Return period billing/payment status and aggregate outstanding "
            "amounts for one customer or subscription."
        ),
        input_model=CustomerPaymentStatusInput,
        method="GET",
        path_builder=_path("/api/internal/v1/customer/payments/"),
        params_builder=_params,
    ),
    "get_customer_outage_history": CustomerToolDefinition(
        name="get_customer_outage_history",
        description=(
            "Return historical outage rows related to one customer or subscription "
            "using deterministic backend impact evidence."
        ),
        input_model=CustomerOutageHistoryInput,
        method="GET",
        path_builder=_history_path,
        params_builder=_params,
    ),
    "get_customer_compensation_history": CustomerToolDefinition(
        name="get_customer_compensation_history",
        description=(
            "Return existing compensation history records without running new "
            "eligibility or amount calculations."
        ),
        input_model=CustomerCompensationHistoryInput,
        method="GET",
        path_builder=_path("/api/internal/v1/customer/compensation/history/"),
        params_builder=_params,
    ),
    "list_customers_by_device": CustomerToolDefinition(
        name="list_customers_by_device",
        description=(
            "List customers served by a network device subgraph without outage "
            "impact or topology recalculation in MCP."
        ),
        input_model=ListCustomersByDeviceInput,
        method="GET",
        path_builder=_path(
            "/api/internal/v1/customer/customers/by-device/{value}/",
            "device_code",
        ),
        params_builder=_params,
    ),
    "list_customers_by_location": CustomerToolDefinition(
        name="list_customers_by_location",
        description=(
            "List customers for an explicit city, district, or neighborhood "
            "with stable cursor pagination."
        ),
        input_model=ListCustomersByLocationInput,
        method="GET",
        path_builder=_path("/api/internal/v1/customer/customers/by-location/"),
        params_builder=_params,
    ),
}


class CustomerMCPTools:
    def __init__(self, client: InternalAPIClient) -> None:
        self.client = client

    def run(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None,
    ) -> MCPToolResponse[dict[str, Any]]:
        definition = CUSTOMER_TOOL_DEFINITIONS.get(tool_name)
        if definition is None:
            return self._failure(
                tool_name=tool_name,
                request_id=None,
                snapshot_identifier=None,
                error=MCPError(
                    code=MCPErrorCode.NOT_FOUND,
                    message="Unknown Customer MCP tool.",
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
                    message="Invalid Customer MCP tool input.",
                    details={"errors": exc.errors(include_url=False)},
                ),
            )
        try:
            payload = self.client.request_json(
                definition.method,
                definition.path_builder(model),
                request_id=model.request_id,
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
        return self._success(
            tool_name=tool_name,
            model=model,
            payload=payload,
        )

    def _success(
        self,
        *,
        tool_name: str,
        model: BaseModel,
        payload: dict[str, Any],
    ) -> MCPToolResponse[dict[str, Any]]:
        backend_metadata = payload.get("metadata", {})
        snapshot_details = backend_metadata.get("snapshot", {})
        metadata = MCPMetadata(
            tool_name=f"customer.{tool_name}",
            tool_version=CUSTOMER_MCP_VERSION,
            request_id=backend_metadata.get("correlation_id") or model.request_id or str(uuid4()),
            deterministic=True,
            snapshot_identifier=model.snapshot_identifier,
            reference_datetime=snapshot_details.get("reference_datetime"),
            evaluation_time=getattr(model, "evaluation_time", None),
            snapshot_details=snapshot_details,
        )
        data = payload.get("data", {})
        if tool_name == "get_customer_outage_history" and getattr(model, "causal_event_code", None):
            impact = data.get("impact", {})
            data = {
                "causal_event_code": data.get("causal_event", {}).get("code"),
                "potential_connection_count": impact.get("potential", 0),
                "verified_impacted_count": impact.get("verified_impacted", 0),
                "verified_no_impact_count": impact.get("verified_no_impact", 0),
                "insufficient_evidence_count": impact.get("insufficient_evidence", 0),
                "pending_count": impact.get("pending", 0),
                "failover_protected_count": 0,
                "reason_code_distribution": impact.get("reason_codes", {}),
            }
        return MCPToolResponse[dict[str, Any]](
            success=True,
            data=data,
            metadata=metadata,
            warnings=[
                MCPWarning.model_validate(warning)
                for warning in payload.get("warnings", [])
            ],
            evidence=[
                MCPEvidence.model_validate(evidence)
                for evidence in payload.get("evidence", [])
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
                tool_name=f"customer.{tool_name}",
                tool_version=CUSTOMER_MCP_VERSION,
                request_id=request_id or str(uuid4()),
                deterministic=True,
                snapshot_identifier=snapshot_identifier,
                evaluation_time=evaluation_time,
            ),
        )
