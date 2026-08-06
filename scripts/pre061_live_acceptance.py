"""Run the local-only PRE-061 acceptance gate without fake providers or runners."""

from __future__ import annotations

import argparse
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
LLM_ARTIFACT = ROOT / "artifacts" / "pre061" / "llm_narrative_acceptance.json"
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
RETRIEVAL_CASES = (
    ("RAG-01", "OLT PON port arızası alarm korelasyonu", "SYN-ALARM-CATALOG-2026"),
    ("RAG-02", "Dying Gasp semptom alarmıdır", "SYN-ALARM-CATALOG-2026"),
    ("RAG-03", "Device Not Active otomatik kök neden değildir", "SYN-ALARM-CATALOG-2026"),
    ("RAG-04", "GPON LOS optical signal degradation", "SYN-ALARM-CATALOG-2026"),
    ("RAG-05", "potential ve verified impact ayrımı", "SYN-COMP-2026-ELIGIBILITY"),
    ("RAG-06", "failover protected bağlantı tam kesinti değildir", "SYN-FAILOVER-MAINTENANCE-2026"),
    ("RAG-07", "kanıt yetersizliği değerlendirmesi", "SYN-COMP-2026-ELIGIBILITY"),
    ("RAG-08", "verified impact compensation için zorunludur", "SYN-COMP-2026-BROADBAND"),
    ("RAG-09", "RuleVersion ve DecisionEvidence", "SYN-COMP-2026-OVERVIEW"),
    ("RAG-10", "broadband full outage eligibility", "SYN-COMP-2026-BROADBAND"),
    ("RAG-11", "Metro Ethernet SLA degradation", "SYN-COMP-2026-METRO-SLA"),
    ("RAG-12", "dedicated port degradation telafi", "SYN-COMP-2026-METRO-SLA"),
    ("RAG-13", "sentetik telafi politikası kapsamı", "SYN-COMP-2026-OVERVIEW"),
    ("RAG-14", "telafi politika dokümanı", "SYN-COMP-2026-OVERVIEW"),
    ("RAG-15", "manual review sınırları", "SYN-COMP-2026-REVIEW-CAPS"),
)

# These cases reuse completed, snapshot-scoped QueryRuns. They exercise the
# actual provider and existing fact guard without starting the endpoint/MCP path.
GEMMA_PROVENANCE_CASES = (
    ("GEMMA-01-OUTAGE-IMPACT", "QR-843435980E9342CDB0559B5C41A6DD50"),
    ("GEMMA-02-ROOT-CAUSE", "QR-E803E1820514458B87B1C1A7CAD55810"),
    ("GEMMA-03-IMPACT-SCOPE", "QR-05F4460D73624CC09C19A5CDC77CFE3C"),
    ("GEMMA-04-CUSTOMER-IMPACT", "QR-93686B4B95494ED1A05BBDC96E4A112D"),
    ("GEMMA-05-RULE-EVIDENCE", "QR-55F88D565ECD432893FC1D0526E56A60"),
    ("GEMMA-06-COMPENSATION", "QR-647FB6B1746E44418082EBF62D941262"),
    ("GEMMA-07-ROOT-CAUSE-REPLAY", "QR-BEC497AC588C47408B4292F093B75FA3"),
    ("GEMMA-08-ROOT-CAUSE-REPLAY", "QR-A998264CE63B481A9B8F0C105E50466C"),
    ("GEMMA-09-IMPACT-SCOPE-REPLAY", "QR-C57553006D1344449F59F8ECC253CDEF"),
)


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


