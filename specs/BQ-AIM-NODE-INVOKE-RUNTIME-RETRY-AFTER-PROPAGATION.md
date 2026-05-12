# BQ-AIM-NODE-INVOKE-RUNTIME-RETRY-AFTER-PROPAGATION — Gate 1 Fix-Spec

**Pillar:** AIM-Node
**Priority:** P1
**Type:** Fix-spec (Gate 1, design-only)
**Repo:** aidotmarket/aim-node
**Branch:** spec/bq-aim-node-invoke-runtime-retry-after-propagation
**Spec path:** specs/BQ-AIM-NODE-INVOKE-RUNTIME-RETRY-AFTER-PROPAGATION.md

## Summary

When a buyer's streaming model invocation through the AIM Node V2 gateway breaches a byte / time / idle cap, ConnectorRuntime correctly raises `InvokeRuntimeError` with a stream-cap reason code but leaves the `retry_after_seconds` field unpopulated. Buyer client SDKs lose the ability to back off cleanly, forcing manual retry loops. This spec defines the canonical `retry_after_seconds` population rule per cap type and the test gating that locks the behavior in.

## §0 Honest-Posture Disclosure

This spec was authored from a sandbox without filesystem read access to `aidotmarket/aim-node`. All file paths, class names, attribute names, test names, and quoted code identifiers below are **grep-derived best-effort** from BQ context (BQ-AIM-NODE-GATEWAY-V2 Chunk 9 record, the BQ body, and the queue work brief). They are **not** verified file:line citations. Gate 2 builder on Titan-1 MUST:

1. Regrep `aim-node/src/**` for `ConnectorRuntime`, `InvokeRuntimeError`, and the cap-breach emission sites; reconcile names below against actual source before code.
2. Locate the strict-xfail test referenced in AC7; confirm exact path and test function name.
3. Confirm the cap-config object shape (whether `window_seconds` or equivalent rolling-window attr exists on byte/time cap configs) before locking AC2's per-cap-type derivation rule.
4. If any AC's source-tree assumption is invalidated by actual grep, escalate as Gate 1 revision rather than silently re-interpreting in Gate 2.

## §1 Background

**Origin:** Sibling follow-up to BQ-AIM-NODE-GATEWAY-V2 Chunk 9 (Observability, Quotas, Latency, Reliability Harness), shipped S560. Chunk 9 landed the cap-detection and `InvokeRuntimeError` emission paths. It did not populate the standardized retry signal because the policy was deferred to a follow-up.

**Current behavior (grep-derived, Gate 2 to verify):**
- ConnectorRuntime invoke streaming path detects three cap breach classes: **byte** (output bytes exceed per-invocation or rolling-window byte budget), **time** (wall-clock duration exceeds budget), **idle** (no bytes emitted for longer than idle threshold).
- On any cap breach, the path raises `InvokeRuntimeError` with a `reason_code` identifying the cap class and aborts the stream.
- The error includes `retry_after_seconds` as a defined field on the error contract (added by Chunk 9 for client-side back-off signaling) but the field is **left None / unset** on every cap-breach emission site.
- A test exists in `tests/gateway_v2/` referencing `test_quota_matrix_covers_invocation_stream_scope_with_retry_after` (or equivalent name — Gate 2 to confirm). The test is marked `strict-xfail` precisely because the field is unpopulated; the test asserts retry-after IS populated, expects to fail today, and acts as a tripwire for when the gap closes.

**Why this is P1:** Client SDKs that consume `InvokeRuntimeError` get no back-off guidance, so they either (a) retry immediately and re-hit the same cap, (b) implement local heuristic delays that diverge from server intent, or (c) surface the failure to the buyer's application as a hard error. None of these is the industry-standard rate-limit semantic (HTTP `Retry-After` / SDK `retry_after_seconds`).

## §2 Design Decision

**Locked: per-cap-type derivation rule with deterministic defaults.**

