import { assertNoPayloadFields, clientMethods } from "./client_contracts";
import type { OpaqueId, SharedRequestMetadata } from "./client_contracts";

export const publishClientMethod = clientMethods.publish;

export type PublishGovernanceState =
  | "pending_review"
  | "review_required"
  | "abuse_blocked"
  | "trust_requirement_unmet"
  | "publish_denied"
  | "published";

export interface SignedReference {
  ref: string;
  artifactHash?: string;
  signerIdentity: OpaqueId;
  signatureState: string;
  verificationState: string;
  expiresAt?: string;
}

export interface ListingMetadata {
  title: string;
  summary: string;
  tags?: string[];
  category?: string;
}

export interface ListingPricing {
  model: string;
  currency: string;
  unitAmountCents: number;
  billingUnit: string;
}

export interface ListingSamplePolicy {
  previewRefs?: SignedReference[];
  summary?: string;
  rowCount?: number;
  columnNames?: string[];
}

export interface LicenseTerms {
  termsRef: SignedReference;
  commercialUse?: boolean;
  retentionDays?: number;
}

export interface PublishRequest {
  metadata: SharedRequestMetadata;
  sellerId: OpaqueId;
  listingMetadata: ListingMetadata;
  deliveryModes: string[];
  pricing: ListingPricing;
  samplePolicy?: ListingSamplePolicy;
  licenseTerms: LicenseTerms;
  trustArtifactRefs?: SignedReference[];
  sellerVerificationRef?: SignedReference;
  listingReviewPolicy?: string;
  abuseSignals?: string[];
}

export interface PatchListingRequest {
  metadata: SharedRequestMetadata;
  listingVersionId?: OpaqueId;
  listingMetadata?: ListingMetadata;
  deliveryModes?: string[];
  pricing?: ListingPricing;
  samplePolicy?: ListingSamplePolicy;
  licenseTerms?: LicenseTerms;
  trustArtifactRefs?: SignedReference[];
  sellerVerificationRef?: SignedReference;
  listingReviewPolicy?: string;
  abuseSignals?: string[];
}

export interface PublishedListing {
  listingId: OpaqueId;
  listingVersionId: OpaqueId;
  sellerId: OpaqueId;
  state: PublishGovernanceState;
  discoverable: boolean;
  quoteEligible: boolean;
  listingMetadata: ListingMetadata;
  deliveryModes: string[];
  pricing: ListingPricing;
  samplePolicy: ListingSamplePolicy;
  licenseTerms: LicenseTerms;
  trustArtifactRefs: SignedReference[];
  sellerVerificationRef?: SignedReference;
  listingReviewPolicy?: string;
  governanceEvents?: string[];
  reasonCode?: string;
}

export interface GatewayPublishClientOptions {
  baseUrl: string;
  apiKey?: string;
  fetch?: typeof fetch;
}

export class LocalPublishDraftCache {
  private readonly drafts = new Map<string, PublishRequest>();

  saveDraft(key: string, draft: PublishRequest): void {
    assertPublishRequestHasNoPayload(draft);
    this.drafts.set(key, structuredClone(draft));
  }

  getDraft(key: string): PublishRequest | undefined {
    const draft = this.drafts.get(key);
    return draft ? structuredClone(draft) : undefined;
  }

  deleteDraft(key: string): boolean {
    return this.drafts.delete(key);
  }
}

export class GatewayPublishClient {
  private readonly baseUrl: string;
  private readonly apiKey?: string;
  private readonly fetchImpl: typeof fetch;
  readonly draftCache = new LocalPublishDraftCache();

  constructor(options: GatewayPublishClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, "");
    this.apiKey = options.apiKey;
    this.fetchImpl = options.fetch ?? fetch;
  }

  async publish(request: PublishRequest): Promise<PublishedListing> {
    assertPublishRequestHasNoPayload(request);
    const response = await this.fetchImpl(`${this.baseUrl}/v1/gateway/publish`, {
      method: "POST",
      headers: this.headers(request.metadata),
      body: JSON.stringify(toWirePublishRequest(request)),
    });
    if (!response.ok) {
      throw new Error(`gateway publish failed: ${response.status} ${response.statusText}`);
    }
    return parsePublishedListing(await response.json());
  }

  async patchListing(listingId: OpaqueId, request: PatchListingRequest, ifMatch?: OpaqueId): Promise<PublishedListing> {
    assertNoPayloadDeep(request as unknown as Record<string, unknown>);
    const headers = this.headers(request.metadata);
    if (ifMatch) {
      headers["if-match"] = ifMatch;
    }
    const response = await this.fetchImpl(`${this.baseUrl}/v1/gateway/listings/${encodeURIComponent(listingId)}`, {
      method: "PATCH",
      headers,
      body: JSON.stringify(toWirePatchListingRequest(request)),
    });
    if (!response.ok) {
      throw new Error(`gateway listing patch failed: ${response.status} ${response.statusText}`);
    }
    return parsePublishedListing(await response.json());
  }

  private headers(metadata: SharedRequestMetadata): Record<string, string> {
    const headers: Record<string, string> = {
      "content-type": "application/json",
      "x-request-id": metadata.requestId,
    };
    if (metadata.idempotencyKey) {
      headers["idempotency-key"] = metadata.idempotencyKey;
    }
    if (this.apiKey) {
      headers.authorization = `Bearer ${this.apiKey}`;
    }
    return headers;
  }
}

