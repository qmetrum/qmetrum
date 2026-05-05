"""Derived series for drawdown and monthly returns over the forecast horizon.

These extend the asset-level HybridForecaster.predict() and the portfolio-level
analyze_portfolio() responses with:

  - A drawdown curve whose running peak is carried from the historical
    maximum into the forecast period, so a forecast does not spuriously
    reset the drawdown to zero on day one.
  - A monthly-returns series that reports the forecast months on the same
    (end-of-month / start-of-month - 1) definition as the historical series,
    with explicit "partial" flags for months the horizon does not fully cover.

Both series expose lower / median / upper bands computed by applying the
same recipe to the lower_ci, forecast, upper_ci paths respectively. For
drawdown, the lower-CI path naturally produces deeper (more negative)
drawdowns and the upper-CI path produces milder ones.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd


def _running_drawdown(prices: np.ndarray, starting_peak: float) -> tuple[np.ndarray, float]:
    """Compute drawdown series D_t = P_t / max(starting_peak, max(P_{<=t})) - 1."""
    if len(prices) == 0:
        return np.zeros(0), starting_peak
    peaks = np.maximum.accumulate(np.concatenate([[starting_peak], prices]))[1:]
    peaks = np.maximum(peaks, starting_peak)
    dd = prices / peaks - 1.0
    return dd, float(peaks[-1])


def build_drawdown_series(
    historical_prices: Sequence[float],
    forecast_prices: Sequence[float],
    lower_ci: Optional[Sequence[float]] = None,
    upper_ci: Optional[Sequence[float]] = None,
    historical_dates: Optional[Sequence[str]] = None,
    forecast_dates: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Drawdown series for history + forecast, with CI bands on the forecast.

    The running peak is carried from history into the forecast so the forecast
    drawdown does not reset; lower_ci and upper_ci each carry their own
    independent running peak from the same historical maximum.
    """
    hist = np.asarray(list(historical_prices), dtype=float)
    fp = np.asarray(list(forecast_prices), dtype=float)

    hist_dd, hist_peak = _running_drawdown(hist, starting_peak=float(hist[0]) if len(hist) else 0.0)
    fc_dd, _ = _running_drawdown(fp, starting_peak=hist_peak)

    out: Dict[str, Any] = {
        "historical": {
            "dates": list(historical_dates) if historical_dates is not None else None,
            "values": hist_dd.tolist(),
        },
        "forecast": {
            "dates": list(forecast_dates) if forecast_dates is not None else None,
            "values": fc_dd.tolist(),
        },
    }

    if lower_ci is not None and upper_ci is not None:
        lo = np.asarray(list(lower_ci), dtype=float)
        up = np.asarray(list(upper_ci), dtype=float)
        if len(lo) == len(fp) and len(up) == len(fp):
            lo_dd, _ = _running_drawdown(lo, starting_peak=hist_peak)
            up_dd, _ = _running_drawdown(up, starting_peak=hist_peak)
            # On the loss side, lower_ci prices => deeper drawdowns. Return them labelled
            # by magnitude: "lower" is the more-negative band.
            out["forecast"]["lower"] = np.minimum(lo_dd, up_dd).tolist()
            out["forecast"]["upper"] = np.maximum(lo_dd, up_dd).tolist()

    return out


def _month_key(ts: pd.Timestamp) -> str:
    return f"{ts.year:04d}-{ts.month:02d}"


_MAX_MONTHLY_RETURN = 2.0  # ±200% per month; anything beyond is data corruption


def _clamp_return(ret: float) -> float:
    if not np.isfinite(ret) or abs(ret) > _MAX_MONTHLY_RETURN:
        return 0.0
    return ret


def _monthly_from_series(dates: Sequence[str], prices: Sequence[float]) -> List[Dict[str, Any]]:
    """Compute per-calendar-month (end/start - 1) returns from aligned dates + prices."""
    if not dates or not prices or len(dates) != len(prices):
        return []
    ts = pd.to_datetime(list(dates))
    px = np.asarray(list(prices), dtype=float)
    series = pd.Series(px, index=ts).sort_index()

    rows: List[Dict[str, Any]] = []
    for month_key, group in series.groupby(series.index.map(_month_key)):
        if len(group) < 2:
            rows.append({"month": month_key, "return": 0.0, "partial": True, "n_days": int(len(group))})
            continue
        ret = _clamp_return(float(group.iloc[-1] / group.iloc[0] - 1.0))
        rows.append({"month": month_key, "return": ret, "partial": False, "n_days": int(len(group))})
    return rows


def build_monthly_returns(
    historical_dates: Sequence[str],
    historical_prices: Sequence[float],
    forecast_dates: Sequence[str],
    forecast_prices: Sequence[float],
    lower_ci: Optional[Sequence[float]] = None,
    upper_ci: Optional[Sequence[float]] = None,
    trailing_months: int = 12,
) -> Dict[str, Any]:
    """Historical and forecast monthly returns with optional lower/upper bands.

    Historical: trailing `trailing_months` calendar months.
    Forecast: every calendar month fully or partially covered by the horizon,
              with `partial=true` if the month has < the minimum number of
              trading days expected.
    """
    hist_rows = _monthly_from_series(historical_dates, historical_prices)
    hist_rows = hist_rows[-int(trailing_months):] if trailing_months > 0 else hist_rows

    fc_rows = _monthly_from_series(forecast_dates, forecast_prices)

    # If the forecast's first month shares a YYYY-MM with the last historical day,
    # the forecast-side partial-month return would miss the carry from the last
    # historical price. Splice in the anchor: start = last historical price of
    # that month, end = last forecast price of the same month.
    if fc_rows and historical_dates and historical_prices:
        hist_ts = pd.to_datetime(list(historical_dates))
        fc_ts = pd.to_datetime(list(forecast_dates))
        shared_month = _month_key(hist_ts[-1])
        if fc_rows[0]["month"] == shared_month:
            fc_mask = pd.Series(fc_ts).apply(_month_key) == shared_month
            fc_month_prices = np.asarray(list(forecast_prices), dtype=float)[fc_mask.values]
            if len(fc_month_prices) >= 1:
                full_start = float(historical_prices[-1])
                full_end = float(fc_month_prices[-1])
                fc_rows[0]["return"] = _clamp_return(float(full_end / full_start - 1.0))
                fc_rows[0]["spliced_with_history"] = True

    if lower_ci is not None and upper_ci is not None and len(lower_ci) == len(forecast_prices) and len(upper_ci) == len(forecast_prices):
        lo_rows = _monthly_from_series(forecast_dates, lower_ci)
        up_rows = _monthly_from_series(forecast_dates, upper_ci)
        lo_map = {r["month"]: r["return"] for r in lo_rows}
        up_map = {r["month"]: r["return"] for r in up_rows}
        for r in fc_rows:
            m = r["month"]
            lo = lo_map.get(m)
            up = up_map.get(m)
            if lo is not None and up is not None:
                r["lower"] = min(lo, up)
                r["upper"] = max(lo, up)

    return {
        "historical": hist_rows,
        "forecast": fc_rows,
    }