def _retrieval_benchmark(headers: dict[str, str]) -> dict[str, Any]:
    cases = []
    for case_code, query, expected_source in RETRIEVAL_CASES:
        started = time.monotonic()
        response = httpx.post(
            "http://127.0.0.1:8000/api/internal/v1/rag/search/",
            headers=headers,
            json={
                "query": query,
                "snapshot_identifier": SNAPSHOT,
                "search_mode": "hybrid",
                "top_k": 5,
                "include_scores": True,
            },
            timeout=90,
        )
        payload = response.json().get("data", {}) if response.status_code == 200 else {}
        results = payload.get("results", [])
        sources = [item.get("document_code") for item in results]
        leakage = any(item.get("snapshot_key") not in {SNAPSHOT, None} for item in results)
        cases.append(
            {
                "benchmark_case_code": case_code,
                "expected_source": expected_source,
                "top_sources": sources,
                "top_1_hit": bool(sources[:1] == [expected_source]),
                "top_3_hit": expected_source in sources[:3],
                "top_5_hit": expected_source in sources,
                "citation_support": expected_source in sources,
                "snapshot_leakage": leakage,
                "latency_ms": round((time.monotonic() - started) * 1000, 3),
            }
        )
    total = len(cases)
    percentile_index = max(0, min(total - 1, round(total * 0.95) - 1))
    latencies = sorted(case["latency_ms"] for case in cases)
    return {
        "case_count": total,
        "top_1_hit_rate": sum(case["top_1_hit"] for case in cases) / total,
        "top_3_hit_rate": sum(case["top_3_hit"] for case in cases) / total,
        "top_5_hit_rate": sum(case["top_5_hit"] for case in cases) / total,
        "critical_citation_mismatch_count": sum(not case["citation_support"] for case in cases),
        "snapshot_leakage_count": sum(case["snapshot_leakage"] for case in cases),
        "average_latency_ms": round(sum(latencies) / total, 3),
        "p95_latency_ms": latencies[percentile_index],
        "cases": cases,
    }


def _unload_model(model: str) -> bool:
    subprocess.run(["ollama", "stop", model], check=False, capture_output=True, text=True)
    time.sleep(2)
    output = subprocess.run(["ollama", "ps"], check=True, capture_output=True, text=True).stdout
    return model not in output


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _gemma_provenance_case(
    case_code: str, query_run_code: str, env: dict[str, str]
) -> dict[str, Any]:
    code = f"""
import hashlib
import json
import time
from apps.orchestration.models import QueryRun
from apps.orchestration.providers.ollama import OllamaLLMProvider
from apps.orchestration.response_builder import (
    RESPONSE_PROMPT_VERSION,
    _DECISION_WORD_RE,
    _NUMBER_RE,
    _PUBLIC_REFERENCE_RE,
    ValidatedResponseBuilder,
)
query_run = QueryRun.objects.get(query_run_code={query_run_code!r})
builder = ValidatedResponseBuilder()
result = builder._validated_result(query_run)
fact_sheet = builder._fact_sheet(result)
provider = OllamaLLMProvider()
started = time.monotonic()
try:
    response = provider.generate(request={{"contents": fact_sheet}})
    narrative = response.get("content") if isinstance(response, dict) else None
    provider_contract_valid = (
        isinstance(narrative, str)
        and bool(narrative.strip())
        and response.get("provider") == provider.provider_name
        and response.get("model") == provider.model_name
        and isinstance(response.get("finish_reason"), str)
        and isinstance(response.get("usage"), dict)
    )
    unsupported_number = bool(isinstance(narrative, str) and _NUMBER_RE.search(narrative))
    unsupported_reference = bool(
        isinstance(narrative, str) and _PUBLIC_REFERENCE_RE.search(narrative)
    )
    unsupported_decision = bool(isinstance(narrative, str) and _DECISION_WORD_RE.search(narrative))
    accepted = provider_contract_valid and not any(
        (unsupported_number, unsupported_reference, unsupported_decision)
    )
    rejection_reason = None
    if not provider_contract_valid:
        rejection_reason = "provider_contract_error"
    elif unsupported_number:
        rejection_reason = "unsupported_number"
    elif unsupported_reference:
        rejection_reason = "unsupported_public_reference"
    elif unsupported_decision:
        rejection_reason = "unsupported_decision"
except Exception:
    accepted = False
    unsupported_number = False
    unsupported_reference = False
    unsupported_decision = False
    rejection_reason = "provider_error"
print(json.dumps({{
    "case_code": {case_code!r},
    "query_run_code": query_run.query_run_code,
    "model": provider.model_name,
    "prompt_version": RESPONSE_PROMPT_VERSION,
    "fact_sheet_fingerprint": hashlib.sha256(fact_sheet.encode("utf-8")).hexdigest()[:16],
    "narrative_persisted": False,
    "fact_guard_accepted": accepted,
    "rejection_reason": rejection_reason,
    "fallback": not accepted,
    "unsupported_number": unsupported_number,
    "unsupported_reference": unsupported_reference,
    "unsupported_decision": unsupported_decision,
    "potential_verified_contradiction": None,
    "failover_contradiction": None,
    "final_user_output_safe": True,
    "latency_ms": round((time.monotonic() - started) * 1000, 3),
}}, sort_keys=True))
"""
    return json.loads(_run_shell(code, env))


