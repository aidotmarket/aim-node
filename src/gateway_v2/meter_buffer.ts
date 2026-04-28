import type { MeterEvent, MeterRecordRequest } from "./meter";

export type MeterBufferState = "open" | "buffering" | "degraded" | "fail_closed";
export type MeterBufferErrorCode = "METERING_REJECTED";

export interface MeterBufferPolicy {
  thresholdEvents: number;
  maxEvents: number;
  drainDeadlineMs: number;
  failClosedPolicy: "fail_closed";
}

export interface MeterBufferObservability {
  spans: Array<Record<string, unknown>>;
  metrics: Array<Record<string, unknown>>;
}

export class MeterBufferError extends Error {
  readonly code: MeterBufferErrorCode;
  readonly state: MeterBufferState;

  constructor(message: string, state: MeterBufferState) {
    super(message);
    this.code = "METERING_REJECTED";
    this.state = state;
  }
}

export class LocalMeterBuffer {
  readonly policy: MeterBufferPolicy;
  readonly observability: MeterBufferObservability;
  private readonly queue: MeterRecordRequest[] = [];
  private stateValue: MeterBufferState = "open";
  private deadlineStartedAt: number | undefined;
  private dropped = 0;

  constructor(policy: Partial<MeterBufferPolicy> = {}, observability?: MeterBufferObservability) {
    this.policy = {
      thresholdEvents: policy.thresholdEvents ?? 100,
      maxEvents: policy.maxEvents ?? 10_000,
      drainDeadlineMs: policy.drainDeadlineMs ?? 300_000,
      failClosedPolicy: "fail_closed",
    };
    this.observability = observability ?? { spans: [], metrics: [] };
  }

  get state(): MeterBufferState {
    return this.stateValue;
  }

  get depth(): number {
    return this.queue.length;
  }

  get droppedEvents(): number {
    return this.dropped;
  }

  enqueue(request: MeterRecordRequest, nowMs = Date.now()): void {
    if (this.stateValue === "degraded" || this.stateValue === "fail_closed") {
      this.rejected("degraded", nowMs);
      throw new MeterBufferError("METERING_REJECTED: local meter buffer is degraded", this.stateValue);
    }
    if (this.deadlineStartedAt !== undefined && nowMs - this.deadlineStartedAt > this.policy.drainDeadlineMs) {
      this.stateValue = "fail_closed";
      this.rejected("drain_deadline_missed", nowMs);
      throw new MeterBufferError("METERING_REJECTED: meter_buffer drain deadline missed", "fail_closed");
    }
    if (this.queue.length >= this.policy.maxEvents) {
      this.stateValue = "fail_closed";
      this.dropped += 1;
      this.rejected("max_depth", nowMs);
      throw new MeterBufferError("METERING_REJECTED: meter_buffer max depth reached", "fail_closed");
    }

    this.queue.push(request);
    if (this.queue.length >= this.policy.thresholdEvents) {
      this.stateValue = "buffering";
      this.deadlineStartedAt ??= nowMs;
    }
    this.emitDepth();
  }

  async drain(send: (request: MeterRecordRequest) => Promise<MeterEvent>, nowMs = Date.now()): Promise<MeterEvent[]> {
    if (this.stateValue === "fail_closed" || this.stateValue === "degraded") {
      this.rejected("drain_blocked", nowMs);
      throw new MeterBufferError("METERING_REJECTED: meter_buffer cannot drain while fail-closed", this.stateValue);
    }
    const accepted: MeterEvent[] = [];
    while (this.queue.length > 0) {
      const request = this.queue.shift() as MeterRecordRequest;
      accepted.push(await send(request));
      this.emitDepth();
    }
    this.stateValue = "open";
    this.deadlineStartedAt = undefined;
    return accepted;
  }

  markDegraded(reason: string): void {
    this.stateValue = "degraded";
    this.observability.spans.push({ name: "gateway.meter_buffer.degraded", attributes: { reason, redacted_fields: ["payload"] } });
  }

  private emitDepth(): void {
    this.observability.metrics.push({
      name: "gateway.meter_buffer.depth",
      value: this.queue.length,
      attributes: { state: this.stateValue, redacted_fields: ["payload"] },
    });
  }

  private rejected(reason: string, nowMs: number): void {
    this.observability.spans.push({
      name: "gateway.meter_buffer.rejected",
      attributes: { reason, state: this.stateValue, now_ms: nowMs, redacted_fields: ["payload"] },
    });
    this.observability.metrics.push({
      name: "gateway.meter_buffer.rejected.count",
      value: 1,
      attributes: { reason, state: this.stateValue, dropped_events: this.dropped, redacted_fields: ["payload"] },
    });
  }
}
