/** Per-aggregate version reconciliation, not a fictitious global commit cursor. */
export interface Delta {
  schema_version: number;
  aggregate_id: string;
  aggregate_version: number;
  event_type: string;
}

export type LiveStatus = "connecting" | "ready" | "reconnecting" | "stale";

export class SnapshotGate {
  private versions = new Map<string, number>();
  private buffered: Delta[] = [];
  private snapshotReady = false;
  private requireSnapshot: () => void;
  private onGap: () => void;

  constructor(requireSnapshot: () => void, onGap = requireSnapshot) {
    this.requireSnapshot = requireSnapshot;
    this.onGap = onGap;
  }

  reconnect(): void {
    this.versions.clear();
    this.buffered = [];
    this.snapshotReady = false;
    this.onGap();
  }

  snapshot(versions: Record<string, number>): void {
    this.versions = new Map(Object.entries(versions));
    this.snapshotReady = true;
    const pending = this.buffered;
    this.buffered = [];
    for (const delta of pending) {
      this.receive(delta);
      if (!this.snapshotReady) break;
    }
  }

  receive(delta: Delta): void {
    if (
      delta.schema_version !== 1 ||
      typeof delta.aggregate_id !== "string" ||
      !delta.aggregate_id ||
      !Number.isSafeInteger(delta.aggregate_version) ||
      delta.aggregate_version < 1
    ) {
      this.reconnect();
      return;
    }
    if (!this.snapshotReady) {
      if (this.buffered.length >= 256) {
        this.reconnect();
        return;
      }
      this.buffered.push(delta);
      return;
    }
    const current = this.versions.get(delta.aggregate_id);
    if (current === undefined || delta.aggregate_version > current + 1) {
      this.reconnect();
      return;
    }
    if (delta.aggregate_version <= current) return;
    this.versions.set(delta.aggregate_id, delta.aggregate_version);
    // We purposely invalidate data rather than synthesizing a price from SSE metadata.
    this.requireSnapshot();
  }
}
