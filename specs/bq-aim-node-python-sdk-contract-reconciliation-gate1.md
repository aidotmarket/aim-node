# BQ-AIM-NODE-PYTHON-SDK-CONTRACT-RECONCILIATION — Gate 1 Design (v1)

**Author:** vulcan_direct (S549)
**Status:** AUTHORED v2 (R1 mandates folded), awaiting R2 verification
**Parent finding:** BQ-AIM-NODE-GATEWAY-V2 Chunk 8 strict xfail at `tests/gateway_v2/test_e2e_paid_buyer_agent_flow.py:68`

## §1 Problem statement

The aim-node Python SDK (under `python/aim_node/gateway_v2/`) emits envelope
shapes that do not match the backend Gateway v2 Pydantic models (under
`ai-market-backend/app/gateway_v2/surfaces/`). Backend models declare
`ConfigDict(extra="forbid")` which makes the mismatch a hard 422 at request
parse time, not a soft warning. The Chunk 8 E2E harness exposes this with a
`strict=True` xfail; the test cannot pass until the SDK produces shapes the
backend accepts.

Three concrete drift surfaces have been confirmed by source inspection:

**Discover response.** SDK `DiscoverResponse` carries `listings: list[DiscoverListing]`
with SDK-specific fields (`title`, `description`, `categories`, `tags`,
`capabilities`, `quote_required`, `pricing_summary`). Backend `DiscoverResponse`
carries `results: tuple[ListingSummary, ...]` with backend-specific fields
including `freshness_ref: SignedReference`. Field name (`listings` vs
`results`), container type (`list` vs `tuple`), element type, and element
fields all differ.

**Discover request.** SDK `DiscoverRequest` is flat with `metadata`,
`categories`, `tags`, `seller_ids`, `provider_ids`, `capabilities`. Backend
`DiscoverRequest` requires `query` (1-512 char) and a nested
`filters: DiscoverFilters` containing `tags`, `seller_ids`, `provider_ids`,
`min_trust_score`, `commercial_models`. SDK fields `categories` and
`capabilities` have no backend home.

**Quote request.** SDK `QuoteRequest` has `seller_id`, `provider_id`,
`quantity`, `units`, `usage_estimate`, `buyer_context`. Backend
`QuoteCreateRequest` requires `buyer_account_id`, `requested_commercial_model`,
`requested_units` (alias of `quantity`), `usage_purpose`, and a
`trust: TrustPrimitiveReferences` block. The shape change is structural:
several SDK fields have no backend home, several backend fields have no SDK
source.

**Verify-provider request.** SDK `VerifyProviderRequest` carries five trust
artifact refs as plain `str`. Backend `VerifyProviderRequest` requires those
five refs as `TrustArtifactReference` objects with shape
`{ref: str, state: TrustArtifactState}`. The string-vs-object mismatch is a
direct 422.

## §2 Architectural decision: Path A (one-shot SDK alignment)

Two paths considered:

- **Path A — One-shot SDK alignment.** Update the SDK envelopes to match
  backend exactly. Remove the strict xfail. No backend changes. No
  compatibility layer.
- **Path B — Backend compat layer.** Backend accepts legacy SDK shapes
  alongside Gateway v2 shapes for a transition period. SDK migrates over
  multiple chunks.

**Decision: Path A.** Rationale:

1. The aim-node Python SDK is pre-public; no external integrator depends on
   the legacy shapes.
2. Backend models declare `extra="forbid"` and document Gateway v2 as the
   contract surface. Forking the contract to absorb SDK drift would weaken
   the canonical schema.
3. Single round of work removes the xfail; Path B requires double migration
   work (introduce compat, then later remove it).
4. Source-of-truth discipline: backend Pydantic models with explicit
   `extra="forbid"` are designed to be authoritative. SDK should derive from
   them, not negotiate with them.

## §3 Scope inventory

### In scope (this BQ)

- `python/aim_node/gateway_v2/discover.py` — `DiscoverRequest`,
  `DiscoverResponse`, `DiscoverListing` (rename to `ListingSummary` to match
  backend), parser updates.
- `python/aim_node/gateway_v2/quote.py` — `QuoteRequest` (rename to
  `QuoteCreateRequest` to match backend) and field reshape, response parser.
