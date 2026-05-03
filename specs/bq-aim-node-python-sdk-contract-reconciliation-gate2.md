# BQ-AIM-NODE-PYTHON-SDK-CONTRACT-RECONCILIATION — Gate 2 Chunking (v1)

**Author:** vulcan_direct (S550)
**Status:** AUTHORED v1, AWAITING_CROSS_REVIEW
**Gate 1 ref:** specs/bq-aim-node-python-sdk-contract-reconciliation-gate1.md @ aim-node 9f256ca
**Repo at chunking time:** aim-node HEAD 9f256ca; ai-market-backend HEAD 9389b48

## §1 Purpose

Decompose the Gate 1 acceptance criteria into shippable chunks, with a leading
inventory chunk that produces the drift map needed to size the rest of the
work, and parameterized implementation chunks that ship one drifted surface
at a time. Answer the four open questions Gate 1 deferred:

- Q1: Full inventory of `python/aim_node/gateway_v2/*.py` drift across all
  nine SDK files vs the eleven backend surfaces under
  `ai-market-backend/app/gateway_v2/surfaces/`.
- Q2: TypeScript SDK analogous-drift audit per AC-7.
- Q3: Single chunk vs per-surface chunking strategy.
- Q4: TS audit method (manual diff vs contract-test harness).
- Q5 (R6 mandate): Auth-surface verification against current backend
  `buyer_*.py` files at chunking-commit SHA.

## §2 Source-of-truth surface inventory

Backend surfaces under `ai-market-backend/app/gateway_v2/surfaces/` at backend
HEAD 9389b48 (eleven Pydantic-modelled surfaces, each with
`ConfigDict(extra="forbid")`):

| Backend surface file              | Backend request model               | Backend response model           | Buyer-auth touched |
|-----------------------------------|-------------------------------------|----------------------------------|--------------------|
| `discover.py`                     | `DiscoverRequest`                   | `DiscoverResponse`               | no                 |
| `quote.py`                        | `QuoteCreateRequest`                | (Gate 2 confirms)                | no                 |
| `connect.py`                      | (Gate 2 confirms via Chunk A)       | (Gate 2 confirms)                | yes                |
| `invoke_records.py`               | (Gate 2 confirms via Chunk A)       | (Gate 2 confirms)                | yes                |
| `meter.py`                        | (Gate 2 confirms via Chunk A)       | (Gate 2 confirms)                | no                 |
| `receipt.py`                      | (Gate 2 confirms via Chunk A)       | (Gate 2 confirms)                | no                 |
| `publish.py`                      | (Gate 2 confirms via Chunk A)       | (Gate 2 confirms)                | no                 |
| `buyer_request_access.py`         | `RequestAccessRequest`              | `AccessRequest`                  | yes                |
| `buyer_estimate_cost.py`          | `EstimateCostRequest`               | `CostEstimate`                   | yes                |
| `buyer_verify_provider.py`        | `VerifyProviderRequest`             | (Gate 2 confirms)                | yes                |
| `buyer_billing_session.py`        | `CreateBillingSessionRequest`       | `BillingSession`                 | yes                |

SDK Python files under `python/aim_node/gateway_v2/` at aim-node HEAD 9f256ca
(nine surface files plus `contracts.py` shared types):

| SDK file        | Method classes (request envelopes)                                                         | Maps to backend surface(s)                                              |
|-----------------|--------------------------------------------------------------------------------------------|--------------------------------------------------------------------------|
| `discover.py`   | `DiscoverRequest`, `DiscoverResponse`                                                      | `discover.py` (DRIFT — Gate 1 §1 confirmed)                              |
| `quote.py`      | `QuoteRequest`                                                                             | `quote.py` (DRIFT — Gate 1 §1 confirmed)                                 |
| `connect.py`    | `ConnectRequest`, `ConnectResponse`                                                        | `connect.py` (Chunk A audits)                                            |
| `invoke.py`     | `InvokeRequest`, `InvokeResponse`, `ConnectorRuntime`                                      | `invoke_records.py` (Chunk A audits)                                     |
| `meter.py`      | `MeterRecordRequest`, `MeterListRequest`, `MeterEvent`                                     | `meter.py` (Chunk A audits)                                              |
| `receipt.py`    | `ReceiptGetRequest`, `ReceiptLookupRequest`                                                | `receipt.py` (Chunk A audits)                                            |
| `publish.py`    | `PublishRequest`, `PatchListingRequest`                                                    | `publish.py` (Chunk A audits)                                            |
| `buyer.py`      | `VerifyProviderRequest`, `RequestAccessRequest`, `EstimateCostRequest`, `CreateBillingSessionRequest` | four `buyer_*.py` surfaces (DRIFT confirmed for `VerifyProviderRequest`; other three Chunk A audits) |
| `contracts.py`  | `GatewaySurface`, `GatewayClientMethod` (shared types)                                     | none direct                                                              |

## §3 Q3 answer: per-surface chunking with leading inventory chunk

