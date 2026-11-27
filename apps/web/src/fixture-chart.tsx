import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import { SVGRenderer } from "echarts/renderers";

echarts.use([LineChart, GridComponent, TooltipComponent, SVGRenderer]);

/** Static synthetic curve, never represented as genuine market history. */
export function FixtureChart() {
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    // JSDOM has no real layout/canvas; render the accessible fallback during unit tests.
    if (!root.current || root.current.clientWidth === 0) return;
    const chart = echarts.init(root.current, undefined, { renderer: "svg" });
    chart.setOption({
      backgroundColor: "transparent",
      animation: false,
      grid: { top: 15, right: 20, left: 35, bottom: 27 },
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: ["T−5", "T−4", "T−3", "T−2", "T−1", "T"],
        axisLine: { lineStyle: { color: "#354760" } },
        axisTick: { show: false },
        axisLabel: { color: "#8ea3bd" },
      },
      yAxis: {
        type: "value",
        scale: true,
        min: 110,
        max: 135,
        splitLine: { lineStyle: { color: "#263851" } },
        axisLabel: { color: "#8799ac" },
      },
      tooltip: {
        trigger: "axis",
        backgroundColor: "#12263c",
        textStyle: { color: "#eaf2ff" },
      },
      series: [
        {
          type: "line",
          name: "SYNTHETIC DEMO",
          data: [115, 118, 117, 122, 120, 123.45],
          symbol: "circle",
          symbolSize: 5,
          smooth: true,
          lineStyle: { color: "#60bdab", width: 2 },
          itemStyle: { color: "#71d5bb" },
          areaStyle: { color: "rgba(91,181,157,0.13)" },
        },
      ],
    });
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.dispose();
    };
  }, []);
  return (
    <div className="demo-chart">
      <p className="eyebrow">SYNTHETIC DEMO / NO MARKET HISTORY</p>
      <div
        ref={root}
        role="img"
        aria-label="합성 예시 차트. 실제 시장 가격 이력 아님"
        style={{ height: 250, width: "100%" }}
      />
    </div>
  );
}