For each cap-breach emission site, populate `retry_after_seconds` according to the cap kind:

**byte_cap breach:**
- If the breached cap is window-based (i.e., the cap config object exposes a rolling-window attribute Gate 2 will confirm — referred to here as `window_seconds`): `retry_after_seconds = max(1, seconds_until_window_close)`.
- If the cap is per-invocation hard-cap (no rolling window): `retry_after_seconds = MIN_HARD_CAP_RETRY` (suggested default 5; Gate 2 locks the constant) AND the error metadata sets `cap_kind = "per_invocation_hard"` so client SDKs can distinguish "wait and retry" from "reduce request scope."

**time_cap breach:**
- Same shape as byte_cap: window-based → seconds-until-window-close; hard-cap → `MIN_HARD_CAP_RETRY` with `cap_kind = "per_invocation_hard"`.

**idle_cap breach:**
- Always populate with `IDLE_RETRY_DEFAULT` (suggested default 10; Gate 2 locks the constant). Idle-cap is a connector responsiveness signal, not a quota-window signal, so the value is a standard connector-health backoff. Set `cap_kind = "idle"`.

**Non-streaming-cap errors** (auth failure, connector internal error, schema-validation error, etc.) — leave `retry_after_seconds = None`. The field must remain a positive-signal field, not a noise field.

**Rationale for this design over alternatives:**
- **Option A (constant per cap class, no config introspection)** — simpler but loses the rolling-window semantic that lets clients hit exactly the next window boundary. Rejected.
- **Option B (this design — config-aware with deterministic fallback)** — clients get accurate window-close timing when available, sane back-off when not, and `cap_kind` metadata to distinguish retry-worthy from request-scope-fix-required. Chosen.
- **Option C (dynamic-from-runtime-buffer-state, e.g., predict-time-until-next-quota-grant from token-bucket math)** — overengineered for Gate 1; defer until observability data justifies the complexity.

## §3 Acceptance Criteria

**AC1 — Current behavior documented.** Spec §1 above documents the cap-breach emission paths in ConnectorRuntime invoke streaming and the strict-xfail test that gates this BQ. References use honest-posture grep-derived names; Gate 2 builder confirms exact identifiers before code.

**AC2 — Policy decision locked.** §2 above defines the per-cap-type `retry_after_seconds` derivation rule (window-based vs per-invocation hard-cap; idle uses deterministic default). Gate 2 builder locks the constants `MIN_HARD_CAP_RETRY` and `IDLE_RETRY_DEFAULT` based on telemetry from Chunk 9 reliability harness.

**AC3 — byte_cap breach populates retry_after_seconds.** When the streaming path raises `InvokeRuntimeError` for byte-cap breach, the error includes `retry_after_seconds` per §2 rule AND error metadata includes `cap_kind` (`window` or `per_invocation_hard`). Verified by positive tests that breach the byte budget under both window-based and per-invocation-hard configurations and assert both fields.

**AC4 — time_cap breach populates retry_after_seconds.** Same shape as AC3 for time-cap breach. Verified by positive tests under both window-based and per-invocation-hard configurations.

**AC5 — idle_cap breach populates retry_after_seconds.** When the streaming path raises `InvokeRuntimeError` for idle-cap breach, the error includes `retry_after_seconds = IDLE_RETRY_DEFAULT` and `cap_kind = "idle"`. Verified by a positive test that holds the stream idle past the threshold and asserts both fields.

**AC6 — Non-streaming-cap errors leave retry_after_seconds = None.** Negative-case test: trigger `InvokeRuntimeError` from a non-cap source (suggested: connector schema-validation failure, or whatever non-cap error path Gate 2 builder finds simplest to provoke deterministically); assert `retry_after_seconds is None`. Protects the field's positive-signal semantic.

**AC7 — strict-xfail marker removed.** The test referenced in §1 (grep-derived name `test_quota_matrix_covers_invocation_stream_scope_with_retry_after`; Gate 2 confirms exact path) has its `strict-xfail` marker removed so the test gates regressions going forward. If the test name has drifted, Gate 2 reconciles to the actual test and updates this AC in the same PR.

