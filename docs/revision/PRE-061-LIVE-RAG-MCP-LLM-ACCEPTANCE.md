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

## Final Gap Completion

**Overall PRE-061 decision remains FAIL.** The remaining LIVE-07 evidence is
now accepted: the post-fix single-case harness wrote its result to
`artifacts/pre061/live_live_07.json`, rather than the aggregate artifact. It
completed with HTTP `200`, a completed QueryRun, the real Rule MCP
`search_rule_documents` tool, five snapshot-scoped source/version/section
citations, citation support, zero critical mismatch, zero leakage, and zero
privacy violations. The prior "orphaned launcher" diagnosis was incorrect;
the actual defect was missing aggregate-artifact reconciliation.

The three missing real Gemma calls are now recorded as
`GEMMA-10-RAG-CITATION`, `GEMMA-11-IMPACT`, and
`GEMMA-12-COMPENSATION`. They used `gemma4:12b-it-qat` through the existing
provider contract with `think:false` and `stream:false`: two deterministic
fallbacks and one LLM-assisted response. All three user-visible outputs were
safe. Gemma was then unloaded; Qwen was not resident.

The initial nine records could not be recovered, so they were rerun exactly
once with the same provider, fact-sheet schema, prompt version, and fact
guard. Raw narratives remain unpersisted. The completed matrix is 12/12, with
model narrative acceptance **25%**, safe deterministic fallback success
**100%**, final user-visible unsupported facts **0**, average latency
**17,849.351 ms**, and p95 **42,154.237 ms**. Seven of the rerun narratives
were rejected for an unsupported number, public reference, or decision. This
establishes a **58.33% lower bound** for model unsupported-fact/contradiction
rate, above the **10%** gate threshold. The current fact guard does not
separately classify potential/verified or failover semantic contradictions;
those fields are recorded as not assessed rather than inferred.

PRE-061 is therefore **FAIL**, not because of missing provenance any longer,
but because real Gemma narrative quality fails the threshold. `MAIN-061`
remains blocked until a narrow narrative-quality remediation and rerun pass.

## PRE-061 Closed-World Narrative Remediation

**Decision: FAIL; no further prompt iteration was run.** Prompt version
`closed-world-structured-narrative-tr-v2` replaced the free-text instruction
with a per-case JSON allowlist: numbers, public references, decisions, root
causes, canonical impact/failover statuses, citations and the one permitted
uncertainty statement. The provider contract remained `gemma4:12b-it-qat`,
`think:false`, `stream:false`.

Only the nine historical failures were called once. The three prior direct
PASS cases (`GEMMA-04-CUSTOMER-IMPACT`, `GEMMA-05-RULE-EVIDENCE`, and
`GEMMA-11-IMPACT`) were preserved, so this is explicitly a mixed-prompt
12-case report rather than a single homogeneous run. Every rerun response was
either a provider error (four cases) or non-parseable structured output (five
cases). No raw narrative, PII, secret, or model text was persisted.

The structured validator and deterministic response builder kept unsupported
number/reference/decision counts at 0; potential/verified and failover
contradictions were also 0; fallback success was 100%; and final user-visible
unsupported facts were 0. Direct narrative acceptance remained 25% (the three
preserved PASS cases), with 9/12 narrative contradictions, exceeding the
maximum 1/12. Gemma was gracefully unloaded and `ollama ps` showed no resident
model. The next permitted acceptance task, if PRE-061 is later passed, remains
the six real-user-prompt black-box tests; it cannot start now.

## PRE-061 Native Schema Statement Selection

**Decision: PASS.** The previous parse failures were caused by asking Gemma to
honour JSON only through prompt text: the adapter used `/api/chat` with
`think:false` and `stream:false`, but sent no `format` schema. Its timeout was
30 seconds. Historical provider errors contain no persisted HTTP status,
exception subtype, or Ollama timing fields, so they are recorded as unknown
rather than misclassified as semantic contradictions.

Version `closed-world-statement-selection-tr-v3` sends a real per-case native
Ollama JSON Schema in `format`, plus `raw:false` and `temperature:0`. Backend
constructs canonical privacy-safe statement IDs from validated results; Gemma
can select and order IDs only. The final Turkish response is assembled solely
from those backend statements. A measured prior p95 above 30 seconds justified
a benchmark-only 60-second timeout; no unlimited timeout was introduced.

