import { assertNoPayloadFields, clientMethods } from "./client_contracts";
import type { OpaqueId, SharedRequestMetadata } from "./client_contracts";

export const meterRecordClientMethod = clientMethods["meter.record"];
export const meterListClientMethod = clientMethods["meter.list"];
export const meterRecordHttpRoute = "/v1/gateway/meter";
export const meterListHttpRoute = "/v1/gateway/meter";
export const meterRecordGrpcMethod = "RecordMetering";
export const meterListGrpcMethod = "ListMetering";

export type MeterEventType = "access_grant" | "invocation" | "delivery_fact" | "reconciliation";
export type MeterState = "accepted" | "rejected";

export interface MeterMeasures {
  bytes?: number;
  rows?: number;
  records?: number;
  calls?: number;
  durationMs?: number;
  retries?: number;
}

export interface MeterSignedReference {
  ref?: string;
  artifactHash?: string;
  signerIdentity?: OpaqueId;
  signatureState?: string;
  verificationState?: string;
  termsHash?: string;
  accessGrantId?: OpaqueId;
  invocationId?: OpaqueId;
}

export interface MeterRecordRequest {
  metadata: SharedRequestMetadata;
  accessGrantId: OpaqueId;
  invocationId: OpaqueId;
  buyerAccountId: OpaqueId;
  sellerAccountId: OpaqueId;
  listingId: OpaqueId;
  listingVersionId: OpaqueId;
  connectorId: OpaqueId;
  eventType: MeterEventType;
  measures: MeterMeasures;
  artifactHash: string;
  occurredAt: string;
  sellerEdgeIdentityHash?: string;
  signedReference?: MeterSignedReference;
}

export interface MeterEvent {
  meterEventId: OpaqueId;
  accessGrantId: OpaqueId;
  invocationId: OpaqueId;
  buyerAccountId: OpaqueId;
  sellerAccountId: OpaqueId;
  listingId: OpaqueId;
  listingVersionId: OpaqueId;
  connectorId: OpaqueId;
  eventType: MeterEventType;
  measures: MeterMeasures;
  artifactHash: string;
  occurredAt: string;
  acceptedAt: string;
  state: MeterState;
  sellerEdgeIdentityHash?: string;
}

export interface MeterListRequest {
  metadata: SharedRequestMetadata;
  accountId: OpaqueId;
  accessGrantId?: OpaqueId;
  invocationId?: OpaqueId;
  artifactHash?: string;
}

export interface GatewayMeterClientOptions {
  baseUrl: string;
  apiKey?: string;
  fetch?: typeof fetch;
}

export class GatewayMeterClient {
  private readonly baseUrl: string;
  private readonly apiKey?: string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: GatewayMeterClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, "");
    this.apiKey = options.apiKey;
    this.fetchImpl = options.fetch ?? fetch;
  }

  async record(request: MeterRecordRequest): Promise<MeterEvent> {
    validateMeterRecordRequest(request);
    const response = await this.fetchImpl(`${this.baseUrl}${meterRecordHttpRoute}`, {
      method: "POST",
      headers: this.headers(request.metadata, true),
      body: JSON.stringify(request),
    });
    if (!response.ok) {
      throw new Error(`gateway meter record failed: ${response.status} ${response.statusText}`);
    }
    return parseMeterEvent(await response.json());
  }

  async list(request: MeterListRequest): Promise<MeterEvent[]> {
    assertNoPayloadFields(Object.keys(request));
    const params = new URLSearchParams();
    params.set("account_id", request.accountId);
    if (request.accessGrantId) params.set("access_grant_id", request.accessGrantId);
    if (request.invocationId) params.set("invocation_id", request.invocationId);
    if (request.artifactHash) params.set("artifact_hash", request.artifactHash);
    const response = await this.fetchImpl(`${this.baseUrl}${meterListHttpRoute}?${params.toString()}`, {
      method: "GET",
      headers: this.headers(request.metadata, false),
    });
    if (!response.ok) {
      throw new Error(`gateway meter list failed: ${response.status} ${response.statusText}`);
    }
    return (await response.json()).map((item: Record<string, unknown>) => parseMeterEvent(item));
  }

  private headers(metadata: SharedRequestMetadata, idempotent: boolean): Record<string, string> {
    const headers: Record<string, string> = {
      "content-type": "application/json",
      "x-request-id": metadata.requestId,
    };
    if (idempotent && metadata.idempotencyKey) headers["idempotency-key"] = metadata.idempotencyKey;
    if (metadata.requestTimestamp) headers["x-gateway-request-timestamp"] = metadata.requestTimestamp;
    if (metadata.nonce) headers["x-gateway-nonce"] = metadata.nonce;
    if (metadata.signedEnvelope) headers["x-gateway-signed-envelope"] = metadata.signedEnvelope;
    if (this.apiKey) headers.authorization = `Bearer ${this.apiKey}`;
    return headers;
  }
}

export function validateMeterRecordRequest(request: MeterRecordRequest): void {
  assertNoPayloadFields(Object.keys(request));
  assertNoPayloadFields(Object.keys(request.measures));
  if (!request.metadata.signedEnvelope && !(request.metadata.requestTimestamp && request.metadata.nonce)) {
    throw new Error("meter events require a signed envelope or timestamp/nonce");
  }
  const total =
    (request.measures.bytes ?? 0) +
    (request.measures.rows ?? 0) +
    (request.measures.records ?? 0) +
    (request.measures.calls ?? 0);
  if (total <= 0) {
    throw new Error("METERING_REJECTED: meter event must include evidence measures");
  }
}

export function parseMeterEvent(data: Record<string, unknown>): MeterEvent {
  return {
    meterEventId: pickString(data, "meter_event_id", "meterEventId"),
    accessGrantId: pickString(data, "access_grant_id", "accessGrantId"),
    invocationId: pickString(data, "invocation_id", "invocationId"),
    buyerAccountId: pickString(data, "buyer_account_id", "buyerAccountId"),
    sellerAccountId: pickString(data, "seller_account_id", "sellerAccountId"),
    listingId: pickString(data, "listing_id", "listingId"),
    listingVersionId: pickString(data, "listing_version_id", "listingVersionId"),
    connectorId: pickString(data, "connector_id", "connectorId"),
    eventType: pickString(data, "event_type", "eventType") as MeterEventType,
    measures: pickRecord(data, "measures"),
    artifactHash: pickString(data, "artifact_hash", "artifactHash"),
    occurredAt: pickString(data, "occurred_at", "occurredAt"),
    acceptedAt: pickString(data, "accepted_at", "acceptedAt"),
    state: pickString(data, "state") as MeterState,
    sellerEdgeIdentityHash: pickOptionalString(data, "seller_edge_identity_hash", "sellerEdgeIdentityHash"),
  };
}

function pickRecord(data: Record<string, unknown>, ...keys: string[]): MeterMeasures {
  const value = pick(data, ...keys);
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`expected object field ${keys[0]}`);
  }
  return value as MeterMeasures;
}

function pickString(data: Record<string, unknown>, ...keys: string[]): string {
  const value = pick(data, ...keys);
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`expected string field ${keys[0]}`);
  }
  return value;
}

function pickOptionalString(data: Record<string, unknown>, ...keys: string[]): string | undefined {
  const value = pick(data, ...keys);
  if (value === undefined || value === null) return undefined;
  if (typeof value !== "string") throw new Error(`expected string field ${keys[0]}`);
  return value;
}

function pick(data: Record<string, unknown>, ...keys: string[]): unknown {
  for (const key of keys) {
    if (key in data) return data[key];
  }
  return undefined;
}
