# V3 Activation Handoff (2026-08-14)

## Safety State

- Current HEAD: `b2f5b6d4abf479307a298296aa8cb5509fa86844`
- Current commit: `feat: finalize v3 operational dataset calibration`
- Recovery tag: `pre-dataset-calibration-20260813T132426`
- V2 rollback snapshot: `54` (preserved)
- Original V3 candidate: `73` (preserved)
- Repair candidate: `74`, validated and inactive
- Snapshot 74 has not been activated or operationally mutated in this task.
- Frontend still selects the snapshot-54 key. Do not change it until all remaining gates pass.
- No activation/docs commit has been created.

## Completed In This Acceptance Run

- Audited snapshot selection: frontend sends an exact snapshot key; `OrchestrationFacade._snapshot()` resolves it. `is_active` is not the AI Analysis selector.
- Committed V3 builder/repair implementation as `b2f5b6d`.
- Verified snapshot-54/74 base-world fingerprints match for customer, subscription, device, port, link, line, and subscription connection IDs.
- Verified snapshot 74 counts: customers 14,400; subscriptions 16,200; devices 238; events 94 (91+3); alarms 420; sessions 77,125; assessments 49,996; compensation evaluations 10,658; DecisionEvidence 10,716.
- Verified CE-MCR-0052 persisted truth: potential 1,441; impacted subscriptions 1,009; affected customers 924; unknown 432; protected 0.
- Verified CE-MCR-0041/0044/0084 hitless truth: impacted 0; protected/no-impact 1; unknown 0.
- Verified compensation total: 204,274.61 TRY; duplicate/unlinked/cross-snapshot counts are zero.
- RAG corpus was safely inherited from declared source snapshot 54 where GroundTruthCase provenance requires it. Snapshot-74 RAG index/Local Qwen embeddings were created. New alarm `XREG_UPSTREAM_DOWN` was added to the canonical alarm docs/manifest.
- Generic fixes currently uncommitted:
  - filtered aggregate no longer groups by incidental word "olaylarında";
  - exact event/outage compensation is not misclassified as dataset analytics;
  - document-meaning intent works without an operational anchor;
  - semantic dimensions cannot expand document retrieval into impact output;
  - customer-impact endpoint prefers persisted authoritative CustomerImpactAssessment facts and retains the old topology fallback only when assessments do not exist;
  - decimal compensation is not redacted as a phone number;
  - ranked/trend comparison facts and unknown-exclusion facts are first-class narrative support;
  - typographic/Turkish thousands separators are normalized before numeric grounding;
  - markdown role prefixes and parenthesized internal support labels are removed;
  - retrieved RAG chunk text is carried as a verified excerpt in RetrievalSource/AnswerPlan.

## Validation Already Passing

- Parser/response/RAG focused run: `157 passed, 11 skipped`.
- Latest response/parser/result-merge/RAG run: `137 passed, 11 skipped`.
- Ruff on the touched acceptance paths: PASS before the latest small edits; rerun is required.
- Direct snapshot-74 endpoint proof:
  - CE-MCR-0006: potential 1,441; impacted subscriptions 1,009; customers 926; unknown 432.
  - CE-MCR-0052: potential 1,441; impacted subscriptions 1,009; customers 924; unknown 432; protected 0.

## Latest Live E2E Results

Artifacts:

- `/tmp/v3_preacceptance_retry5.jsonl`
- `/tmp/v3_preacceptance_retry6.jsonl`
- deterministic audit: `/tmp/v3_acceptance_readonly.json`

Passing snapshot-74 QueryRuns from the latest run:

- Failed-failover aggregate: `QR-F79C997E525D4351BD297C0014A1B381`, completed/llm_assisted/warnings=[], total 5,921, included 7, excluded unknown 0.
- Hitless: `QR-38012E68F4C44B419A46867C3F474C65`, completed/llm_assisted/warnings=[], impacted 0, protected 1.
- Correlation: `QR-8C616F7425254BDCB75A0AE2BB930C9E`, completed/llm_assisted/warnings=[].
- Trend: `QR-813B705801514B378CFB5AB41B0463B1`, completed/llm_assisted/warnings=[], June 11,477, July 10,719, change -758, decrease.
- RAG transport/retrieval: `QR-276A028814C2488994F30945F793F99C`, completed/llm_assisted/warnings=[]; retrieved snapshot-74/Qwen sources.