**Decision: per-surface chunking**, with a leading inventory chunk (Chunk A)
that produces the drift map and decides which downstream chunks ship.

Rationale:

1. The three known drifts (discover, quote, verify-provider) and the six
   unaudited surfaces are independent in implementation. Per-surface chunks
   minimize blast radius on the e2e test harness — if Chunk B (discover)
   breaks, Chunks C-H still merge cleanly behind it.
2. A single big chunk would force every reviewer to hold the entire
   nine-surface diff in working memory; AG and DS both perform better on
   focused diffs.
3. Some unaudited surfaces may show no drift at all. Per-surface chunking
   lets those surfaces ship as zero-line "no-op" chunks (dropped from the
   chunk list at Chunk A close), avoiding wasted work.
4. The xfail removal in `test_e2e_paid_buyer_agent_flow.py` is a single
   one-line change but depends on every drifted surface having shipped
   first. Per-surface chunking lets the xfail removal land cleanly as the
   final chunk.

## §4 Chunk decomposition

### Chunk A — Drift inventory & TS audit (no production code)

**Deliverables:**
- A1. Field-level drift table for each of the six unaudited Python surface
  files (`buyer.py` non-verify-provider methods, `connect.py`, `invoke.py`,
  `meter.py`, `receipt.py`, `publish.py`) vs the corresponding backend
  Pydantic models. Surfaces with no drift recorded as "PARITY — no chunk
  needed."
- A2. Auth-surface verification per R6: SDK Bearer-token construction,
  `buyer_account_id` field naming, and any signature/principal scheme used
  by SDK methods that hit `buyer_*.py` surfaces. Verified against backend
  HEAD pinned in §1.
- A3. TypeScript SDK audit per AC-7: manual diff of the twelve TS files
  under `aim-node/src/gateway_v2/` against the same eleven backend
  surfaces. Verdict written into Chunk A §A3 as either "no drift found"
  (closes AC-7) or "drift found in [list]" (triggers sibling BQ filing).
- A4. Final chunk list: which of B–H ship, which are dropped as PARITY,
  ordering relative to xfail-removal chunk.

**Format:** `specs/bq-aim-node-python-sdk-contract-reconciliation-gate2-chunkA.md`
committed to aim-node. No code modifications. No test changes.

**Acceptance:** A1 table covers all six unaudited surfaces; A2 records
verified-against-commit SHA for backend; A3 lists TS audit verdict; A4
finalises the downstream chunk list.

### Chunks B–H — Per-surface SDK alignment (parameterized by Chunk A)

Each chunk follows the same template:

- Chunk B: `discover.py` — known drift; rename `listings`→`results`,
  reshape `DiscoverRequest` to flat-`query` + nested `filters`, drop
  `categories`/`capabilities` unless Chunk A finds backend home.
- Chunk C: `quote.py` — known drift; rename request to `QuoteCreateRequest`,
  reshape fields per AC-3.
- Chunk D: `buyer.py` `VerifyProviderRequest` — known drift; introduce
  `TrustArtifactReference` dataclass, change five trust ref fields from
  `str` to `TrustArtifactReference`.
- Chunks E–H: one chunk per remaining drifted surface confirmed by Chunk A
  (`buyer.py` non-verify-provider methods, `connect.py`, `invoke.py`,
  `meter.py`, `receipt.py`, `publish.py`). Surfaces with PARITY verdict
  from Chunk A produce no chunk.

**Per-chunk deliverables:**
- SDK envelope reshape under `python/aim_node/gateway_v2/<surface>.py`.
- Unit test updates under `tests/gateway_v2/test_<surface>*.py` to assert
  new shapes (no test deleted; only shape expectations updated, per AC-9).
- Internal-caller fixes inline within the same commit if any caller
  imports the old shape (per AC-10, no compat shim).
- Chunk-local commit message references AC numbers covered.

**Per-chunk acceptance:**
- `pytest tests/gateway_v2/test_<surface>*.py -v` passes.
- The full `pytest tests/gateway_v2/` suite remains green except for the
  E2E xfail (which the final chunk removes).
- `git diff origin/main..HEAD -- ai-market-backend/` is empty for that
  chunk (per AC-8).

### Chunk Z — Final xfail removal

**Deliverable:** Remove `@pytest.mark.xfail(strict=True)` decorator from
`tests/gateway_v2/test_e2e_paid_buyer_agent_flow.py::test_python_sdk_canonical_paid_buyer_agent_flow_against_backend_asgi_fixtures`.
Confirm test passes against backend ASGI fixtures.

**Acceptance:** AC-5 satisfied; AC-6 satisfied (no xfail count, no xpassed).

**Order:** ships strictly after all of Chunks B–H land on main. Chunk A's
final chunk list (deliverable A4) confirms this ordering.

## §5 Q4 answer: TS audit method = manual diff (single pass)

The TS surface is twelve files at modest size (~5-15 KB each). A manual
field-level diff against the same eleven backend Pydantic models is cheap
in this Chunk A pass and produces a definitive AC-7 verdict in one round.

