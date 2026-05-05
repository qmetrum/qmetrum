"""Quantum Reservoir Computing for time-series forecasting.

Fujii-Nakajima-style reservoir implemented classically as statevector
evolution on n qubits. Design choices, with citations in parentheses:

  Time-delay encoding (Martinez-Pena et al. 2021) — qubit k receives
  Ry(input_scale * x_{t-k}) so the very first layer embeds the last n
  lags of the series into the quantum state. Biggest single quality win
  vs. applying the same x_t to every qubit.

  Fixed random entangling unitary U_res per time step, seeded for
  reproducibility. State carries across steps; unitary dynamics give
  fading memory via entanglement spreading.

  Multi-basis observables: <X_i>, <Y_i>, <Z_i> single-qubit + all <Z_iZ_j>
  and a subset of <X_iX_j>, <Y_iY_j> pairs. For n=6 this yields ~48
  features per step per reservoir. Computed directly from the statevector
  — no basis rotations / separate shots.

  Ensemble of K seeded reservoirs. Their features are concatenated; a
  single ridge solves over the union, letting the readout ignore any
  reservoir that didn't align with the signal. K=3 is a good default.

  Washout: the first `washout_steps` steps are discarded from training
  because the initial |0...0> state is arbitrary and contaminates the
  first few reservoir states. 50 is the RC-literature default.

  Leak rate applies at the feature level, not the statevector level.
  Unitary quantum reservoirs can't have classical leak without moving
  to density-matrix / open-system formalism (4^n memory). Feature-level
  leak is what most QRC papers do in practice. Default leak_rate=0
  preserves pure-unitary reservoir semantics.

All math done in numpy on a 2^n complex statevector — a 6-qubit
reservoir runs many thousands of steps per second per seed, so the
auto-tuner stays tractable even with ensembles.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from itertools import combinations, product
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Gate utilities
# --------------------------------------------------------------------------

def _ry_matrix(theta: float) -> np.ndarray:
    c, s = math.cos(theta / 2.0), math.sin(theta / 2.0)
    return np.array([[c, -s], [s, c]], dtype=complex)


def _rz_matrix(theta: float) -> np.ndarray:
    e = np.exp(-1j * theta / 2.0)
    return np.array([[e, 0], [0, e.conjugate()]], dtype=complex)


def _apply_single_qubit_gate(state: np.ndarray, gate: np.ndarray, qubit: int, n_qubits: int) -> np.ndarray:
    shape = [2] * n_qubits
    tensor = state.reshape(shape)
    tensor = np.moveaxis(tensor, qubit, 0).reshape(2, -1)
    tensor = gate @ tensor
    tensor = tensor.reshape([2] + [2] * (n_qubits - 1))
    tensor = np.moveaxis(tensor, 0, qubit)
    return tensor.reshape(-1)


def _apply_cnot(state: np.ndarray, control: int, target: int, n_qubits: int) -> np.ndarray:
    out = state.copy()
    flat_idx = np.arange(len(state))
    c_bit = (flat_idx >> (n_qubits - 1 - control)) & 1
    flipped = flat_idx ^ (1 << (n_qubits - 1 - target))
    mask = c_bit == 1
    out[flat_idx[mask]] = state[flipped[mask]]
    return out


# --------------------------------------------------------------------------
# Reservoir unitary + input encoding
# --------------------------------------------------------------------------

def _build_reservoir_layer(n_qubits: int, depth: int, seed: int) -> List[Tuple[str, tuple, float]]:
    rng = np.random.default_rng(int(seed))
    instructions: List[Tuple[str, tuple, float]] = []
    for _ in range(int(depth)):
        for q in range(n_qubits):
            instructions.append(("ry", (q,), float(rng.uniform(-np.pi, np.pi))))
            instructions.append(("rz", (q,), float(rng.uniform(-np.pi, np.pi))))
        for q in range(n_qubits - 1):
            instructions.append(("cnot", (q, q + 1), 0.0))
        if n_qubits > 2:
            instructions.append(("cnot", (n_qubits - 1, 0), 0.0))
    return instructions


def _apply_instructions(state: np.ndarray, instructions: Sequence[Tuple[str, tuple, float]], n_qubits: int) -> np.ndarray:
    for gate, qubits, theta in instructions:
        if gate == "ry":
            state = _apply_single_qubit_gate(state, _ry_matrix(theta), qubits[0], n_qubits)
        elif gate == "rz":
            state = _apply_single_qubit_gate(state, _rz_matrix(theta), qubits[0], n_qubits)
        elif gate == "cnot":
            state = _apply_cnot(state, qubits[0], qubits[1], n_qubits)
    return state


def _encode_time_delay(state: np.ndarray, x_lags: np.ndarray, input_scale: float, n_qubits: int) -> np.ndarray:
    """Apply Ry(scale * x_{t-k}) to qubit k, k = 0..n-1. x_lags[k] is x_{t-k}."""
    for q in range(n_qubits):
        gate = _ry_matrix(float(x_lags[q]) * input_scale)
        state = _apply_single_qubit_gate(state, gate, q, n_qubits)
    return state


# --------------------------------------------------------------------------
# Observables
# --------------------------------------------------------------------------

def _z_expectations(state: np.ndarray, n_qubits: int) -> np.ndarray:
    probs = np.abs(state) ** 2
    idx = np.arange(len(state))
    out = np.zeros(n_qubits)
    for q in range(n_qubits):
        bit = (idx >> (n_qubits - 1 - q)) & 1
        out[q] = float(probs[bit == 0].sum() - probs[bit == 1].sum())
    return out


def _x_expectations(state: np.ndarray, n_qubits: int) -> np.ndarray:
    """<X_q> = 2 Re(sum over pairs where qubit q differs by 1 bit: conj(a0) * a1)."""
    out = np.zeros(n_qubits)
    for q in range(n_qubits):
        mask = 1 << (n_qubits - 1 - q)
        idx = np.arange(len(state))
        qbit = (idx >> (n_qubits - 1 - q)) & 1
        zero_idx = idx[qbit == 0]
        one_idx = zero_idx ^ mask
        out[q] = float(2.0 * np.real(np.sum(np.conj(state[zero_idx]) * state[one_idx])))
    return out


def _y_expectations(state: np.ndarray, n_qubits: int) -> np.ndarray:
    """<Y_q> = 2 Im(sum over pairs: conj(a0) * a1) with sign convention for Y."""
    out = np.zeros(n_qubits)
    for q in range(n_qubits):
        mask = 1 << (n_qubits - 1 - q)
        idx = np.arange(len(state))
        qbit = (idx >> (n_qubits - 1 - q)) & 1
        zero_idx = idx[qbit == 0]
        one_idx = zero_idx ^ mask
        out[q] = float(2.0 * np.imag(np.sum(np.conj(state[zero_idx]) * state[one_idx])))
    return out


def _zz_expectations(state: np.ndarray, n_qubits: int) -> np.ndarray:
    probs = np.abs(state) ** 2
    idx = np.arange(len(state))
    pairs = list(combinations(range(n_qubits), 2))
    out = np.zeros(len(pairs))
    for k, (i, j) in enumerate(pairs):
        bi = (idx >> (n_qubits - 1 - i)) & 1
        bj = (idx >> (n_qubits - 1 - j)) & 1
        parity = bi ^ bj
        out[k] = float(probs[parity == 0].sum() - probs[parity == 1].sum())
    return out


def _xx_nn_expectations(state: np.ndarray, n_qubits: int) -> np.ndarray:
    """<X_i X_{i+1}> for nearest-neighbour pairs only (keeps feature count modest)."""
    out = np.zeros(max(0, n_qubits - 1))
    for i in range(n_qubits - 1):
        mask = (1 << (n_qubits - 1 - i)) | (1 << (n_qubits - 1 - (i + 1)))
        idx = np.arange(len(state))
        flipped = idx ^ mask
        # X_i X_j |b...> = |b with bits i,j flipped>
        # <X_iX_j> = sum_b conj(a_b) * a_{b flipped}
        out[i] = float(np.real(np.sum(np.conj(state) * state[flipped])))
    return out


def _yy_nn_expectations(state: np.ndarray, n_qubits: int) -> np.ndarray:
    """<Y_i Y_{i+1}> for nearest-neighbour pairs. Y_iY_j flips both bits with a sign depending on parity."""
    out = np.zeros(max(0, n_qubits - 1))
    for i in range(n_qubits - 1):
        mask_i = 1 << (n_qubits - 1 - i)
        mask_j = 1 << (n_qubits - 1 - (i + 1))
        idx = np.arange(len(state))
        flipped = idx ^ (mask_i | mask_j)
        bi_old = (idx >> (n_qubits - 1 - i)) & 1
        bj_old = (idx >> (n_qubits - 1 - (i + 1))) & 1
        # Y|0> = i|1>, Y|1> = -i|0>. Y_iY_j phase = i * i * (sign_i)(sign_j),
        # where sign_k = +1 if old bit = 0 else -1.
        sign = (1 - 2 * bi_old) * (1 - 2 * bj_old)  # ±1
        # i*i = -1, so overall factor = -sign
        out[i] = float(np.real(np.sum(np.conj(state) * state[flipped] * (-sign))))
    return out


def _all_features_from_state(state: np.ndarray, n_qubits: int, use_zz: bool, use_xy_pairs: bool) -> np.ndarray:
    parts = [_z_expectations(state, n_qubits), _x_expectations(state, n_qubits), _y_expectations(state, n_qubits)]
    if use_zz:
        parts.append(_zz_expectations(state, n_qubits))
    if use_xy_pairs and n_qubits > 1:
        parts.append(_xx_nn_expectations(state, n_qubits))
        parts.append(_yy_nn_expectations(state, n_qubits))
    return np.concatenate(parts)


# --------------------------------------------------------------------------
# Forecaster
# --------------------------------------------------------------------------

@dataclass
class QRCConfig:
    n_qubits: int = 6
    reservoir_depth: int = 2
    reservoir_seeds: Tuple[int, ...] = (7, 13, 29)   # ensemble
    input_scale: float = 1.0
    leak_rate: float = 0.0                           # feature-level leak; 0 = pure unitary
    ridge_alpha: float = 1e-2
    lookback: int = 1                                # number of past x values fed directly to readout
    washout_steps: int = 50
    use_zz: bool = True
    use_xy_pairs: bool = True


class QuantumReservoirForecaster:
    """Ensemble quantum reservoir forecaster with ridge readout."""

    def __init__(self, config: Optional[QRCConfig] = None):
        self.cfg = config or QRCConfig()
        self._ensemble_instructions = [
            _build_reservoir_layer(self.cfg.n_qubits, self.cfg.reservoir_depth, seed)
            for seed in self.cfg.reservoir_seeds
        ]
        self._W: Optional[np.ndarray] = None
        self._x_mean: float = 0.0
        self._x_std: float = 1.0
        self._fit_states: List[np.ndarray] = []

    # ----- per-reservoir feature extraction -----
    def _reservoir_features(self, x_series: np.ndarray, instructions: Sequence[Tuple[str, tuple, float]]) -> Tuple[np.ndarray, np.ndarray]:
        n = self.cfg.n_qubits
        state = np.zeros(1 << n, dtype=complex)
        state[0] = 1.0
        feats_per_step = []
        prev = None
        # Pre-build time-delay lag buffer
        lag_buffer = np.zeros(n)
        for t, x_t in enumerate(x_series):
            # Shift buffer: x_lags[0] = x_t, x_lags[1] = x_{t-1}, ...
            lag_buffer = np.concatenate([[float(x_t)], lag_buffer[:-1]])
            state = _encode_time_delay(state, lag_buffer, self.cfg.input_scale, n)
            state = _apply_instructions(state, instructions, n)
            feats = _all_features_from_state(state, n, self.cfg.use_zz, self.cfg.use_xy_pairs)
            if prev is not None and self.cfg.leak_rate > 0.0:
                feats = (1.0 - self.cfg.leak_rate) * feats + self.cfg.leak_rate * prev
            prev = feats
            feats_per_step.append(feats)
        return np.asarray(feats_per_step), state

    def _ensemble_features(self, x_series: np.ndarray) -> Tuple[np.ndarray, List[np.ndarray]]:
        parts, terminal_states = [], []
        for instr in self._ensemble_instructions:
            feats, final_state = self._reservoir_features(x_series, instr)
            parts.append(feats)
            terminal_states.append(final_state)
        return np.hstack(parts), terminal_states

    def _design_matrix(self, feats: np.ndarray, x_norm: np.ndarray) -> np.ndarray:
        T = feats.shape[0]
        lb = self.cfg.lookback
        past = np.zeros((T, lb))
        for k in range(1, lb + 1):
            past[k:, k - 1] = x_norm[:T - k]
        bias = np.ones((T, 1))
        return np.hstack([feats, past, bias])

    def fit(self, x_series: np.ndarray) -> "QuantumReservoirForecaster":
        x = np.asarray(x_series, dtype=float)
        if len(x) < max(20, self.cfg.washout_steps + 10):
            raise ValueError(f"QRC needs >= {self.cfg.washout_steps + 10} training points")

        self._x_mean = float(np.mean(x))
        self._x_std = float(np.std(x) or 1.0)
        x_norm = (x - self._x_mean) / self._x_std

        all_feats, terminal_states = self._ensemble_features(x_norm)
        self._fit_states = terminal_states
        self._last_x_norm = float(x_norm[-1])
        self._last_x_lag_buffer = x_norm[-self.cfg.n_qubits:][::-1]
        if len(self._last_x_lag_buffer) < self.cfg.n_qubits:
            self._last_x_lag_buffer = np.concatenate(
                [self._last_x_lag_buffer, np.zeros(self.cfg.n_qubits - len(self._last_x_lag_buffer))]
            )

        # One-step-ahead: predict x_{t+1} from reservoir-feats_t + past lookback + bias
        X_design = self._design_matrix(all_feats[:-1], x_norm[:-1])
        y_target = x_norm[1:]

        # Washout: discard first N rows from training
        w = min(self.cfg.washout_steps, len(X_design) - 10)
        if w > 0:
            X_design = X_design[w:]
            y_target = y_target[w:]

        reg = self.cfg.ridge_alpha * np.eye(X_design.shape[1])
        self._W = np.linalg.solve(X_design.T @ X_design + reg, X_design.T @ y_target)
        return self

    def forecast(self, horizon: int) -> np.ndarray:
        if self._W is None:
            raise RuntimeError("fit() must be called before forecast()")
        n = self.cfg.n_qubits
        states = [s.copy() for s in self._fit_states]
        lag_buffer = self._last_x_lag_buffer.copy()
        last_x = self._last_x_norm
        past_buffer = list(lag_buffer)[:self.cfg.lookback]

        preds_norm: List[float] = []
        for _ in range(int(horizon)):
            # Advance lag buffer with most recent predicted value
            lag_buffer = np.concatenate([[last_x], lag_buffer[:-1]])
            ensemble_feats = []
            new_states = []
            for state, instr in zip(states, self._ensemble_instructions):
                state = _encode_time_delay(state, lag_buffer, self.cfg.input_scale, n)
                state = _apply_instructions(state, instr, n)
                ensemble_feats.append(_all_features_from_state(state, n, self.cfg.use_zz, self.cfg.use_xy_pairs))
                new_states.append(state)
            states = new_states

            feats = np.concatenate(ensemble_feats)
            past = np.zeros(self.cfg.lookback)
            for k in range(self.cfg.lookback):
                past[k] = past_buffer[-1 - k] if len(past_buffer) > k else 0.0
            x_row = np.concatenate([feats, past, [1.0]])
            y_hat = float(x_row @ self._W)
            preds_norm.append(y_hat)

            past_buffer.append(last_x)
            last_x = y_hat

        preds = np.asarray(preds_norm) * self._x_std + self._x_mean
        return preds


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------

def _rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.sqrt(np.mean((np.asarray(y_true) - np.asarray(y_pred)) ** 2)))


def _mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    yt, yp = np.asarray(y_true, dtype=float), np.asarray(y_pred, dtype=float)
    mask = np.abs(yt) > 1e-9
    if not mask.any():
        return float("nan")
    return float(np.mean(np.abs((yt[mask] - yp[mask]) / yt[mask])))


def _mase(y_true: np.ndarray, y_pred: np.ndarray, y_history: np.ndarray) -> float:
    """Mean Absolute Scaled Error against naive-persistence baseline on the training history."""
    y_true, y_pred, y_history = np.asarray(y_true), np.asarray(y_pred), np.asarray(y_history)
    if len(y_history) < 2:
        return float("nan")
    naive_mae = float(np.mean(np.abs(np.diff(y_history))))
    if naive_mae < 1e-12:
        return float("nan")
    return float(np.mean(np.abs(y_true - y_pred)) / naive_mae)


# --------------------------------------------------------------------------
# Auto-tuner
# --------------------------------------------------------------------------

def _precompute_reservoir_cache(prices: np.ndarray, cfg: QRCConfig) -> Dict[str, Any]:
    """Compute the full-series reservoir feature matrix and per-step states once per reservoir config.

    Reservoir dynamics are causal and alpha-independent, so this is reused across all
    walk-forward splits and all ridge_alpha values. Returns everything needed to fit+forecast
    at arbitrary split indices.
    """
    x_mean = float(np.mean(prices))
    x_std = float(np.std(prices) or 1.0)
    x_norm = (prices - x_mean) / x_std

    n = cfg.n_qubits
    T = len(x_norm)
    per_seed_feats: List[np.ndarray] = []
    per_seed_states: List[List[np.ndarray]] = []

    for seed in cfg.reservoir_seeds:
        instructions = _build_reservoir_layer(n, cfg.reservoir_depth, int(seed))
        state = np.zeros(1 << n, dtype=complex)
        state[0] = 1.0
        feats_list, states_list = [], []
        lag_buffer = np.zeros(n)
        prev_feats = None
        for t in range(T):
            lag_buffer = np.concatenate([[float(x_norm[t])], lag_buffer[:-1]])
            state = _encode_time_delay(state, lag_buffer, cfg.input_scale, n)
            state = _apply_instructions(state, instructions, n)
            states_list.append(state.copy())
            feats = _all_features_from_state(state, n, cfg.use_zz, cfg.use_xy_pairs)
            if prev_feats is not None and cfg.leak_rate > 0.0:
                feats = (1.0 - cfg.leak_rate) * feats + cfg.leak_rate * prev_feats
            prev_feats = feats
            feats_list.append(feats)
        per_seed_feats.append(np.asarray(feats_list))
        per_seed_states.append(states_list)

    ensemble_feats = np.hstack(per_seed_feats)
    return {
        "x_norm": x_norm, "x_mean": x_mean, "x_std": x_std,
        "ensemble_feats": ensemble_feats,
        "per_seed_states": per_seed_states,
    }


def _design_with_past(feats_slice: np.ndarray, x_norm: np.ndarray, lookback: int) -> np.ndarray:
    T = feats_slice.shape[0]
    past = np.zeros((T, lookback))
    for k in range(1, lookback + 1):
        past[k:, k - 1] = x_norm[:T - k]
    bias = np.ones((T, 1))
    return np.hstack([feats_slice, past, bias])


def _ridge_solve(X: np.ndarray, y: np.ndarray, alpha: float) -> np.ndarray:
    reg = alpha * np.eye(X.shape[1])
    return np.linalg.solve(X.T @ X + reg, X.T @ y)


def _forecast_from_cache(
    cache: Dict[str, Any],
    cfg: QRCConfig,
    W: np.ndarray,
    split: int,
    horizon: int,
) -> np.ndarray:
    """Roll reservoir states at time `split - 1` forward `horizon` steps."""
    n = cfg.n_qubits
    states = [s[split - 1].copy() for s in cache["per_seed_states"]]
    x_norm = cache["x_norm"]
    # Lag buffer as of time split-1 (most recent = x_{split-1})
    lag_buffer = np.zeros(n)
    for k in range(min(n, split)):
        lag_buffer[k] = x_norm[split - 1 - k]
    past_buffer = [x_norm[split - 1 - k] for k in range(min(cfg.lookback, split))]
    last_x = float(x_norm[split - 1])

    instr_per_seed = [_build_reservoir_layer(n, cfg.reservoir_depth, int(s)) for s in cfg.reservoir_seeds]
    preds_norm: List[float] = []
    for _ in range(int(horizon)):
        lag_buffer = np.concatenate([[last_x], lag_buffer[:-1]])
        ensemble_feats = []
        for i, (state, instr) in enumerate(zip(states, instr_per_seed)):
            state = _encode_time_delay(state, lag_buffer, cfg.input_scale, n)
            state = _apply_instructions(state, instr, n)
            states[i] = state
            ensemble_feats.append(_all_features_from_state(state, n, cfg.use_zz, cfg.use_xy_pairs))
        feats = np.concatenate(ensemble_feats)
        past = np.zeros(cfg.lookback)
        for k in range(cfg.lookback):
            past[k] = past_buffer[-1 - k] if len(past_buffer) > k else 0.0
        x_row = np.concatenate([feats, past, [1.0]])
        y_hat = float(x_row @ W)
        preds_norm.append(y_hat)
        past_buffer.append(last_x)
        last_x = y_hat
    return np.asarray(preds_norm) * cache["x_std"] + cache["x_mean"]


def _walk_forward_score_cached(
    prices: np.ndarray,
    cache: Dict[str, Any],
    cfg: QRCConfig,
    alpha: float,
    n_splits: int = 3,
    test_horizon: int = 10,
) -> Dict[str, float]:
    T = len(prices)
    min_train = max(cfg.washout_steps + 30, T - n_splits * test_horizon)
    if min_train >= T - test_horizon:
        min_train = max(cfg.washout_steps + 30, int(T * 0.6))
    x_norm = cache["x_norm"]
    ensemble_feats = cache["ensemble_feats"]

    rmses, mapes, mases = [], [], []
    for i in range(n_splits):
        split = min_train + i * test_horizon
        if split + test_horizon > T or split <= cfg.washout_steps + 5:
            continue
        try:
            feats_train_raw = ensemble_feats[:split - 1]
            x_train_norm = x_norm[:split]
            X_design = _design_with_past(feats_train_raw, x_train_norm[:-1], cfg.lookback)
            y_target = x_train_norm[1:]
            w = min(cfg.washout_steps, len(X_design) - 10)
            if w > 0:
                X_design, y_target = X_design[w:], y_target[w:]
            W = _ridge_solve(X_design, y_target, alpha)
            test_actual = prices[split:split + test_horizon]
            preds = _forecast_from_cache(cache, cfg, W, split, test_horizon)
            rmses.append(_rmse(test_actual, preds))
            mapes.append(_mape(test_actual, preds))
            mases.append(_mase(test_actual, preds, prices[:split]))
        except Exception as e:
            logger.debug("QRC cached split %d failed: %s", i, e)
            continue
    if not rmses:
        return {"rmse": float("inf"), "mape": float("inf"), "mase": float("inf"), "n_splits_ok": 0}
    return {
        "rmse": float(np.mean(rmses)),
        "mape": float(np.mean(mapes)),
        "mase": float(np.mean(mases)),
        "n_splits_ok": len(rmses),
    }


def auto_tune_qrc(
    prices: Sequence[float],
    n_qubits_grid: Sequence[int] = (4, 6),
    input_scale_grid: Sequence[float] = (0.5, 1.0, 1.5),
    reservoir_depth_grid: Sequence[int] = (1, 2, 3),
    ridge_alpha_grid: Sequence[float] = (1e-3, 1e-2, 1e-1, 1.0),
    leak_rate_grid: Sequence[float] = (0.0, 0.2),
    ensemble_seeds_grid: Sequence[Tuple[int, ...]] = ((7, 13, 29),),
    washout_steps: int = 50,
    n_splits: int = 3,
    test_horizon: int = 10,
    complexity_penalty: float = 0.0,
) -> Dict[str, Any]:
    """Grid-search QRC hyperparameters via walk-forward CV.

    complexity_penalty > 0 biases toward smaller n_qubits for comparable RMSE
    (adds `complexity_penalty * 2^n_qubits` to the score).
    """
    prices_arr = np.asarray(list(prices), dtype=float)
    # Group the grid by reservoir-config (everything except alpha) so simulation
    # runs once per reservoir and the alpha sweep is a pure linear-algebra step.
    reservoir_configs = list(product(
        n_qubits_grid, input_scale_grid, reservoir_depth_grid,
        leak_rate_grid, ensemble_seeds_grid,
    ))
    total_cells = len(reservoir_configs) * len(ridge_alpha_grid)
    logger.info(
        "QRC auto-tune: %d reservoir configs × %d alphas = %d cells over %d points",
        len(reservoir_configs), len(ridge_alpha_grid), total_cells, len(prices_arr),
    )

    t0 = time.time()
    results = []
    best: Optional[Dict[str, Any]] = None
    sim_ms = 0
    solve_ms = 0
    for nq, ins, dep, leak, seeds in reservoir_configs:
        cfg = QRCConfig(
            n_qubits=int(nq),
            reservoir_depth=int(dep),
            reservoir_seeds=tuple(int(s) for s in seeds),
            input_scale=float(ins),
            leak_rate=float(leak),
            ridge_alpha=1.0,  # placeholder — overridden in the sweep
            washout_steps=int(washout_steps),
        )
        try:
            t_sim = time.time()
            cache = _precompute_reservoir_cache(prices_arr, cfg)
            sim_ms += int((time.time() - t_sim) * 1000)
        except Exception as e:
            logger.debug("QRC precompute failed for %s: %s", cfg, e)
            continue

        for alpha in ridge_alpha_grid:
            t_solve = time.time()
            scores = _walk_forward_score_cached(
                prices_arr, cache, cfg, float(alpha),
                n_splits=n_splits, test_horizon=test_horizon,
            )
            solve_ms += int((time.time() - t_solve) * 1000)
            adjusted = scores["rmse"] + complexity_penalty * (1 << int(nq))
            entry = {
                "config": {
                    "n_qubits": int(nq), "input_scale": float(ins),
                    "reservoir_depth": int(dep), "ridge_alpha": float(alpha),
                    "leak_rate": float(leak), "reservoir_seeds": list(seeds),
                    "washout_steps": int(washout_steps),
                },
                "rmse": scores["rmse"], "mape": scores["mape"], "mase": scores["mase"],
                "n_splits_ok": scores["n_splits_ok"],
                "complexity_adjusted_score": adjusted,
            }
            results.append(entry)
            if best is None or adjusted < best["complexity_adjusted_score"]:
                best = entry

    return {
        "method": "Quantum Reservoir Computing (auto-tuned)",
        "n_points": int(len(prices_arr)),
        "grid_size": total_cells,
        "reservoir_configs_evaluated": len(reservoir_configs),
        "alphas_per_config": len(ridge_alpha_grid),
        "runtime_ms": int((time.time() - t0) * 1000),
        "runtime_breakdown_ms": {"simulation": sim_ms, "ridge_and_forecast": solve_ms},
        "best": best,
        "all_results": sorted(results, key=lambda r: r["complexity_adjusted_score"])[:10],
    }


def fit_forecast_qrc(
    prices: Sequence[float],
    horizon: int,
    auto_tune: bool = True,
    config: Optional[QRCConfig] = None,
) -> Dict[str, Any]:
    prices_arr = np.asarray(list(prices), dtype=float)
    tuning = None
    if auto_tune:
        tuning = auto_tune_qrc(prices_arr)
        cfg_dict = tuning["best"]["config"]
        cfg = QRCConfig(
            n_qubits=cfg_dict["n_qubits"],
            reservoir_depth=cfg_dict["reservoir_depth"],
            reservoir_seeds=tuple(cfg_dict["reservoir_seeds"]),
            input_scale=cfg_dict["input_scale"],
            leak_rate=cfg_dict["leak_rate"],
            ridge_alpha=cfg_dict["ridge_alpha"],
            washout_steps=cfg_dict["washout_steps"],
        )
    else:
        cfg = config or QRCConfig()

    t0 = time.time()
    model = QuantumReservoirForecaster(cfg).fit(prices_arr)
    preds = model.forecast(int(horizon))
    elapsed_ms = int((time.time() - t0) * 1000)

    return {
        "method": "Quantum Reservoir Computing",
        "config": {
            "n_qubits": cfg.n_qubits, "reservoir_depth": cfg.reservoir_depth,
            "reservoir_seeds": list(cfg.reservoir_seeds), "input_scale": cfg.input_scale,
            "leak_rate": cfg.leak_rate, "ridge_alpha": cfg.ridge_alpha,
            "washout_steps": cfg.washout_steps, "use_zz": cfg.use_zz,
            "use_xy_pairs": cfg.use_xy_pairs, "lookback": cfg.lookback,
        },
        "forecast_horizon": int(horizon),
        "forecast_prices": preds.tolist(),
        "last_history_price": float(prices_arr[-1]),
        "tuning": tuning,
        "runtime_ms": elapsed_ms,
    }
