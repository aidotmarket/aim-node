# Gateway V2 Subsumption Migration

Gate 2 Chunk 11 defines how paused AIM-Node work moves into Gateway V2 without expanding runtime scope. Gateway Console becomes the local operator UI for Gateway V2, while canonical market, billing, receipt, trust, and balance state stay backend-derived.

Locked Gateway V2 SDK surfaces from `src/gateway_v2/client_contracts.ts` are:

- `gateway.discover` for `discover`
- `gateway.quote.create` and `gateway.quote.get` for `quote.create` and `quote.get`
- `gateway.connect` for `connect`
- `gateway.invoke` for `invoke`
- `gateway.meter.record` and `gateway.meter.list` for `meter.record` and `meter.list`
- `gateway.receipt.get` and `gateway.receipt.lookup` for `receipt.get` and `receipt.lookup`
- `gateway.publish` for `publish`
- `gateway.verifyProvider` for `verify_provider`
- `gateway.requestAccess` for `request_access`
- `gateway.estimateCost` for `estimate_cost`
- `gateway.createBillingSession` for `create_billing_session`

DIST naming from Chunk 10 remains `gateway-v2-runtime` in the `aim-node-gateway-v2-runtime` package boundary, with `buyer_local` and `seller_edge` modes.

## DASHBOARD

Preserved content now appears in Gateway Console:

| Old dashboard content | Gateway Console replacement | Surface or source |
| --- | --- | --- |
| Connector/provider health | Runtime health and connector readiness | `src/gateway_v2/health.ts`, `connector_registry_readiness` |
| Local credential visibility without secrets | Credential presence, local secret refs, and storage status only | `local_secret_store_availability`, `local://aim-node/secrets/` refs |
| Invocation logs | Gateway invocation activity and local runtime status | `gateway.invoke` with invocation metadata only |
| Usage counters | Meter event summaries and counters | `gateway.meter.list` |
| Receipt lookup | Canonical receipt lookup | `gateway.receipt.lookup`, `gateway.receipt.get` |
| Local runtime status | Gateway V2 health report for `buyer_local` or `seller_edge` | `evaluateGatewayV2Health` |

Retired content:

- The standalone dashboard strategy is retired. `/dashboard` is deprecated and redirects to Gateway Console.
- Marketplace admin scope is retired from AIM-Node local dashboard views. Listing administration remains on backend-derived seller surfaces and `gateway.publish`; Gateway Console may show read-only status but must not become a marketplace admin console.
- Raw credentials or secrets are never displayed. Only local secret references and availability state may be shown.

Deprecated names and replacements:

| Deprecated command/UI/SDK | Replacement | Behavior |
| --- | --- | --- |
| `aim-node dashboard` | `aim-node gateway console` | Deprecation warning, then open Gateway Console overview |
| `/dashboard` | `/gateway/console` | 308 redirect with deprecation banner |
| `/dashboard/receipts` | `/gateway/console/receipts` | 308 redirect |
| `gateway.dashboard.status` | `gateway.console.status` | Deprecated SDK alias; local console route only |

## EARNINGS

Preserved content now appears as read-only backend-derived Gateway Console views:

| Old earnings content | Gateway Console replacement | Surface or source |
| --- | --- | --- |
| Seller billable usage | Metered usage grouped by listing and listing version | `gateway.meter.list` |
| Transaction receipts | Canonical transaction receipts | `gateway.receipt.lookup`, `gateway.receipt.get` |
| Payout references | Settlement and payout references from backend | Backend-derived payout/settlement views |
| Revenue attribution by listing/version | Read-only attribution grouped by `listing_id` and `listing_version_id` | Backend-derived receipts and meter events |

Retired content:

- AIM-Node local balance calculation is removed. `balance_ledger` is a forbidden AIM-Node source-of-truth model.
- Local earnings pages must not compute seller balance, payout eligibility, commission, or settlement status from local sessions.
- `/earnings` is deprecated in favor of read-only Gateway Console revenue views.

Deprecated names and replacements:

