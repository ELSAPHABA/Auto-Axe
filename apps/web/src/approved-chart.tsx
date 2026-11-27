import { useEffect, useMemo, useRef } from "react";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import { SVGRenderer } from "echarts/renderers";

import type { ApprovedMarketPage } from "./api";

echarts.use([LineChart, GridComponent, TooltipComponent, SVGRenderer]);

export function ApprovedChart({ page }: { page: ApprovedMarketPage }) {
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
