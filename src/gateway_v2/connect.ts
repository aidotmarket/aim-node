import { assertNoPayloadFields, clientMethods } from "./client_contracts";
import type { OpaqueId, SharedRequestMetadata } from "./client_contracts";
import { assertLocalSecretRef, assertNoRawSellerSecrets, type LocalSecretRef } from "./local_secret_refs";

export const connectClientMethod = clientMethods.connect;

export interface ConnectorPreferences {
  preferredConnectorIds?: OpaqueId[];
  preferredSellerEdgeId?: OpaqueId;
  connectionTypes?: string[];
  region?: string;
}

export interface ConnectRequest {
  metadata: SharedRequestMetadata;
  quoteId: OpaqueId;
  billingSessionId: OpaqueId;
  deliveryMode: string;
  connectorPreferences?: ConnectorPreferences;
  acceptedTermsHash: string;
  sellerEdgeId?: OpaqueId;
}

export interface SellerEdgeBinding {
  sellerEdgeId: OpaqueId;
  sellerId: OpaqueId;
  connectorId: OpaqueId;
  listingId: OpaqueId;
  identityHash: string;
}

export interface GrantConnection {
  type: "local" | "seller_edge";
  localSecretRef: LocalSecretRef;
  sellerEdge?: SellerEdgeBinding;
}

export interface AllowedScope {
  listingId: OpaqueId;
  quoteId: OpaqueId;
  billingSessionId: OpaqueId;
  deliveryMode: string;
  operations: string[];
  maxConcurrency: number;
}

export interface ConnectResponse {
  accessGrantId: OpaqueId;
  connectorId: OpaqueId;
  state: "active" | "revoked";
  expiresAt: string;
  connection: GrantConnection;
  allowedScope: AllowedScope;
  termsHash: string;
}

export interface GatewayConnectClientOptions {
  baseUrl: string;
  apiKey?: string;
  fetch?: typeof fetch;
}

export class GatewayConnectClient {
  private readonly baseUrl: string;
  private readonly apiKey?: string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: GatewayConnectClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, "");
    this.apiKey = options.apiKey;
    this.fetchImpl = options.fetch ?? fetch;
  }

  async connect(request: ConnectRequest): Promise<ConnectResponse> {
    assertNoPayloadFields(Object.keys(request));
    assertNoRawSellerSecrets(request as unknown as Record<string, unknown>);

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

    const response = await this.fetchImpl(`${this.baseUrl}/v1/gateway/connect`, {
      method: "POST",
      headers,
      body: JSON.stringify(request),
    });
    if (!response.ok) {
      throw new Error(`gateway connect failed: ${response.status} ${response.statusText}`);
    }
    return parseConnectResponse(await response.json());
  }
}

export function parseConnectResponse(data: Record<string, unknown>): ConnectResponse {
  const connection = pickRecord(data, "connection");
  const allowedScope = pickRecord(data, "allowed_scope", "allowedScope");
  const localSecretRef = pickString(connection, "local_secret_ref", "localSecretRef");
  assertLocalSecretRef(localSecretRef);

  return {
    accessGrantId: pickString(data, "access_grant_id", "accessGrantId"),
    connectorId: pickString(data, "connector_id", "connectorId"),
    state: pickString(data, "state") as ConnectResponse["state"],
    expiresAt: pickString(data, "expires_at", "expiresAt"),
    connection: {
      type: pickString(connection, "type") as GrantConnection["type"],
      localSecretRef,
      sellerEdge: parseSellerEdge(pickOptionalRecord(connection, "seller_edge", "sellerEdge")),
    },
    allowedScope: {
      listingId: pickString(allowedScope, "listing_id", "listingId"),
      quoteId: pickString(allowedScope, "quote_id", "quoteId"),
      billingSessionId: pickString(allowedScope, "billing_session_id", "billingSessionId"),
      deliveryMode: pickString(allowedScope, "delivery_mode", "deliveryMode"),
      operations: pickStringArray(allowedScope, "operations"),
      maxConcurrency: pickNumber(allowedScope, "max_concurrency", "maxConcurrency"),
    },
    termsHash: pickString(data, "terms_hash", "termsHash"),
  };
}

function parseSellerEdge(data?: Record<string, unknown>): SellerEdgeBinding | undefined {
  if (!data) {
    return undefined;
  }
  return {
    sellerEdgeId: pickString(data, "seller_edge_id", "sellerEdgeId"),
    sellerId: pickString(data, "seller_id", "sellerId"),
    connectorId: pickString(data, "connector_id", "connectorId"),
    listingId: pickString(data, "listing_id", "listingId"),
    identityHash: pickString(data, "identity_hash", "identityHash"),
  };
}

function pickRecord(data: Record<string, unknown>, ...keys: string[]): Record<string, unknown> {
  const value = pick(data, ...keys);
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`expected object field ${keys[0]}`);
  }
  return value as Record<string, unknown>;
}

function pickOptionalRecord(data: Record<string, unknown>, ...keys: string[]): Record<string, unknown> | undefined {
  const value = pick(data, ...keys);
  if (value === undefined || value === null) {
    return undefined;
  }
  if (typeof value !== "object" || Array.isArray(value)) {
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

function pickNumber(data: Record<string, unknown>, ...keys: string[]): number {
  const value = pick(data, ...keys);
  if (typeof value !== "number") {
    throw new Error(`expected number field ${keys[0]}`);
  }
  return value;
}

function pickStringArray(data: Record<string, unknown>, ...keys: string[]): string[] {
  const value = pick(data, ...keys);
  if (!Array.isArray(value) || !value.every((item) => typeof item === "string")) {
    throw new Error(`expected string array field ${keys[0]}`);
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