| Deprecated command/UI/SDK | Replacement | Behavior |
| --- | --- | --- |
| `aim-node earnings` | `aim-node gateway receipts --seller` | Deprecation warning, read-only receipt view |
| `aim-node balance` | none | Explicit removal: local balance calculation removed; use backend payout and settlement references |
| `/earnings` | `/gateway/console/revenue` | 308 redirect with read-only banner |
| `gateway.earnings.summary` | none | Explicit removal: use `gateway.meter.list` plus `gateway.receipt.lookup` backend-derived data |

## BUYER-MODE

Preserved buyer and agent flows now use one Gateway V2 surface at a time:

| Old buyer-mode capability | Gateway V2 replacement |
| --- | --- |
| Discover providers/listings | `gateway.discover` |
| Verify provider | `gateway.verifyProvider` |
| Estimate cost | `gateway.estimateCost` |
| Create quote | `gateway.quote.create` |
| Read quote | `gateway.quote.get` |
| Request access | `gateway.requestAccess` |
| Create billing session | `gateway.createBillingSession` |
| Connect local runtime to granted listing | `gateway.connect` |
| Invoke through local or seller edge runtime | `gateway.invoke` |
| Read receipt | `gateway.receipt.get`, `gateway.receipt.lookup` |

Retired content:

- Generic buyer mode is retired. `/buyer` and `/buyer-mode` are removed or redirected to specific Gateway Console workflow routes.
- Local-only purchase state is removed. Billing sessions, quote state, access state, receipts, and accepted meter events are backend-derived.
- Compatibility shims must not combine search, purchase, and invocation into one command. Any alias that performs discover plus payment plus invoke is explicitly rejected.

Deprecated names and replacements:

| Deprecated command/UI/SDK | Replacement | Behavior |
| --- | --- | --- |
| `aim-node buyer discover` | `aim-node gateway discover` | Deprecation warning |
| `aim-node buyer verify` | `aim-node gateway verify-provider` | Deprecation warning |
| `aim-node buyer estimate` | `aim-node gateway estimate-cost` | Deprecation warning |
| `aim-node buyer quote` | `aim-node gateway quote create` | Deprecation warning |
| `aim-node buyer access` | `aim-node gateway request-access` | Deprecation warning |
| `aim-node buyer billing` | `aim-node gateway billing-session create` | Deprecation warning |
| `aim-node buyer connect` | `aim-node gateway connect` | Deprecation warning |
| `aim-node buyer invoke` | `aim-node gateway invoke` | Deprecation warning |
| `aim-node buyer receipt` | `aim-node gateway receipt get` | Deprecation warning |
| `aim-node buyer buy-and-run` | none | Explicit removal: combined discover + payment + invoke aliases are rejected |
| `/buyer` | `/gateway/console/discover` | 308 redirect to discover workflow |
| `/buyer-mode` | `/gateway/console/discover` | 308 redirect to discover workflow |
| `/buyer/checkout` | `/gateway/console/billing` | 308 redirect |
| `/buyer/sessions` | `/gateway/console/invocations` | 308 redirect |
| `gateway.buyer.discover` | `gateway.discover` | Deprecated SDK alias with warning |
| `gateway.buyer.verifyProvider` | `gateway.verifyProvider` | Deprecated SDK alias with warning |
| `gateway.buyer.estimateCost` | `gateway.estimateCost` | Deprecated SDK alias with warning |
| `gateway.buyer.requestAccess` | `gateway.requestAccess` | Deprecated SDK alias with warning |
| `gateway.buyer.createBillingSession` | `gateway.createBillingSession` | Deprecated SDK alias with warning |
| `gateway.buyer.purchaseAndInvoke` | none | Explicit removal: use discover, quote, billing, connect, invoke, and receipt as separate calls |

## Compatibility Rules

1. Deprecated command names and UI routes may redirect or alias only to a locked Gateway V2 surface or Gateway Console route.
2. Deprecated SDK calls affected by rename/subsumption must either call the new Gateway V2 method with a deprecation warning or be documented as removed with a replacement.
3. Removed names must fail with explicit user-facing messages that include the removed name and the replacement flow.
4. No shim may combine `discover`, payment or billing, and `invoke` into one command or SDK call.
5. Gateway Console views for credentials must expose local secret references and availability only, never raw secret values.
6. Revenue and receipts are read-only in AIM-Node and are derived from backend accepted meter events, canonical receipts, payout references, and settlement references.
