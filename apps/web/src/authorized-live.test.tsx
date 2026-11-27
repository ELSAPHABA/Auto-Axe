import { act, cleanup, renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { marketEvent, useAuthorizedStream } from "./authorized-live";

const envelope = { schema_version: 1, mode: "market_read" };

class SyntheticStream extends EventTarget {
  static instances: SyntheticStream[] = [];
  close = vi.fn();
  onerror: (() => void) | null = null;

  constructor() {
    super();
    SyntheticStream.instances.push(this);
  }

  emit(name: string, payload: object = envelope) {
    this.dispatchEvent(
      new MessageEvent(name, { data: JSON.stringify(payload) }),
    );
  }
}

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  SyntheticStream.instances = [];
});

test("market envelopes reject unsupported mode, schema, and malformed JSON", () => {
  expect(
    marketEvent(new MessageEvent("ready", { data: JSON.stringify(envelope) })),
  ).toEqual(envelope);
  for (const data of [
    "null",
    "{",
    "{}",
    JSON.stringify({ ...envelope, mode: "LIVE" }),
    JSON.stringify({ ...envelope, schema_version: 2 }),
  ]) {
    expect(() => marketEvent(new MessageEvent("ready", { data }))).toThrow();
  }
});

test("heartbeat timeout closes stale stream, reopens once, ignores old messages", async () => {
  vi.useFakeTimers();
  vi.stubGlobal("EventSource", SyntheticStream);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => ({
      ok: true,
      json: async () =>
        url.includes("/auth/session")
          ? { meta: { authenticated: true } }
          : { data: [], meta: { ...envelope, versions: {} } },
    })),
  );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  client.setQueryData(["auth", "session"], true);
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
  }
  const hook = renderHook(() => useAuthorizedStream(), { wrapper: Wrapper });
  const advance = async (ms: number) =>
    act(async () => {
      await vi.advanceTimersByTimeAsync(ms);
    });
  await advance(1);
  const first = SyntheticStream.instances[0];
  if (!first) throw new Error("expected first stream");
  await act(async () => first.emit("ready"));
  await advance(10);
  expect(hook.result.current).toBe("ready");
  await advance(10_000);
  await act(async () => first.emit("heartbeat"));
  await advance(14_900);
  expect(first.close).not.toHaveBeenCalled();
  await advance(200);
  expect(first.close).toHaveBeenCalledTimes(1);
  expect(hook.result.current).toBe("reconnecting");
  await advance(3_001);
  expect(SyntheticStream.instances).toHaveLength(2);
  const second = SyntheticStream.instances[1];
  if (!second) throw new Error("expected second stream");
  await act(async () => first.emit("ready"));
  expect(second.close).not.toHaveBeenCalled();
  await act(async () => second.emit("ready", { ...envelope, mode: "LIVE" }));
  expect(second.close).toHaveBeenCalledTimes(1);
  await advance(5_999);
  expect(SyntheticStream.instances).toHaveLength(2);
  await advance(2);
  expect(SyntheticStream.instances).toHaveLength(3);
  hook.unmount();
  await advance(60_000);
  expect(SyntheticStream.instances).toHaveLength(3);
  client.clear();
});
