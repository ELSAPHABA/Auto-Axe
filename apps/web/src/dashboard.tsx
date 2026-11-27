import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import {
  useInfiniteQuery,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { Link, useParams } from "react-router";
import {
  getApprovedMarketSeries,
  getDashboardPage,
  getHealth,
  getOfficialEvents,
  hasAuthorizedSession,
  type IndicatorView,
} from "./api";
import { useAuthorizedSnapshot } from "./authorized-live";
import { SnapshotGate, type Delta, type LiveStatus } from "./live";
import {
  CorporateGuidancePanel,
  ExpiryCalendarPanel,
  SeibroPanel,
} from "./reviewed-panels";
import { useUi, type RatioKind } from "./store";

const FixtureChart = lazy(() =>
  import("./fixture-chart").then((item) => ({ default: item.FixtureChart })),
);
const ApprovedChart = lazy(() =>
  import("./approved-chart").then((module) => ({
    default: module.ApprovedChart,
  })),
);

const CATEGORIES = [
  { id: "market", title: "시장", description: "가격·변동성·선물" },
  { id: "equities", title: "주식 / ETF", description: "재무·거래량·기술지표" },
  { id: "macro", title: "경제 지표", description: "경기·물가·고용" },
  { id: "rates", title: "기준금리", description: "중앙은행 정책" },
  { id: "calendar", title: "일정 / 공시", description: "발표·만기·가이던스" },
  { id: "sentiment", title: "심리", description: "Fear & Greed · DOUGHCON" },
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

function DoughconCard({ row }: { row: IndicatorView }) {
  const session = useQuery({
    queryKey: ["auth", "session"],
    queryFn: hasAuthorizedSession,
    retry: false,
    refetchInterval: 30_000,
  });
  const history = useQuery({
    queryKey: ["authorized", "history", row.indicator_id],
    queryFn: () => getApprovedMarketSeries(row.indicator_id),
    enabled: session.data === true && !session.isError,
    retry: false,
    refetchInterval: 30_000,
  });
  const point =
    session.data === true && !session.isError && !history.isError
      ? history.data?.data[0]
      : undefined;
  const level = point && /^[1-5]$/.test(point.value ?? "") ? point.value : null;
  const collectorStatus = history.data?.meta.collector_status;
  const checkedAt = history.data?.meta.collector_checked_at;
  const checkedRecently = checkedAt
    ? Date.parse(history.data?.meta.as_of ?? "") - Date.parse(checkedAt) <=
      660_000
    : false;
  const collecting =
    checkedRecently &&
    (collectorStatus === "healthy" || collectorStatus === "no_update");
  const statusText = level
    ? collecting
      ? "최근 저장값 · 참고용"
      : "이전 저장값 · 수집 상태 확인 필요"
    : "조회 가능한 데이터 없음";
  return (
    <article className="indicator-card" aria-label={row.label}>
      <div className="indicator-card-top">
        <span className="indicator-source">pizzint</span>
        <span className="data-status">{statusText}</span>
      </div>
      <h3>DOUGHCON</h3>
      <div className="indicator-value">{level ?? "—"}</div>
      <p className="indicator-note">
        {level && point?.source_event_at
          ? "API 시각 (UTC): " + point.source_event_at
          : "인증·데이터 제공 상태 확인 필요"}
      </p>
      <span className="indicator-frequency">
        5분 수집 · 금융 판단 및 자동 주문에 사용하지 않음
      </span>
    </article>
  );
}

function IndicatorCard({ row }: { row: IndicatorView }) {
  const snapshot = useAuthorizedSnapshot();
  const point = snapshot?.data.find(
    (item) => item.series_id === row.indicator_id,
  );
  if (row.indicator_id === "PENTAGON_PIZZA_PIZZINT")
    return <DoughconCard row={row} />;
  return (
    <article className="indicator-card" aria-label={row.label}>
      <div className="indicator-card-top">
        <span className="indicator-source">{row.source_id}</span>
        {point ? (
          <span className="data-status">{point.quality}</span>
        ) : (
          <DataStatus row={row} />
        )}
      </div>
      <h3 title={row.label}>{row.label}</h3>
      <div className="indicator-value">
        {point ? (point.value ?? "—") : (row.value ?? "—")}
        <span>
          {point?.value != null || row.value !== null
            ? row.unit
            : "데이터 없음"}
        </span>
      </div>
      <p className="indicator-note">
        {point?.source_event_at
          ? "원본 시각 (UTC): " + point.source_event_at
          : row.source_note || row.cadence}
      </p>
      <span className="indicator-frequency">{row.cadence}</span>
      {(row.category === "market" || point) && (
        <Link
          className="indicator-detail-link"
          to={"/market/" + encodeURIComponent(row.indicator_id)}
        >
          원본·시계열 상세
        </Link>
      )}
    </article>
  );
}

export function RatioPanel({ rows }: { rows: IndicatorView[] }) {
  const { showRatios, ratioKind, toggleRatios, setRatioKind } = useUi();
  const market = useAuthorizedSnapshot();
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
            {ratioRows.map((row) => {
              const point = market?.data.find(
                (item) => item.series_id === row.indicator_id,
              );
              const ratio = point?.value == null ? NaN : Number(point.value);
              const valid =
                Number.isFinite(ratio) &&
                ratio >= 0 &&
                point?.quality === "valid";
              const left = valid ? (100 * ratio) / (1 + ratio) : 0;
              const leftLabel = ratioKind === "taker_volume" ? "BUY" : "LONG";
              const rightLabel =
                ratioKind === "taker_volume" ? "SELL" : "SHORT";
              return (
                <div className="ratio-card" key={row.indicator_id}>
                  <div>
                    <strong>{row.indicator_id.split("_").slice(-1)[0]}</strong>
                    <span>{valid ? point?.value : "확인된 비율 없음"}</span>
                  </div>
                  <div
                    className="ratio-track"
                    aria-label={
                      valid
                        ? leftLabel + " " + left.toFixed(2) + "%"
                        : "Long/Short 비율 데이터 없음"
                    }
                  >
                    {valid && (
                      <span
                        style={{
                          display: "block",
                          width: left + "%",
                          height: "100%",
                          background: "var(--accent, #41c4a0)",
                        }}
                      />
                    )}
                  </div>
                  <div className="ratio-footer">
                    <span>
                      {leftLabel} {valid ? left.toFixed(2) + "%" : "—"}
                    </span>
                    <span>
                      {rightLabel} {valid ? (100 - left).toFixed(2) + "%" : "—"}
                    </span>
                  </div>
                  {point && (
                    <Link
                      to={"/market/" + encodeURIComponent(row.indicator_id)}
                    >
                      원본·시계열 상세
                    </Link>
                  )}
                  {point && (
                    <p className="indicator-note">
                      {point.quality} ·{" "}
                      {point.source_event_at ?? "원본 시각 미확인"}
                    </p>
                  )}
                </div>
              );
            })}
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
  const market = useAuthorizedSnapshot();
  const stored =
    market?.data.filter((point) => point.value !== null).length ?? 0;
  return (
    <div className="summary-strip">
      <div>
        <span>등록 지표</span>
        <strong>{total || "—"}</strong>
        <small>자동 수집 보장 아님</small>
      </div>
      <div>
        <span>실제 시장 시세</span>
        <strong>{market ? stored : "—"}</strong>
        <small>{market ? "승인된 저장 관측값" : "승인 전 비활성"}</small>
      </div>
      <div>
        <span>자동 거래</span>
        <strong>OFF</strong>
        <small>주문·외부 MCP 차단</small>
      </div>
      <div>
        <span>시스템 모드</span>
        <strong>{market ? "MARKET READ" : "FIXTURE"}</strong>
        <small>
          {market ? "저장 데이터 조회 · 거래 OFF" : "합성 데이터 전용"}
        </small>
      </div>
    </div>
  );
}

function MarketThermometer() {
  const snapshot = useAuthorizedSnapshot();
  const point = snapshot?.data.find(
    (item) => item.series_id === "CNN_FEAR_GREED_CNN",
  );
  const score = point?.value == null ? NaN : Number(point.value);
  const valid = Number.isFinite(score) && score >= 0 && score <= 100;
  return (
    <section className="panel thermometer-panel" aria-label="시장 온도계">
      <div>
        <p className="eyebrow">MARKET SENTIMENT</p>
        <h2>시장 온도계</h2>
        <p className="subline">CNN Fear &amp; Greed · 검증된 수집 근거 필요</p>
      </div>
      <div className="thermometer-content">
        <span className="thermometer-value">{valid ? score : "—"}</span>
        <div>
          <div
            className="thermometer-track"
            aria-label={
              valid ? "승인된 심리 지표 " + score : "확인된 심리 지표 없음"
            }
          >
            {valid && (
              <span
                style={{
                  display: "block",
                  width: score + "%",
                  height: "100%",
                  background: "currentColor",
                }}
              />
            )}
          </div>
          <div className="thermometer-legend">
            <span>EXTREME FEAR</span>
            <span>NEUTRAL</span>
            <span>EXTREME GREED</span>
          </div>
        </div>
      </div>
      <p className="indicator-note">
        {valid
          ? "원본 시각: " +
            (point?.source_event_at ?? "미확인") +
            " · " +
            point?.quality
          : "실제 지표 수집 권한이 확인되기 전에는 점수와 포인터를 표시하지 않습니다."}
      </p>
    </section>
  );
}

function OfficialEventsPanel() {
  const session = useQuery({
    queryKey: ["auth", "session"],
    queryFn: hasAuthorizedSession,
    retry: false,
    staleTime: 30_000,
  });
  const events = useQuery({
    queryKey: ["official-events", "approved"],
    queryFn: getOfficialEvents,
    enabled: session.data === true && !session.isError,
    retry: false,
    staleTime: 60_000,
  });
  return (
    <section className="panel" aria-label="경제지표 발표·수정 이력">
      <p className="eyebrow">OFFICIAL RELEASES / POINT-IN-TIME</p>
      <h2>경제지표 발표·수정 이력</h2>
      <p className="subline">
        이용 목적에 맞는 공식 데이터 보관·열람 권한과 계정 인증을 확인합니다.
        발표 시각이 확인되지 않으면 임의로 채우지 않습니다.
      </p>
      {session.data !== true || session.isError ? (
        <p className="panel-empty">
          인증 및 제공자 권한 확인 전 — 표시 가능한 공식 발표값이 없습니다.
        </p>
      ) : events.isError ? (
        <p className="panel-empty" role="status">
          공식 데이터 연결 또는 제공 권한을 확인할 수 없습니다.
        </p>
      ) : events.isPending ? (
        <p className="panel-empty" role="status">
          검증된 공식 관측값을 조회 중입니다.
        </p>
      ) : events.data.data.length === 0 ? (
        <p className="panel-empty">
          이 계정에 제공 가능한 승인된 공식 관측값이 없습니다.
        </p>
      ) : (
        <div className="official-events-table-wrap">
          <table className="official-events-table">
            <thead>
              <tr>
                <th scope="col">지표</th>
                <th scope="col">Actual</th>
                <th scope="col">Forecast</th>
                <th scope="col">Revision</th>
                <th scope="col">예정 (UTC)</th>
                <th scope="col">실제 발표 (UTC)</th>
                <th scope="col">최초 관측 (UTC)</th>
                <th scope="col">원본</th>
              </tr>
            </thead>
            <tbody>
              {events.data.data.map((event) => (
                <tr
                  key={
                    event.source_id +
                    ":" +
                    event.event_key +
                    ":" +
                    event.revision
                  }
                >
                  <td>{event.event_key}</td>
                  <td>
                    {event.actual ?? "—"} {event.unit}
                  </td>
                  <td>{event.forecast ?? "—"}</td>
                  <td>{event.revision}</td>
                  <td>{event.scheduled_at ?? "—"}</td>
                  <td>{event.released_at ?? "—"}</td>
                  <td>{event.first_seen_at}</td>
                  <td>
                    <a
                      href={event.source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {event.source_id}
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export function DashboardHome() {
  const market = useAuthorizedSnapshot();
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
          <p>
            {market
              ? "승인된 저장 관측값과 합성 검증 데이터를 구분하여 표시합니다."
              : "실시간 금융 데이터가 아닌 합성 Fixture 기반 개발 화면입니다."}
          </p>
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
      {data
        .filter((row) => row.indicator_id === "PENTAGON_PIZZA_PIZZINT")
        .map((row) => (
          <section className="section-block" key={row.indicator_id}>
            <div className="section-title">
              <h2>참고 지표</h2>
            </div>
            <div className="indicator-grid">
              <IndicatorCard row={row} />
            </div>
          </section>
        ))}
      <RatioPanel rows={data} />
      <OfficialEventsPanel />
      <CorporateGuidancePanel />
      <ExpiryCalendarPanel />
      <SeibroPanel />
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
  const session = useQuery({
    queryKey: ["auth", "session"],
    queryFn: hasAuthorizedSession,
    retry: false,
    staleTime: 30_000,
  });
  const history = useQuery({
    queryKey: ["authorized", "history", instrumentId],
    queryFn: () => getApprovedMarketSeries(instrumentId!),
    enabled: session.data === true && !session.isError && !!instrumentId,
    retry: false,
  });
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
        ) : session.data !== true || session.isError ? (
          <p className="panel-empty">
            시세 내역은 인증 및 원본 재배포 권한이 확인된 경우에만 조회합니다.
          </p>
        ) : history.isPending ? (
          <p className="panel-empty" role="status">
            승인된 시계열 조회 중…
          </p>
        ) : history.isError ? (
          <p className="panel-empty" role="status">
            해당 시계열의 제공 권한 또는 연결을 확인할 수 없습니다.
          </p>
        ) : history.data.data.length === 0 ? (
          <p className="panel-empty">승인된 관측값이 없습니다.</p>
        ) : (
          <>
            <Suspense fallback={<p>승인된 차트 로딩 중…</p>}>
              <ApprovedChart page={history.data} />
            </Suspense>
            <div className="official-events-table-wrap">
              <table className="official-events-table">
                <thead>
                  <tr>
                    <th scope="col">원본 시각 (UTC)</th>
                    <th scope="col">값</th>
                    <th scope="col">품질</th>
                    <th scope="col">개정</th>
                  </tr>
                </thead>
                <tbody>
                  {history.data.data.map((point) => (
                    <tr key={point.event_key + ":" + point.revision}>
                      <td>{point.source_event_at ?? "원본 시각 미확인"}</td>
                      <td>
                        {point.value ?? "—"} {history.data.meta.unit}
                      </td>
                      <td>{point.quality}</td>
                      <td>{point.revision}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
      <RatioPanel rows={data} />
    </div>
  );
}
