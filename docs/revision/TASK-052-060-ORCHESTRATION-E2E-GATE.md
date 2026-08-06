# Task 052-060 Orchestration E2E Gate

## Scope

The authenticated internal orchestration endpoint connects the existing layers
without adding planner, MCP business logic, retrieval, or provider behavior:

`QueryRun -> StructuredQuery -> deterministic planner -> ToolExecutor ->
ResultMergerValidator -> ValidatedResponseBuilder`.

The request requires an explicit snapshot identifier and idempotency key. Its
only accepted execution inputs are the redacted original query, a strict
StructuredQuery mapping, and a deterministic or LLM-assisted presentation
mode. Provider, model, tool, transport, timeout, prompt, raw payload, and
database-primary-key overrides are rejected.

## Lifecycle And Replay

The facade creates or retrieves a snapshot-bound QueryRun, persists the valid
StructuredQuery and ToolPlan, then delegates execution and finalization to the
existing services. It preserves `pending -> planned -> executing ->
completed|failed`; a clarification or unplannable plan remains `planned` and
does not invoke the executor.

Completed runs are replayed from the validated machine result without planning
or executing tools again. Executing runs return `run_in_progress`; failed runs
return their stable safe error and require a new idempotency key. A reused key
with another snapshot or structured query returns `idempotency_conflict`.
Changing response mode is presentation-only and never replays MCP execution.

## Safety Boundaries

The endpoint uses the existing internal service-token authentication and
correlation-ID conventions. Snapshot identity remains equal across QueryRun,
StructuredQuery, ToolPlan, executor result, and validated result. The response
envelope contains only a public QueryRun code, status, snapshot identifier,
replay flag, typed response, clarification, or stable safe error.

QueryRun audit and endpoint output exclude original query text, raw MCP or
provider payloads, credentials, headers, IP/MAC values, customer identifiers,
and tracebacks. LLM-assisted output continues to use the existing deterministic
fallback, so a provider failure still yields a successful deterministic response
when the machine result is valid.

## Verification

- Targeted endpoint, orchestration, provider, and MCP-contract regression set:
  **164 passed**.
- Ruff: `All checks passed` for `backend` and `mcp_servers`.
- Django check: no issues.
- `makemigrations --check`: no changes detected.
- Full suite: **836 passed in 396.28s (0:06:36)**.

All endpoint tests inject fake MCP execution and mock/fake LLM providers. No
native seed, RAG indexing, real Gemini/Ollama request, or MCP network/process
execution ran.

## Transition

Task 060 closes the synchronous authenticated orchestration integration. The
next integration work must be selected from the current project plan; it must
not change the validated snapshot or add a new provider/tool override surface.
