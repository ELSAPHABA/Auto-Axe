import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getAuthorizedSnapshot, hasAuthorizedSession } from "./api";
import { SnapshotGate, type Delta, type LiveStatus } from "./live";

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
    const connect = () => {
      if (disposed) return;
      try {
        source = new EventSource("/api/v1/dashboard/authorized/stream", {
          withCredentials: true,
        });
      } catch {
        setStatus("stale");
        return; // polling fallback remains active
      }
      source.addEventListener("ready", () => {
        gate = newGate();
        void synchronize();
      });
      source.addEventListener("market.invalidate", (event) => {
        try {
          const delta = JSON.parse(
            (event as MessageEvent<string>).data,
          ) as Delta;
          if (delta.event_type !== "market.observation.recorded")
            throw new Error("invalid event");
          gate.receive(delta);
        } catch {
          gate.reconnect();
        }
      });
      source.addEventListener("market.refresh", coalesce);
      source.addEventListener("resync", () => {
        generation += 1;
        gate = newGate();
        source?.close();
        setStatus("reconnecting");
        purge();
        void client.invalidateQueries({ queryKey: ["auth", "session"] });
        timer = window.setTimeout(connect, 3000);
      });
      source.onerror = () => {
        generation += 1;
        gate = newGate();
        setStatus("reconnecting");
        purge();
        void client.invalidateQueries({ queryKey: ["auth", "session"] });
      };
    };
    connect();
    const fallback = window.setInterval(refresh, 15_000);
    return () => {
      disposed = true;
      generation += 1;
      source?.close();
      if (timer !== undefined) window.clearTimeout(timer);
      if (refreshTimer !== undefined) window.clearTimeout(refreshTimer);
      window.clearInterval(fallback);
    };
  }, [authenticated, client]);
  return authenticated ? status : "stale";
}