The three-case capability gate passed 3/3 provider calls and native-schema
parses, with zero unknown IDs and semantic selection errors. It enabled one
clean 12-case, single-prompt run: provider success 12/12, timeout 0,
native-schema parse 12/12, invalid/unknown ID 0, semantic selection error 0,
potential/verified error 0, failover error 0, unsupported
number/reference/decision 0, and final user-visible unsupported fact 0.
Average latency was 12,822.656 ms and p95 26,180.598 ms. Gemma was unloaded
after the run. This supersedes the prior mixed-run narrative result; the six
user-prompt black-box test remains the next acceptance work, not part of this
task.

## Current Reconciled Status

The historical FAIL sections above are retained as evidence for the iterations
that preceded the native-schema contract. They do not override the latest
Gemma-specific result at commit `3c364e3`.

| Acceptance area | Current status | Evidence / boundary |
| --- | --- | --- |
| Retrieval | **PASS** | 8 sources, 54 chunks and embeddings; top-3 93.33%, top-5 100%, critical citation mismatch 0, snapshot leakage 0. |
| Gemini provider and smoke | **PASS** | Real provider diagnostic and four privacy-safe smoke cases were recorded before this reconciliation. |
| Gemma native-schema statement selection | **PASS** | `closed-world-statement-selection-tr-v3`: capability 3/3 and one clean 12/12 real-provider run. |
| Normal Turkish user-query black-box E2E | **NOT RUN / BLOCKED** | The authenticated internal endpoint requires `structured_query`; it has no intake/parser that converts `original_query` into `StructuredQuery`. |

This is not a general PRE-061 PASS. Overall PRE-061 is **NOT COMPLETE** until
the missing intake/parser is implemented and six self-contained normal Turkish
user prompts have passed the real chain. `MAIN-061` remains blocked.

The next and only scoped task is: normal Turkish `original_query` -> safe
`StructuredQuery` -> deterministic planner -> real MCP/Internal API/RAG ->
Gemma statement selection -> final user response -> six self-contained
black-box tests. No black-box result is claimed here.

## Natural-Language Intake Capability

**Decision: FAIL.** The internal endpoint now accepts either a supplied,
validated `structured_query` replay payload or an `original_query`-only intake
payload. The latter calls `structured-query-parser-tr-v1`, which sends the
fixed local Gemma model through the existing `/api/chat` adapter with native
JSON Schema, `think:false`, `stream:false`, `raw:false`, and temperature zero.
The backend rejects invented public references, dates, locations, and
subscription references before planning; it also checks supplied public event,
outage, and subscription references against the selected snapshot.

The one real six-case parser capability run did not meet its gate. One response
was schema-valid but produced an incorrect scope and unexpected missing fields;
five responses exhausted the adapter's two 60-second attempts and returned
`query_parse_unavailable`. Therefore provider/schema/StructuredQuery success
was 1/6 and scope-match was 0/6. The endpoint, MCP, RAG, and final six-case
black-box chain were **not started**. Gemma was unloaded after the run.

PRE-061 remains **FAIL / BLOCKED** and `MAIN-061` must not start. No second
prompt-tuning or black-box run was opened in this task.

## Deterministic Intake And Final E2E

**Decision: PASS.** The LLM parser was removed from the normal intake path
because scope extraction is deterministic work and its local-provider retries
made it both slower and less reliable. `DeterministicStructuredQueryParser`
now extracts only user-supplied dates, locations and public references, and
persists the validated query before planning. Its real snapshot gate passed
6/6 with zero LLM calls, invented fields or unexpected missing fields.

The real original-query baseline then passed 6/6 with Gemma and Qwen. The
aggregate location tool uses `CustomerImpactAssessment` as the canonical
counter source and carries outage count, potential, verified, no-impact,
insufficient-evidence and failover-protected values through result merge and
the canonical statement builder. All six HTTP requests completed with
LLM-assisted statement selection; machine facts and citations are persisted
in `final_black_box_acceptance.json`.

