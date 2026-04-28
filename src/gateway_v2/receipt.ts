import { assertNoPayloadFields, clientMethods } from "./client_contracts";
import type { OpaqueId, SharedRequestMetadata } from "./client_contracts";
import type { MeterMeasures } from "./meter";

export const receiptGetClientMethod = clientMethods["receipt.get"];
export const receiptLookupClientMethod = clientMethods["receipt.lookup"];
export const receiptGetHttpRoute = "/v1/gateway/receipts";
export const receiptLookupHttpRoute = "/v1/gateway/receipts";
export const receiptGetGrpcMethod = "GetReceipt";
export const receiptLookupGrpcMethod = "LookupReceipt";
export const receiptSourceOfTruth = "ai-market-backend";

export type PaymentState = "authorized" | "settled" | "failed" | "refunded";
export type ReceiptPrincipalType = "buyer_user" | "buyer_agent" | "seller_user" | "support_governance";

export interface ReceiptViewPrincipal {
  principalType: ReceiptPrincipalType;
  principalId: OpaqueId;
  accountId?: OpaqueId;
  delegatedAccountId?: OpaqueId;
  auditReason?: string;
}

export interface MeteringReceiptSummary {
  meterEventIds: OpaqueId[];
  measures: MeterMeasures;
  artifactHashes: string[];
  connectorIds: OpaqueId[];
}

export interface Receipt {
  receiptId: OpaqueId;
  quoteId: OpaqueId;
  accessGrantId: OpaqueId;
  buyerAccountId: OpaqueId;
  sellerAccountId: OpaqueId;
  listingId: OpaqueId;
  listingVersionId: OpaqueId;
  termsHash: string;
  trustArtifactReferences: Record<string, unknown>;
  meteringSummary: MeteringReceiptSummary;
  paymentState: PaymentState;
  issuedAt: string;
}

export interface ReceiptGetRequest {
  metadata: SharedRequestMetadata;
  receiptId: OpaqueId;
  principal: ReceiptViewPrincipal;
}

export interface ReceiptLookupRequest {
  metadata: SharedRequestMetadata;
  quoteId?: OpaqueId;
  accessGrantId?: OpaqueId;
  invocationId?: OpaqueId;
  principal: ReceiptViewPrincipal;
}

export interface GatewayReceiptClientOptions {
  baseUrl: string;
  apiKey?: string;
  fetch?: typeof fetch;
}

export class GatewayReceiptClient {
  private readonly baseUrl: string;
  private readonly apiKey?: string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: GatewayReceiptClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, "");
    this.apiKey = options.apiKey;
    this.fetchImpl = options.fetch ?? fetch;
  }

  async get(request: ReceiptGetRequest): Promise<Receipt> {
    validateReceiptPrincipal(request.principal);
    assertNoPayloadFields(Object.keys(request));
    const response = await this.fetchImpl(`${this.baseUrl}${receiptGetHttpRoute}/${request.receiptId}`, {
      method: "GET",
      headers: this.headers(request.metadata),
    });
    if (!response.ok) {
      throw new Error(`gateway receipt get failed: ${response.status} ${response.statusText}`);
    }
    return parseReceipt(await response.json());
  }

  async lookup(request: ReceiptLookupRequest): Promise<Receipt[]> {
    validateReceiptPrincipal(request.principal);
    assertNoPayloadFields(Object.keys(request));
    const params = new URLSearchParams();
    if (request.quoteId) params.set("quote_id", request.quoteId);
    if (request.accessGrantId) params.set("access_grant_id", request.accessGrantId);
    if (request.invocationId) params.set("invocation_id", request.invocationId);
    const response = await this.fetchImpl(`${this.baseUrl}${receiptLookupHttpRoute}?${params.toString()}`, {
      method: "GET",
      headers: this.headers(request.metadata),
    });
    if (!response.ok) {
      throw new Error(`gateway receipt lookup failed: ${response.status} ${response.statusText}`);
    }
    return (await response.json()).map((item: Record<string, unknown>) => parseReceipt(item));
  }

  private headers(metadata: SharedRequestMetadata): Record<string, string> {
    const headers: Record<string, string> = {
      "content-type": "application/json",
      "x-request-id": metadata.requestId,
    };
    if (this.apiKey) headers.authorization = `Bearer ${this.apiKey}`;
    return headers;
  }
}

export function validateReceiptPrincipal(principal: ReceiptViewPrincipal): void {
  if (principal.principalType === "support_governance" && !principal.auditReason) {
    throw new Error("support/governance receipt access requires an audit reason");
  }
}

export function parseReceipt(data: Record<string, unknown>): Receipt {
  return {
    receiptId: pickString(data, "receipt_id", "receiptId"),
    quoteId: pickString(data, "quote_id", "quoteId"),
    accessGrantId: pickString(data, "access_grant_id", "accessGrantId"),
    buyerAccountId: pickString(data, "buyer_account_id", "buyerAccountId"),
    sellerAccountId: pickString(data, "seller_account_id", "sellerAccountId"),
    listingId: pickString(data, "listing_id", "listingId"),
    listingVersionId: pickString(data, "listing_version_id", "listingVersionId"),
    termsHash: pickString(data, "terms_hash", "termsHash"),
    trustArtifactReferences: pickRecord(data, "trust", "trustArtifactReferences"),
    meteringSummary: pickRecord(data, "metering_summary", "meteringSummary") as MeteringReceiptSummary,
    paymentState: pickString(data, "payment_state", "paymentState") as PaymentState,
    issuedAt: pickString(data, "issued_at", "issuedAt"),
  };
}

function pickRecord(data: Record<string, unknown>, ...keys: string[]): Record<string, unknown> {
  const value = pick(data, ...keys);
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`expected object field ${keys[0]}`);
  }
  return value as Record<string, unknown>;
}

function pickString(data: Record<string, unknown>, ...keys: string[]): string {
  const value = pick(data, ...keys);
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`expected string field ${keys[0]}`);
  }
  return value;
}

function pick(data: Record<string, unknown>, ...keys: string[]): unknown {
  for (const key of keys) {
    if (key in data) return data[key];
  }
  return undefined;
}
