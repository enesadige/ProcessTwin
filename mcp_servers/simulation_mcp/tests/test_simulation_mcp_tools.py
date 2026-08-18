from __future__ import annotations

from mcp_servers.shared.backend_client import InternalAPIClientError
from mcp_servers.shared.contracts import MCPError, MCPErrorCode
from mcp_servers.simulation_mcp.tools import SIMULATION_TOOL_DEFINITIONS, SimulationMCPTools


class FakeBackendClient:
    def __init__(self, *, payload=None, error=None):
        self.payload = payload or {
            "data": {"run": {"status": "completed"}},
            "warnings": [],
            "evidence": [],
            "metadata": {"correlation_id": "simulation-mcp-test", "snapshot": {}},
        }
        self.error = error
        self.calls = []

    def request_json(self, method, path, *, request_id=None, json=None, params=None):
        self.calls.append(
            {"method": method, "path": path, "request_id": request_id, "params": params}
        )
        if self.error:
            raise self.error
        return self.payload


def test_exactly_four_read_only_simulation_tools_are_registered():
    assert sorted(SIMULATION_TOOL_DEFINITIONS) == [
        "get_simulation_events",
        "get_simulation_evidence",
        "get_simulation_result",
        "get_simulation_run_status",
    ]


def test_simulation_tools_use_bounded_get_paths_and_snapshot_parameters():
    client = FakeBackendClient()
    tools = SimulationMCPTools(client)
    examples = {
        "get_simulation_run_status": {},
        "get_simulation_result": {},
        "get_simulation_events": {"cursor": 2, "limit": 10},
        "get_simulation_evidence": {},
    }
    for tool_name, extra in examples.items():
        response = tools.run(
            tool_name,
            {
                "request_id": "simulation-mcp-tool-1",
                "snapshot_identifier": "snapshot-1",
                "simulation_run_code": "SIM-001",
                **extra,
            },
        )
        assert response.success is True
        assert response.metadata.deterministic is True
        call = client.calls[-1]
        assert call["method"] == "GET"
        expected_path = (
            "/api/internal/v1/simulation/runs/SIM-001/"
            f"{SIMULATION_TOOL_DEFINITIONS[tool_name].path_suffix}/"
        )
        assert call["path"] == expected_path
        assert call["params"]["snapshot_identifier"] == "snapshot-1"
        assert "simulation_run_code" not in call["params"]


def test_simulation_tools_reject_invalid_input_and_forward_internal_not_found():
    tools = SimulationMCPTools(FakeBackendClient())
    invalid = tools.run("get_simulation_result", {"snapshot_identifier": "snapshot-1"})
    assert invalid.success is False
    assert invalid.error.code == MCPErrorCode.VALIDATION_ERROR

    upstream = InternalAPIClientError(
        MCPError(code=MCPErrorCode.NOT_FOUND, message="Simulation run was not found.")
    )
    missing = SimulationMCPTools(FakeBackendClient(error=upstream)).run(
        "get_simulation_result",
        {"snapshot_identifier": "snapshot-1", "simulation_run_code": "MISSING"},
    )
    assert missing.success is False
    assert missing.error.code == MCPErrorCode.NOT_FOUND
