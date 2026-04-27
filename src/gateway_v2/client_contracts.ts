export type GatewaySurface =
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
  | "create_billing_session";

export type OpaqueId = string;

export const commonIdFields = [
  "listing_id",
  "listing_version_id",
  "seller_id",
  "provider_id",
  "quote_id",
  "access_grant_id",
  "connector_id",
  "invocation_id",
  "meter_event_id",
  "receipt_id",
  "billing_session_id",
  "trust_profile_id",
  "attestation_id",
] as const;

export interface SharedRequestMetadata {
  requestId: string;
  principalId?: OpaqueId;
  accountId?: OpaqueId;
  traceparent?: string;
  idempotencyKey?: string;
  requestTimestamp?: string;
  nonce?: string;
  signedEnvelope?: string;
}

export interface GatewayClientMethod {
  surface: GatewaySurface;
  sdkMethod: string;
  idempotencyRequired: boolean;
  sourceOfTruth: "ai-market-backend" | "local-or-seller-edge-runtime";
}

export const clientMethods: Record<GatewaySurface, GatewayClientMethod> = {
  discover: {
    surface: "discover",
    sdkMethod: "gateway.discover",
    idempotencyRequired: false,
    sourceOfTruth: "ai-market-backend",
  },
  "quote.create": {
    surface: "quote.create",
    sdkMethod: "gateway.quote.create",
    idempotencyRequired: true,
    sourceOfTruth: "ai-market-backend",
  },
  "quote.get": {
    surface: "quote.get",
    sdkMethod: "gateway.quote.get",
    idempotencyRequired: false,
    sourceOfTruth: "ai-market-backend",
  },
  connect: {
    surface: "connect",
    sdkMethod: "gateway.connect",
    idempotencyRequired: true,
    sourceOfTruth: "ai-market-backend",
  },
  invoke: {
    surface: "invoke",
    sdkMethod: "gateway.invoke",
    idempotencyRequired: true,
    sourceOfTruth: "local-or-seller-edge-runtime",
  },
  "meter.record": {
    surface: "meter.record",
    sdkMethod: "gateway.meter.record",
    idempotencyRequired: true,
    sourceOfTruth: "ai-market-backend",
  },
  "meter.list": {
    surface: "meter.list",
    sdkMethod: "gateway.meter.list",
    idempotencyRequired: false,
    sourceOfTruth: "ai-market-backend",
  },
  "receipt.get": {
    surface: "receipt.get",
    sdkMethod: "gateway.receipt.get",
    idempotencyRequired: false,
    sourceOfTruth: "ai-market-backend",
  },
  "receipt.lookup": {
    surface: "receipt.lookup",
    sdkMethod: "gateway.receipt.lookup",
    idempotencyRequired: false,
    sourceOfTruth: "ai-market-backend",
  },
  publish: {
    surface: "publish",
    sdkMethod: "gateway.publish",
    idempotencyRequired: true,
    sourceOfTruth: "ai-market-backend",
  },
  verify_provider: {
    surface: "verify_provider",
    sdkMethod: "gateway.verifyProvider",
    idempotencyRequired: false,
    sourceOfTruth: "ai-market-backend",
  },
  request_access: {
    surface: "request_access",
    sdkMethod: "gateway.requestAccess",
    idempotencyRequired: true,
    sourceOfTruth: "ai-market-backend",
  },
  estimate_cost: {
    surface: "estimate_cost",
    sdkMethod: "gateway.estimateCost",
    idempotencyRequired: false,
    sourceOfTruth: "ai-market-backend",
  },
  create_billing_session: {
    surface: "create_billing_session",
    sdkMethod: "gateway.createBillingSession",
    idempotencyRequired: true,
    sourceOfTruth: "ai-market-backend",
  },
};

export const aimNodeLocalRuntimeModels = [
  "local_credentials",
  "connector_configuration",
  "cached_discover_result_with_freshness",
  "gateway_invocation_runtime",
  "local_meter_buffer",
  "retry_idempotency_coordination",
  "developer_console_health",
] as const;

export const aimNodeForbiddenSourceOfTruthModels = [
  "canonical_listing",
  "canonical_quote",
  "canonical_billing_session",
  "accepted_meter_event",
  "canonical_receipt",
  "balance_ledger",
  "trust_state",
] as const;

export const forbiddenPayloadFieldTokens = [
  "payload",
  "payload_bytes",
  "dataset_bytes",
  "raw_bytes",
  "file_bytes",
  "content_bytes",
  "sample_bytes",
  "sample_payload",
  "raw_secret",
  "seller_secret",
] as const;

export function assertNoPayloadFields(fieldNames: string[]): void {
  const forbidden = fieldNames.filter((field) =>
    forbiddenPayloadFieldTokens.some((token) => field.toLowerCase().includes(token)),
  );
  if (forbidden.length > 0) {
    throw new Error(`payload-bearing fields are forbidden: ${forbidden.join(", ")}`);
  }
}
