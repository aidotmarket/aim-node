import { assertNoPayloadFields, clientMethods } from "./client_contracts";
import type { OpaqueId, SharedRequestMetadata } from "./client_contracts";

export const verifyProviderClientMethod = clientMethods.verify_provider;
export const requestAccessClientMethod = clientMethods.request_access;
export const estimateCostClientMethod = clientMethods.estimate_cost;
export const createBillingSessionClientMethod = clientMethods.create_billing_session;

export interface BuyerBudgetCap {
  perSessionCents: number;
  lifetimeCents: number;
  lifetimeSpendCents?: number;
  currency?: string;
}

export interface BuyerPolicyEnvelope {
  agentId: OpaqueId;
  delegatedUserId: OpaqueId;
  delegatedAccountId: OpaqueId;
  scopes: string[];
  budgetCap: BuyerBudgetCap;
  humanApprovalRequired?: boolean;
  humanApprovalState?: "not_required" | "pending" | "approved" | "denied";
}

export interface VerifyProviderRequest {
  metadata: SharedRequestMetadata;
  sellerId: OpaqueId;
  listingId: OpaqueId;
  policyEnvelope: BuyerPolicyEnvelope;
  sellerVerificationRef: string;
  provenanceAttestationRef: string;
  termsUseRightsRef: string;
  qualityProfileRef: string;
  sampleReceiptRef: string;
}

export interface VerifyProviderResponse {
  verificationId: OpaqueId;
  sellerId: OpaqueId;
  listingId: OpaqueId;
  status: string;
  checkedRefs: string[];
  payloadBytesReturned: 0;
}

export interface RequestAccessRequest {
  metadata: SharedRequestMetadata;
  buyerAccountId: OpaqueId;
  sellerId: OpaqueId;
  listingId: OpaqueId;
  requestedUse: string;
  policyEnvelope: BuyerPolicyEnvelope;
}

export interface AccessRequestResponse {
  accessRequestId: OpaqueId;
  buyerAccountId: OpaqueId;
  sellerId: OpaqueId;
  listingId: OpaqueId;
  state: "pending_seller_approval" | "approved" | "denied";
  approvalWorkflowRef: string;
  paymentStateCreated: boolean;
  invocationStateCreated: boolean;
}

export interface EstimateCostRequest {
  metadata: SharedRequestMetadata;
  buyerAccountId: OpaqueId;
  listingId: OpaqueId;
  requestedUnits?: number;
  policyEnvelope: BuyerPolicyEnvelope;
}

export interface CostEstimateResponse {
  estimateId: OpaqueId;
  listingId: OpaqueId;
  projectedAmountCents: number;
  platformFeeBps: number;
  platformFeeCents: number;
  sellerAmountCents: number;
  currency: string;
  nonBinding: true;
  quoteRequiredForBilling: true;
}

export interface CreateBillingSessionRequest {
  metadata: SharedRequestMetadata;
  buyerAccountId: OpaqueId;
  sellerId: OpaqueId;
  quoteId: OpaqueId;
  accessRequestId: OpaqueId;
  termsAcceptanceId: OpaqueId;
  budgetCapCents: number;
  paymentState: "authorized" | "completed" | "payment_required" | "payment_failed";
  policyEnvelope: BuyerPolicyEnvelope;
}

export interface BillingSessionResponse {
  billingSessionId: OpaqueId;
  quoteId: OpaqueId;
  accessRequestId: OpaqueId;
  termsAcceptanceId: OpaqueId;
  buyerAccountId: OpaqueId;
  state: "authorized" | "payment_required" | "payment_failed";
  amountCents: number;
  currency: string;
  accessGranted: false;
}

export interface GatewayBuyerClientOptions {
  baseUrl: string;
  apiKey?: string;
  fetch?: typeof fetch;
}

export class GatewayBuyerClient {
  private readonly baseUrl: string;
  private readonly apiKey?: string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: GatewayBuyerClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, "");
    this.apiKey = options.apiKey;
    this.fetchImpl = options.fetch ?? fetch;
  }

  VerifyProvider(request: VerifyProviderRequest): Promise<VerifyProviderResponse> {
    return this.post("/v1/gateway/buyer/verify_provider", request, false) as Promise<VerifyProviderResponse>;
  }

  RequestAccess(request: RequestAccessRequest): Promise<AccessRequestResponse> {
    return this.post("/v1/gateway/buyer/request_access", request, true) as Promise<AccessRequestResponse>;
  }

  EstimateCost(request: EstimateCostRequest): Promise<CostEstimateResponse> {
    return this.post("/v1/gateway/buyer/estimate_cost", request, false) as Promise<CostEstimateResponse>;
  }

  CreateBillingSession(request: CreateBillingSessionRequest): Promise<BillingSessionResponse> {
    return this.post("/v1/gateway/buyer/billing_sessions", request, true) as Promise<BillingSessionResponse>;
  }

  verifyProvider(request: VerifyProviderRequest): Promise<VerifyProviderResponse> {
    return this.VerifyProvider(request);
  }

  requestAccess(request: RequestAccessRequest): Promise<AccessRequestResponse> {
    return this.RequestAccess(request);
  }

  estimateCost(request: EstimateCostRequest): Promise<CostEstimateResponse> {
    return this.EstimateCost(request);
  }

  createBillingSession(request: CreateBillingSessionRequest): Promise<BillingSessionResponse> {
    return this.CreateBillingSession(request);
  }

  private async post(path: string, request: { metadata: SharedRequestMetadata }, idempotent: boolean): Promise<unknown> {
    assertNoPayloadFields(Object.keys(request));
    const headers: Record<string, string> = {
      "content-type": "application/json",
      "x-request-id": request.metadata.requestId,
    };
    if (idempotent && request.metadata.idempotencyKey) {
      headers["idempotency-key"] = request.metadata.idempotencyKey;
    }
    if (this.apiKey) {
      headers.authorization = `Bearer ${this.apiKey}`;
    }

    const response = await this.fetchImpl(`${this.baseUrl}${path}`, {
      method: "POST",
      headers,
      body: JSON.stringify(request),
    });
    if (!response.ok) {
      throw new Error(`gateway buyer request failed: ${response.status} ${response.statusText}`);
    }
    return response.json();
  }
}
