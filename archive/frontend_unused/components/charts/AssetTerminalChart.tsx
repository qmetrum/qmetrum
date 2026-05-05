"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  AreaSeries,
  CandlestickSeries,
  ColorType,
  createChart,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  type CandlestickData,
  type HistogramData,
  type LineData,
  type Time,
} from "lightweight-charts";
import {
  bollingerBands,
  exponentialMovingAverage,
  macd,
  rsi,
  simpleMovingAverage,
  vwap,
} from "@/lib/finance";

type Timeframe = "1M" | "3M" | "6M" | "1Y" | "2Y";

type IndicatorKey = "ma50" | "ma200" | "ema" | "macd" | "rsi" | "boll" | "vwap";

type IndicatorState = Record<IndicatorKey, boolean>;

type PricePoint = {
  date: string;
  price: number;
};

type ForecastPayload = {
  dates?: string[];
  prices?: number[];
  lower?: number[];
  upper?: number[];
};

const TIMEFRAMES: Timeframe[] = ["1M", "3M", "6M", "1Y", "2Y"];

const INDICATOR_LABELS: Array<{ key: IndicatorKey; label: string }> = [
  { key: "ma50", label: "MA (50)" },
  { key: "ma200", label: "MA (200)" },
  { key: "ema", label: "EMA" },
  { key: "macd", label: "MACD" },
  { key: "rsi", label: "RSI" },
  { key: "boll", label: "Bollinger" },
  { key: "vwap", label: "VWAP" },
];

function timeframeDays(frame: Timeframe): number {
  switch (frame) {
    case "1M":
      return 31;
    case "3M":
      return 93;
    case "6M":
      return 186;
    case "1Y":
      return 365;
    case "2Y":
      return 730;
    default:
      return 365;
  }
}

function toTime(date: string): Time {
  const parsed = new Date(date);
  if (Number.isNaN(parsed.getTime())) return date;
  const year = parsed.getUTCFullYear();
  const month = parsed.getUTCMonth() + 1;
  const day = parsed.getUTCDate();
  return { year, month, day };
}

function toLineSeries(times: Time[], values: Array<number | null>): LineData<Time>[] {
  const out: LineData<Time>[] = [];
  for (let index = 0; index < values.length; index += 1) {
    if (values[index] == null) continue;
    out.push({ time: times[index], value: values[index] as number });
  }
  return out;
}

