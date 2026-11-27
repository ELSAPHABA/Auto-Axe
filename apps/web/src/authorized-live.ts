import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getAuthorizedSnapshot, hasAuthorizedSession } from "./api";
import { SnapshotGate, type Delta, type LiveStatus } from "./live";

export function marketEvent(event: Event): Record<string, unknown> {
  const payload: unknown = JSON.parse((event as MessageEvent<string>).data);
  if (
    !payload ||
    typeof payload !== "object" ||
    !("schema_version" in payload) ||
    payload.schema_version !== 1 ||
    !("mode" in payload) ||
    payload.mode !== "market_read"
  ) {
    throw new Error("invalid market stream envelope");
  }
  return payload as Record<string, unknown>;
}

export function useAuthorizedSession() {
  return useQuery({
    queryKey: ["auth", "session"],
    queryFn: hasAuthorizedSession,
    retry: false,
    refetchInterval: 10_000,
  });
}

export function useAuthorizedSnapshot() {
  const session = useAuthorizedSession();
  const authenticated = session.data === true && !session.isError;
  const snapshot = useQuery({
    queryKey: ["authorized", "snapshot", "market_read"],
    queryFn: getAuthorizedSnapshot,
    enabled: authenticated,
    retry: false,
    refetchInterval: 15_000,
  });
  return authenticated && !snapshot.isError ? snapshot.data : undefined;
}

// One subscription for the application shell, including route changes.
// Replay metadata is versioned per series; REST is the sole value authority.
export function useAuthorizedStream(): LiveStatus {
  const session = useAuthorizedSession();
  const authenticated = session.data === true && !session.isError;
  const client = useQueryClient();
  const [status, setStatus] = useState<LiveStatus>("connecting");
  useEffect(() => {
    const purge = () => {
      void client.resetQueries({ queryKey: ["authorized"] });
      void client.resetQueries({ queryKey: ["official-events"] });
    };
    const refresh = () => {
      void client.invalidateQueries({ queryKey: ["authorized"] });
      void client.invalidateQueries({ queryKey: ["official-events"] });
    };
    if (!authenticated) {
      client.removeQueries({ queryKey: ["authorized"] });
      client.removeQueries({ queryKey: ["official-events"] });
      return;
    }
    let disposed = false;
    let source: EventSource | undefined;
    let timer: number | undefined;
    let generation = 0;
    let refreshTimer: number | undefined;
    let heartbeatTimer: number | undefined;
    let failures = 0;
    const coalesce = () => {
      if (refreshTimer !== undefined) return;
      refreshTimer = window.setTimeout(() => {
        refreshTimer = undefined;
        if (!disposed) refresh();
      }, 100);
    };
    const synchronize = async () => {
      const attempt = ++generation;
      setStatus("reconnecting");
      try {
        await client.cancelQueries({ queryKey: ["authorized", "snapshot"] });
        if (disposed || generation !== attempt) return;
        const snapshot = await client.fetchQuery({
          queryKey: ["authorized", "snapshot", "market_read"],
          queryFn: getAuthorizedSnapshot,
          staleTime: 0,
        });
        if (!disposed && generation === attempt) {
          gate.snapshot(snapshot.meta.versions);
          if (generation === attempt) setStatus("ready");
          coalesce();
        }
      } catch {
        if (!disposed && generation === attempt) setStatus("stale");
      }
    };
    const newGate = () =>
      new SnapshotGate(coalesce, () => {
        void synchronize();
      });
    let gate = newGate();
    const disconnect = (current: EventSource) => {
      if (disposed || source !== current) return;
      generation += 1;
      source = undefined;
      current.close();
      gate = newGate();
      if (heartbeatTimer !== undefined) window.clearTimeout(heartbeatTimer);
      if (refreshTimer !== undefined) {
        window.clearTimeout(refreshTimer);
        refreshTimer = undefined;
      }
      setStatus("reconnecting");
      purge();
      void client.invalidateQueries({ queryKey: ["auth", "session"] });
      failures = Math.min(failures + 1, 5);
      timer = window.setTimeout(
        connect,
        Math.min(30_000, 3000 * 2 ** (failures - 1)),
      );
    };
    const connect = () => {
      if (disposed) return;
      let current: EventSource;
      try {
        current = new EventSource("/api/v1/dashboard/authorized/stream", {
          withCredentials: true,
        });
        source = current;
      } catch {
        setStatus("stale");
        return; // polling fallback remains active
      }
      let ready = false;
      const watchdog = () => {
        if (heartbeatTimer !== undefined) window.clearTimeout(heartbeatTimer);
        heartbeatTimer = window.setTimeout(() => disconnect(current), 15_000);
      };
      const listen = (
        name: string,
        handler: (payload: Record<string, unknown>) => void,
      ) => {
        current.addEventListener(name, (event) => {
          if (disposed || source !== current) return;
          try {
            const payload = marketEvent(event);
            if (!ready && name !== "ready") throw new Error("ready required");
            handler(payload);
            watchdog();
          } catch {
            disconnect(current);
          }
        });
      };
      watchdog(); // includes a connection that never sends ready
      listen("ready", () => {
        if (ready) throw new Error("duplicate ready");
        ready = true;
        gate = newGate();
        void synchronize();
      });
      listen("market.invalidate", (payload) => {
        if (payload.event_type !== "market.observation.recorded")
          throw new Error("invalid event");
        gate.receive(payload as unknown as Delta);
      });
      listen("market.refresh", coalesce);
      listen("heartbeat", () => {
        failures = 0; // only a confirmed healthy stream resets the delay
      });
      current.addEventListener("resync", () => disconnect(current));
      current.onerror = () => disconnect(current);
    };
    connect();
    const fallback = window.setInterval(refresh, 15_000);
    return () => {
      disposed = true;
      generation += 1;
      source?.close();
      if (timer !== undefined) window.clearTimeout(timer);
      if (refreshTimer !== undefined) window.clearTimeout(refreshTimer);
      if (heartbeatTimer !== undefined) window.clearTimeout(heartbeatTimer);
      window.clearInterval(fallback);
    };
  }, [authenticated, client]);
  return authenticated ? status : "stale";
}
