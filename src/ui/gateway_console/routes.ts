// FUTURE-BUILD ARTIFACT
// TypeScript source. No build pipeline exists for src/gateway_v2/ or src/ui/ as of Chunk 10.
// Compilation, packaging, and Dockerfile integration will be addressed in a follow-up BQ
// (BQ-AIM-NODE-GATEWAY-V2-TYPESCRIPT-BUILD-PIPELINE).
// Defined for BQ-AIM-NODE-GATEWAY-V2 Gate 2 Chunk 11 migration compatibility.

export type GatewayConsoleRouteStatus = "canonical" | "deprecated_redirect" | "removed";

export interface GatewayConsoleRoute {
  path: string;
  status: GatewayConsoleRouteStatus;
  replacementPath?: string;
  message: string;
}

export const gatewayConsoleRoutes: GatewayConsoleRoute[] = [
  {
    path: "/gateway/console",
    status: "canonical",
    message:
      "Gateway Console overview: connector health, local credential refs without secrets, invocation logs, usage counters, receipt lookup, and local runtime status.",
  },
  {
    path: "/gateway/console/discover",
    status: "canonical",
    message: "Buyer and agent discovery through gateway.discover.",
  },
  {
    path: "/gateway/console/provider-verification",
    status: "canonical",
    message: "Provider verification through gateway.verifyProvider.",
  },
  {
    path: "/gateway/console/quotes",
    status: "canonical",
    message: "Quote creation and lookup through gateway.quote.create and gateway.quote.get.",
  },
  {
    path: "/gateway/console/access",
    status: "canonical",
    message: "Access requests through gateway.requestAccess.",
  },
  {
    path: "/gateway/console/billing",
    status: "canonical",
    message: "Billing sessions through gateway.createBillingSession.",
  },
  {
    path: "/gateway/console/connections",
    status: "canonical",
    message: "Connector grants and local runtime connections through gateway.connect.",
  },
  {
    path: "/gateway/console/invocations",
    status: "canonical",
    message: "Invocation logs and runtime status through gateway.invoke metadata.",
  },
  {
    path: "/gateway/console/usage",
    status: "canonical",
    message: "Usage counters through gateway.meter.list.",
  },
  {
    path: "/gateway/console/receipts",
    status: "canonical",
    message: "Receipt lookup through gateway.receipt.lookup and gateway.receipt.get.",
  },
  {
    path: "/gateway/console/revenue",
    status: "canonical",
    message:
      "Read-only seller billable usage, transaction receipts, payout references, settlement references, and revenue attribution by listing/version.",
  },
  {
    path: "/dashboard",
    replacementPath: "/gateway/console",
    status: "deprecated_redirect",
    message: "deprecated: DASHBOARD is subsumed by Gateway Console.",
  },
  {
    path: "/dashboard/receipts",
    replacementPath: "/gateway/console/receipts",
    status: "deprecated_redirect",
    message: "deprecated: receipt lookup moved to Gateway Console.",
  },
  {
    path: "/earnings",
    replacementPath: "/gateway/console/revenue",
    status: "deprecated_redirect",
    message: "deprecated: EARNINGS is a read-only backend-derived Gateway Console view.",
  },
  {
    path: "/buyer",
    replacementPath: "/gateway/console/discover",
    status: "deprecated_redirect",
    message: "deprecated: generic BUYER-MODE is replaced by Gateway V2 workflow routes.",
  },
  {
    path: "/buyer-mode",
    replacementPath: "/gateway/console/discover",
    status: "deprecated_redirect",
    message: "deprecated: generic BUYER-MODE is replaced by Gateway V2 workflow routes.",
  },
  {
    path: "/buyer/checkout",
    replacementPath: "/gateway/console/billing",
    status: "deprecated_redirect",
    message: "deprecated: local-only purchase state is retired; use Gateway V2 billing sessions.",
  },
  {
    path: "/buyer/sessions",
    replacementPath: "/gateway/console/invocations",
    status: "deprecated_redirect",
    message: "deprecated: buyer sessions moved to Gateway Console invocation views.",
  },
  {
    path: "/buyer/buy-and-run",
    status: "removed",
    message:
      "removed: combined discover + payment + invoke UI routes are rejected; use separate discover, quote, billing, connect, invoke, and receipt routes.",
  },
];

export function resolveGatewayConsoleRoute(path: string): GatewayConsoleRoute | undefined {
  return gatewayConsoleRoutes.find((route) => route.path === path);
}