A contract-test harness that exercises both SDKs against shared backend
fixtures is more durable but is over-engineered for a one-shot audit. If
Chunk A's manual diff finds significant TS drift (more than two surfaces),
the sibling BQ
`BQ-AIM-NODE-TYPESCRIPT-SDK-CONTRACT-RECONCILIATION` filed at Chunk A
close can then propose the harness as part of its own Gate 2 chunking.

## §6 Q5 answer: auth-surface verification at Chunk A time

R6 mandates that Gate 2 chunking inventory verify the SDK auth surface
against the current backend `app/gateway_v2/surfaces/buyer_*.py` files.
Chunk A deliverable A2 carries this:

- Verify SDK `GatewayBuyerClient` Bearer-token construction matches the
  scheme that backend `buyer_request_access.py`, `buyer_estimate_cost.py`,
  `buyer_verify_provider.py`, `buyer_billing_session.py` expect.
- Confirm `buyer_account_id` field naming on the SDK side matches each
  backend request model exactly (Pydantic `extra="forbid"` will 422
  silently if the SDK sends a near-miss field name).
- Verify any signature/principal scheme used in SDK auth flows against
  current backend handlers; a pinned-SHA reference for backend at audit
  time is recorded in A2 to make the verification traceable.

If A2 surfaces drift, that drift is folded into the relevant per-surface
chunk (typically Chunk D for verify-provider, Chunk E or later for the
other buyer methods).

## §7 Risks (Gate 2-specific)

R-G2-1. **Chunk A surfaces unexpected systemic drift** (e.g. all six
unaudited surfaces drift). Mitigation: per-surface chunking absorbs the
volume; chunk count grows but reviewer load per chunk does not.

R-G2-2. **TS audit (A3) finds drift comparable to Python.** Mitigation: AC-7
is non-blocking on this BQ; sibling BQ filed at Chunk A close. This BQ
proceeds without waiting on TS work.

R-G2-3. **Backend HEAD moves during Chunk A audit.** Mitigation: A2 records
the audited backend SHA explicitly. If backend moves before Chunk Z lands,
Chunk Z re-pins to the latest backend SHA and re-runs the e2e flow before
removing the xfail; if backend has drifted in a way that re-introduces
mismatch, file a follow-on BQ rather than expanding scope here.

R-G2-4. **Internal caller fixes within per-surface chunks balloon the
chunk size.** Mitigation: AC-10 forbids shims, but if any chunk's caller
fan-out exceeds five files of mechanical fix-up, split the caller fixes
into a sibling chunk that ships immediately before the surface chunk.

## §8 Reviewer rotation

- **Gate 2 R1:** AG primary cross-vote on this chunking spec. DeepSeek
  plus-one (now active per S548 lift). MP not on Gate 2 review for this
  BQ; this is a chunking spec without code, and AG+DS are sufficient.
- **Gate 2 R2 (if needed):** AG R2 verifies fold of any R1 mandates;
  DS R2 only if DS R1 returned non-NIT findings.
- **Gate 3 (per-chunk reviews):** AG primary on each B–H code chunk; DS
  plus-one on each. MP authors per chunk per the Gate 1 rotation in Gate 1
  §9 if Vulcan-direct authoring proves slower per surface than expected.

## §9 Out of scope (Gate 2)

- TypeScript SDK reconciliation work (covered at audit-only level by AC-7;
  full reconciliation is a sibling BQ if filed).
- Backend Pydantic model changes (per AC-8).
- Frontend-consumer updates (no Python-SDK consumer in frontend; TS-SDK
  consumers in frontend covered by sibling BQ if filed).
- Adding gRPC entrypoints to the SDK; current SDK uses HTTP-only, backend
  exposes both `def <method>(...)` HTTP and `grpc_<method>` parallels —
  Gate 2 does not require SDK to gain gRPC parity in this work.

## §10 Implementation references

- Gate 1 spec: `aim-node/specs/bq-aim-node-python-sdk-contract-reconciliation-gate1.md` @ 9f256ca.
- Backend surfaces (HEAD 9389b48): `ai-market-backend/app/gateway_v2/surfaces/{discover,quote,connect,invoke_records,meter,receipt,publish,buyer_request_access,buyer_estimate_cost,buyer_verify_provider,buyer_billing_session}.py`.
- SDK Python (HEAD 9f256ca): `aim-node/python/aim_node/gateway_v2/{discover,quote,connect,invoke,meter,receipt,publish,buyer,contracts}.py`.
- SDK TypeScript (HEAD 9f256ca): `aim-node/src/gateway_v2/{discover,quote,connect,invoke,meter,meter_buffer,receipt,publish,buyer,client_contracts,local_secret_refs}.ts` plus `connectors/runtime.ts`.
- Anchor xfail: `aim-node/tests/gateway_v2/test_e2e_paid_buyer_agent_flow.py:68`.
- Living State entity: `build:bq-aim-node-python-sdk-contract-reconciliation`.
