"""Run the local-only PRE-061 acceptance gate without fake providers or runners."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
SNAPSHOT = (
    "multi-city-realism-v2-causal-r1-multi-city-realism-snapshot-v1-multi-city-realism-v2-causal-r1"
)
ARTIFACT = ROOT / "artifacts" / "pre061" / "live_acceptance_report.json"
MCP_MODULES = {
    "network": "mcp_servers.network",
    "customer": "mcp_servers.customer",
    "rule": "mcp_servers.rules",
    "compensation": "mcp_servers.compensation",
}
MCP_CALLS = {
    "network": (
        "correlate_alarms",
        lambda code: {"snapshot_identifier": SNAPSHOT, "causal_event_code": code},
    ),
    "customer": (
        "get_customer_outage_history",
        lambda code: {"snapshot_identifier": SNAPSHOT, "causal_event_code": code},
    ),
    "rule": (
        "get_rule_evidence",
        lambda code: {"snapshot_identifier": SNAPSHOT, "causal_event_code": code},
    ),
    "compensation": (
        "get_compensation_evidence",
        lambda code: {"snapshot_identifier": SNAPSHOT, "causal_event_code": code},
    ),
}


def _run_shell(code: str, env: dict[str, str]) -> str:
    result = subprocess.run(
        [sys.executable, "backend/manage.py", "shell", "-c", code],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip().splitlines()[-1]


async def _mcp_call(
    module: str, token: str, name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", module],
        cwd=str(ROOT),
        env={
            **os.environ,
            "MCP_BACKEND_BASE_URL": "http://127.0.0.1:8000",
            "MCP_BACKEND_SERVICE_TOKEN": token,
        },
    )
    async with stdio_client(server) as (read_stream, write_stream):
        session = ClientSession(read_stream, write_stream)
        async with session:
            await session.initialize()
            tools = await session.list_tools()
            result = await session.call_tool(name, arguments)
    payload = getattr(result, "structuredContent", None)
    if not isinstance(payload, dict):
        payload = json.loads(result.content[0].text)
    return {"tool_count": len(tools.tools), "success": bool(payload.get("success"))}


def _wait_ready(token: str) -> None:
    headers = {"Authorization": f"Bearer {token}"}
    for _ in range(30):
        try:
            if (
                httpx.get(
                    "http://127.0.0.1:8000/api/internal/v1/health/", headers=headers
                ).status_code
                == 200
            ):
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise RuntimeError("backend_not_ready")


def main() -> int:
    token = secrets.token_urlsafe(32)
    env = {
        **os.environ,
        "INTERNAL_API_SERVICE_TOKEN": token,
        "MCP_BACKEND_SERVICE_TOKEN": token,
        "MCP_BACKEND_BASE_URL": "http://127.0.0.1:8000",
        "ORCHESTRATION_MCP_TRANSPORT": "stdio",
        "LLM_PROVIDER": "ollama",
        "RAG_EMBEDDING_PROVIDER": "ollama",
    }
    causal_lookup = (
        "from apps.datasets.models import DataSnapshot; "
        "from apps.operations.models import CausalEvent; "
        f"s=DataSnapshot.objects.get(snapshot_key='{SNAPSHOT}'); "
        "print(CausalEvent.objects.filter(data_snapshot=s).order_by('event_code')"
        ".values_list('event_code', flat=True).first())"
    )
    causal_code = _run_shell(causal_lookup, env)
    server = subprocess.Popen(
        [sys.executable, "backend/manage.py", "runserver", "127.0.0.1:8000", "--noreload"],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    started = time.monotonic()
    report: dict[str, Any] = {
        "gate": "PRE-061",
        "snapshot_identifier": SNAPSHOT,
        "causal_event_code": causal_code,
    }
    try:
        _wait_ready(token)
        headers = {"Authorization": f"Bearer {token}", "X-Correlation-ID": "pre061-rag-001"}
        rag = httpx.post(
            "http://127.0.0.1:8000/api/internal/v1/rag/search/",
            headers=headers,
            json={
                "query": "failover protected connection full outage değildir",
                "snapshot_identifier": SNAPSHOT,
                "search_mode": "hybrid",
                "top_k": 5,
                "include_scores": True,
            },
            timeout=90,
        )
        report["rag"] = {
            "status_code": rag.status_code,
            "result_count": len(rag.json().get("data", {}).get("results", []))
            if rag.headers.get("content-type", "").startswith("application/json")
            else 0,
        }
        report["mcp"] = {
            key: asyncio.run(
                _mcp_call(module, token, *MCP_CALLS[key][:1], MCP_CALLS[key][1](causal_code))
            )
            for key, module in MCP_MODULES.items()
        }
        request = {
            "snapshot_identifier": SNAPSHOT,
            "idempotency_key": f"pre061-live-network-{secrets.token_hex(8)}",
            "original_query": "GPON olayının kök nedenini açıkla.",
            "structured_query": {
                "intent": "network_investigation",
                "requested_outputs": ["summary", "root_cause"],
                "snapshot_identifier": SNAPSHOT,
                "causal_event_code": causal_code,
            },
            "response_mode": "llm_assisted",
        }
        endpoint = httpx.post(
            "http://127.0.0.1:8000/api/internal/v1/orchestration/queries/execute/",
            headers={**headers, "X-Correlation-ID": "pre061-e2e-001"},
            json=request,
            timeout=180,
        )
        payload = (
            endpoint.json()
            if endpoint.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        report["endpoint"] = {
            "status_code": endpoint.status_code,
            "status": payload.get("status"),
            "generation_mode": payload.get("response", {}).get("generation_mode"),
            "has_response": bool(payload.get("response")),
        }
        report["duration_seconds"] = round(time.monotonic() - started, 3)
        report["decision"] = (
            "PASS"
            if report["rag"]["status_code"] == 200
            and all(value["success"] for value in report["mcp"].values())
            and endpoint.status_code == 200
            else "FAIL"
        )
    except Exception as exc:
        report["decision"] = "FAIL"
        report["error_code"] = exc.__class__.__name__.lower()
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(
        json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 0 if report["decision"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
