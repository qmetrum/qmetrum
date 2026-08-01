"use client";

import { useEffect, useMemo, useRef } from "react";
import {
  createChart,
  CandlestickSeries,
  type IChartApi,
  type ISeriesApi,
  type Time,
} from "lightweight-charts";
import { buildOhlc, type AggregationPeriod } from "@/lib/candlesticks";
import { useBranding } from "@/components/providers/BrandingProvider";

// lightweight-charts isn't CSS-driven, so axis/grid/text colors must be set in
// JS and re-applied on theme toggle (values mirror the --text-secondary /
// --card-border tokens for each theme).
function themeColors(isDark: boolean) {
  return {
    text: isDark ? "#8B95A8" : "#5A6270",
    grid: isDark ? "#1E2A3E" : "#EEF0F3",
    border: isDark ? "#1E2A3E" : "#E2E6EB",
  };
}

type Props = {
  historyPrices: number[];
  historyDates: string[];
  forecastPrices?: number[];
  forecastDates?: string[];
  period?: AggregationPeriod;
  height?: number;
};

export function CandlestickChart({
  historyPrices,
  historyDates,
  forecastPrices = [],
  forecastDates = [],
  period = "weekly",
  height = 320,
}: Props) {
  const branding = useBranding();
  const dark = branding.theme === "dark";
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const histSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const fcSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);

  const bars = useMemo(
    () => buildOhlc(historyPrices, historyDates, forecastPrices, forecastDates, period),
    [historyPrices, historyDates, forecastPrices, forecastDates, period],
  );

  // Init chart once
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const chart = createChart(container, {
      width: container.clientWidth,
      height,
      layout: {
        background: { color: "transparent" },
        textColor: "#5A6270",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "#EEF0F3" },
        horzLines: { color: "#EEF0F3" },
      },
      rightPriceScale: { borderColor: "#E2E6EB" },
      timeScale: { borderColor: "#E2E6EB" },
      crosshair: { mode: 1 },
    });

    chartRef.current = chart;
    histSeriesRef.current = chart.addSeries(CandlestickSeries, {
      upColor: "#0F8B6E",
      downColor: "#D85A30",
      wickUpColor: "#0F8B6E",
      wickDownColor: "#D85A30",
      borderVisible: false,
    });
    fcSeriesRef.current = chart.addSeries(CandlestickSeries, {
      upColor: "#8FC4B5",
      downColor: "#E8A58F",
      wickUpColor: "#8FC4B5",
      wickDownColor: "#E8A58F",
      borderVisible: false,
    });

    const onResize = () => {
      if (chartRef.current && containerRef.current) {
        chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
      }
    };
    window.addEventListener("resize", onResize);

    return () => {
      window.removeEventListener("resize", onResize);
      chart.remove();
      chartRef.current = null;
      histSeriesRef.current = null;
      fcSeriesRef.current = null;
    };
  }, [height]);

  // Re-theme axes/grid/text on light↔dark toggle without recreating the chart.
  useEffect(() => {
    const c = chartRef.current;
    if (!c) return;
    const tc = themeColors(dark);
    c.applyOptions({
      layout: { textColor: tc.text },
      grid: { vertLines: { color: tc.grid }, horzLines: { color: tc.grid } },
      rightPriceScale: { borderColor: tc.border },
      timeScale: { borderColor: tc.border },
    });
  }, [dark]);

  // Update data whenever bars change
  useEffect(() => {
    if (!chartRef.current || !histSeriesRef.current || !fcSeriesRef.current) return;

    const toChartBar = (b: { time: string; open: number; high: number; low: number; close: number }) => ({
      time: b.time as unknown as Time,
      open: b.open,
      high: b.high,
      low: b.low,
      close: b.close,
    });

    histSeriesRef.current.setData(bars.filter((b) => !b.isForecast).map(toChartBar));
    fcSeriesRef.current.setData(bars.filter((b) => b.isForecast).map(toChartBar));
    chartRef.current.timeScale().fitContent();
  }, [bars]);

  if (bars.length === 0) {
    return (
      <div
        role="img"
        aria-label="Candlestick price chart with historical and forecast bars."
        className="flex items-center justify-center text-sm text-[var(--text-muted)]"
        style={{ height }}
      >
        No data available
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      role="img"
      aria-label="Candlestick price chart with historical and forecast bars."
      style={{ height, width: "100%" }}
    />
  );
}
