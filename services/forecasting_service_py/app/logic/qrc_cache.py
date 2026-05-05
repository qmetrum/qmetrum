"""Per-ticker cache of auto-tuned QRC configs.

Design (per the option-2 plan agreed with the user):

  - Auto-tune is expensive (~100s per ticker) and does not need to run nightly.
    The caching contract is: tune once per ticker, persist the winning config
    and its walk-forward-CV metrics, reuse until the config is considered stale.
  - Staleness is checked on every load. Three triggers, any one is sufficient:
      (a) cache age > STALE_AGE_DAYS (default 7) — matches the observed rate of
          regime change in liquid equities.
      (b) training series has grown more than STALE_GROWTH_FRACTION (default 20%)
          since the cache was written — new data should get a fresh search.
      (c) live trailing RMSE (optional input) exceeds STALE_RMSE_MULTIPLIER *
          the cached CV RMSE — regime break detector.
  - Safety net: any failure in load (missing file, parse error, schema drift)
    silently returns a default config. HybridForecaster should never fail to
    train just because the QRC cache is broken.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.logic.quantum_reservoir import QRCConfig

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(__file__).resolve().parent.parent / "cache" / "qrc_configs"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

STALE_AGE_DAYS: float = 7.0
STALE_GROWTH_FRACTION: float = 0.20
STALE_RMSE_MULTIPLIER: float = 1.5
_MS_PER_DAY = 86_400_000.0

# Default fallback config: empirically a reasonable starting point from the AAPL tune.
DEFAULT_CONFIG = QRCConfig(
    n_qubits=6,
    reservoir_depth=2,
    reservoir_seeds=(7, 13, 29),
    input_scale=0.5,
    leak_rate=0.2,
    ridge_alpha=0.1,
    washout_steps=50,
)


def _cache_path(ticker: str) -> Path:
    safe = "".join(c for c in ticker.upper() if c.isalnum() or c in "._-")
    return _CACHE_DIR / f"{safe or 'UNKNOWN'}.json"


def _config_to_dict(cfg: QRCConfig) -> Dict[str, Any]:
    d = asdict(cfg)
    d["reservoir_seeds"] = list(cfg.reservoir_seeds)
    return d


def _dict_to_config(d: Dict[str, Any]) -> QRCConfig:
    return QRCConfig(
        n_qubits=int(d.get("n_qubits", DEFAULT_CONFIG.n_qubits)),
        reservoir_depth=int(d.get("reservoir_depth", DEFAULT_CONFIG.reservoir_depth)),
        reservoir_seeds=tuple(int(s) for s in d.get("reservoir_seeds", DEFAULT_CONFIG.reservoir_seeds)),
        input_scale=float(d.get("input_scale", DEFAULT_CONFIG.input_scale)),
        leak_rate=float(d.get("leak_rate", DEFAULT_CONFIG.leak_rate)),
        ridge_alpha=float(d.get("ridge_alpha", DEFAULT_CONFIG.ridge_alpha)),
        lookback=int(d.get("lookback", DEFAULT_CONFIG.lookback)),
        washout_steps=int(d.get("washout_steps", DEFAULT_CONFIG.washout_steps)),
        use_zz=bool(d.get("use_zz", DEFAULT_CONFIG.use_zz)),
        use_xy_pairs=bool(d.get("use_xy_pairs", DEFAULT_CONFIG.use_xy_pairs)),
    )


def save_cached_config(
    ticker: str,
    config: QRCConfig,
    validation_scores: Dict[str, float],
    n_training_points: int,
) -> Dict[str, Any]:
    payload = {
        "ticker": ticker,
        "config": _config_to_dict(config),
        "validation_scores": {
            "rmse": float(validation_scores.get("rmse", float("nan"))),
            "mape": float(validation_scores.get("mape", float("nan"))),
            "mase": float(validation_scores.get("mase", float("nan"))),
        },
        "n_training_points": int(n_training_points),
        "trained_at_ms": int(time.time() * 1000),
    }
    _cache_path(ticker).write_text(json.dumps(payload))
    return payload


def _is_stale(
    payload: Dict[str, Any],
    current_n_points: int,
    trailing_rmse: Optional[float],
) -> List[str]:
    """Return the list of staleness triggers hit. Empty list = fresh."""
    triggers: List[str] = []
    age_ms = time.time() * 1000 - float(payload.get("trained_at_ms", 0))
    if age_ms / _MS_PER_DAY > STALE_AGE_DAYS:
        triggers.append(f"age>{STALE_AGE_DAYS:.0f}d")

    trained_n = int(payload.get("n_training_points", 0))
    if trained_n > 0 and current_n_points > trained_n * (1.0 + STALE_GROWTH_FRACTION):
        triggers.append(
            f"series_grew>{int(STALE_GROWTH_FRACTION * 100)}%"
        )

    cached_rmse = float(payload.get("validation_scores", {}).get("rmse", float("nan")))
    if (
        trailing_rmse is not None
        and cached_rmse == cached_rmse  # not NaN
        and cached_rmse > 0
        and trailing_rmse > STALE_RMSE_MULTIPLIER * cached_rmse
    ):
        triggers.append(
            f"trailing_rmse>{STALE_RMSE_MULTIPLIER}x_cached"
        )
    return triggers


def load_cached_config(
    ticker: str,
    current_n_points: int,
    trailing_rmse: Optional[float] = None,
) -> Dict[str, Any]:
    """Load cached config, reporting freshness. Always returns a usable config.

    Return shape:
        {
            "config": QRCConfig,
            "source": "cache" | "default_fallback" | "default_stale_cache",
            "payload": original_cache_payload_or_None,
            "stale_triggers": [...],
        }
    """
    path = _cache_path(ticker)
    if not path.exists():
        return {
            "config": DEFAULT_CONFIG,
            "source": "default_fallback",
            "payload": None,
            "stale_triggers": ["no_cache"],
        }
    try:
        payload = json.loads(path.read_text())
    except Exception as e:
        logger.warning("QRC cache for %s unreadable: %s. Using default.", ticker, e)
        return {
            "config": DEFAULT_CONFIG,
            "source": "default_fallback",
            "payload": None,
            "stale_triggers": ["unreadable_cache"],
        }

    triggers = _is_stale(payload, current_n_points, trailing_rmse)
    try:
        cfg = _dict_to_config(payload["config"])
    except Exception as e:
        logger.warning("QRC cache schema drift for %s: %s. Using default.", ticker, e)
        return {
            "config": DEFAULT_CONFIG,
            "source": "default_fallback",
            "payload": None,
            "stale_triggers": ["schema_drift"],
        }

    source = "cache" if not triggers else "default_stale_cache"
    return {
        "config": cfg if not triggers else DEFAULT_CONFIG,
        "source": source,
        "payload": payload,
        "stale_triggers": triggers,
    }


def list_cached_tickers() -> List[Dict[str, Any]]:
    out = []
    for p in sorted(_CACHE_DIR.glob("*.json")):
        try:
            d = json.loads(p.read_text())
            out.append({
                "ticker": d.get("ticker"),
                "trained_at_ms": d.get("trained_at_ms"),
                "n_training_points": d.get("n_training_points"),
                "validation_scores": d.get("validation_scores", {}),
            })
        except Exception:
            continue
    return out


def retune_and_save(
    ticker: str,
    prices: List[float],
    **tune_kwargs,
) -> Dict[str, Any]:
    """Run auto_tune_qrc, persist best config and metrics, return the saved payload.

    Called from the weekly re-tune job. Each ticker is independent; callers can
    parallelise via ProcessPoolExecutor (CPU-bound numpy, GIL-limited) or
    ThreadPoolExecutor if memory pressure dominates. See retune_endpoint in main.py.
    """
    from app.logic.quantum_reservoir import auto_tune_qrc

    tuning = auto_tune_qrc(prices, **tune_kwargs)
    best = tuning.get("best") or {}
    cfg_dict = best.get("config") or {}
    cfg = _dict_to_config(cfg_dict)
    scores = {
        "rmse": best.get("rmse", float("nan")),
        "mape": best.get("mape", float("nan")),
        "mase": best.get("mase", float("nan")),
    }
    payload = save_cached_config(ticker, cfg, scores, n_training_points=len(prices))
    payload["tune_runtime_ms"] = tuning.get("runtime_ms")
    payload["grid_size"] = tuning.get("grid_size")
    return payload