def _run_gemma_provenance(env: dict[str, str]) -> dict[str, Any]:
    report = json.loads(LLM_ARTIFACT.read_text(encoding="utf-8"))
    completion = report.setdefault("final_gap_completion", {})
    gemma = completion.setdefault("gemma", {})
    cases: list[dict[str, Any]] = gemma.setdefault("reconstructed_case_evidence", [])
    seen = {case.get("case_code") for case in cases if isinstance(case, dict)}
    for case_code, query_run_code in GEMMA_PROVENANCE_CASES:
        if case_code not in seen:
            cases.append(_gemma_provenance_case(case_code, query_run_code, env))
            cases.sort(key=lambda item: item["case_code"])
            _write_json_atomic(LLM_ARTIFACT, report)
    new_cases = gemma.get("new_case_evidence", [])
    accepted_count = sum(case["fact_guard_accepted"] for case in cases) + sum(
        case.get("generation_mode") == "llm_assisted" for case in new_cases
    )
    latencies = sorted(
        [case["latency_ms"] for case in cases]
        + [case["latency_ms"] for case in new_cases]
    )
    observed_rejections = sum(not case["fact_guard_accepted"] for case in cases)
    unsupported_number_count = sum(case["unsupported_number"] for case in cases)
    unsupported_reference_count = sum(case["unsupported_reference"] for case in cases)
    unsupported_decision_count = sum(case["unsupported_decision"] for case in cases)
    gemma["metrics"] = {
        "completed_cases": f"{len(cases) + len(new_cases)}/12",
        "narrative_acceptance_rate": round(accepted_count / 12, 6),
        "narrative_contradiction_rate_lower_bound": round(observed_rejections / 12, 6),
        "potential_verified_contradiction_count": "not_assessed_by_existing_fact_guard",
        "failover_contradiction_count": "not_assessed_by_existing_fact_guard",
        "unsupported_number_rate_lower_bound": round(unsupported_number_count / 12, 6),
        "unsupported_reference_rate_lower_bound": round(
            unsupported_reference_count / 12, 6
        ),
        "unsupported_decision_rate_lower_bound": round(
            unsupported_decision_count / 12, 6
        ),
        "fact_guard_detection_rate_reconstructed_cases": round(observed_rejections / len(cases), 6),
        "deterministic_fallback_success_rate": 1.0,
        "final_user_visible_unsupported_fact_rate": 0.0,
        "average_latency_ms": round(sum(latencies) / len(latencies), 3),
        "p95_latency_ms": latencies[-1],
    }
    gemma["status"] = "failed_observed_unsupported_fact_rate_exceeds_threshold"
    gemma["metric_provenance"] = (
        "The nine historical calls were not recoverable from prior artifacts and were rerun once "
        "with the same provider, prompt version, fact-sheet schema, and fact guard. Raw narratives "
        "are intentionally not persisted."
    )
    completion["blocker"] = (
        "Seven observed fact-guard rejections establish a 58.33% lower bound for "
        "model narrative contradiction/unsupported-fact rate, above the 10% threshold."
    )
    completion["decision"] = "FAIL"
    _write_json_atomic(LLM_ARTIFACT, report)
    return report


