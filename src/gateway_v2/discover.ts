import { clientMethods } from "./client_contracts";
import type { OpaqueId, SharedRequestMetadata } from "./client_contracts";

export const discoverClientMethod = clientMethods.discover;

export interface DiscoverRequest {
  metadata: SharedRequestMetadata;
  query?: string;
  categories?: string[];
  tags?: string[];
  sellerIds?: OpaqueId[];
  providerIds?: OpaqueId[];
  capabilities?: string[];
  limit?: number;
  cursor?: string;
}

export interface DiscoverListing {
  listingId: OpaqueId;
  listingVersionId: OpaqueId;
  sellerId: OpaqueId;
  providerId?: OpaqueId;
  title: string;
  description?: string;
  categories?: string[];
  tags?: string[];
  capabilities?: string[];
  quoteRequired?: boolean;
  pricingSummary?: Record<string, unknown>;
}

export interface DiscoverResponse {
  listings: DiscoverListing[];
  nextCursor?: string;
  requestId?: string;
}

export interface GatewayDiscoverClientOptions {
  baseUrl: string;
  apiKey?: string;
  fetch?: typeof fetch;
}

export class GatewayDiscoverClient {
  private readonly baseUrl: string;
  private readonly apiKey?: string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: GatewayDiscoverClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, "");
    this.apiKey = options.apiKey;
    this.fetchImpl = options.fetch ?? fetch;
  }

  async discover(request: DiscoverRequest): Promise<DiscoverResponse> {
    const headers: Record<string, string> = {
      "content-type": "application/json",
      "x-request-id": request.metadata.requestId,
    };

    if (this.apiKey) {
      headers.authorization = `Bearer ${this.apiKey}`;
    }

    const response = await this.fetchImpl(`${this.baseUrl}/v1/gateway/discover`, {
      method: "POST",
      headers,
      body: JSON.stringify(request),
    });

    if (!response.ok) {
      throw new Error(`gateway discover failed: ${response.status} ${response.statusText}`);
    }

    return (await response.json()) as DiscoverResponse;
  }
}
