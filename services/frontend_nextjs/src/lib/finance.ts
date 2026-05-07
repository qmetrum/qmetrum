export function formatCurrency(value?: number | null, maximumFractionDigits = 2): string {
  if (value == null || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits,
  }).format(value);
}

export function formatCompact(value?: number | null): string {
  if (value == null || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("en-US", {
    notation: "compact",
    maximumFractionDigits: 2,
  }).format(value);
}

export function formatNumber(value?: number | null, digits = 2): string {
  if (value == null || Number.isNaN(value)) return "—";
  return value.toFixed(digits);
}

export function formatPercent(value?: number | null, digits = 2): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

export function formatSignedPercent(value?: number | null, digits = 2): string {
  if (value == null || Number.isNaN(value)) return "—";
  const prefix = value >= 0 ? "+" : "";
  return `${prefix}${(value * 100).toFixed(digits)}%`;
}

export function simpleMovingAverage(values: number[], period: number): Array<number | null> {
  const out: Array<number | null> = new Array(values.length).fill(null);
  if (period <= 0) return out;

  let sum = 0;
  for (let index = 0; index < values.length; index += 1) {
    sum += values[index];
    if (index >= period) sum -= values[index - period];
    if (index >= period - 1) out[index] = sum / period;
  }

  return out;
}

export function exponentialMovingAverage(values: number[], period: number): Array<number | null> {
  const out: Array<number | null> = new Array(values.length).fill(null);
  if (!values.length || period <= 0) return out;

  const k = 2 / (period + 1);
  let ema = values[0];
  out[0] = ema;

  for (let index = 1; index < values.length; index += 1) {
    ema = values[index] * k + ema * (1 - k);
    out[index] = ema;
  }

  return out;
}

export function bollingerBands(values: number[], period = 20, multiplier = 2) {
  const mid = simpleMovingAverage(values, period);
  const upper: Array<number | null> = new Array(values.length).fill(null);
  const lower: Array<number | null> = new Array(values.length).fill(null);

  for (let index = period - 1; index < values.length; index += 1) {
    const slice = values.slice(index - period + 1, index + 1);
    const mean = mid[index] ?? 0;
    const variance = slice.reduce((acc, value) => acc + (value - mean) ** 2, 0) / period;
    const stdev = Math.sqrt(variance);
    upper[index] = mean + multiplier * stdev;
    lower[index] = mean - multiplier * stdev;
  }

  return { mid, upper, lower };
}

export function macd(values: number[]) {
  const ema12 = exponentialMovingAverage(values, 12);
  const ema26 = exponentialMovingAverage(values, 26);

  const line: Array<number | null> = values.map((_, index) => {
    if (ema12[index] == null || ema26[index] == null) return null;
    return (ema12[index] as number) - (ema26[index] as number);
  });

  const lineAsNumbers = line.map((value) => value ?? 0);
  const signalRaw = exponentialMovingAverage(lineAsNumbers, 9);
  const signal = signalRaw.map((value, index) => (line[index] == null ? null : value));

  const histogram = line.map((value, index) => {
    if (value == null || signal[index] == null) return null;
    return value - (signal[index] as number);
  });

  return { line, signal, histogram };
}

export function rsi(values: number[], period = 14): Array<number | null> {
  const out: Array<number | null> = new Array(values.length).fill(null);
  if (values.length <= period) return out;

  let gains = 0;
  let losses = 0;

  for (let index = 1; index <= period; index += 1) {
    const delta = values[index] - values[index - 1];
    if (delta >= 0) gains += delta;
    else losses -= delta;
  }

  let avgGain = gains / period;
  let avgLoss = losses / period;

  for (let index = period + 1; index < values.length; index += 1) {
    const delta = values[index] - values[index - 1];
    const gain = Math.max(delta, 0);
    const loss = Math.max(-delta, 0);

    avgGain = (avgGain * (period - 1) + gain) / period;
    avgLoss = (avgLoss * (period - 1) + loss) / period;

    if (avgLoss === 0) {
      out[index] = 100;
      continue;
    }

    const rs = avgGain / avgLoss;
    out[index] = 100 - 100 / (1 + rs);
  }

  return out;
}

export function vwap(closes: number[]): Array<number | null> {
  const out: Array<number | null> = new Array(closes.length).fill(null);
  let cumulativeValue = 0;
  let cumulativeVolume = 0;

  for (let index = 0; index < closes.length; index += 1) {
    const syntheticVolume = 1 + (index % 5);
    cumulativeValue += closes[index] * syntheticVolume;
    cumulativeVolume += syntheticVolume;
    out[index] = cumulativeVolume ? cumulativeValue / cumulativeVolume : null;
  }

  return out;
}

export function latestNumber(...values: unknown[]): number | null {
  for (const value of values) {
    if (typeof value === "number" && Number.isFinite(value)) return value;
    if (Array.isArray(value)) {
      for (let index = value.length - 1; index >= 0; index -= 1) {
        const item = value[index];
        if (typeof item === "number" && Number.isFinite(item)) return item;
      }
    }
  }
  return null;
}

export function numberFromRecord(
  record: Record<string, unknown> | undefined,
  keys: string[],
): number | null {
  if (!record) return null;
  for (const key of keys) {
    const direct = record[key];
    if (typeof direct === "number" && Number.isFinite(direct)) return direct;

    const lower = Object.entries(record).find(([candidate]) => candidate.toLowerCase() === key.toLowerCase())?.[1];
    if (typeof lower === "number" && Number.isFinite(lower)) return lower;
  }
  return null;
}

export function inferSentiment(headline: string): "Bullish" | "Bearish" | "Neutral" {
  const text = headline.toLowerCase();
  const positiveHits = ["beats", "surge", "upgrade", "growth", "record", "buy", "bull"].filter((token) =>
    text.includes(token),
  ).length;
  const negativeHits = ["misses", "downgrade", "drop", "sell", "slump", "lawsuit", "bear"].filter((token) =>
    text.includes(token),
  ).length;

  if (positiveHits > negativeHits) return "Bullish";
  if (negativeHits > positiveHits) return "Bearish";
  return "Neutral";
}

export function gaussianSamples(
  mean: number,
  sigma: number,
  count: number,
  seed = 42,
): number[] {
  let state = seed;

  const nextRandom = () => {
    state = (state * 1664525 + 1013904223) % 0x100000000;
    return state / 0x100000000;
  };

  const samples: number[] = [];
  for (let i = 0; i < count; i += 1) {
    const u1 = Math.max(nextRandom(), 1e-7);
    const u2 = Math.max(nextRandom(), 1e-7);
    const z = Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
    samples.push(mean + z * sigma);
  }

  return samples;
}

export function histogram(samples: number[], bins = 18) {
  if (!samples.length) return [] as Array<{ bucket: string; count: number }>;

  const min = Math.min(...samples);
  const max = Math.max(...samples);
  const width = (max - min) / bins || 1;

  const counts = new Array(bins).fill(0) as number[];
  for (const value of samples) {
    const index = Math.min(bins - 1, Math.max(0, Math.floor((value - min) / width)));
    counts[index] += 1;
  }

  return counts.map((count, index) => {
    const start = min + index * width;
    const end = start + width;
    return {
      bucket: `${(start * 100).toFixed(0)}%..${(end * 100).toFixed(0)}%`,
      count,
    };
  });
}