export function assertPublishRequestHasNoPayload(request: PublishRequest): void {
  assertNoPayloadDeep(request as unknown as Record<string, unknown>);
}

function assertNoPayloadDeep(value: unknown): void {
  if (Array.isArray(value)) {
    value.forEach(assertNoPayloadDeep);
    return;
  }
  if (typeof value !== "object" || value === null) {
    return;
  }
  const record = value as Record<string, unknown>;
  assertNoPayloadFields(Object.keys(record));
  Object.values(record).forEach(assertNoPayloadDeep);
}

function toWirePublishRequest(request: PublishRequest): Record<string, unknown> {
  return dropUndefined({
    metadata: toWireMetadata(request.metadata),
    seller_id: request.sellerId,
    listing_metadata: toWireListingMetadata(request.listingMetadata),
    delivery_modes: request.deliveryModes,
    pricing: toWirePricing(request.pricing),
    sample_policy: request.samplePolicy ? toWireSamplePolicy(request.samplePolicy) : undefined,
    license_terms: toWireLicenseTerms(request.licenseTerms),
    trust_artifact_refs: request.trustArtifactRefs?.map(toWireSignedReference),
    seller_verification_ref: request.sellerVerificationRef ? toWireSignedReference(request.sellerVerificationRef) : undefined,
    listing_review_policy: request.listingReviewPolicy,
    abuse_signals: request.abuseSignals,
  });
}

function toWirePatchListingRequest(request: PatchListingRequest): Record<string, unknown> {
  return dropUndefined({
    metadata: toWireMetadata(request.metadata),
    listing_version_id: request.listingVersionId,
    listing_metadata: request.listingMetadata ? toWireListingMetadata(request.listingMetadata) : undefined,
    delivery_modes: request.deliveryModes,
    pricing: request.pricing ? toWirePricing(request.pricing) : undefined,
    sample_policy: request.samplePolicy ? toWireSamplePolicy(request.samplePolicy) : undefined,
    license_terms: request.licenseTerms ? toWireLicenseTerms(request.licenseTerms) : undefined,
    trust_artifact_refs: request.trustArtifactRefs?.map(toWireSignedReference),
    seller_verification_ref: request.sellerVerificationRef ? toWireSignedReference(request.sellerVerificationRef) : undefined,
    listing_review_policy: request.listingReviewPolicy,
    abuse_signals: request.abuseSignals,
  });
}

function toWireMetadata(metadata: SharedRequestMetadata): Record<string, unknown> {
  return dropUndefined({
    request_id: metadata.requestId,
    principal_id: metadata.principalId,
    account_id: metadata.accountId,
    traceparent: metadata.traceparent,
    idempotency_key: metadata.idempotencyKey,
    request_timestamp: metadata.requestTimestamp,
    nonce: metadata.nonce,
    signed_envelope: metadata.signedEnvelope,
  });
}

function toWireSignedReference(ref: SignedReference): Record<string, unknown> {
  return dropUndefined({
    ref: ref.ref,
    artifact_hash: ref.artifactHash,
    signer_identity: ref.signerIdentity,
    signature_state: ref.signatureState,
    verification_state: ref.verificationState,
    expires_at: ref.expiresAt,
  });
}

function toWireListingMetadata(metadata: ListingMetadata): Record<string, unknown> {
  return dropUndefined({
    title: metadata.title,
    summary: metadata.summary,
    tags: metadata.tags,
    category: metadata.category,
  });
}

function toWirePricing(pricing: ListingPricing): Record<string, unknown> {
  return {
    model: pricing.model,
    currency: pricing.currency,
    unit_amount_cents: pricing.unitAmountCents,
    billing_unit: pricing.billingUnit,
  };
}

function toWireSamplePolicy(policy: ListingSamplePolicy): Record<string, unknown> {
  return dropUndefined({
    preview_refs: policy.previewRefs?.map(toWireSignedReference),
    summary: policy.summary,
    row_count: policy.rowCount,
    column_names: policy.columnNames,
  });
}

function toWireLicenseTerms(terms: LicenseTerms): Record<string, unknown> {
  return dropUndefined({
    terms_ref: toWireSignedReference(terms.termsRef),
    commercial_use: terms.commercialUse,
    retention_days: terms.retentionDays,
  });
}