## Remaining Blockers Before Activation

1. Compensation evidence normalization
   - `OUT-MCR-0052` has 984 persisted CompensationEvaluation rows, but QueryRun `QR-543F80F99C164A4E9D614B68D8B993B5` ends with `required_evidence_missing` although the compensation MCP call succeeds.
   - Trace `mcp_servers/compensation/tools.py::_success`, `result_merge._compensation_evidence`, and required category assembly.
   - Prove an anchored outage returns total/RuleVersion/DecisionEvidence from its persisted snapshot-local records. Do not recalculate or mutate compensation.

2. Plain internal support labels in RAG prose
   - Parenthesized `(S2)` is removed, but the provider can emit plain `S1` / `S3` in prose.
   - Extend user-facing support-label sanitization only for standalone internal statement references. Do not alter real public IDs.
   - Rerun RAG E2E and ensure the answer is grounded in the newly propagated retrieved excerpts and source metadata.

3. Recheck unsupported qualitative prose
   - The latest generic qualitative filters were added after the failed-event E2E. Rerun CE-MCR-0052 and ensure recommendations such as system strengthening, mechanism inadequacy, or unverified user/business consequences are removed unless excerpt/AnswerPlan support exists.

## Exact Continuation Order

1. Keep snapshots 54/73/74 unchanged and 74 inactive.
2. Fix the two blockers above with focused tests.
3. Run Ruff and the focused parser/response/result-merge/network/RAG suites.
4. Restart backend with environment (do not print secrets):
   - server must use `INTERNAL_API_SERVICE_TOKEN=v3-acceptance-local`;
   - acceptance process must use `MCP_BACKEND_BASE_URL=http://127.0.0.1:8000` and `MCP_BACKEND_SERVICE_TOKEN=v3-acceptance-local` plus project `.env` for Groq/Qwen.
5. Rerun failed-event, compensation, RAG, ranking, trend, unknown-ID and clarification E2E on explicit snapshot 74. Require completed, llm_assisted where provider healthy, warnings=[], and no unsupported prose.
6. Run complete deterministic analytics/correlation/RAG integrity gates and Django/Ruff/migration/frontend checks.
7. Only when every pre-activation gate passes, change `frontend/src/pages/AIAnalysisPage.tsx` exact snapshot key from 54 to 74. Do not set `is_active` blindly.
8. Create at least three new QueryRuns and prove in DB that `data_snapshot_id == 74`; prove replay preserves older QueryRun snapshot IDs.
9. Run post-activation UI/integrity smoke.
10. Commit focused integration changes, update all four tracking surfaces, and leave a clean tree. Do not start MAIN-066.

## Current Verdict

`V3 PRODUCTION-CANDIDATE ACCEPTANCE: NOT YET PASSING`

Activation was intentionally not performed.

## Final Activation State

- Integration and safe selection commit: `60fa4fa feat: activate validated v3 operational snapshot`.
- AI Analysis now sends the exact snapshot-74 key. Snapshot 74 operational data
  was not mutated; snapshots 54 and 73 remain preserved rollback candidates.
- Live proofs include compensation `QR-8A6E3F7F80DF4D9AAED5497324E5E87B` and
  trend `QR-7E25E206763347C6B71EF993D7891AC7`, both completed/llm_assisted with
  warnings=[] and deterministic backend cards.
- Groq can externally rate-limit during a burst; individual healthy calls pass
  grounded synthesis. Existing deterministic fallback remains safe.
- Rollback requires changing only the frontend exact snapshot key to snapshot 54.

`V3 PRODUCTION-CANDIDATE ACCEPTANCE: PASS`
