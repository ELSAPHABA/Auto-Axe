import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
} from "echarts/components";
import { SVGRenderer } from "echarts/renderers";
import { getCnnGraphs, type CnnGraphPage } from "./api";
import { useAuthorizedSnapshot } from "./authorized-live";

echarts.use([
  LineChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  SVGRenderer,
]);

const components = [
  ["market_momentum_sp500", "시장 모멘텀", "S&P 500 · 지수"],
  ["stock_price_strength", "주가 강도", "신고가·신저가 지표 · 원본 단위"],
  ["stock_price_breadth", "시장 폭", "McClellan 거래량 지표 · 원본 단위"],
  ["put_call_options", "풋·콜 옵션", "Put/Call 비율"],
  ["market_volatility_vix", "시장 변동성", "CNN VIX 이력 · 지수"],
  [
    "junk_bond_demand",
    "하이일드 채권 수요",
    "채권 수익률 스프레드 · 원본 단위",
  ],
  ["safe_haven_demand", "안전자산 선호", "주식·채권 수익률 차이 · 원본 단위"],
] as const;
const comparisons = [
  ["previous_close", "직전 종가"],
  ["previous_1_week", "1주 전"],
  ["previous_1_month", "1개월 전"],
  ["previous_1_year", "1년 전"],
] as const;
const headline = "fear_and_greed_historical";

export function CnnPanel() {
  const snapshot = useAuthorizedSnapshot();
  const allowed =
    snapshot?.data.some((p) => p.series_id === "CNN_FEAR_GREED_CNN") === true;
  const query = useQuery({
    queryKey: ["authorized", "cnn", "graphs"],
    queryFn: getCnnGraphs,
    enabled: allowed,
    retry: false,
    refetchInterval: 60_000,
  });
  return (
    <section className="panel" aria-label="CNN 공포·탐욕 분석">
      <h2>CNN 공포·탐욕 분석</h2>
      <p className="subline">
        검수된 CNN 과거 그래프 · 실시간 VIX 및 거래 신호와 분리
      </p>
      {!allowed || query.isError ? (
        <p className="panel-empty">수집·열람 권한 또는 연결 미확인</p>
      ) : query.isPending ? (
        <p role="status">CNN 관측값 조회 중…</p>
      ) : (
        <CnnGraphs page={query.data} />
      )}
    </section>
  );
}

export function CnnGraphs({ page }: { page: CnnGraphPage }) {
  const [selected, setSelected] = useState(headline);
  const [mode, setMode] = useState("raw");
  const [period, setPeriod] = useState("365");
  const root = useRef<HTMLDivElement>(null);
  const current = page.current;
  const normalized = selected === headline || mode === "score";
  const key =
    selected === headline
      ? headline
      : mode === "score"
        ? "score:" + selected
        : selected;
  const since = Date.parse(page.as_of) - Number(period) * 86400_000;
  const rows = (page.graphs[key] ?? []).filter(
    (p) => Date.parse(p.timestamp) >= since,
  );
  const comparisonKey =
    mode === "raw" && selected === "market_momentum_sp500"
      ? "market_momentum_sp125"
      : mode === "raw" && selected === "market_volatility_vix"
        ? "market_volatility_vix_50"
        : null;
  const label =
    selected === headline
      ? "종합 공포·탐욕 지수"
      : mode === "score"
        ? "CNN 정규화 점수"
        : (components.find((c) => c[0] === selected)?.[2] ?? "");
  useEffect(() => {
    if (!root.current || !root.current.clientWidth || !rows.length) return;
    const chart = echarts.init(root.current, undefined, { renderer: "svg" });
    const data = (id: string) =>
      (page.graphs[id] ?? [])
        .filter((p) => Date.parse(p.timestamp) >= since)
        .map((p) => [Date.parse(p.timestamp), Number(p.value)]);
    chart.setOption({
      animation: false,
      tooltip: { trigger: "axis" },
      legend: { textStyle: { color: "#96aec8" } },
      grid: { left: 65, right: 20, top: 40, bottom: 35 },
      xAxis: { type: "time", axisLabel: { color: "#96aec8" } },
      yAxis: {
        type: "value",
        min: normalized ? 0 : undefined,
        max: normalized ? 100 : undefined,
        scale: !normalized,
        axisLabel: { color: "#96aec8" },
      },
      series: [
        {
          type: "line",
          name: label,
          data: data(key),
          showSymbol: rows.length < 20,
          connectNulls: false,
        },
        ...(comparisonKey
          ? [
              {
                type: "line",
                name:
                  selected === "market_momentum_sp500"
                    ? "125일 이동평균"
                    : "50일 이동평균",
                data: data(comparisonKey),
                showSymbol: false,
                connectNulls: false,
              },
            ]
          : []),
      ],
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(root.current);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [
    page,
    key,
    normalized,
    comparisonKey,
    since,
    label,
    selected,
    rows.length,
  ]);
  return (
    <>
      {current ? (
        <>
          <p>
            종합 {current.score} · {current.rating} · 원본 {current.timestamp}
          </p>
          <div className="indicator-grid">
            {comparisons.map(([id, name]) => (
              <div className="indicator-card" key={id}>
                <h3>{name}</h3>
                <strong>{current.comparisons[id] ?? "—"}</strong>
              </div>
            ))}
          </div>
          <div className="indicator-grid">
            {components.map(([id, name]) => (
              <button
                className="indicator-card"
                key={id}
                aria-pressed={selected === id}
                onClick={() => setSelected(id)}
              >
                <span>{name}</span>
                <strong>{current.components[id]?.score ?? "—"}</strong>
                <small>{current.components[id]?.rating ?? "—"}</small>
              </button>
            ))}
          </div>
        </>
      ) : (
        <p className="panel-empty">검수된 CNN 관측값 없음</p>
      )}
      <div className="section-title">
        <label>
          지표{" "}
          <select
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
          >
            <option value={headline}>종합 공포·탐욕 지수</option>
            {components.map(([id, name]) => (
              <option key={id} value={id}>
                {name}
              </option>
            ))}
          </select>
        </label>
        <label>
          기간{" "}
          <select value={period} onChange={(e) => setPeriod(e.target.value)}>
            <option value="30">1개월</option>
            <option value="90">3개월</option>
            <option value="365">1년</option>
          </select>
        </label>
        {selected !== headline && (
          <label>
            값{" "}
            <select value={mode} onChange={(e) => setMode(e.target.value)}>
              <option value="raw">기초 관측값</option>
              <option value="score">수집 당시 평가 점수</option>
            </select>
          </label>
        )}
      </div>
      <p>{label}</p>
      {rows.length ? (
        <div
          ref={root}
          role="img"
          aria-label={label + " 추이"}
          style={{ height: 320, width: "100%" }}
        />
      ) : (
        <p className="panel-empty">선택한 기간에 검수된 데이터 없음</p>
      )}
      <p className="indicator-note">
        과거 기초값과 평가 점수는 다른 시계열입니다. 하위 평가 점수는 실제 수집
        시점부터 누적합니다. 과거 관측값이 당시 이용 가능했다는 의미는 아닙니다.
      </p>
    </>
  );
}
