/**
 * Aggregate a daily price series into weekly or monthly OHLC bars.
 *
 * Reuses the same price arrays the forecast line chart already receives —
 * so the candlestick view is always consistent with the line chart it sits
 * under. The forecast portion is aggregated the same way as history; the
 * `isForecast` flag lets the UI style those bars differently.
 */
export type OhlcBar = {
  time: string; // ISO date of the bucket's last day (YYYY-MM-DD)
  open: number;
  high: number;
  low: number;
  close: number;
  isForecast: boolean;
};

export type AggregationPeriod = "weekly" | "monthly";

function bucketKey(dateStr: string, period: AggregationPeriod): string {
  const d = new Date(dateStr);
  if (period === "monthly") {
    return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
  }
  // ISO week key: year-week number
  const tmp = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()));
  const dayNum = tmp.getUTCDay() || 7;
  tmp.setUTCDate(tmp.getUTCDate() + 4 - dayNum);
  const yearStart = new Date(Date.UTC(tmp.getUTCFullYear(), 0, 1));
  const week = Math.ceil(((tmp.getTime() - yearStart.getTime()) / 86400000 + 1) / 7);
  return `${tmp.getUTCFullYear()}-W${String(week).padStart(2, "0")}`;
}

function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

export function buildOhlc(
  historyPrices: number[],
  historyDates: string[],
  forecastPrices: number[],
  forecastDates: string[],
  period: AggregationPeriod = "weekly",
): OhlcBar[] {
  type PendingBucket = {
    key: string;
    dates: Date[];
    prices: number[];
    isForecast: boolean;
  };
  const buckets = new Map<string, PendingBucket>();

  const push = (rawDate: string, price: number, isForecast: boolean) => {
    if (!rawDate || !isFinite(price)) return;
    const d = new Date(rawDate);
    if (isNaN(d.getTime())) return;
    const key = (isForecast ? "F-" : "H-") + bucketKey(rawDate, period);
    const existing = buckets.get(key);
    if (existing) {
      existing.dates.push(d);
      existing.prices.push(price);
    } else {
      buckets.set(key, { key, dates: [d], prices: [price], isForecast });
    }
  };

  const histLen = Math.min(historyPrices.length, historyDates.length);
  for (let i = 0; i < histLen; i++) push(historyDates[i], historyPrices[i], false);

  const fcLen = Math.min(forecastPrices.length, forecastDates.length);
  for (let i = 0; i < fcLen; i++) push(forecastDates[i], forecastPrices[i], true);

  const bars: OhlcBar[] = [];
  for (const b of buckets.values()) {
    if (!b.prices.length) continue;
    const sortIdx = b.dates
      .map((_, i) => i)
      .sort((a, c) => b.dates[a].getTime() - b.dates[c].getTime());
    const sortedPrices = sortIdx.map((i) => b.prices[i]);
    const lastDate = b.dates[sortIdx[sortIdx.length - 1]];
    bars.push({
      time: isoDate(lastDate),
      open: sortedPrices[0],
      close: sortedPrices[sortedPrices.length - 1],
      high: Math.max(...sortedPrices),
      low: Math.min(...sortedPrices),
      isForecast: b.isForecast,
    });
  }

  bars.sort((a, b) => (a.time < b.time ? -1 : a.time > b.time ? 1 : 0));
  return bars;
}
