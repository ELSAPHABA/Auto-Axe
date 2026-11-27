import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getAuthorizedSnapshot, hasAuthorizedSession } from "./api";
import type { LiveStatus } from "./live";

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
// The server sends coalesced invalidations only. Every change/reconnect reads
// a fresh committed REST snapshot (no fabricated sequence or price delta).
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
        const attempt = ++generation;
        setStatus("reconnecting");
        // Always re-read REST after readiness, even if deltas arrived already.
        void client
          .fetchQuery({
            queryKey: ["authorized", "snapshot", "market_read"],
            queryFn: getAuthorizedSnapshot,
            staleTime: 0,
          })
          .then(() => {
            if (!disposed && generation === attempt) setStatus("ready");
          })
          .catch(() => {
            if (!disposed && generation === attempt) setStatus("stale");
          });
        refresh();
      });
      source.addEventListener("market.invalidate", () => refresh());
      source.addEventListener("resync", () => {
        generation += 1;
        source?.close();
        setStatus("reconnecting");
        purge();
        void client.invalidateQueries({ queryKey: ["auth", "session"] });
        timer = window.setTimeout(connect, 3000);
      });
      source.onerror = () => {
        generation += 1;
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
      window.clearInterval(fallback);
    };
  }, [authenticated, client]);
  return authenticated ? status : "stale";
}
