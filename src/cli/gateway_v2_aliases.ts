// FUTURE-BUILD ARTIFACT
// TypeScript source. No build pipeline exists for src/gateway_v2/ or src/cli/ as of Chunk 10.
// Compilation, packaging, and Dockerfile integration will be addressed in a follow-up BQ
// (BQ-AIM-NODE-GATEWAY-V2-TYPESCRIPT-BUILD-PIPELINE).
// Defined for BQ-AIM-NODE-GATEWAY-V2 Gate 2 Chunk 11 migration compatibility.

type GatewayV2Surface =
  | "discover"
  | "quote.create"
  | "quote.get"
  | "connect"
  | "invoke"
  | "meter.record"
  | "meter.list"
  | "receipt.get"
  | "receipt.lookup"
  | "publish"
  | "verify_provider"
  | "request_access"
  | "estimate_cost"
  | "create_billing_session"
  | "gateway_console";

export interface GatewayV2CommandAlias {
  deprecatedName: string;
  replacementName?: string;
  surface?: GatewayV2Surface;
  status: "deprecated" | "removed";
  message: string;
}

export const gatewayV2CommandAliases: GatewayV2CommandAlias[] = [
  {
    deprecatedName: "aim-node dashboard",
    replacementName: "aim-node gateway console",
    surface: "gateway_console",
    status: "deprecated",
    message: "deprecated: aim-node dashboard is subsumed by Gateway Console.",
  },
  {
    deprecatedName: "aim-node earnings",
    replacementName: "aim-node gateway receipts --seller",
    surface: "receipt.lookup",
    status: "deprecated",
    message: "deprecated: earnings are read-only backend-derived Gateway Console receipt views.",
  },
  {
    deprecatedName: "aim-node balance",
    status: "removed",
    message: "removed: AIM-Node local balance calculation is retired; use backend payout and settlement references.",
  },
  {
    deprecatedName: "aim-node buyer discover",
    replacementName: "aim-node gateway discover",
    surface: "discover",
    status: "deprecated",
    message: "deprecated: use Gateway V2 discover.",
  },
  {
    deprecatedName: "aim-node buyer verify",
    replacementName: "aim-node gateway verify-provider",
    surface: "verify_provider",
    status: "deprecated",
    message: "deprecated: use Gateway V2 verify_provider.",
  },
  {
    deprecatedName: "aim-node buyer estimate",
    replacementName: "aim-node gateway estimate-cost",
    surface: "estimate_cost",
    status: "deprecated",
    message: "deprecated: use Gateway V2 estimate_cost.",
  },
  {
    deprecatedName: "aim-node buyer quote",
    replacementName: "aim-node gateway quote create",
    surface: "quote.create",
    status: "deprecated",
    message: "deprecated: use Gateway V2 quote.create.",
  },
  {
    deprecatedName: "aim-node buyer access",
    replacementName: "aim-node gateway request-access",
    surface: "request_access",
    status: "deprecated",
    message: "deprecated: use Gateway V2 request_access.",
  },
  {
    deprecatedName: "aim-node buyer billing",
    replacementName: "aim-node gateway billing-session create",
    surface: "create_billing_session",
    status: "deprecated",
    message: "deprecated: use Gateway V2 create_billing_session.",
  },
  {
    deprecatedName: "aim-node buyer connect",
    replacementName: "aim-node gateway connect",
    surface: "connect",
    status: "deprecated",
    message: "deprecated: use Gateway V2 connect.",
  },
  {
    deprecatedName: "aim-node buyer invoke",
    replacementName: "aim-node gateway invoke",
    surface: "invoke",
    status: "deprecated",
    message: "deprecated: use Gateway V2 invoke.",
  },
  {
    deprecatedName: "aim-node buyer receipt",
    replacementName: "aim-node gateway receipt get",
    surface: "receipt.get",
    status: "deprecated",
    message: "deprecated: use Gateway V2 receipt.get or receipt.lookup.",
  },
  {
    deprecatedName: "aim-node buyer buy-and-run",
    status: "removed",
    message:
      "removed: combined discover + payment + invoke aliases are rejected; run discover, quote, billing, connect, invoke, and receipt separately.",
  },
];

export const removedCombinedGatewayV2Aliases = [
  "aim-node buyer buy-and-run",
  "gateway.buyer.purchaseAndInvoke",
] as const;

export function resolveGatewayV2CommandAlias(name: string): GatewayV2CommandAlias | undefined {
  return gatewayV2CommandAliases.find((alias) => alias.deprecatedName === name);
}

export function rejectCombinedDiscoverPaymentInvokeAlias(name: string): string | undefined {
  if (removedCombinedGatewayV2Aliases.includes(name as (typeof removedCombinedGatewayV2Aliases)[number])) {
    return "removed: compatibility shims must not combine discover + payment + invoke in one command.";
  }
  return undefined;
}
