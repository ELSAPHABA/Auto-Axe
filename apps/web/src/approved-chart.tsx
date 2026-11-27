import { useEffect, useMemo, useRef } from "react";
import * as echarts from "echarts/core";
import { BarChart, CandlestickChart, LineChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import { SVGRenderer } from "echarts/renderers";

import type { ApprovedMarketPage } from "./api";

echarts.use([
  BarChart,
  CandlestickChart,
  LineChart,
  GridComponent,
  TooltipComponent,
  SVGRenderer,
]);

export function ApprovedChart({ page }: { page: ApprovedMarketPage }) {
  const daily = page.data
    .flatMap((item) => (item.bar ? [item.bar] : []))
    .sort((a, b) => a.session_date.localeCompare(b.session_date));
  const fundamentals = page.data[0]?.fundamentals;
  if (daily.length) return <DailyChart rows={daily} />;
  if (fundamentals)
    return (
      <div>
        <p>수집 당시 재무 지표 · 과거 발표 시각 미검증</p>
        <dl>
          {Object.entries(fundamentals).map(([key, value]) => (
            <div key={key}>
              <dt>{key}</dt>
              <dd>{value ?? "—"}</dd>
            </div>
          ))}
        </dl>
      </div>
    );
  return <LineHistory page={page} />;
}

type DailyBar = NonNullable<ApprovedMarketPage["data"][number]["bar"]>;

function DailyChart({ rows }: { rows: DailyBar[] }) {
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!root.current || !root.current.clientWidth) return;
    const chart = echarts.init(root.current, undefined, { renderer: "svg" });
    const dates = rows.map((row) => row.session_date);
    chart.setOption({
      animation: false,
      tooltip: { trigger: "axis" },
      grid: [
        { left: 65, right: 18, top: 12, height: "60%" },
        { left: 65, right: 18, top: "76%", height: "16%" },
      ],
      xAxis: [
        { type: "category", data: dates, axisLabel: { show: false } },
        {
          type: "category",
          data: dates,
          gridIndex: 1,
          axisLabel: { color: "#96aec8" },
        },
      ],
      yAxis: [
        { scale: true, axisLabel: { color: "#96aec8" } },
        { gridIndex: 1, axisLabel: { color: "#96aec8" } },
      ],
      series: [
        {
          type: "candlestick",
          name: "조정 OHLC",
          data: rows.map((r) => [
            Number(r.open),
            Number(r.close),
            Number(r.low),
            Number(r.high),
          ]),
        },
        {
          type: "bar",
          name: "거래량",
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: rows.map((r) => Number(r.volume)),
        },
      ],
    });
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.dispose();
    };
  }, [rows]);
  return (
    <div className="demo-chart">
      <p>조정 일봉 · 수집 시점 기준, 거래소 세션 및 과거 시점 유효성 미검증</p>
      <div
        ref={root}
        role="img"
        aria-label="조정 일봉 및 거래량"
        style={{ height: 380, width: "100%" }}
      />
      <dl>
        {Object.entries(rows[rows.length - 1]?.features ?? {}).map(
          ([key, value]) => (
            <div key={key}>
              <dt>{key}</dt>
              <dd>{value ?? "워밍업"}</dd>
            </div>
          ),
        )}
      </dl>
    </div>
  );
}

function LineHistory({ page }: { page: ApprovedMarketPage }) {
  const root = useRef<HTMLDivElement>(null);
  const rows = useMemo(
    () =>
      [...page.data]
        .filter((item) => item.value !== null && item.source_event_at !== null)
        .sort((a, b) =>
          (a.source_event_at ?? "").localeCompare(b.source_event_at ?? ""),
        ),
    [page.data],
  );
  useEffect(() => {
    if (!root.current || root.current.clientWidth === 0 || rows.length < 2)
      return;
    const chart = echarts.init(root.current, undefined, { renderer: "svg" });
    chart.setOption({
      backgroundColor: "transparent",
      animation: false,
      grid: { top: 18, left: 50, right: 20, bottom: 50 },
      xAxis: {
        type: "category",
        data: rows.map((r) => r.source_event_at),
        axisLabel: { color: "#96aec8", rotate: 25 },
        axisLine: {
          lineStyle: { color: "#345072" },
        },
      },
      yAxis: {
        type: "value",
        scale: true,
        axisLabel: { color: "#96aec8" },
        splitLine: { lineStyle: { color: "#263851" } },
      },
      tooltip: {
        trigger: "axis",
        backgroundColor: "#12263c",
        textStyle: { color: "#eaf2ff" },
      },
      series: [
        {
          type: "line",
          name: page.meta.series_id,
          data: rows.map((r) => (r.value === null ? null : Number(r.value))),
          showSymbol: rows.length < 20,
          connectNulls: false,
          symbolSize: 5,
          lineStyle: { color: "#72c4a5", width: 2 },
          itemStyle: { color: "#72c4a5" },
        },
      ],
    });
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.dispose();
    };
  }, [page.meta.series_id, rows]);
  if (rows.length < 2)
    return (
      <p className="panel-empty">
        확인된 시점의 값이 2개 이상일 때만 시계열 차트를 그립니다.
      </p>
    );
  return (
    <div className="demo-chart" aria-label="승인된 과거 시세">
      <p className="eyebrow">
        APPROVED HISTORY · {page.meta.source_id} · {page.meta.unit}
      </p>
      <div
        ref={root}
        role="img"
        aria-label="승인된 원본 시각을 사용한 관측값 선 그래프"
        style={{ height: 290, width: "100%" }}
      />
    </div>
  );
}
