from __future__ import annotations

from pydantic import Field

from mcp_servers.shared.contracts import BaseMCPInput


class SimulationRunInput(BaseMCPInput):
    snapshot_identifier: str = Field(min_length=1)
    simulation_run_code: str = Field(min_length=1)


class SimulationEventsInput(SimulationRunInput):
    cursor: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=100)
