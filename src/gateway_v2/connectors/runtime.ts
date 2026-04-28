export type InvokeState =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "partial_transfer"
  | "provider_timeout"
  | "grant_revoked_mid_stream"
  | "trust_revoked_mid_stream"
  | "resume_unsupported"
  | "metering_accepted_receipt_pending";

export interface RuntimeGrantBinding {
  accessGrantId: string;
  buyerAccountId: string;
  listingId: string;
  listingVersionId: string;
  connectorId: string;
  deliveryMode: string;
  termsHash: string;
  operations: string[];
  sellerEdgeIdentityHash?: string;
  expiresAt: string;
  state: "active" | "revoked";
  maxConcurrency: number;
}

export interface InvokeLimits {
  byteCap: number;
  rowCap: number;
  recordCap: number;
  wallClockCapMs: number;
  idleTimeoutMs: number;
  perGrantConcurrency: number;
  retryAfterSeconds: number;
}

export interface ResumeCursor {
  signedOffset?: string;
  resumeToken?: string;
}

export interface MeteringSummary {
  bytes: number;
  rows: number;
  records: number;
  calls: number;
  durationMs: number;
  retries: number;
  providerLatencyMs: number;
  cacheState: string;
  connectorType: string;
  sellerEdgeRoute: string;
}

export interface InvokeRuntimeRequest {
  accessGrantId: string;
  buyerAccountId: string;
  listingId: string;
  listingVersionId: string;
  connectorId: string;
  deliveryMode: string;
  termsHash: string;
  operation: string;
  mode: "unary" | "stream";
  sellerEdgeIdentityHash?: string;
  resume?: ResumeCursor;
  limits: InvokeLimits;
}

export interface InvokeRuntimeResult {
  invocationId: string;
  state: InvokeState;
  metering: MeteringSummary;
  retryAfterSeconds?: number;
  resumeRequired: boolean;
  signedOffset?: string;
  resumeToken?: string;
}

export class InvokeRuntimeError extends Error {
  readonly state: InvokeState;
  readonly retryAfterSeconds?: number;

  constructor(state: InvokeState, message: string, retryAfterSeconds?: number) {
    super(message);
    this.state = state;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

export class ConnectorRuntime {
  private readonly activePerGrant = new Map<string, number>();

  async invoke(
    request: InvokeRuntimeRequest,
    grant: RuntimeGrantBinding,
    provider: AsyncIterable<Uint8Array>,
    options: { resumeSupported?: boolean; trustRevoked?: boolean; grantRevoked?: boolean; now?: Date } = {},
  ): Promise<InvokeRuntimeResult> {
    this.validateGrantBinding(request, grant, options.now ?? new Date());
    if (options.trustRevoked) {
      throw new InvokeRuntimeError("trust_revoked_mid_stream", "trust revoked mid stream");
    }
    if (options.grantRevoked) {
      throw new InvokeRuntimeError("grant_revoked_mid_stream", "grant revoked mid stream");
    }
    if (request.resume && !(request.resume.signedOffset || request.resume.resumeToken)) {
      throw new InvokeRuntimeError("resume_unsupported", "stream resume requires signed offset or resume token");
    }
    if (request.resume && options.resumeSupported === false) {
      throw new InvokeRuntimeError("resume_unsupported", "connector does not support resume");
    }

    const active = this.activePerGrant.get(request.accessGrantId) ?? 0;
    if (active >= request.limits.perGrantConcurrency) {
      throw new InvokeRuntimeError("failed", "per_grant concurrency exceeded", request.limits.retryAfterSeconds);
    }

    this.activePerGrant.set(request.accessGrantId, active + 1);
    try {
      const started = Date.now();
      let bytes = 0;
      let records = 0;
      for await (const chunk of provider) {
        bytes += chunk.byteLength;
        records += 1;
        if (bytes > request.limits.byteCap || records > request.limits.recordCap) {
          throw new InvokeRuntimeError("partial_transfer", "invoke cap exceeded");
        }
        if (Date.now() - started > request.limits.wallClockCapMs) {
          throw new InvokeRuntimeError("provider_timeout", "wall-clock cap exceeded");
        }
      }
      return {
        invocationId: stableInvocationId(request),
        state: "completed",
        metering: {
          bytes,
          rows: 0,
          records,
          calls: 1,
          durationMs: Date.now() - started,
          retries: request.resume ? 1 : 0,
          providerLatencyMs: Date.now() - started,
          cacheState: "unknown",
          connectorType: request.connectorId,
          sellerEdgeRoute: request.sellerEdgeIdentityHash ?? "local",
        },
        resumeRequired: request.mode === "stream",
        signedOffset: request.resume?.signedOffset,
        resumeToken: request.resume?.resumeToken,
      };
    } finally {
      this.activePerGrant.set(request.accessGrantId, active);
    }
  }

  validateGrantBinding(request: InvokeRuntimeRequest, grant: RuntimeGrantBinding, now: Date): void {
    if (grant.state !== "active" || Date.parse(grant.expiresAt) <= now.getTime()) {
      throw new InvokeRuntimeError("failed", "active unexpired grant required");
    }
    const checks: Array<[boolean, string]> = [
      [request.accessGrantId === grant.accessGrantId, "access_grant_id"],
      [request.buyerAccountId === grant.buyerAccountId, "buyer_account_id"],
      [request.listingId === grant.listingId, "listing_id"],
      [request.listingVersionId === grant.listingVersionId, "listing_version_id"],
      [request.connectorId === grant.connectorId, "connector_id"],
      [request.deliveryMode === grant.deliveryMode, "delivery_mode"],
      [request.termsHash === grant.termsHash, "terms_hash"],
      [grant.operations.includes(request.operation), "operation"],
      [
        !grant.sellerEdgeIdentityHash || request.sellerEdgeIdentityHash === grant.sellerEdgeIdentityHash,
        "seller_edge_identity_hash",
      ],
    ];
    const failed = checks.find(([ok]) => !ok);
    if (failed) {
      throw new InvokeRuntimeError("failed", `grant binding mismatch: ${failed[1]}`);
    }
  }
}

function stableInvocationId(request: InvokeRuntimeRequest): string {
  return `inv_${request.accessGrantId}_${request.operation}`.replace(/[^A-Za-z0-9_]/g, "_");
}