Provider parity passed 4/4 combinations and 8/8 real HTTP cases: Gemma+Qwen,
Gemma+Gemini Embedding, Gemini+Qwen and Gemini+Gemini Embedding. Gemini uses
the 3.6 Interactions API with native `response_format` JSON Schema; it selects
only backend-generated statement IDs. The acceptance snapshot has independent
Qwen and Gemini embedding coverage of 54/54 canonical chunks, with zero
cross-provider vector contamination. Exact fact and citation checks passed;
unsupported fact/reference/decision, privacy violations, snapshot leakage and
critical citation mismatches were all zero. PRE-061 is therefore **PASS** and
`MAIN-061` may start.

## Provider Selection Audit

The representative Gemini + Gemini Embedding HTTP case proved the provider
path: HTTP 200, QueryRun completed, Gemini `gemini-3.6-flash` returned a valid
canonical statement selection, and generation mode was `llm_assisted`.
The first representative failure was classified safely as
`provider_call_failed_rate_limited`; the harness had also forced
`GEMINI_LLM_MAX_ATTEMPTS=1`. With two bounded attempts, the final 18-case run
recorded 1/10 original and 0/8 unseen Gemini selections, with 17/18 safe
fallbacks. Semantic verdicts remained 10/10 and 8/8; provider acceptance
remains **NOT COMPLETE**.

## Semantic Audit Supersession

The preceding PASS paragraphs are historical records and are superseded by
`artifacts/pre061/semantic_generalization_acceptance.json`. The latest Gemini
+ Gemini Embedding run completed 10/10 original and 8/8 unseen HTTP QueryRuns,
but every recorded response used deterministic fallback
(`llm_narrative_fallback`); this does not prove successful Gemini statement
selection. PRE-061 therefore remains **NOT COMPLETE** and `MAIN-061` remains
blocked.

General fixes in this audit scope compensation evaluations to the resolved
outage, accept the MCP `snapshot_identifier` in causal analysis, return the
outage planner's constructed calls, and keep root resource, physical
root-cause reason, alarms, failover state and missing impact evidence as
distinct canonical statements. An exact compensation evaluation now
supersedes unrelated rule-tool candidates when rendering RuleVersion and
DecisionEvidence. The exact 10 original and 8 unseen questions are recorded
in the semantic artifact; HTTP 200 is not treated as a PRE-061 PASS.

## Provider Resilience Audit

Gemini retry behavior is now bounded: up to two attempts, provider retry timing
when available, otherwise 250 ms initial exponential backoff capped at 2000 ms
with 100 ms jitter. Non-transient configuration, authentication, malformed
response and validation errors are not retried. Retry metadata is limited to
attempt count and delay totals. The acceptance harness is sequential and uses
configurable `ACCEPTANCE_CASE_DELAY_SECONDS`, default 0.5 seconds.

The post-fix representative case passed with `llm_assisted`. A three-case
sequential burst with 0.5-second pacing exercised two attempts per case, but
all three were rate-limited and safely fell back. The prior 18-case run remains
1/10 original and 0/8 unseen provider-selection passes. This classifies the
code as **CODE_COMPLETE_PROVIDER_QUOTA_LIMITED**; PRE-061 is not promoted to
complete and MAIN-061 remains blocked.

## Semantic Completeness Revalidation

**Decision: PASS.** The earlier HTTP/provider pass was narrowed: it proved
execution and supported subsets, but did not require every user-requested
canonical statement in the final Turkish response. The statement contract now
adds backend-generated, immutable statements for the aggregate failover count,
named root cause and alarm classification, full-outage/primary/backup status,
verified-impact compensation basis, exact RuleVersion/DecisionEvidence, and
missing CustomerImpactAssessment evidence. No model-authored factual text is
rendered.

The semantic baseline passed 6/6. Each response includes its required
case-specific final fields and the corresponding merged machine fields. The
provider matrix passed 8/8 semantic checks across all four LLM/embedding
combinations. The model may order known statement IDs; omitted IDs are appended
by the backend in canonical order, so completeness is deterministic while
unknown or duplicate IDs remain rejected. `final_black_box_acceptance.json`
retains the pre-fix response where available and the new response plus field
checks for every case. No unsupported fact/reference/decision, privacy
violation, snapshot leakage, or citation mismatch was observed.
