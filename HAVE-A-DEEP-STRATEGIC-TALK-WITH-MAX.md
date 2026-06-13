# Have a deep strategic talk with Max — AIM NODE future

**Status: PARKED pending strategic decision.** Do NOT move any AIM NODE work forward until this talk happens.
**Scheduled:** Mon 2026-06-22, 10:00–11:00 (Europe/Madrid) — focus block on Max's primary calendar.
**Filed:** 2026-06-13 (S833, Vulcan), at Max's direction.

## The decision to make
AIM DATA was substantially updated recently. AIM NODE is the partner-integration form of AIM DATA — the version meant to be embedded into more complex partners — so AIM NODE's scope must expand to **encompass everything AIM DATA now does**. Before any further AIM NODE build, decide:

1. **Target scope** — AIM NODE as the AIM DATA superset: what exactly it must encompass.
2. **Sequencing** vs the ai.market repositioning work (Gateway V2 is already gated behind Repositioning Gate 1).
3. **Per open item below** — resume as-is, fold into the new scope, or retire.

## Open AIM NODE work (parked — 8 items)
| Item | State | Note |
|---|---|---|
| Gateway V2 | in progress, gate 3 | anchor; subsumes Dashboard/Earnings/Buyer-mode; blocked behind Repositioning Gate 1 |
| Gateway V2 TypeScript build pipeline | planned, gate 1 | TS components ship un-runnable |
| SDK ↔ Gateway V2 envelope reconciliation (S810) | planned, P2 | pre-req for Gateway V2 dev go-live |
| Python SDK contract reconciliation | planned, gate 2 | discover/quote/verify envelopes misaligned with backend v2 |
| Invoke-runtime retry-after propagation | planned | clients cannot back off cleanly |
| S3 fulfillment runtime (S684) | blocked, P0, gate 1 | overlaps AIM DATA S3/STS fulfillment — central to the "encompass AIM DATA" point |
| Logs & diagnostics | in progress, gate 1 | |
| Distribution (S669) | planned, P1 | cross-OS installer / signing / auto-update |

## Already shipped (12 items, for context)
core, app, contracts, dist, dashboard, earnings, buyer-mode, seller-publish, setup-wizard, mgmt-api-v2, allai-copilot, ui-scaffold.

## Related context for the talk
- **AIM DATA recent direction:** devectorization (remove chunk/embed/Qdrant), S3/STS fulfillment, $10 allAI monthly cap, guided metadata review, AIM Channel → AIM Data umbrella rename.
- **ai.market repositioning** (data-conduit thesis) — Gateway V2 already depends on its Gate 1.

_Each parked item carries a Living State note pointing here. Unpark only after this conversation._