**AC8 — Rollback procedure documented and tested.** A feature flag (suggested env: `AIM_NODE_INVOKE_RETRY_AFTER_ENABLED`, default `true`) gates the populate-retry-after code path. Setting the flag to `false` restores the pre-fix behavior of leaving `retry_after_seconds` unpopulated on cap-breach emissions. No data-model migration is required; the field is additive on an existing dataclass / pydantic model. A rollback test asserts the flag's effect.

## §4 Test Plan

All tests live in `tests/gateway_v2/` (path grep-derived; Gate 2 confirms):

**Positive tests:**
- `test_byte_cap_breach_window_populates_retry_after_seconds` — window-based byte cap configured; stream emits past byte budget within window; assert `retry_after_seconds` is a positive integer in `(0, window_seconds]` and `cap_kind == "window"`.
- `test_byte_cap_breach_hard_cap_populates_retry_after_seconds` — per-invocation hard byte cap; assert `retry_after_seconds == MIN_HARD_CAP_RETRY` and `cap_kind == "per_invocation_hard"`.
- `test_time_cap_breach_window_populates_retry_after_seconds` — mirror of byte tests for time cap.
- `test_time_cap_breach_hard_cap_populates_retry_after_seconds` — mirror of byte tests for time cap.
- `test_idle_cap_breach_populates_retry_after_seconds` — stream idle past threshold; assert `retry_after_seconds == IDLE_RETRY_DEFAULT` and `cap_kind == "idle"`.

**Negative test:**
- `test_non_cap_invoke_runtime_error_leaves_retry_after_seconds_none` — trigger non-cap `InvokeRuntimeError`; assert `retry_after_seconds is None`.

**Regression unlock:**
- The existing strict-xfail test (`test_quota_matrix_covers_invocation_stream_scope_with_retry_after` — name grep-derived) has its xfail marker removed; it now asserts populated retry_after_seconds and acts as the integration-shape canary.

**Rollback test:**
- `test_retry_after_population_disabled_by_feature_flag` — set `AIM_NODE_INVOKE_RETRY_AFTER_ENABLED=false`; trigger any cap-breach; assert `retry_after_seconds is None`.

## §5 Risks

1. **Sandbox-no-read fidelity.** All identifiers in this spec are grep-derived. If Gate 2 builder finds `retry_after_seconds` is not the actual field name (could be `retry_after`, `retry_after_ms`, or nested under `.metadata`), the AC wording stays correct in intent but the identifier substitution must happen in the same Gate 2 PR. Severity: low (mechanical).
2. **Cap-config window attribute assumption.** §2's byte_cap and time_cap rules assume cap config objects expose a discoverable rolling-window attribute. If caps are hardcoded per-invocation only (no rolling-window concept in the schema), AC2's `window` branch becomes dead code and the policy collapses to per-invocation-hard-cap only. Severity: medium — requires Gate 1 amendment if confirmed.
3. **Test name drift.** `test_quota_matrix_covers_invocation_stream_scope_with_retry_after` is grep-derived from the BQ context; the actual strict-xfail test may have a different name or path. AC7 includes a reconcile-in-PR clause to handle this. Severity: low.
4. **HTTP / SSE transport not covered.** This spec defines the in-process `InvokeRuntimeError` field population. If the streaming error is currently transported via SSE or chunked HTTP without an HTTP `Retry-After` header translation, buyer SDKs must read the field directly from the deserialized error body. Sibling BQ may be needed for transport-layer plumbing. Severity: medium — flagged in Open Questions.
5. **Constants chosen without telemetry.** `MIN_HARD_CAP_RETRY = 5` and `IDLE_RETRY_DEFAULT = 10` are suggested defaults; the real values should come from Chunk 9 reliability harness observability data. Locking constants without telemetry risks either too-aggressive retry (hammering the connector) or too-conservative (clients give up). Severity: medium — Gate 2 builder pulls telemetry before locking.
6. **Backward compatibility.** Clients that don't read `retry_after_seconds` see no regression — the field was previously always None and becomes sometimes-populated. Strictly additive. Severity: none (called out for completeness).

