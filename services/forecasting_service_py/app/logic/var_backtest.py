"""Value-at-Risk backtesting / coverage tests.

Pure-python, numpy + scipy only. No DB, no network, no model dependency:
callers supply a realized-return series and a predicted-VaR series (or the
raw simulated price-path matrix) and get back exception counts plus the
standard regulatory coverage tests.

Sign convention (matches ``tensor_network_risk.tensor_network_risk``):
VaR_95 is the *signed* 5th-percentile of the return distribution, i.e. a
negative number such as ``-0.03``. An exception ("breach") on day t is
therefore ``realized_return[t] < predicted_var[t]`` — the realized loss was
deeper than the threshold the model said would only be breached
``(1 - confidence)`` of the time.

Tests implemented:
  - Kupiec POF (unconditional coverage)        — chi^2(1)
  - Christoffersen independence                — chi^2(1)
  - Christoffersen conditional coverage        — chi^2(2) = POF + independence
  - Basel "traffic light" zone                 — binomial CDF zones
  - Observed Expected Shortfall (CVaR) on breach days

References: Kupiec (1995), Christoffersen (1998), Basel Committee (1996/2019).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Sequence, Union

import numpy as np
from scipy.special import xlogy  # xlogy(0, 0) == 0, the convention we need
from scipy.stats import binom, chi2

logger = logging.getLogger(__name__)

ArrayLike = Union[Sequence[float], np.ndarray, float]


# --------------------------------------------------------------------------- #
# VaR extraction from a simulated path matrix
# --------------------------------------------------------------------------- #
def extract_var_from_paths(
    paths: np.ndarray,
    base: float = 1.0,
    confidence: float = 0.95,
) -> np.ndarray:
    """Per-horizon VaR (signed simple return) from a simulated price matrix.

    ``paths`` has shape (T, S): T forecast horizons, S simulated paths, each
    indexed so that ``base`` is the value at t=0 (this is exactly the local
    ``paths`` matrix built in ``portfolio_logic._fan_from_mps`` and
    ``tensor_network_risk``). Returns a length-T array where element t is the
    cumulative VaR from t=0 to horizon t, expressed as a simple return
    (negative number).

    For a 1-day backtest pass a (1, S) matrix and read element 0.
    """
    arr = np.asarray(paths, dtype=float)
    if arr.ndim != 2:
        raise ValueError(f"paths must be 2-D (T, S); got shape {arr.shape}")
    if not (0.0 < confidence < 1.0):
        raise ValueError(f"confidence must be in (0, 1); got {confidence}")
    if base <= 0:
        raise ValueError(f"base must be positive; got {base}")
    q = (1.0 - confidence) * 100.0
    price_q = np.percentile(arr, q, axis=1)
    return price_q / base - 1.0


# --------------------------------------------------------------------------- #
# Coverage tests
# --------------------------------------------------------------------------- #
def kupiec_pof(n_obs: int, n_exceptions: int, alpha: float = 0.05,
               confidence: float = 0.95) -> Dict[str, Any]:
    """Kupiec Proportion-of-Failures (unconditional coverage) test.

    H0: the true breach probability equals ``p = 1 - confidence``.
    The likelihood-ratio statistic is asymptotically chi^2(1).
    """
    if n_obs <= 0:
        raise ValueError("n_obs must be positive")
    if not (0 <= n_exceptions <= n_obs):
        raise ValueError("n_exceptions must be in [0, n_obs]")
    p = 1.0 - confidence
    x = float(n_exceptions)
    n = float(n_obs)
    pi_hat = x / n

    # log-likelihood under H0 (rate fixed at p) vs the unrestricted MLE (pi_hat).
    # xlogy(k, q) == k * log(q) with the convention 0 * log(0) = 0, so x=0 and
    # x=n are handled without NaNs.
    ll_null = xlogy(x, p) + xlogy(n - x, 1.0 - p)
    ll_alt = xlogy(x, pi_hat) + xlogy(n - x, 1.0 - pi_hat)
    stat = max(-2.0 * (ll_null - ll_alt), 0.0)
    p_value = float(chi2.sf(stat, df=1))
    return {
        "test": "Kupiec POF (unconditional coverage)",
        "statistic": float(stat),
        "p_value": p_value,
        "df": 1,
        "reject": bool(p_value < alpha),
        "observed_rate": pi_hat,
        "expected_rate": p,
    }


def christoffersen(breaches: Sequence[bool], alpha: float = 0.05,
                   confidence: float = 0.95) -> Dict[str, Any]:
    """Christoffersen independence + conditional-coverage tests.

    Independence (chi^2(1)) tests whether breaches cluster (a first-order
    Markov chain on the breach indicator). Conditional coverage (chi^2(2)) is
    the sum of the Kupiec POF statistic and the independence statistic, so it
    jointly tests correct frequency *and* independence.
    """
    b = np.asarray(breaches).astype(bool).ravel()
    n_obs = int(b.size)

    # First-order transition counts of the breach indicator.
    n00 = n01 = n10 = n11 = 0
    for prev, cur in zip(b[:-1], b[1:]):
        if not prev and not cur:
            n00 += 1
        elif not prev and cur:
            n01 += 1
        elif prev and not cur:
            n10 += 1
        else:
            n11 += 1

    pi01 = n01 / (n00 + n01) if (n00 + n01) > 0 else 0.0
    pi11 = n11 / (n10 + n11) if (n10 + n11) > 0 else 0.0
    pi = (n01 + n11) / (n00 + n01 + n10 + n11) if (n00 + n01 + n10 + n11) > 0 else 0.0

    ll_null = xlogy(n01 + n11, pi) + xlogy(n00 + n10, 1.0 - pi)
    ll_alt = (xlogy(n01, pi01) + xlogy(n00, 1.0 - pi01)
              + xlogy(n11, pi11) + xlogy(n10, 1.0 - pi11))
    lr_ind = max(-2.0 * (ll_null - ll_alt), 0.0)
    p_ind = float(chi2.sf(lr_ind, df=1))

    x = int(b.sum())
    pof = kupiec_pof(n_obs, x, alpha=alpha, confidence=confidence)
    lr_cc = pof["statistic"] + lr_ind
    p_cc = float(chi2.sf(lr_cc, df=2))

    return {
        "independence": {
            "test": "Christoffersen independence",
            "statistic": float(lr_ind),
            "p_value": p_ind,
            "df": 1,
            "reject": bool(p_ind < alpha),
        },
        "conditional_coverage": {
            "test": "Christoffersen conditional coverage",
            "statistic": float(lr_cc),
            "p_value": p_cc,
            "df": 2,
            "reject": bool(p_cc < alpha),
        },
        "transitions": {"n00": n00, "n01": n01, "n10": n10, "n11": n11},
    }


def basel_traffic_light(n_obs: int, n_exceptions: int,
                        confidence: float = 0.95) -> Dict[str, Any]:
    """Basel "traffic light" zone via the binomial CDF.

    Green   : P(X <= x) < 0.95
    Yellow  : 0.95 <= P(X <= x) < 0.9999
    Red     : P(X <= x) >= 0.9999

    Reproduces the published Basel table for the canonical n=250, p=0.01 case
    (x<=4 green, 5..9 yellow, >=10 red) for any (n, confidence).
    """
    p = 1.0 - confidence
    cdf = float(binom.cdf(n_exceptions, n_obs, p))
    if cdf < 0.95:
        zone = "green"
    elif cdf < 0.9999:
        zone = "yellow"
    else:
        zone = "red"
    return {"zone": zone, "cumulative_probability": cdf}


def expected_shortfall(realized: ArrayLike, var_threshold: ArrayLike) -> Optional[float]:
    """Observed Expected Shortfall (CVaR): mean realized return on breach days.

    Returns None when there are no breaches (ES undefined).
    """
    r = np.asarray(realized, dtype=float).ravel()
    v = np.broadcast_to(np.asarray(var_threshold, dtype=float), r.shape)
    mask = r < v
    if not mask.any():
        return None
    return float(r[mask].mean())


# --------------------------------------------------------------------------- #
# End-to-end backtest
# --------------------------------------------------------------------------- #
def run_var_backtest(
    realized_returns: ArrayLike,
    predicted_var: ArrayLike,
    confidence: float = 0.95,
    alpha: float = 0.05,
    dates: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Backtest a predicted-VaR series against realized returns.

    ``predicted_var`` may be a scalar (constant threshold applied to every day)
    or an array aligned 1:1 with ``realized_returns``. Both are *signed*
    returns; a breach is ``realized < predicted_var``.

    Returns a JSON-serialisable dict with exception counts, Kupiec /
    Christoffersen / Basel results, observed ES, an overall ``model_passes``
    verdict, and the per-day ``series`` for plotting.
    """
    if not (0.0 < confidence < 1.0):
        raise ValueError(f"confidence must be in (0, 1); got {confidence}")
    r = np.asarray(realized_returns, dtype=float).ravel()
    if r.size == 0:
        raise ValueError("realized_returns is empty")
    v = np.broadcast_to(np.asarray(predicted_var, dtype=float).ravel()
                        if np.ndim(predicted_var) else np.asarray(predicted_var, dtype=float),
                        r.shape).astype(float)
    if v.shape != r.shape:
        raise ValueError(
            f"predicted_var length {v.shape} does not match realized_returns {r.shape}"
        )

    p = 1.0 - confidence
    breaches = r < v
    x = int(breaches.sum())
    n = int(r.size)

    pof = kupiec_pof(n, x, alpha=alpha, confidence=confidence)
    chris = christoffersen(breaches, alpha=alpha, confidence=confidence)
    basel = basel_traffic_light(n, x, confidence=confidence)
    es = expected_shortfall(r, v)

    model_passes = (not pof["reject"]) and (not chris["conditional_coverage"]["reject"])

    return {
        "confidence": confidence,
        "alpha": alpha,
        "n_observations": n,
        "exceptions": x,
        "expected_exceptions": round(n * p, 2),
        "breach_rate": x / n,
        "expected_breach_rate": p,
        "kupiec": pof,
        "christoffersen": chris,
        "basel_traffic_light": basel,
        "observed_expected_shortfall": es,
        "model_passes": bool(model_passes),
        "series": {
            "date": list(dates) if dates is not None else None,
            "realized_return": r.tolist(),
            "var_threshold": v.tolist(),
            "breach": breaches.tolist(),
        },
    }
