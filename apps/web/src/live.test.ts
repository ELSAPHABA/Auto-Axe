import { expect, test, vi } from "vitest";
import { SnapshotGate } from "./live";

test("snapshot consumes buffered contiguous version and ignores replay", () => {
  const refresh = vi.fn();
  const gate = new SnapshotGate(refresh);
  gate.receive({
    schema_version: 1,
    aggregate_id: "fixture",
    aggregate_version: 2,
    event_type: "market.observation.recorded",
  });
  expect(refresh).not.toHaveBeenCalled();
  gate.snapshot({ fixture: 1 });
  expect(refresh).toHaveBeenCalledTimes(1);
  gate.receive({
    schema_version: 1,
    aggregate_id: "fixture",
    aggregate_version: 2,
    event_type: "market.observation.recorded",
  });
  expect(refresh).toHaveBeenCalledTimes(1);
});

test("unknown aggregate, gap, unsupported version and reconnect force REST resync", () => {
  const refresh = vi.fn();
  const gate = new SnapshotGate(refresh);
  gate.snapshot({ fixture: 1 });
  gate.receive({
    schema_version: 1,
    aggregate_id: "other",
    aggregate_version: 2,
    event_type: "market.observation.recorded",
  });
  expect(refresh).toHaveBeenCalledTimes(1);
  gate.snapshot({ fixture: 1 });
  gate.receive({
    schema_version: 1,
    aggregate_id: "fixture",
    aggregate_version: 4,
    event_type: "market.observation.recorded",
  });
  expect(refresh).toHaveBeenCalledTimes(2);
  gate.snapshot({ fixture: 4 });
  gate.receive({
    schema_version: 99,
    aggregate_id: "fixture",
    aggregate_version: 5,
    event_type: "unknown",
  });
  expect(refresh).toHaveBeenCalledTimes(3);
  gate.reconnect();
  expect(refresh).toHaveBeenCalledTimes(4);
});

test("buffer overflow and invalid deltas require a fresh snapshot, never replay partial data", () => {
  const refresh = vi.fn();
  const gap = vi.fn();
  const gate = new SnapshotGate(refresh, gap);
  const event = {
    schema_version: 1,
    aggregate_id: "VIX",
    aggregate_version: 2,
    event_type: "market.observation.recorded",
  };
  for (let i = 0; i < 257; i++)
    gate.receive({ ...event, aggregate_version: i + 1 });
  expect(gap).toHaveBeenCalledTimes(1);
  expect(refresh).not.toHaveBeenCalled();
  gate.snapshot({ VIX: 257 });
  gate.receive({ ...event, aggregate_version: 258 });
  gate.receive({ ...event, aggregate_version: 258 });
  expect(refresh).toHaveBeenCalledTimes(1);
  gate.receive({ ...event, aggregate_version: -1 });
  expect(gap).toHaveBeenCalledTimes(2);
});