function parsePublishedListing(data: Record<string, unknown>): PublishedListing {
  return {
    listingId: pickString(data, "listing_id", "listingId"),
    listingVersionId: pickString(data, "listing_version_id", "listingVersionId"),
    sellerId: pickString(data, "seller_id", "sellerId"),
    state: pickString(data, "state") as PublishGovernanceState,
    discoverable: pickBoolean(data, "discoverable"),
    quoteEligible: pickBoolean(data, "quote_eligible", "quoteEligible"),
    listingMetadata: parseListingMetadata(pickRecord(data, "listing_metadata", "listingMetadata")),
    deliveryModes: pickStringArray(data, "delivery_modes", "deliveryModes"),
    pricing: parsePricing(pickRecord(data, "pricing")),
    samplePolicy: parseSamplePolicy(pickRecord(data, "sample_policy", "samplePolicy")),
    licenseTerms: parseLicenseTerms(pickRecord(data, "license_terms", "licenseTerms")),
    trustArtifactRefs: pickRecordArray(data, "trust_artifact_refs", "trustArtifactRefs").map(parseSignedReference),
    sellerVerificationRef: parseOptionalSignedReference(pickOptionalRecord(data, "seller_verification_ref", "sellerVerificationRef")),
    listingReviewPolicy: pickOptionalString(data, "listing_review_policy", "listingReviewPolicy"),
    governanceEvents: pickOptionalStringArray(data, "governance_events", "governanceEvents"),
    reasonCode: pickOptionalString(data, "reason_code", "reasonCode"),
  };
}

function parseSignedReference(data: Record<string, unknown>): SignedReference {
  return {
    ref: pickString(data, "ref"),
    artifactHash: pickOptionalString(data, "artifact_hash", "artifactHash"),
    signerIdentity: pickString(data, "signer_identity", "signerIdentity"),
    signatureState: pickString(data, "signature_state", "signatureState"),
    verificationState: pickString(data, "verification_state", "verificationState"),
    expiresAt: pickOptionalString(data, "expires_at", "expiresAt"),
  };
}

function parseOptionalSignedReference(data?: Record<string, unknown>): SignedReference | undefined {
  return data ? parseSignedReference(data) : undefined;
}

function parseListingMetadata(data: Record<string, unknown>): ListingMetadata {
  return {
    title: pickString(data, "title"),
    summary: pickString(data, "summary"),
    tags: pickOptionalStringArray(data, "tags"),
    category: pickOptionalString(data, "category"),
  };
}

function parsePricing(data: Record<string, unknown>): ListingPricing {
  return {
    model: pickString(data, "model"),
    currency: pickString(data, "currency"),
    unitAmountCents: pickNumber(data, "unit_amount_cents", "unitAmountCents"),
    billingUnit: pickString(data, "billing_unit", "billingUnit"),
  };
}

function parseSamplePolicy(data: Record<string, unknown>): ListingSamplePolicy {
  return {
    previewRefs: pickRecordArray(data, "preview_refs", "previewRefs").map(parseSignedReference),
    summary: pickOptionalString(data, "summary"),
    rowCount: pickOptionalNumber(data, "row_count", "rowCount"),
    columnNames: pickOptionalStringArray(data, "column_names", "columnNames"),
  };
}

function parseLicenseTerms(data: Record<string, unknown>): LicenseTerms {
  return {
    termsRef: parseSignedReference(pickRecord(data, "terms_ref", "termsRef")),
    commercialUse: pickOptionalBoolean(data, "commercial_use", "commercialUse"),
    retentionDays: pickOptionalNumber(data, "retention_days", "retentionDays"),
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

function pickRecordArray(data: Record<string, unknown>, ...keys: string[]): Record<string, unknown>[] {
  const value = pick(data, ...keys);
  if (value === undefined) {
    return [];
  }
  if (!Array.isArray(value) || !value.every((item) => typeof item === "object" && item !== null && !Array.isArray(item))) {
    throw new Error(`expected object array field ${keys[0]}`);
  }
  return value as Record<string, unknown>[];
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
  return typeof value === "string" ? value : undefined;
}

function pickNumber(data: Record<string, unknown>, ...keys: string[]): number {
  const value = pick(data, ...keys);
  if (typeof value !== "number") {
    throw new Error(`expected number field ${keys[0]}`);
  }
  return value;
}

function pickOptionalNumber(data: Record<string, unknown>, ...keys: string[]): number | undefined {
  const value = pick(data, ...keys);
  return typeof value === "number" ? value : undefined;
}

function pickBoolean(data: Record<string, unknown>, ...keys: string[]): boolean {
  const value = pick(data, ...keys);
  if (typeof value !== "boolean") {
    throw new Error(`expected boolean field ${keys[0]}`);
  }
  return value;
}

function pickOptionalBoolean(data: Record<string, unknown>, ...keys: string[]): boolean | undefined {
  const value = pick(data, ...keys);
  return typeof value === "boolean" ? value : undefined;
}

function pickStringArray(data: Record<string, unknown>, ...keys: string[]): string[] {
  const value = pick(data, ...keys);
  if (!Array.isArray(value) || !value.every((item) => typeof item === "string")) {
    throw new Error(`expected string array field ${keys[0]}`);
  }
  return value;
}

function pickOptionalStringArray(data: Record<string, unknown>, ...keys: string[]): string[] | undefined {
  const value = pick(data, ...keys);
  if (value === undefined) {
    return undefined;
  }
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

function dropUndefined(data: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(data).filter(([, value]) => value !== undefined));
}
