import { clientMethods } from "./client_contracts";
import type { OpaqueId, SharedRequestMetadata } from "./client_contracts";

export const quoteCreateClientMethod = clientMethods["quote.create"];

export interface QuoteRequest {
  metadata: SharedRequestMetadata;
  listingId: OpaqueId;
  listingVersionId?: OpaqueId;
  sellerId?: OpaqueId;
  providerId?: OpaqueId;
  quantity?: number;
  units?: string;
  usageEstimate?: Record<string, unknown>;
  buyerContext?: Record<string, unknown>;
  expiresAfterSeconds?: number;
}

export interface QuoteLineItem {
  code: string;
  description?: string;
  quantity?: number;
  unitAmount?: number;
  amount: number;
  currency: string;
}

export interface QuoteResponse {
  quoteId: OpaqueId;
  listingId: OpaqueId;
  listingVersionId?: OpaqueId;
  sellerId?: OpaqueId;
  providerId?: OpaqueId;
  amount: number;
  currency: string;
  status: string;
  lineItems?: QuoteLineItem[];
  expiresAt?: string;
  requestId?: string;
}

export interface GatewayQuoteClientOptions {
  baseUrl: string;
  apiKey?: string;
  fetch?: typeof fetch;
}

export class GatewayQuoteClient {
  private readonly baseUrl: string;
  private readonly apiKey?: string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: GatewayQuoteClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, "");
    this.apiKey = options.apiKey;
    this.fetchImpl = options.fetch ?? fetch;
  }

  async quote(request: QuoteRequest): Promise<QuoteResponse> {
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

    const response = await this.fetchImpl(`${this.baseUrl}/v1/gateway/quotes`, {
      method: "POST",
      headers,
      body: JSON.stringify(request),
    });

    if (!response.ok) {
      throw new Error(`gateway quote failed: ${response.status} ${response.statusText}`);
    }

    return (await response.json()) as QuoteResponse;
  }
}
