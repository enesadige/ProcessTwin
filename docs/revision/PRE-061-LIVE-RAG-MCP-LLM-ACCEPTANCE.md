# PRE-061 Live RAG + MCP + LLM Acceptance

## Gate Decision

**FAIL — acceptance coverage incomplete.** The local core has a real successful
smoke path, but the required benchmark and scenario coverage has not yet met
the gate's full acceptance threshold. `MAIN-061` must not start from this gate.

## Verified Local Smoke

- Snapshot: `multi-city-realism-v2-causal-r1-multi-city-realism-snapshot-v1-multi-city-realism-v2-causal-r1`.
- Scoped corpus: 8 SourceDocuments, 23 chunks, and 23 active
  `ollama/qwen3-embedding:4b` embeddings at 768 dimensions.
- Real hybrid retrieval returned 5 snapshot-scoped results.
- Four separate stdio MCP processes completed one real call each: Network 9,
  Customer 7, Rule 8, Compensation 6 tools.
- The authenticated endpoint completed one real QueryRun through stdio MCP and
  Internal API. The real Ollama provider path was invoked; fact validation
  returned the deterministic fallback, preserving the validated machine result.
- Qwen had no resident process before Gemma acceptance began. Gemma remained
  resident after the call; no simultaneous residency was observed.

## Narrow Fixes Applied

- Added an acceptance-only stdio transport selected by
  `ORCHESTRATION_MCP_TRANSPORT=stdio`; the default direct transport is unchanged.
- Normalized string snapshot metadata from causal Internal API responses before
  MCP response construction.
- Refreshed the caller QueryRun after the executor's persisted
  `planned -> executing` transition so result merge sees the current state.
- Applied the existing `orchestration.0001_initial` migration to the local
  PostgreSQL environment; no snapshot data was reset or regenerated.

## Remaining Blockers

- The harness currently records one smoke case, not the required 15-case
  GroundTruth/RAG benchmark distribution or top-k/citation metrics.
- Rule-document retrieval has not yet been carried through a real endpoint
  plan because the current deterministic planner deliberately returns
  clarification for that intent.
- Gemini credentials are configured but no external Gemini smoke was run.
- The Gemma narrative outcome was fallback; separate narrative error-rate and
  adversarial fact-guard metrics are still required.

The machine-readable smoke artifact is
`artifacts/pre061/live_acceptance_report.json`; it contains only public codes,
counts, statuses, and timings.