- `python/aim_node/gateway_v2/buyer.py` — `VerifyProviderRequest` trust
  artifact ref fields changed to `TrustArtifactReference` objects (introduce
  the dataclass in the SDK or import from a shared module).
- Any other `python/aim_node/gateway_v2/*.py` surface where Gate 2
  inventory finds drift (Gate 2 chunking task: full audit).
- Removal of the `@pytest.mark.xfail(strict=True)` decorator on
  `tests/gateway_v2/test_e2e_paid_buyer_agent_flow.py::test_python_sdk_canonical_paid_buyer_agent_flow_against_backend_asgi_fixtures`.
- Updating SDK unit tests (`tests/gateway_v2/*` excluding the E2E flow file)
  to assert the new shapes.

### Out of scope (separate BQs)

- TypeScript SDK reconciliation. AC-7 below requires an audit of the TS SDK
  for analogous drift; if found, a sibling BQ is filed and addressed
  separately.
- Backend Gateway v2 model changes. Backend is the source of truth for this
  effort; any backend model changes are a separate decision out of this BQ.
- Frontend SDK consumers. Frontend uses the TS SDK; covered by the TS audit
  AC-7.

## §4 Acceptance criteria

AC-1. SDK `DiscoverResponse` aligns with backend: field renamed
`listings` → `results`; element type aligned with backend `ListingSummary`
(field-by-field mapping completed at Gate 2 chunking). Parser updated to
read `results` from response JSON.

AC-2. SDK `DiscoverRequest` aligns with backend: `query` becomes required;
`filters` becomes a nested object containing `tags`, `seller_ids`,
`provider_ids`, `min_trust_score`, `commercial_models`. SDK-only fields
(`categories`, `capabilities`) removed unless Gate 2 finds a backend home.

AC-3. SDK `QuoteRequest` aligns with backend `QuoteCreateRequest`. Field
reshape: add `buyer_account_id`, `requested_commercial_model`,
`requested_units`, `usage_purpose`, `trust`; remove or remap `seller_id`,
`provider_id`, `quantity`, `units`, `usage_estimate`, `buyer_context`.
Method name and HTTP path follow backend (Gate 2 confirms exact path).

AC-4. SDK `VerifyProviderRequest` trust artifact ref fields take
`TrustArtifactReference` objects: `seller_verification_ref`,
`provenance_attestation_ref`, `terms_use_rights_ref`, `quality_profile_ref`,
`sample_receipt_ref`. SDK introduces a `TrustArtifactReference` dataclass
mirroring backend shape (`ref: str`, `state: str` defaulting to `"active"`).

AC-5. `@pytest.mark.xfail(strict=True)` decorator removed from
`tests/gateway_v2/test_e2e_paid_buyer_agent_flow.py::test_python_sdk_canonical_paid_buyer_agent_flow_against_backend_asgi_fixtures`
and the test passes against backend ASGI fixtures.

AC-6. `pytest tests/gateway_v2/ -v` reports the previous test count plus the
xfail conversion as PASS (no XFAIL count, no xpassed). All other gateway_v2
tests continue to pass.

AC-7. TypeScript SDK parity audit conducted as part of Gate 2 chunking.
Output: either "no drift found" written into the chunking spec, or a sibling
BQ filed (`BQ-AIM-NODE-TYPESCRIPT-SDK-CONTRACT-RECONCILIATION`) with a
parallel scope. Does not block this BQ from closing.

AC-8. Zero backend changes. Verified by `git diff origin/main..HEAD --
ai-market-backend` showing zero modifications in that path during this BQ's
work. Backend model surface is treated as authoritative ground truth.

AC-9. SDK unit tests in `tests/gateway_v2/test_*.py` (excluding the E2E
flow file) updated to assert the new envelope shapes. No test deleted; only
shape expectations updated.

AC-10. No silent backward-compat shim in the SDK. The reshape is direct.
Old field names removed. If any caller (internal scripts, ops tooling, or
any other Python consumer) imports the old shapes, fix the caller as part
of the chunk that ships the change and document the import path migration.
Frontend is not a caller of the Python SDK (frontend uses the TS SDK; see
§3 out-of-scope) and is therefore not affected.

## §5 Test plan

