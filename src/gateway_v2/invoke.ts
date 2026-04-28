import { assertNoPayloadFields, clientMethods } from "./client_contracts";
import type { OpaqueId, SharedRequestMetadata } from "./client_contracts";
import type { InvokeLimits, InvokeState, MeteringSummary, ResumeCursor } from "./connectors/runtime";

export const invokeClientMethod = clientMethods.invoke;
export const invokeHttpRoute = "/v1/gateway/invoke";
export const invokeGrpcUnaryMethod = "Invoke";
export const invokeGrpcStreamingMethod = "InvokeStream";

export interface InvokeRequest {
  metadata: SharedRequestMetadata;
  accessGrantId: OpaqueId;
  buyerAccountId: OpaqueId;
  listingId: OpaqueId;
  listingVersionId: OpaqueId;
  connectorId: OpaqueId;
  deliveryMode: string;
  termsHash: string;
  operation: string;
  mode: "unary" | "stream";
  sellerEdgeIdentityHash?: string;
  resume?: ResumeCursor;
  limits?: InvokeLimits;
}

export interface InvokeResponse {
  invocationId: OpaqueId;
  state: InvokeState;
  metering: MeteringSummary;
  retryAfterSeconds?: number;
  resumeRequired: boolean;
}

export interface GatewayInvokeClientOptions {
  baseUrl: string;
  apiKey?: string;
  fetch?: typeof fetch;
}

export class GatewayInvokeClient {
  private readonly baseUrl: string;
  private readonly apiKey?: string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: GatewayInvokeClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, "");
    this.apiKey = options.apiKey;
    this.fetchImpl = options.fetch ?? fetch;
  }

  async invoke(request: InvokeRequest): Promise<InvokeResponse> {
    assertNoPayloadFields(Object.keys(request));
    const headers: Record<string, string> = {
      "content-type": "application/json",
      "x-request-id": request.metadata.requestId,
    };
    if (request.metadata.idempotencyKey) {
      headers["idempotency-key"] = request.metadata.idempotencyKey;
    }
    if (this.apiKey) {
      headers.authorization = `Bearer ${this.apiKey}`;
    }
    const response = await this.fetchImpl(`${this.baseUrl}${invokeHttpRoute}`, {
      method: "POST",
      headers,
      body: JSON.stringify(request),
    });
    if (!response.ok) {
      throw new Error(`gateway invoke failed: ${response.status} ${response.statusText}`);
    }
    return parseInvokeResponse(await response.json());
  }
}

export function parseInvokeResponse(data: Record<string, unknown>): InvokeResponse {
  return {
    invocationId: pickString(data, "invocation_id", "invocationId"),
    state: pickString(data, "state") as InvokeState,
    metering: pickRecord(data, "metering"),
    retryAfterSeconds: pickOptionalNumber(data, "retry_after_seconds", "retryAfterSeconds"),
    resumeRequired: Boolean(pick(data, "resume_required", "resumeRequired")),
  };
}

function pickRecord(data: Record<string, unknown>, ...keys: string[]): MeteringSummary {
  const value = pick(data, ...keys);
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`expected object field ${keys[0]}`);
  }
  return value as MeteringSummary;
}

function pickString(data: Record<string, unknown>, ...keys: string[]): string {
  const value = pick(data, ...keys);
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`expected string field ${keys[0]}`);
  }
  return value;
}

function pickOptionalNumber(data: Record<string, unknown>, ...keys: string[]): number | undefined {
  const value = pick(data, ...keys);
  if (value === undefined || value === null) {
    return undefined;
  }
  if (typeof value !== "number") {
    throw new Error(`expected number field ${keys[0]}`);
  }
  return value;
}

function pick(data: Record<string, unknown>, ...keys: string[]): unknown {
  for (const key of keys) {
    if (key in data) {
      return data[key];
    }
  }
  return undefined;
}