## §6 Open Questions

1. **Field location.** Is `retry_after_seconds` a top-level field on `InvokeRuntimeError` or nested (e.g., `.metadata.retry.after_seconds`)? Gate 2 confirms from source.
2. **HTTP transport surface.** Does the V2 gateway translate `InvokeRuntimeError` to an HTTP response with a `Retry-After` header today, or does it emit in-band SSE? If in-band only, do we want to add HTTP-header translation in the same PR, or sibling-BQ it?
3. **Higher-fidelity timing.** RFC 7231 `Retry-After` header is integer seconds. For idle-cap especially, sub-second fidelity may matter. Should the error contract carry both `retry_after_seconds` (RFC-compatible) and `retry_after_ms` (higher fidelity), with the HTTP surface using whichever the client negotiated? Suggest: defer to sibling BQ unless Gate 2 telemetry shows sub-second precision matters.
4. **Constant locking.** What should `MIN_HARD_CAP_RETRY` and `IDLE_RETRY_DEFAULT` actually be? Suggested defaults in §2 are placeholders; Gate 2 pulls observability data from Chunk 9 harness before locking.
5. **Buyer SDK consumption.** Does the buyer SDK currently read `retry_after_seconds` from the error contract, or is server-side population a half-measure without coordinated SDK update? If SDK update is needed, sibling BQ.

## §7 Rollback

**Mechanism:** Feature flag `AIM_NODE_INVOKE_RETRY_AFTER_ENABLED` (env var, default `true`). When `false`, the populate-retry-after code path is skipped at every cap-breach emission site; `retry_after_seconds` stays None as before the fix.

**No data migration required.** The field is additive on an existing error contract; pre-fix and post-fix shapes are wire-compatible. Older clients ignore the field; newer clients see None when the flag is off, matching pre-fix behavior.

**Rollback trigger conditions:** If post-deploy telemetry shows buyer SDKs misinterpreting the populated field (e.g., retrying so aggressively that connector health degrades), set the env to `false` on the affected deployment and surface a follow-up BQ for the misinterpretation.

**Test coverage:** AC8 rollback test asserts the flag's effect; this gives ops a verified flip-switch before merge.

## §8 Out of Scope

- HTTP `Retry-After` header translation in the gateway response surface (flagged in Open Question 2; sibling BQ if needed).
- Buyer SDK changes to consume `retry_after_seconds` (Open Question 5; sibling BQ if needed).
- Quota config schema migration (this spec assumes existing schema; if AC2's window-attr assumption is invalidated, that's a Gate 1 amendment, not in-scope here).
- Higher-fidelity timing (`retry_after_ms`; Open Question 3).
- Refactoring cap-detection code paths — only the error-emission site changes.

## §9 References

- **Parent BQ:** BQ-AIM-NODE-GATEWAY-V2 (Chunk 9 — Observability, Quotas, Latency, Reliability Harness — shipped S560). Chunk 9 record surfaces the retry-after-unpopulated gap as a follow-up.
- **Queue brief:** `config:parallel-worker-queue.body.worker_pickup_signal.head_work_brief` (S610 round 1 assignment, 2026-05-12T10:20:00Z).
- **Memory #29 R3 5-check stamp:** `config:parallel-worker-queue.body.worker_bqs[0].memory_29_r3_stamp` (verified by vulcan-primary-S610-round-1).
- **RFC 7231 §7.1.3:** HTTP `Retry-After` header semantics (integer seconds or HTTP-date).
- **Honest-posture clause:** §0 above; sandbox-no-read disclosure applies to every grep-derived identifier in this spec.
