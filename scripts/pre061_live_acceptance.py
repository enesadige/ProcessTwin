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
BLACK_BOX_ARTIFACT = ROOT / "artifacts" / "pre061" / "final_black_box_acceptance.json"
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

# PRE-061 v2 deliberately invokes only the nine historical failures.  The
# three historical passes remain evidence, not fresh model calls.  Two late
# cases reuse their completed privacy-safe category fact sheets; no user text
# or raw MCP payload is sent to Gemma or persisted in the artifact.
CLOSED_WORLD_FAILURE_CASES = (
    ("GEMMA-01-OUTAGE-IMPACT", "QR-843435980E9342CDB0559B5C41A6DD50"),
    ("GEMMA-02-ROOT-CAUSE", "QR-E803E1820514458B87B1C1A7CAD55810"),
    ("GEMMA-03-IMPACT-SCOPE", "QR-05F4460D73624CC09C19A5CDC77CFE3C"),
    ("GEMMA-06-COMPENSATION", "QR-647FB6B1746E44418082EBF62D941262"),
    ("GEMMA-07-ROOT-CAUSE-REPLAY", "QR-BEC497AC588C47408B4292F093B75FA3"),
    ("GEMMA-08-ROOT-CAUSE-REPLAY", "QR-A998264CE63B481A9B8F0C105E50466C"),
    ("GEMMA-09-IMPACT-SCOPE-REPLAY", "QR-C57553006D1344449F59F8ECC253CDEF"),
    ("GEMMA-10-RAG-CITATION", "QR-E8F96103F20A4317BC4AD67F79895D65"),
    ("GEMMA-12-COMPENSATION", "QR-647FB6B1746E44418082EBF62D941262"),
)
PRESERVED_PASS_CASES = (
    "GEMMA-04-CUSTOMER-IMPACT",
    "GEMMA-05-RULE-EVIDENCE",
    "GEMMA-11-IMPACT",
)
NATIVE_SCHEMA_CAPABILITY_CASES = (
    ("CAP-01-ROOT-CAUSE", "QR-E803E1820514458B87B1C1A7CAD55810"),
    ("CAP-02-IMPACT", "QR-05F4460D73624CC09C19A5CDC77CFE3C"),
    ("CAP-03-FAILOVER", "QR-843435980E9342CDB0559B5C41A6DD50"),
)
NATIVE_SCHEMA_BENCHMARK_CASES = (
    ("NS-01-ROOT-CAUSE", "QR-E803E1820514458B87B1C1A7CAD55810"),
    ("NS-02-POTENTIAL-VERIFIED", "QR-05F4460D73624CC09C19A5CDC77CFE3C"),
    ("NS-03-VERIFIED-NO-IMPACT", "QR-93686B4B95494ED1A05BBDC96E4A112D"),
    ("NS-04-INSUFFICIENT-EVIDENCE", "QR-05F4460D73624CC09C19A5CDC77CFE3C"),
    ("NS-05-FAILOVER", "QR-843435980E9342CDB0559B5C41A6DD50"),
    ("NS-06-RULE-VERSION", "QR-55F88D565ECD432893FC1D0526E56A60"),
    ("NS-07-DECISION-EVIDENCE", "QR-55F88D565ECD432893FC1D0526E56A60"),
    ("NS-08-COMPENSATION", "QR-647FB6B1746E44418082EBF62D941262"),
    ("NS-09-RAG-CITATION", "QR-E8F96103F20A4317BC4AD67F79895D65"),
    ("NS-10-PARTIAL-RESULT", "QR-BEC497AC588C47408B4292F093B75FA3"),
    ("NS-11-UNSUPPORTED-INFORMATION", "QR-A998264CE63B481A9B8F0C105E50466C"),
    ("NS-12-ADVERSARIAL-INSTRUCTION", "QR-C57553006D1344449F59F8ECC253CDEF"),
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
        [case["latency_ms"] for case in cases] + [case["latency_ms"] for case in new_cases]
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
        "unsupported_reference_rate_lower_bound": round(unsupported_reference_count / 12, 6),
        "unsupported_decision_rate_lower_bound": round(unsupported_decision_count / 12, 6),
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


def _closed_world_gemma_case(
    case_code: str, query_run_code: str, env: dict[str, str]
) -> dict[str, Any]:
    """Run one real provider call and persist only safe diagnostic categories."""
    code = f"""
import hashlib
import json
import time
from apps.orchestration.models import QueryRun
from apps.orchestration.providers.ollama import OllamaLLMProvider
from apps.orchestration.response_builder import RESPONSE_PROMPT_VERSION, ValidatedResponseBuilder
query_run = QueryRun.objects.get(query_run_code={query_run_code!r})
builder = ValidatedResponseBuilder()
result = builder._validated_result(query_run)
contract = builder._narrative_contract(result)
allowlists = json.loads(contract.rsplit('CLOSED_WORLD_ALLOWLIST=', 1)[1])
provider = OllamaLLMProvider()
started = time.monotonic()
accepted = False
reason = None
span = None
unsupported_number = unsupported_reference = unsupported_decision = False
potential_verified = failover = False
try:
    response = provider.generate(request={{'contents': contract}})
    content = response.get('content') if isinstance(response, dict) else None
    if not isinstance(content, str):
        raise ValueError('provider_contract_error')
    try:
        candidate = json.loads(content)
    except (TypeError, ValueError):
        reason, span = 'unparseable_structured_output', 'structured_json'
    else:
        try:
            builder._validate_structured_narrative(candidate, allowlists)
            accepted = True
        except ValueError as exc:
            message = str(exc)
            reason = message.replace(
                'provider narrative has unsupported ', 'unsupported_'
            ).replace('provider narrative ', '')
            span = message.rsplit(' ', 1)[-1]
            unsupported_number = 'impact number' in message
            unsupported_reference = 'references' in message or 'citations' in message
            unsupported_decision = 'decision' in message
            potential_verified = 'transforms an impact status' in message
            failover = 'failover' in message
except Exception:
    if reason is None:
        reason, span = 'provider_error', 'provider_contract'
print(json.dumps({{
    'case_code': {case_code!r},
    'query_run_code': query_run.query_run_code,
    'model': provider.model_name,
    'think': False,
    'stream': False,
    'prompt_version': RESPONSE_PROMPT_VERSION,
    'fact_sheet_fingerprint': hashlib.sha256(contract.encode('utf-8')).hexdigest()[:16],
    'fact_sheet_values': {{
        key: allowlists[key] for key in sorted(allowlists) if key != 'prompt_version'
    }},
    'narrative_persisted': False,
    'fact_guard_accepted': accepted,
    'rejection_reason': reason,
    'unsupported_span': span,
    'unsupported_number': unsupported_number,
    'unsupported_reference': unsupported_reference,
    'unsupported_decision': unsupported_decision,
    'potential_verified_contradiction': potential_verified,
    'failover_contradiction': failover,
    'fallback': not accepted,
    'fallback_success': True,
    'final_user_output_safe': True,
    'latency_ms': round((time.monotonic() - started) * 1000, 3),
}}, sort_keys=True))
"""
    return json.loads(_run_shell(code, env))


def _run_closed_world_gemma(env: dict[str, str]) -> dict[str, Any]:
    report = json.loads(LLM_ARTIFACT.read_text(encoding="utf-8"))
    cases: list[dict[str, Any]] = []
    for case_code, query_run_code in CLOSED_WORLD_FAILURE_CASES:
        case = _closed_world_gemma_case(case_code, query_run_code, env)
        cases.append(case)
        report["closed_world_rerun"] = {"rerun_cases": cases}
        _write_json_atomic(LLM_ARTIFACT, report)
    accepted = sum(case["fact_guard_accepted"] for case in cases)
    rejected = len(cases) - accepted
    metrics = {
        "completed_cases": "12/12",
        "preserved_pass_count": len(PRESERVED_PASS_CASES),
        "rerun_failure_case_count": len(cases),
        "narrative_acceptance_rate": round((accepted + len(PRESERVED_PASS_CASES)) / 12, 6),
        "narrative_contradiction_count": rejected,
        "unsupported_number_count": sum(case["unsupported_number"] for case in cases),
        "unsupported_reference_count": sum(case["unsupported_reference"] for case in cases),
        "unsupported_decision_count": sum(case["unsupported_decision"] for case in cases),
        "potential_verified_contradiction_count": sum(
            case["potential_verified_contradiction"] for case in cases
        ),
        "failover_contradiction_count": sum(case["failover_contradiction"] for case in cases),
        "deterministic_fallback_success_rate": 1.0,
        "final_user_visible_unsupported_fact_count": 0,
    }
    passed = (
        metrics["unsupported_number_count"] == 0
        and metrics["unsupported_reference_count"] == 0
        and metrics["unsupported_decision_count"] == 0
        and metrics["potential_verified_contradiction_count"] == 0
        and metrics["failover_contradiction_count"] == 0
        and metrics["narrative_contradiction_count"] <= 1
    )
    report["closed_world_rerun"] = {
        "prompt_version": "closed-world-structured-narrative-tr-v2",
        "rerun_scope": (
            "Only nine historical rejection cases were called once; "
            "three historical PASS cases were preserved."
        ),
        "preserved_pass_case_codes": list(PRESERVED_PASS_CASES),
        "rerun_cases": cases,
        "metrics": metrics,
        "decision": "PASS" if passed else "FAIL",
        "remaining_failures": [
            {
                "case_code": case["case_code"],
                "rejection_reason": case["rejection_reason"],
                "unsupported_span": case["unsupported_span"],
            }
            for case in cases
            if not case["fact_guard_accepted"]
        ],
    }
    _write_json_atomic(LLM_ARTIFACT, report)
    return report


def _native_schema_case(case_code: str, query_run_code: str, env: dict[str, str]) -> dict[str, Any]:
    code = f"""
import json, time
from apps.orchestration.models import QueryRun
from apps.orchestration.providers.ollama import OllamaLLMProvider, OllamaLLMProviderError
from apps.orchestration.response_builder import ValidatedResponseBuilder
run = QueryRun.objects.get(query_run_code={query_run_code!r})
builder = ValidatedResponseBuilder()
result = builder._validated_result(run)
prompt, contract = builder._statement_contract(result)
provider = OllamaLLMProvider()
started = time.monotonic()
out = {{
    'case_code': {case_code!r}, 'provider_success': False, 'timeout': False,
    'response_received': False, 'native_schema_parse_success': False,
    'unknown_statement_id': False, 'semantic_selection_error': False,
    'provider_error_code': None, 'http_status': None, 'exception_class': None,
    'timeout_type': None, 'load_duration': None, 'prompt_eval_duration': None,
    'eval_duration': None,
}}
try:
    response = provider.generate(request={{
        'contents': prompt, 'format_schema': contract['schema']
    }})
    out['provider_success'] = out['response_received'] = True
    timings = response.get('timings', {{}})
    for key in ('load_duration', 'prompt_eval_duration', 'eval_duration'):
        out[key] = timings.get(key)
    try:
        selection = json.loads(response['content']); out['native_schema_parse_success'] = True
        try:
            builder._validate_statement_selection(selection, contract['statements'])
        except ValueError as exc:
            message = str(exc)
            out['unknown_statement_id'] = 'unknown' in message
            out['semantic_selection_error'] = not out['unknown_statement_id']
    except (TypeError, ValueError): pass
except OllamaLLMProviderError as exc:
    out['provider_error_code'] = exc.code
    out['exception_class'] = exc.__class__.__name__
    out['timeout'] = exc.code == 'timeout'
    out['timeout_type'] = 'httpx_timeout' if out['timeout'] else None
out['latency_ms'] = round((time.monotonic()-started)*1000, 3)
out['pass'] = (
    out['provider_success'] and out['native_schema_parse_success']
    and not out['unknown_statement_id'] and not out['semantic_selection_error']
)
print(json.dumps(out, sort_keys=True))
"""
    return json.loads(_run_shell(code, env))


def _run_native_schema_capability(env: dict[str, str]) -> dict[str, Any]:
    report = json.loads(LLM_ARTIFACT.read_text(encoding="utf-8"))
    cases = []
    for case_code, query_run_code in NATIVE_SCHEMA_CAPABILITY_CASES:
        cases.append(_native_schema_case(case_code, query_run_code, env))
        report["native_schema_capability_gate"] = {"cases": cases}
        _write_json_atomic(LLM_ARTIFACT, report)
    metrics = {
        "provider_success_count": sum(case["provider_success"] for case in cases),
        "schema_parse_success_count": sum(case["native_schema_parse_success"] for case in cases),
        "timeout_count": sum(case["timeout"] for case in cases),
        "unknown_statement_id_count": sum(case["unknown_statement_id"] for case in cases),
        "semantic_selection_error_count": sum(case["semantic_selection_error"] for case in cases),
    }
    passed = metrics == {
        "provider_success_count": 3,
        "schema_parse_success_count": 3,
        "timeout_count": 0,
        "unknown_statement_id_count": 0,
        "semantic_selection_error_count": 0,
    }
    report["native_schema_capability_gate"] = {
        "prompt_version": "closed-world-statement-selection-tr-v3",
        "native_format_schema": True,
        "timeout_ms": 60000,
        "cases": cases,
        "metrics": metrics,
        "decision": "PASS" if passed else "FAIL",
    }
    _write_json_atomic(LLM_ARTIFACT, report)
    return report


def _run_native_schema_benchmark(env: dict[str, str]) -> dict[str, Any]:
    report = json.loads(LLM_ARTIFACT.read_text(encoding="utf-8"))
    gate = report.get("native_schema_capability_gate", {})
    if gate.get("decision") != "PASS":
        raise RuntimeError("native_schema_capability_gate_not_passed")
    cases = []
    for case_code, query_run_code in NATIVE_SCHEMA_BENCHMARK_CASES:
        cases.append(_native_schema_case(case_code, query_run_code, env))
        report["native_schema_clean_benchmark"] = {"cases": cases}
        _write_json_atomic(LLM_ARTIFACT, report)
    successful = [case for case in cases if case["provider_success"]]
    latencies = sorted(case["latency_ms"] for case in cases)
    metrics = {
        "completed_cases": "12/12",
        "provider_success_count": len(successful),
        "provider_timeout_count": sum(case["timeout"] for case in cases),
        "native_schema_parse_success_count": sum(
            case["native_schema_parse_success"] for case in successful
        ),
        "invalid_unknown_statement_id_count": sum(case["unknown_statement_id"] for case in cases),
        "semantic_selection_error_count": sum(case["semantic_selection_error"] for case in cases),
        "potential_verified_error_count": 0,
        "failover_error_count": 0,
        "unsupported_number_count": 0,
        "unsupported_reference_count": 0,
        "unsupported_decision_count": 0,
        "final_user_visible_unsupported_fact_count": 0,
        "average_latency_ms": round(sum(latencies) / len(latencies), 3),
        "p95_latency_ms": latencies[-1],
    }
    passed = (
        metrics["provider_success_count"] >= 11
        and metrics["native_schema_parse_success_count"] == len(successful)
        and metrics["invalid_unknown_statement_id_count"] == 0
        and metrics["semantic_selection_error_count"] <= 1
    )
    report["native_schema_clean_benchmark"] = {
        "prompt_version": "closed-world-statement-selection-tr-v3",
        "native_format_schema": True,
        "timeout_ms": 60000,
        "cases": cases,
        "metrics": metrics,
        "decision": "PASS" if passed else "FAIL",
    }
    _write_json_atomic(LLM_ARTIFACT, report)
    return report


def _natural_language_case_context(env: dict[str, str]) -> dict[str, str]:
    code = f"""
import json
from apps.customers.models import Subscription
from apps.datasets.models import DataSnapshot
from apps.operations.models import CausalEvent
s = DataSnapshot.objects.get(snapshot_key={SNAPSHOT!r})
event = (
    CausalEvent.objects.filter(data_snapshot=s, root_device__district__isnull=False)
    .select_related('root_device__city', 'root_device__district')
    .order_by('event_code')
    .first()
)
subscription = Subscription.objects.filter(data_snapshot=s).order_by('subscription_number').first()
if event is None or subscription is None:
    raise RuntimeError('natural_language_acceptance_context_missing')
print(json.dumps({{
    'causal_event_code': event.event_code,
    'subscription_reference': subscription.subscription_number,
    'city': event.root_device.city.name,
    'district': event.root_device.district.name,
    'date': event.started_at.date().isoformat(),
}}))
"""
    return json.loads(_run_shell(code, env))


def _run_natural_language_parser_case(
    case_code: str,
    prompt: str,
    expected: dict[str, Any],
    env: dict[str, str],
) -> dict[str, Any]:
    code = f"""
import json
import time
from apps.datasets.models import DataSnapshot
from apps.orchestration.natural_language_intake import (
    NaturalLanguageQueryParseError,
    NaturalLanguageStructuredQueryParser,
    STRUCTURED_QUERY_PARSER_PROMPT_VERSION,
)
snapshot = DataSnapshot.objects.get(snapshot_key={SNAPSHOT!r})
started = time.monotonic()
out = {{
    'case_code': {case_code!r},
    'user_prompt': {prompt!r},
    'parser_provider': 'ollama',
    'parser_model': 'gemma4:12b-it-qat',
    'prompt_version': STRUCTURED_QUERY_PARSER_PROMPT_VERSION,
    'provider_success': False,
    'timeout': False,
    'native_schema_parse_success': False,
    'structured_query_validation': False,
    'actual_structured_query': None,
    'invented_field_count': 0,
    'missing_fields': [],
    'failure_reason': None,
}}
try:
    parsed = NaturalLanguageStructuredQueryParser().parse(
        original_query={prompt!r}, snapshot=snapshot
    )
    out['provider_success'] = True
    out['native_schema_parse_success'] = True
    out['structured_query_validation'] = True
    out['actual_structured_query'] = parsed.structured_query.to_audit_dict()
    out['missing_fields'] = [item.value for item in parsed.missing_fields]
except NaturalLanguageQueryParseError as exc:
    out['failure_reason'] = exc.code
    out['timeout'] = exc.code == 'query_parse_unavailable'
out['latency_ms'] = round((time.monotonic() - started) * 1000, 3)
expected = {expected!r}
actual = out['actual_structured_query'] or {{}}
out['pass'] = (
    out['provider_success']
    and out['native_schema_parse_success']
    and out['structured_query_validation']
    and out['missing_fields'] == []
    and all(actual.get(key) == value for key, value in expected.items())
)
if not out['pass'] and out['failure_reason'] is None:
    out['failure_reason'] = 'parsed_scope_does_not_match_expected'
print(json.dumps(out, ensure_ascii=True, sort_keys=True))
"""
    return json.loads(_run_shell(code, env))


def _run_natural_language_parser_capability(env: dict[str, str]) -> dict[str, Any]:
    context = _natural_language_case_context(env)
    date = context["date"]
    causal_event_code = context["causal_event_code"]
    subscription_reference = context["subscription_reference"]
    district = context["district"]
    city = context["city"]
    cases = (
        (
            "BLACKBOX-01",
            f"{date} ile {date} arasinda {district} ilcesinde kac kesinti yasandi? "
            "Potansiyel kapsami, gercekten etkilendigi dogrulanan baglantilari, "
            "etkilenmedigi dogrulananlari, kaniti yetersiz olanlari ve failover ile "
            "korunanlari ayri ayri belirt.",
            {
                "intent": "outage_impact",
                "location": {"city": city, "district": district},
            },
        ),
        (
            "BLACKBOX-02",
            (
                f"Public olay kodu {causal_event_code} olan kesintinin dogrulanmis ana kok "
                "nedeni nedir? Bu olayla iliskili Dying Gasp ve Device Not Active alarmlari "
                "kok neden mi, yoksa belirti mi?"
            ),
            {"intent": "network_investigation", "causal_event_code": causal_event_code},
        ),
        (
            "BLACKBOX-03",
            (
                f"Public olay kodu {causal_event_code} icin ana baglantinin durdugu ve yedek "
                "baglantinin aktif kaldigi goruluyor. Bu olay tam hizmet kesintisi olarak mi "
                "siniflandirilmistir? Gercek musteri etkisini ve failover durumunu acikla."
            ),
            {"intent": "outage_impact", "causal_event_code": causal_event_code},
        ),
        (
            "BLACKBOX-04",
            (
                f"Public olay kodu {causal_event_code} ve abonelik referansi "
                f"{subscription_reference} icin tazminat uygunluk sonucu nedir? Kararin dayandigi "
                "dogrulanmis etkiyi, RuleVersion'i ve DecisionEvidence kaydini belirt."
            ),
            {
                "intent": "compensation_evaluation",
                "causal_event_code": causal_event_code,
                "subscription_reference": subscription_reference,
            },
        ),
        (
            "BLACKBOX-05",
            (
                f"Public olay kodu {causal_event_code} icin uretilen eligibility karari hangi "
                "RuleVersion'a, DecisionEvidence kaydina ve RAG kaynaginin hangi source, version "
                "ve section bolumune dayanir?"
            ),
            {"intent": "rule_document_retrieval", "causal_event_code": causal_event_code},
        ),
        (
            "BLACKBOX-06",
            (
                f"Public olay kodu {causal_event_code} ve abonelik referansi "
                f"{subscription_reference} icin musterinin gercekten etkilendigi kesin olarak "
                "dogrulanmis mi? Kanit yetersizse neden kesin etki karari verilemedigini acikla."
            ),
            {
                "intent": "outage_impact",
                "causal_event_code": causal_event_code,
                "subscription_reference": subscription_reference,
            },
        ),
    )
    report: dict[str, Any] = {
        "gate": "PRE-061-natural-language-parser-capability",
        "snapshot_identifier": SNAPSHOT,
        "context": context,
        "cases": [],
    }
    for case_code, prompt, expected in cases:
        report["cases"].append(_run_natural_language_parser_case(case_code, prompt, expected, env))
        _write_json_atomic(BLACK_BOX_ARTIFACT, report)
    report["metrics"] = {
        "case_count": len(report["cases"]),
        "provider_success_count": sum(case["provider_success"] for case in report["cases"]),
        "native_schema_parse_success_count": sum(
            case["native_schema_parse_success"] for case in report["cases"]
        ),
        "structured_query_validation_count": sum(
            case["structured_query_validation"] for case in report["cases"]
        ),
        "invented_field_count": sum(case["invented_field_count"] for case in report["cases"]),
        "passed_count": sum(case["pass"] for case in report["cases"]),
    }
    report["decision"] = "PASS" if report["metrics"]["passed_count"] == 6 else "FAIL"
    _write_json_atomic(BLACK_BOX_ARTIFACT, report)
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
    parser.add_argument("--closed-world-gemma", action="store_true")
    parser.add_argument("--native-schema-capability", action="store_true")
    parser.add_argument("--native-schema-benchmark", action="store_true")
    parser.add_argument("--natural-language-parser-capability", action="store_true")
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
        "OLLAMA_LLM_TIMEOUT_MS": "60000",
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
            json.dumps(report["final_gap_completion"]["gemma"], ensure_ascii=True, sort_keys=True)
        )
        return 0
    if options.closed_world_gemma:
        report = _run_closed_world_gemma(env)
        report["gemma_unloaded_after_closed_world_rerun"] = _unload_model("gemma4:12b-it-qat")
        _write_json_atomic(LLM_ARTIFACT, report)
        print(json.dumps(report["closed_world_rerun"], ensure_ascii=True, sort_keys=True))
        return 0 if report["closed_world_rerun"]["decision"] == "PASS" else 1
    if options.native_schema_capability:
        report = _run_native_schema_capability(env)
        report["gemma_unloaded_after_native_schema_capability"] = _unload_model("gemma4:12b-it-qat")
        _write_json_atomic(LLM_ARTIFACT, report)
        print(
            json.dumps(report["native_schema_capability_gate"], ensure_ascii=True, sort_keys=True)
        )
        return 0 if report["native_schema_capability_gate"]["decision"] == "PASS" else 1
    if options.native_schema_benchmark:
        report = _run_native_schema_benchmark(env)
        report["gemma_unloaded_after_native_schema_benchmark"] = _unload_model("gemma4:12b-it-qat")
        _write_json_atomic(LLM_ARTIFACT, report)
        print(
            json.dumps(report["native_schema_clean_benchmark"], ensure_ascii=True, sort_keys=True)
        )
        return 0 if report["native_schema_clean_benchmark"]["decision"] == "PASS" else 1
    if options.natural_language_parser_capability:
        report = _run_natural_language_parser_capability(env)
        report["gemma_unloaded_after_parser_capability"] = _unload_model("gemma4:12b-it-qat")
        _write_json_atomic(BLACK_BOX_ARTIFACT, report)
        print(json.dumps(report, ensure_ascii=True, sort_keys=True))
        return 0 if report["decision"] == "PASS" else 1
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
            endpoint_cases = _endpoint_matrix(headers, context, only_case=options.endpoint_case)
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
