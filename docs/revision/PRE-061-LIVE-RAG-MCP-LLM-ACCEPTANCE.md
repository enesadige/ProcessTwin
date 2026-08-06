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

## Extended Run: Retrieval Benchmark

The second live run reused the existing 23 corpus embeddings and executed 15
real Qwen hybrid queries before a graceful Qwen unload. It recorded **0.40**
top-1, **0.40** top-3, and **0.40** top-5 expected-source hit rates; 9 cases
had a critical citation mismatch. Snapshot leakage remained **0**. Average
latency was 2209.851 ms and p95 was 2520.506 ms.

This is a real retrieval-quality failure, not a mock limitation. The causal
snapshot has only 23 scoped chunks while retrieval also surfaces active global
documents; the acceptance criteria require corpus/metadata/hybrid-ranking work
before the remaining Gemma, Gemini, and endpoint scenario benchmarks can be
meaningfully accepted. Qwen and Gemma were gracefully unloaded after the run.

## Retrieval Root-Cause Follow-up

The failure analysis established that the expected broadband, Metro SLA,
overview, and review-cap SourceDocuments existed in the causal snapshot but
had zero indexed chunks. The initial live embedding run therefore covered only
the 23 pre-existing alarm-catalog and eligibility chunks. The scoped idempotent
index command added the missing policy chunks, increasing the scoped corpus to
54 chunks before generating only the missing Qwen embeddings.

The final retrieval-only run exposed a harness early-return persistence bug:
its in-memory metrics were not written to the artefact. The writer is fixed,
but the 15-case benchmark was not launched a third time. The gate remains
**FAIL** until a single persisted post-index benchmark supplies the required
top-k and citation metrics.

## Persisted Post-Index Benchmark

The persisted 15-case run on the 54-chunk / 54-embedding scoped corpus yielded
top-1 **66.67%**, top-3 **80%**, and top-5 **86.67%**. Critical citation
mismatches fell from 9 to 2; snapshot leakage remained 0. Average latency was
2206.707 ms and p95 was 2801.314 ms. The top-5 and zero-mismatch requirements
are not met, so retrieval remains **FAIL**. The two remaining cases are in
`artifacts/pre061/rag_retrieval_failure_analysis.json`.

## Final Citation Correction

RAG-06 and RAG-09 were stale benchmark labels, not retrieval failures. The
failover procedure's `İstisnalar ve Kanıt` section is authoritative for RAG-06;
the overview document's `Kanıt ve Açıklanabilirlik` section is authoritative
for RAG-09. No chunk, embedding, prompt, model, or ranking change was made.
The final persisted run reached top-1 **73.33%**, top-3 **93.33%**, top-5
**100%**, zero citation mismatches, and zero leakage (average 1655.490 ms,
p95 1747.204 ms). The PRE-061 retrieval stage is **PASS**; Gemma/Gemini
acceptance may proceed in its dedicated phase.

## Final LLM Acceptance Correction

**Overall PRE-061 decision remains FAIL.** The Gemini 400 classification was
corrected without changing the fixed `gemini-3.5-flash` descriptor or retry
policy: the real SDK response has an API-key marker and is now safely mapped
to `invalid_api_key`, not `invalid_request`. The real smoke remains blocked;
no key, prompt, or provider body was persisted.

The non-retrieval endpoint matrix ran once through the real backend, stdio
MCP transport, Internal API, native snapshot, and Ollama provider. LIVE-08
initially exposed an outage-scoped root-cause response normalization gap. The
Network MCP now projects only allowlisted first-candidate fields; the targeted
real rerun completed `200`, `completed`, and `llm_assisted`. HTTP/lifecycle
expectations are therefore 10/10 after reconciliation.

This is not a gate PASS. LIVE-07 is still planner clarification because the
current schema/planner has no safe retrieval-query field, so no real endpoint
RAG-citation answer exists. Nine real Gemma narrative calls are recorded,
below the required 12-case set. Observed final responses retained validated
deterministic blocks with zero unsupported user-visible facts, but this does
not replace the incomplete narrative benchmark. Gemma was gracefully unloaded
and no Qwen/Gemma co-residency was observed.

## Gemini Matrix And LIVE-07 Follow-up

The ephemeral configured key was present in the diagnostic process and passed
explicitly to `genai.Client`; `GOOGLE_API_KEY` was absent. The real matrix
returned `API_TEST_OK` for `gemini-3.6-flash` through `interactions.create`
(3078.713 ms), `gemini-3.5-flash` through `interactions.create` (2510.039 ms),
and `gemini-2.5-flash` through `models.generate_content` (1085.279 ms).
Production Gemini is therefore the deterministic first choice:
`gemini-3.6-flash` with the interactions family. The adapter receives the
resolved API key explicitly; request payloads cannot select model, API family,
or credentials.

Four real completed-QueryRun fact-sheet smokes reached the selected Gemini
provider. All four safely fell back to deterministic output after fact guard;
no user-visible unsupported fact was observed. The earlier `invalid_api_key`
classification was an old process/config result, not a failure of the supplied
ephemeral key.

LIVE-07 was fixed at schema/planner level with a strict `retrieval_query` that
plans the existing Rule MCP `search_rule_documents` tool. Its first live call
then found a required-evidence policy conflict, fixed by making document
retrieval the sole required category for that intent. The post-fix live
launcher did not persist an artefact and was gracefully stopped; this is not
accepted as a passing live result. Together with Gemma still at 9/12 cases,
the overall gate remains **FAIL**.

## Final Live LLM Attempt

**Overall PRE-061 decision: FAIL.** Retrieval remains PASS, but the mandatory
live LLM and endpoint acceptance matrix is incomplete; `MAIN-061` must not
start from this gate.

- One real Gemma call used the completed QueryRun's privacy-safe fact sheet
  through `OllamaLLMProvider` (`gemma4:12b-it-qat`, `think:false`,
  `stream:false`). The provider response contract was valid, but the narrative
  introduced a public reference absent from the fact sheet. The fact guard
  correctly rejected it and the user-visible path remains deterministic
  fallback. This is a model narrative failure, not a guard false positive.
- The required 12-case Gemma narrative/adversarial matrix was not completed,
  so its acceptance, contradiction, fallback, and final-output rates cannot
  be claimed.
- `GEMINI_API_KEY` was configured. One real `gemini-3.5-flash` adapter smoke
  attempt returned the redacted stable provider code `invalid_request`; no
  credential, prompt, or provider body was recorded. The required four-case
  Gemini smoke matrix therefore remains blocked.
- The prior real stdio MCP/Internal API/Gemma endpoint smoke remains recorded,
  but only one of the required ten endpoint scenarios has live evidence. The
  current planner also returns clarification for rule-document retrieval, so
  a real endpoint RAG-citation case cannot yet satisfy the requested matrix.
- Qwen was not resident at phase start. Gemma was gracefully unloaded after
  the diagnostic; no simultaneous Qwen/Gemma residency was observed.