T1. Discover surface — request shape (matches AC-1, AC-2).
T2. Discover surface — response parsing (matches AC-1).
T3. Quote surface — request shape (matches AC-3).
T4. Quote surface — response parsing.
T5. Verify-provider surface — request shape (matches AC-4).
T6. Verify-provider surface — `TrustArtifactReference` dataclass shape.
T7. E2E canonical flow — xfail removed; passes (matches AC-5, AC-6).
T8. Other Gateway v2 surfaces touched in Gate 2 — one shape test per surface.

## §6 Risks

R1. **Additional drift surfaces beyond the three named.** SDK files
`buyer.py`, `connect.py`, `invoke.py`, `meter.py`, `receipt.py` not yet
audited. Mitigation: Gate 2 chunking task §3 explicitly audits all
`python/aim_node/gateway_v2/*.py` files against backend counterparts. (AC-7
covers the TypeScript SDK audit specifically and is not the mitigation for
Python drift inventory.)

R2. **TypeScript SDK has same drift.** The frontend uses the TS SDK; if it
has analogous drift, a future production incident is plausible. Mitigation:
AC-7 forces audit; sibling BQ filed if drift found.

R3. **Internal callers depend on legacy shapes.** Internal Python scripts,
ops tooling, or other Python tools may import the old SDK names. (Frontend
is not affected; frontend uses the TS SDK per §3 out-of-scope.) Mitigation:
AC-10 forbids shims; chunks include caller fixes inline. Gate 2 chunking
inventories callers.

R4. **Backend model changes during this BQ's work.** If backend Gateway v2
models drift while this BQ is in flight, rework is needed. Mitigation:
complete the work in 1-2 sessions; coordinate with anyone working on
gateway_v2 backend during that window.

R5. **Hidden semantic mismatch beyond field names.** Even when shapes
align, semantic differences (e.g. SDK `quantity` was integer count of items
while backend `requested_units` may be billed-units count) could produce
silent wrong behavior. Mitigation: each shape change includes a comment
documenting semantic mapping; E2E canonical flow at AC-5 catches semantic
mismatches in practice.

## §7 Open questions for Gate 2 chunking

Q1. Full inventory of drift across all `python/aim_node/gateway_v2/*.py`
surfaces — does Gate 2 confirm exactly the three named, or are there more?

Q2. Does `python/aim_node/gateway_v2/connect.py`, `invoke.py`, `meter.py`,
`receipt.py`, `buyer.py` (beyond verify-provider) have drift?

Q3. Single chunk feasible (one PR for all surfaces) or natural per-surface
chunk decomposition (one chunk per drifted surface)?

Q4. TypeScript SDK audit method — manual diff against backend models, or
introduce a contract-test harness that exercises both SDKs against the same
backend fixtures?

## §8 Implementation references

- Backend models: `ai-market-backend/app/gateway_v2/surfaces/discover.py`,
  `quote.py`, `buyer_verify_provider.py`,
  `buyer_request_access.py`, `buyer_estimate_cost.py`, `connect.py`,
  `invoke_records.py`, `meter.py`, `receipt.py`,
  `publish_governance.py`, `grants.py`.
- SDK current state:
  `aim-node/python/aim_node/gateway_v2/{buyer,connect,discover,invoke,meter,quote,receipt}.py`
  and `aim-node/python/aim_node/gateway_v2/contracts.py`.
- Anchor test:
  `aim-node/tests/gateway_v2/test_e2e_paid_buyer_agent_flow.py:68`
  (`test_python_sdk_canonical_paid_buyer_agent_flow_against_backend_asgi_fixtures`).
- Originating dispatch: BQ-AIM-NODE-GATEWAY-V2 Chunk 8 (S525), commits
  backend@cbfe063 + aim-node@38799e5.
- Living State entity:
  `build:bq-aim-node-python-sdk-contract-reconciliation` v1+ (filed S526).

## §9 Reviewer rotation

- **Gate 1 R1:** AG primary cross-vote. DeepSeek plus-one (auto-resolution
  layer prepends diff context). MP authored as Gate 0; not a Gate 1
  reviewer.
- **Gate 1 R2 (if needed):** AG R2 verifies fold of any R1 mandates.
- **Gate 2:** AG primary on chunking. DS plus-one if any chunk touches
  shared envelope code beyond a single file.