export function AssetTerminalChart({
  symbol,
  history,
  forecast,
}: {
  symbol: string;
  history: PricePoint[];
  forecast?: ForecastPayload | null;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [timeframe, setTimeframe] = useState<Timeframe>("1Y");
  const [indicators, setIndicators] = useState<IndicatorState>({
    ma50: true,
    ma200: false,
    ema: false,
    macd: true,
    rsi: true,
    boll: false,
    vwap: false,
  });
  const [hover, setHover] = useState<{
    date: string;
    open: number;
    high: number;
    low: number;
    close: number;
  } | null>(null);

  const filteredHistory = useMemo(() => {
    if (!history.length) return [] as PricePoint[];
    const lastDate = new Date(history[history.length - 1].date);
    if (Number.isNaN(lastDate.getTime())) return history;
    const cutoff = lastDate.getTime() - timeframeDays(timeframe) * 24 * 60 * 60 * 1000;
    return history.filter((point) => {
      const parsed = new Date(point.date);
      if (Number.isNaN(parsed.getTime())) return true;
      return parsed.getTime() >= cutoff;
    });
  }, [history, timeframe]);

  const parsed = useMemo(() => {
    const times = filteredHistory.map((point) => toTime(point.date));
    const closes = filteredHistory.map((point) => point.price);

    const candles: CandlestickData<Time>[] = filteredHistory.map((point, index) => {
      const prevClose = index === 0 ? point.price : filteredHistory[index - 1].price;
      const open = prevClose;
      const close = point.price;
      const span = Math.max(Math.abs(close - open), close * 0.0035);
      const high = Math.max(open, close) + span * 0.6;
      const low = Math.min(open, close) - span * 0.6;
      return {
        time: toTime(point.date),
        open,
        high,
        low,
        close,
      };
    });

    const ma50 = simpleMovingAverage(closes, 50);
    const ma200 = simpleMovingAverage(closes, 200);
    const ema = exponentialMovingAverage(closes, 50);
    const boll = bollingerBands(closes, 20, 2);
    const vwapSeries = vwap(closes);
    const macdSeries = macd(closes);
    const rsiSeries = rsi(closes, 14);

    const forecastLine: LineData<Time>[] = (forecast?.prices ?? []).map((price, index) => ({
      time: toTime(forecast?.dates?.[index] ?? `${index + 1}`),
      value: price,
    }));

    const upperBand: LineData<Time>[] = (forecast?.upper ?? []).map((value, index) => ({
      time: toTime(forecast?.dates?.[index] ?? `${index + 1}`),
      value,
    }));

    const lowerBand: LineData<Time>[] = (forecast?.lower ?? []).map((value, index) => ({
      time: toTime(forecast?.dates?.[index] ?? `${index + 1}`),
      value,
    }));

    const macdLineData = toLineSeries(times, macdSeries.line);
    const macdSignalData = toLineSeries(times, macdSeries.signal);

    const macdHistogramData: HistogramData<Time>[] = [];
    for (let index = 0; index < macdSeries.histogram.length; index += 1) {
      const value = macdSeries.histogram[index];
      if (value == null) continue;
      macdHistogramData.push({
        time: times[index],
        value,
        color: value >= 0 ? "rgba(34,197,94,0.85)" : "rgba(239,68,68,0.85)",
      });
    }

    const rsiData = toLineSeries(times, rsiSeries);
    const rsiUpper = times.map((time) => ({ time, value: 70 }));
    const rsiLower = times.map((time) => ({ time, value: 30 }));

    return {
      candles,
      times,
      ma50: toLineSeries(times, ma50),
      ma200: toLineSeries(times, ma200),
      ema: toLineSeries(times, ema),
      bollUpper: toLineSeries(times, boll.upper),
      bollMid: toLineSeries(times, boll.mid),
      bollLower: toLineSeries(times, boll.lower),
      vwap: toLineSeries(times, vwapSeries),
      macdLineData,
      macdSignalData,
      macdHistogramData,
      rsiData,
      rsiUpper,
      rsiLower,
      forecastLine,
      upperBand,
      lowerBand,
    };
  }, [filteredHistory, forecast]);

  const totalHeight = 520 + (indicators.macd ? 120 : 0) + (indicators.rsi ? 120 : 0);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || parsed.candles.length < 2) return;

    const chart = createChart(container, {
      width: container.clientWidth,
      height: totalHeight,
      layout: {
        background: { type: ColorType.Solid, color: "#161B22" },
        textColor: "#94A3B8",
        fontFamily: "Inter, sans-serif",
      },
      grid: {
        vertLines: { color: "rgba(148,163,184,0.08)" },
        horzLines: { color: "rgba(148,163,184,0.08)" },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: {
          color: "rgba(59,130,246,0.5)",
          labelBackgroundColor: "#1f2937",
        },
        horzLine: {
          color: "rgba(59,130,246,0.3)",
          labelBackgroundColor: "#1f2937",
        },
      },
      rightPriceScale: {
        borderColor: "rgba(148,163,184,0.2)",
      },
      timeScale: {
        borderColor: "rgba(148,163,184,0.2)",
      },
      handleScale: {
        mouseWheel: true,
        pinch: true,
        axisPressedMouseMove: true,
      },
      handleScroll: {
        mouseWheel: true,
        pressedMouseMove: true,
        vertTouchDrag: true,
        horzTouchDrag: true,
      },
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#22c55e",
      downColor: "#ef4444",
      wickUpColor: "#22c55e",
      wickDownColor: "#ef4444",
      borderVisible: false,
      priceLineVisible: false,
    });
    candleSeries.setData(parsed.candles);

    if (parsed.forecastLine.length) {
      const forecastSeries = chart.addSeries(LineSeries, {
        color: "#3b82f6",
        lineWidth: 2,
        priceLineVisible: false,
      });
      forecastSeries.setData(parsed.forecastLine);
    }

    if (parsed.upperBand.length && parsed.lowerBand.length) {
      const upperArea = chart.addSeries(AreaSeries, {
        lineColor: "rgba(59,130,246,0.7)",
        topColor: "rgba(59,130,246,0.25)",
        bottomColor: "rgba(59,130,246,0.02)",
        lineWidth: 1,
        priceLineVisible: false,
      });
      upperArea.setData(parsed.upperBand);

      const lowerMask = chart.addSeries(AreaSeries, {
        lineColor: "rgba(0,0,0,0)",
        topColor: "#161B22",
        bottomColor: "#161B22",
        lineWidth: 1,
        priceLineVisible: false,
      });
      lowerMask.setData(parsed.lowerBand);
    }

    if (indicators.ma50) {
      const ma50Series = chart.addSeries(LineSeries, {
        color: "#f59e0b",
        lineWidth: 1,
        priceLineVisible: false,
      });
      ma50Series.setData(parsed.ma50);
    }

    if (indicators.ma200) {
      const ma200Series = chart.addSeries(LineSeries, {
        color: "#a855f7",
        lineWidth: 1,
        priceLineVisible: false,
      });
      ma200Series.setData(parsed.ma200);
    }

    if (indicators.ema) {
      const emaSeries = chart.addSeries(LineSeries, {
        color: "#06b6d4",
        lineWidth: 1,
        priceLineVisible: false,
      });
      emaSeries.setData(parsed.ema);
    }

    if (indicators.boll) {
      const upper = chart.addSeries(LineSeries, {
        color: "rgba(148,163,184,0.8)",
        lineWidth: 1,
        lineStyle: 2,
        priceLineVisible: false,
      });
      upper.setData(parsed.bollUpper);

      const mid = chart.addSeries(LineSeries, {
        color: "rgba(148,163,184,0.65)",
        lineWidth: 1,
        priceLineVisible: false,
      });
      mid.setData(parsed.bollMid);

      const lower = chart.addSeries(LineSeries, {
        color: "rgba(148,163,184,0.8)",
        lineWidth: 1,
        lineStyle: 2,
        priceLineVisible: false,
      });
      lower.setData(parsed.bollLower);
    }

    if (indicators.vwap) {
      const vwapSeries = chart.addSeries(LineSeries, {
        color: "#38bdf8",
        lineWidth: 1,
        priceLineVisible: false,
      });
      vwapSeries.setData(parsed.vwap);
    }

    let paneIndex = 1;

    if (indicators.macd) {
      const hist = chart.addSeries(
        HistogramSeries,
        {
          base: 0,
          priceLineVisible: false,
          lastValueVisible: false,
        },
        paneIndex,
      );
      hist.setData(parsed.macdHistogramData);

      const line = chart.addSeries(
        LineSeries,
        {
          color: "#60a5fa",
          lineWidth: 1,
          priceLineVisible: false,
          lastValueVisible: false,
        },
        paneIndex,
      );
      line.setData(parsed.macdLineData);

      const signal = chart.addSeries(
        LineSeries,
        {
          color: "#f97316",
          lineWidth: 1,
          priceLineVisible: false,
          lastValueVisible: false,
        },
        paneIndex,
      );
      signal.setData(parsed.macdSignalData);

      paneIndex += 1;
    }

    if (indicators.rsi) {
      const rsiLine = chart.addSeries(
        LineSeries,
        {
          color: "#38bdf8",
          lineWidth: 1,
          priceLineVisible: false,
          lastValueVisible: false,
        },
        paneIndex,
      );
      rsiLine.setData(parsed.rsiData);

      const upper = chart.addSeries(
        LineSeries,
        {
          color: "rgba(239,68,68,0.8)",
          lineWidth: 1,
          lineStyle: 2,
          priceLineVisible: false,
          lastValueVisible: false,
        },
        paneIndex,
      );
      upper.setData(parsed.rsiUpper);

      const lower = chart.addSeries(
        LineSeries,
        {
          color: "rgba(34,197,94,0.8)",
          lineWidth: 1,
          lineStyle: 2,
          priceLineVisible: false,
          lastValueVisible: false,
        },
        paneIndex,
      );
      lower.setData(parsed.rsiLower);
    }

    const panes = chart.panes();
    if (panes.length) {
      const auxCount = panes.length - 1;
      panes[0].setHeight(Math.max(340, totalHeight - auxCount * 120));
      for (let i = 1; i < panes.length; i += 1) {
        panes[i].setHeight(120);
      }
    }

    chart.timeScale().fitContent();

    chart.subscribeCrosshairMove((param) => {
      const candleData = param.seriesData.get(candleSeries) as
        | {
            open?: number;
            high?: number;
            low?: number;
            close?: number;
          }
        | undefined;

      if (!param.time || !candleData || candleData.close == null) {
        setHover(null);
        return;
      }

      let label = "";
      if (typeof param.time === "string") {
        label = param.time;
      } else if ("year" in param.time) {
        label = `${param.time.year}-${String(param.time.month).padStart(2, "0")}-${String(param.time.day).padStart(2, "0")}`;
      } else {
        label = String(param.time);
      }

      setHover({
        date: label,
        open: candleData.open ?? candleData.close,
        high: candleData.high ?? candleData.close,
        low: candleData.low ?? candleData.close,
        close: candleData.close,
      });
    });

    const onResize = () => {
      if (!container) return;
      chart.resize(container.clientWidth, totalHeight);
    };

    window.addEventListener("resize", onResize);

    return () => {
      window.removeEventListener("resize", onResize);
      chart.remove();
    };
  }, [parsed, totalHeight, indicators]);

  return (
    <section className="terminal-panel p-3 md:p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-1">
          {TIMEFRAMES.map((frame) => (
            <button
              key={frame}
              type="button"
              onClick={() => setTimeframe(frame)}
              className={`rounded border px-2.5 py-1 text-xs ${
                timeframe === frame
                  ? "border-blue-500/50 bg-blue-500/20 text-blue-200"
                  : "border-[var(--terminal-border)] text-slate-300 hover:bg-[#1f2630]"
              }`}
            >
              {frame}
            </button>
          ))}
        </div>

        <div className="flex flex-wrap gap-1">
          {INDICATOR_LABELS.map((item) => (
            <button
              key={item.key}
              type="button"
              onClick={() =>
                setIndicators((prev) => ({
                  ...prev,
                  [item.key]: !prev[item.key],
                }))
              }
              className={`rounded border px-2 py-1 text-[11px] ${
                indicators[item.key]
                  ? "border-blue-500/40 bg-blue-500/15 text-blue-200"
                  : "border-[var(--terminal-border)] text-slate-400"
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      <div className="relative overflow-hidden rounded border border-[var(--terminal-border)]">
        <div ref={containerRef} className="w-full" style={{ height: totalHeight }} />

        {hover ? (
          <div className="pointer-events-none absolute left-2 top-2 rounded border border-[var(--terminal-border)] bg-[rgba(14,17,23,0.85)] px-2 py-1 text-[11px] text-slate-200">
            <div className="font-medium text-blue-200">{symbol}</div>
            <div>{hover.date}</div>
            <div>O {hover.open.toFixed(2)}</div>
            <div>H {hover.high.toFixed(2)}</div>
            <div>L {hover.low.toFixed(2)}</div>
            <div>C {hover.close.toFixed(2)}</div>
          </div>
        ) : null}
      </div>

      <div className="mt-2 text-[11px] text-[var(--terminal-muted)]">
        Drag to pan, scroll to zoom, and hover for crosshair price details.
      </div>
    </section>
  );
}
