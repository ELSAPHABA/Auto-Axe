import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import {
  useInfiniteQuery,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { Link, useParams } from "react-router";
import { getDashboardPage, getHealth, type IndicatorView } from "./api";
import { SnapshotGate, type Delta, type LiveStatus } from "./live";
import { useUi, type RatioKind } from "./store";

const FixtureChart = lazy(() =>
  import("./fixture-chart").then((item) => ({ default: item.FixtureChart })),
);

const CATEGORIES = [
  { id: "market", title: "시장", description: "가격·변동성·선물" },
  { id: "equities", title: "주식 / ETF", description: "재무·거래량·기술지표" },
  { id: "macro", title: "경제 지표", description: "경기·물가·고용" },
  { id: "rates", title: "기준금리", description: "중앙은행 정책" },
  { id: "calendar", title: "일정 / 공시", description: "발표·만기·가이던스" },
  { id: "sentiment", title: "심리", description: "Fear & Greed · Pizza" },
  { id: "industry", title: "산업", description: "DRAM · 해외주식 결제" },
  { id: "manual", title: "수동 입력", description: "허용된 수동 관측" },
] as const;

const RATIO_LABELS: Record<RatioKind, string> = {
  global_accounts: "전체 계정",
  top_accounts: "상위 계정",
  top_positions: "상위 포지션",
  taker_volume: "Taker 매수·매도 거래량",
};

function useDashboard(category?: string) {
  return useInfiniteQuery({
    queryKey: ["dashboard", "fixture", category ?? "all"],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      getDashboardPage({ category, cursor: pageParam }),
    getNextPageParam: (last) => last.meta.next_cursor,
    retry: false,
    staleTime: 10_000,
  });
}

function useFixtureStream(): LiveStatus {
  const [status, setStatus] = useState<LiveStatus>("connecting");
  const query = useQueryClient();
  useEffect(() => {
    let disposed = false;
    let generation = 0;
    let ready = false;
    const refresh = () => {
      void query.invalidateQueries({ queryKey: ["dashboard"] });
    };
    // During SSE outage, GET remains the authoritative fallback, not cached SSE values.
    const fallback = window.setInterval(() => {
      if (!ready && !disposed) refresh();
    }, 15_000);
    const gate = new SnapshotGate(refresh);
    const synchronize = async () => {
      const myGeneration = ++generation;
      ready = false;
      setStatus("reconnecting");
      gate.reconnect();
      try {
        const snapshot = await getDashboardPage();
        if (disposed || myGeneration !== generation) return;
        gate.snapshot({ dashboard: snapshot.meta.version });
        ready = true;
        setStatus("ready");
      } catch {
        if (!disposed && myGeneration === generation) {
          ready = false;
          setStatus("stale");
        }
      }
    };
    let stream: EventSource;
    try {
      stream = new EventSource("/api/v1/dashboard/stream", {
        withCredentials: true,
      });
    } catch {
      setStatus("stale");
      return () => window.clearInterval(fallback);
    }
    stream.addEventListener("ready", () => {
      void synchronize();
    });
    stream.addEventListener("market.invalidate", (event) => {
      try {
        gate.receive(JSON.parse((event as MessageEvent<string>).data) as Delta);
        if (!disposed) void synchronize();
      } catch {
        gate.reconnect();
        setStatus("stale");
      }
    });
    stream.onerror = () => {
      generation += 1;
      ready = false;
      setStatus("reconnecting");
      gate.reconnect();
    };
    return () => {
      disposed = true;
      generation += 1;
      window.clearInterval(fallback);
      stream.close();
    };
  }, [query]);
  return status;
}

function DataStatus({ row }: { row: IndicatorView }) {
  const fixture = row.quality === "synthetic_fixture";
  return (
    <span className={"data-status " + (fixture ? "data-status-fixture" : "")}>
      <span aria-hidden="true" className="status-dot" />
      {fixture ? "합성 데이터" : "수집 권한 미확인"}
    </span>
  );
}

function IndicatorCard({ row }: { row: IndicatorView }) {
  return (
    <article className="indicator-card" aria-label={row.label}>
      <div className="indicator-card-top">
        <span className="indicator-source">{row.source_id}</span>
        <DataStatus row={row} />
      </div>
      <h3 title={row.label}>{row.label}</h3>
      <div className="indicator-value">
        {row.value !== null ? row.value : "—"}
        <span>{row.value !== null ? row.unit : "데이터 없음"}</span>
      </div>
      <p className="indicator-note">{row.source_note || row.cadence}</p>
      <span className="indicator-frequency">{row.cadence}</span>
    </article>
  );
}

export function RatioPanel({ rows }: { rows: IndicatorView[] }) {
  const { showRatios, ratioKind, toggleRatios, setRatioKind } = useUi();
  const ratioRows = rows.filter(
    (r) =>
      r.indicator_id.startsWith("BINANCE_") &&
      r.indicator_id.includes(ratioKind.toUpperCase()),
  );
  return (
    <section className="panel" aria-label="롱숏 비율">
      <div className="panel-header">
        <div>
          <p className="eyebrow">DERIVATIVES</p>
          <h2>글로벌 롱·숏 비율</h2>
          <p className="subline">
            최소 5분 집계 · BTC 가격은 Spot / 비율은 Futures
          </p>
        </div>
        <label className="toggle">
          <input type="checkbox" checked={showRatios} onChange={toggleRatios} />
          비율 패널 {showRatios ? "ON" : "OFF"}
        </label>
      </div>
      {showRatios ? (
        <>
          <div
            className="segment-tabs"
            role="group"
            aria-label="롱숏 집계 종류"
          >
            {(Object.keys(RATIO_LABELS) as RatioKind[]).map((kind) => (
              <button
                className={ratioKind === kind ? "active" : ""}
                key={kind}
                onClick={() => setRatioKind(kind)}
                aria-pressed={ratioKind === kind}
              >
                {RATIO_LABELS[kind]}
              </button>
            ))}
          </div>
          <div className="ratio-grid">
            {ratioRows.map((row) => (
              <div className="ratio-card" key={row.indicator_id}>
                <div>
                  <strong>{row.indicator_id.split("_").slice(-1)[0]}</strong>
                  <span>확인된 비율 없음</span>
                </div>
                <div
                  className="ratio-track"
                  aria-label="Long/Short 비율 데이터 없음"
                />
                <div className="ratio-footer">
                  <span>LONG —</span>
                  <span>SHORT —</span>
                </div>
              </div>
            ))}
          </div>
          {ratioKind === "taker_volume" && (
            <p className="subline">
              Taker는 매수·매도 거래량 비율이며 보유 포지션 비율이 아닙니다.
            </p>
          )}
        </>
      ) : (
        <p className="panel-empty">
          비율 패널을 켜면 네 종류의 집계 데이터를 확인할 수 있습니다.
        </p>
      )}
    </section>
  );
}

function StreamBadge({ status }: { status: LiveStatus }) {
  return (
    <span className="stream-badge">
      <span className="status-dot" />
      {status === "ready"
        ? "Fixture 연결됨"
        : status === "reconnecting"
          ? "재연결 · 재동기화"
          : status === "stale"
            ? "연결 상태 미확인"
            : "연결 중"}
    </span>
  );
}

function SummaryStrip({ total }: { total: number }) {
  return (
    <div className="summary-strip">
      <div>
        <span>등록 지표</span>
        <strong>{total || "—"}</strong>
        <small>자동 수집 보장 아님</small>
      </div>
      <div>
        <span>실제 시장 시세</span>
        <strong>—</strong>
        <small>승인 전 비활성</small>
      </div>
      <div>
        <span>자동 거래</span>
        <strong>OFF</strong>
        <small>주문·외부 MCP 차단</small>
      </div>
      <div>
        <span>시스템 모드</span>
        <strong>FIXTURE</strong>
        <small>합성 데이터 전용</small>
      </div>
    </div>
  );
}

function MarketThermometer() {
  return (
    <section className="panel thermometer-panel" aria-label="시장 온도계">
      <div>
        <p className="eyebrow">MARKET SENTIMENT</p>
        <h2>시장 온도계</h2>
        <p className="subline">CNN Fear &amp; Greed · 검증된 수집 근거 필요</p>
      </div>
      <div className="thermometer-content">
        <span className="thermometer-value">—</span>
        <div>
          <div
            className="thermometer-track"
            aria-label="확인된 심리 지표 없음"
          />
          <div className="thermometer-legend">
            <span>EXTREME FEAR</span>
            <span>NEUTRAL</span>
            <span>EXTREME GREED</span>
          </div>
        </div>
      </div>
      <p className="indicator-note">
        실제 지표 수집 권한이 확인되기 전에는 점수와 포인터를 표시하지 않습니다.
      </p>
    </section>
  );
}

export function DashboardHome() {
  const health = useQuery({
    queryKey: ["health"],
    queryFn: getHealth,
    retry: false,
  });
  const dashboard = useDashboard();
  const stream = useFixtureStream();
  const data = useMemo(
    () => dashboard.data?.pages.flatMap((p) => p.data) ?? [],
    [dashboard.data],
  );
  const fixture = data.find((row) => row.indicator_id === "FIXTURE_PRICE");
  return (
    <div className="dashboard-view">
      <div className="page-heading">
        <div>
          <p className="eyebrow">AUTO-AXE / MARKET OVERVIEW</p>
          <h1>시장 대시보드</h1>
          <p>실시간 금융 데이터가 아닌 합성 Fixture 기반 개발 화면입니다.</p>
        </div>
        <StreamBadge status={stream} />
      </div>
      <SummaryStrip total={data.length} />
      <MarketThermometer />
      {health.isError && (
        <p className="error" role="alert">
          개발 API 연결 상태를 확인할 수 없습니다.
        </p>
      )}
      {dashboard.isError && (
        <p className="error" role="alert">
          지표를 불러오지 못했습니다. 다시 연결하거나 새로고침하세요.
        </p>
      )}
      <section className="section-block">
        <div className="section-title">
          <div>
            <p className="eyebrow">WATCHLIST</p>
            <h2>주요 시세</h2>
          </div>
          <Link to="/indicators">전체 지표 보기</Link>
        </div>
        <div className="quote-grid">
          {[
            "BITCOIN_BINANCE_SPOT",
            "GOLD_BINANCE_PERP",
            "WTI_BINANCE_PERP",
            "NASDAQ100_MEXC_PERP_USDT",
          ].map((id) => {
            const row = data.find((item) => item.indicator_id === id);
            return row ? <IndicatorCard key={id} row={row} /> : null;
          })}
        </div>
      </section>
      <RatioPanel rows={data} />
      <section className="section-block">
        <div className="section-title">
          <div>
            <p className="eyebrow">DEVELOPMENT</p>
            <h2>합성 검증 값</h2>
          </div>
        </div>
        {fixture && (
          <div className="fixture-panel">
            <IndicatorCard row={fixture} />
            <p>
              합성 가격 123.45는 API 및 UI 데이터 계약 검증용입니다. 실거래
              시세로 사용하지 않습니다.
            </p>
          </div>
        )}
        {fixture && (
          <Suspense fallback={<p role="status">합성 차트 로딩 중…</p>}>
            <FixtureChart />
          </Suspense>
        )}
      </section>
      {dashboard.hasNextPage && (
        <button
          className="outline-button"
          onClick={() => {
            void dashboard.fetchNextPage();
          }}
        >
          지표 더 가져오기
        </button>
      )}
    </div>
  );
}

export function IndicatorsPage() {
  const [category, setCategory] = useState<string | undefined>();
  const dashboard = useDashboard(category);
  const data = dashboard.data?.pages.flatMap((p) => p.data) ?? [];
  return (
    <div className="dashboard-view">
      <div className="page-heading">
        <div>
          <p className="eyebrow">DATA CATALOG</p>
          <h1>지표 탐색</h1>
          <p>권한이 확인되지 않은 수집기는 값 대신 데이터 상태를 표시합니다.</p>
        </div>
      </div>
      <div className="category-list" role="group" aria-label="지표 카테고리">
        <button
          className={!category ? "selected" : ""}
          onClick={() => setCategory(undefined)}
        >
          전체
        </button>
        {CATEGORIES.map(({ id, title }) => (
          <button
            className={category === id ? "selected" : ""}
            key={id}
            onClick={() => setCategory(id)}
          >
            {title}
          </button>
        ))}
      </div>
      {dashboard.isError && (
        <p className="error" role="alert">
          지표 목록을 불러오지 못했습니다.
        </p>
      )}
      {dashboard.isPending && <p role="status">데이터 조회 중...</p>}
      <div className="indicator-grid">
        {data.map((row) => (
          <IndicatorCard key={row.indicator_id} row={row} />
        ))}
      </div>
      {dashboard.hasNextPage && (
        <button
          className="outline-button"
          onClick={() => {
            void dashboard.fetchNextPage();
          }}
        >
          더 보기
        </button>
      )}
    </div>
  );
}

export function MarketDetailPage() {
  const { instrumentId } = useParams();
  const dashboard = useDashboard();
  const data = dashboard.data?.pages.flatMap((p) => p.data) ?? [];
  const selected = data.find((row) => row.indicator_id === instrumentId);
  return (
    <div className="dashboard-view">
      <div className="page-heading">
        <div>
          <p className="eyebrow">MARKET DETAILS</p>
          <h1>{selected?.label ?? instrumentId}</h1>
          <p>시장 원본·계약·원본 시각 및 품질 상태를 분리하여 표시합니다.</p>
        </div>
        <Link className="outline-button" to="/">
          대시보드
        </Link>
      </div>
      {selected && (
        <div className="indicator-grid">
          <IndicatorCard row={selected} />
        </div>
      )}
      <div className="panel">
        <p className="eyebrow">PRICE HISTORY</p>
        <h2>시계열 차트</h2>
        {selected?.source_id === "fixture" ? (
          <Suspense fallback={<p>합성 차트 로딩 중…</p>}>
            <FixtureChart />
          </Suspense>
        ) : (
          <p className="panel-empty">
            해당 시계열의 검증된 가격 봉이 없습니다. 실제 차트로 위장하지
            않습니다.
          </p>
        )}
      </div>
      <RatioPanel rows={data} />
    </div>
  );
}