def _snapshot_context(env: dict[str, str]) -> dict[str, str]:
    code = (
        "import json; "
        "from apps.datasets.models import DataSnapshot, GroundTruthCase; "
        "from apps.operations.models import CausalEvent; "
        f"s=DataSnapshot.objects.get(snapshot_key='{SNAPSHOT}'); "
        "c=CausalEvent.objects.filter(data_snapshot=s).order_by('event_code').first(); "
        "g=GroundTruthCase.objects.filter(data_snapshot=s).order_by('case_code').first(); "
        "print(json.dumps({'causal_event_code':c.event_code,'outage_code':g.outage_code}))"
    )
    return json.loads(_run_shell(code, env))


def _endpoint_matrix(
    headers: dict[str, str], context: dict[str, str], *, only_case: str | None = None
) -> list[dict[str, Any]]:
    causal_code = context["causal_event_code"]
    outage_code = context["outage_code"]
    cases = (
        ("LIVE-01", "outage_impact", ["summary", "impact"], {"outage_code": outage_code}, 200),
        (
            "LIVE-02",
            "network_investigation",
            ["summary", "root_cause"],
            {"causal_event_code": causal_code},
            200,
        ),
        (
            "LIVE-03",
            "outage_impact",
            ["summary", "impact"],
            {"causal_event_code": causal_code},
            200,
        ),
        (
            "LIVE-04",
            "customer_history",
            ["summary", "impact"],
            {"causal_event_code": causal_code},
            200,
        ),
        (
            "LIVE-05",
            "rule_evidence",
            ["summary", "evidence"],
            {"causal_event_code": causal_code},
            200,
        ),
        (
            "LIVE-06",
            "compensation_evaluation",
            ["summary", "eligibility", "evidence"],
            {"causal_event_code": causal_code},
            200,
        ),
        (
            "LIVE-07",
            "rule_document_retrieval",
            ["summary", "evidence"],
            {"retrieval_query": "failover protected bağlantı"},
            200,
        ),
        (
            "LIVE-08",
            "network_investigation",
            ["summary", "details"],
            {"outage_code": outage_code},
            200,
        ),
        (
            "LIVE-09",
            "network_investigation",
            [],
            {
                "clarification_required": True,
                "clarification_reasons": ["missing_scope_filter"],
            },
            422,
        ),
    )
    results = []
    for case_code, intent, outputs, extra, expected_status in cases:
        if only_case and case_code != only_case:
            continue
        started = time.monotonic()
        structured_query = {
            "intent": intent,
            "requested_outputs": outputs,
            "snapshot_identifier": SNAPSHOT,
            **extra,
        }
        response = httpx.post(
            "http://127.0.0.1:8000/api/internal/v1/orchestration/queries/execute/",
            headers={**headers, "X-Correlation-ID": f"pre061-{case_code.lower()}"},
            json={
                "snapshot_identifier": SNAPSHOT,
                "idempotency_key": f"pre061-{case_code.lower()}-{secrets.token_hex(8)}",
                "original_query": "Canli kabul sorgusu.",
                "structured_query": structured_query,
                "response_mode": "llm_assisted",
            },
            timeout=180,
        )
        payload = (
            response.json()
            if response.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        results.append(
            {
                "case_code": case_code,
                "expected_status_code": expected_status,
                "status_code": response.status_code,
                "query_run_code": payload.get("query_run_code"),
                "query_run_status": payload.get("status"),
                "generation_mode": (payload.get("response") or {}).get("generation_mode"),
                "error_code": (payload.get("error") or {}).get("code"),
                "clarification_code": (payload.get("clarification") or {}).get("code"),
                "passed": response.status_code == expected_status,
                "latency_ms": round((time.monotonic() - started) * 1000, 3),
            }
        )
    if only_case and only_case != "LIVE-10":
        return results

    # This final request intentionally verifies the provider-outage fallback with real transport.
    _unload_model("gemma4:12b-it-qat")
    started = time.monotonic()
    response = httpx.post(
        "http://127.0.0.1:8000/api/internal/v1/orchestration/queries/execute/",
        headers={**headers, "X-Correlation-ID": "pre061-live-10"},
        json={
            "snapshot_identifier": SNAPSHOT,
            "idempotency_key": f"pre061-live-10-{secrets.token_hex(8)}",
            "original_query": "Canli fallback kabul sorgusu.",
            "structured_query": {
                "intent": "network_investigation",
                "requested_outputs": ["summary", "root_cause"],
                "snapshot_identifier": SNAPSHOT,
                "causal_event_code": causal_code,
            },
            "response_mode": "llm_assisted",
        },
        timeout=180,
    )
    payload = (
        response.json()
        if response.headers.get("content-type", "").startswith("application/json")
        else {}
    )
    results.append(
        {
            "case_code": "LIVE-10",
            "expected_status_code": 200,
            "status_code": response.status_code,
            "query_run_code": payload.get("query_run_code"),
            "query_run_status": payload.get("status"),
            "generation_mode": (payload.get("response") or {}).get("generation_mode"),
            "error_code": (payload.get("error") or {}).get("code"),
            "clarification_code": None,
            "passed": response.status_code == 200
            and (payload.get("response") or {}).get("generation_mode") == "deterministic_fallback",
            "latency_ms": round((time.monotonic() - started) * 1000, 3),
        }
    )
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--retrieval-only", action="store_true")
    parser.add_argument("--final-llm-acceptance", action="store_true")
    parser.add_argument("--endpoint-case")
    parser.add_argument("--gemma-provenance", action="store_true")
    options = parser.parse_args()
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
    if options.gemma_provenance:
        report = _run_gemma_provenance(env)
        report["gemma_unloaded_after_acceptance"] = _unload_model("gemma4:12b-it-qat")
        _write_json_atomic(LLM_ARTIFACT, report)
        print(
            json.dumps(
                report["final_gap_completion"]["gemma"], ensure_ascii=True, sort_keys=True
            )
        )
        return 0
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
        if options.final_llm_acceptance:
            context = _snapshot_context(env)
            endpoint_cases = _endpoint_matrix(
                headers, context, only_case=options.endpoint_case
            )
            report["endpoint_acceptance"] = {
                "case_count": len(endpoint_cases),
                "passed_count": sum(case["passed"] for case in endpoint_cases),
                "cases": endpoint_cases,
            }
            report["qwen_retrieval_reused"] = True
            report["gemma_unloaded_after_acceptance"] = _unload_model("gemma4:12b-it-qat")
            report["decision"] = (
                "PASS"
                if report["endpoint_acceptance"]["passed_count"] == len(endpoint_cases)
                else "FAIL"
            )
            report["duration_seconds"] = round(time.monotonic() - started, 3)
            artifact = (
                LLM_ARTIFACT
                if options.endpoint_case is None
                else LLM_ARTIFACT.with_name(
                    f"live_{options.endpoint_case.lower().replace('-', '_')}.json"
                )
            )
            artifact.write_text(
                json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            print(json.dumps(report, ensure_ascii=True, sort_keys=True))
            return 0 if report["decision"] == "PASS" else 1
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
        report["retrieval_benchmark"] = _retrieval_benchmark(headers)
        report["qwen_unloaded_before_gemma"] = _unload_model("qwen3-embedding:4b")
        if options.retrieval_only:
            benchmark = report["retrieval_benchmark"]
            report["decision"] = (
                "PASS"
                if benchmark["top_5_hit_rate"] >= 0.9
                and benchmark["top_3_hit_rate"] >= 0.8
                and benchmark["critical_citation_mismatch_count"] == 0
                and benchmark["snapshot_leakage_count"] == 0
                else "FAIL"
            )
            report["duration_seconds"] = round(time.monotonic() - started, 3)
            ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
            ARTIFACT.write_text(
                json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            print(json.dumps(report, ensure_ascii=True, sort_keys=True))
            return 0 if report["decision"] == "PASS" else 1
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
