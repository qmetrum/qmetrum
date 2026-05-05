"""Quantum-kernel classification for regime detection and related tasks.

Builds a fidelity quantum kernel over a ZZ feature map and wraps an SVC
around the Gram matrix. Used as a general-purpose quantum classifier: the
regime detector below is the first consumer, but the same kernel can be
reused for anomaly triage, sentiment classification, or fat-tail event
prediction.

Also exposes `generate_quantum_kernel_features` — fidelity scores of each
input row against a small reference set, usable as exogenous features in
downstream forecasters. Replaces the simpler single-observable feature
with a genuinely-quantum multi-column feature bank.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_FEATURE_COLUMNS = ["ret_5d", "ret_21d", "vol_21d", "vol_63d", "skew_63d", "kurt_63d", "mom_126d"]


def _build_regime_features(prices: pd.Series) -> pd.DataFrame:
    """Per-day feature vector summarising the recent return distribution."""
    log_ret = np.log(prices / prices.shift(1))
    feats = pd.DataFrame(index=prices.index)
    feats["ret_5d"] = log_ret.rolling(5).sum()
    feats["ret_21d"] = log_ret.rolling(21).sum()
    feats["vol_21d"] = log_ret.rolling(21).std()
    feats["vol_63d"] = log_ret.rolling(63).std()
    feats["skew_63d"] = log_ret.rolling(63).skew()
    feats["kurt_63d"] = log_ret.rolling(63).kurt()
    feats["mom_126d"] = log_ret.rolling(126).sum()
    return feats.dropna()


def _label_regimes(features: pd.DataFrame) -> pd.Series:
    """Rule-based regime labels used as ground truth for training the QSVC.

    High_Vol when recent/long vol ratio > 1.5; Low_Vol when < 0.8; else Normal.
    This mirrors the classical logic in PortfolioManager.analyze_portfolio.
    """
    ratio = features["vol_21d"] / features["vol_63d"].replace(0.0, np.nan)
    labels = pd.Series("Normal", index=features.index)
    labels[ratio > 1.5] = "High_Vol"
    labels[ratio < 0.8] = "Low_Vol"
    return labels


def quantum_regime_classify(
    prices: pd.Series,
    n_qubits: int = 4,
    reps: int = 2,
    train_points: int = 200,
) -> Dict[str, Any]:
    """Train a quantum-kernel SVC on historical regime labels and classify today.

    Returns the current regime label, class probabilities (via SVC decision function
    softmaxed), accuracy on a held-out tail, and backend metadata.
    """
    from sklearn.preprocessing import StandardScaler
    from sklearn.svm import SVC
    from qiskit.circuit.library import ZZFeatureMap
    from qiskit_machine_learning.kernels import FidelityQuantumKernel

    features = _build_regime_features(prices)
    labels = _label_regimes(features)
    if len(features) < 60:
        raise ValueError("Insufficient history for quantum regime classification")

    # Use the most recent `train_points` points; hold the last 20% as a test tail.
    features = features.tail(train_points)
    labels = labels.loc[features.index]
    split = max(10, int(len(features) * 0.8))

    # Reduce to n_qubits dims by selecting the most informative subset (keep simple: first n_qubits).
    feat_cols = _FEATURE_COLUMNS[:n_qubits]
    X = features[feat_cols].values
    y = labels.values

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    # Map to [-pi, pi] so angles in the feature map stay in a well-behaved range.
    X_scaled = np.tanh(X_scaled) * np.pi

    X_train, X_test = X_scaled[:split], X_scaled[split:]
    y_train, y_test = y[:split], y[split:]
    x_latest = X_scaled[-1:].copy()

    feature_map = ZZFeatureMap(feature_dimension=n_qubits, reps=reps, entanglement="linear")
    kernel = FidelityQuantumKernel(feature_map=feature_map)

    gram_train = kernel.evaluate(x_vec=X_train)
    svc = SVC(kernel="precomputed", C=1.0, probability=False)
    svc.fit(gram_train, y_train)

    accuracy: Optional[float] = None
    if len(X_test) >= 1:
        gram_test = kernel.evaluate(x_vec=X_test, y_vec=X_train)
        preds = svc.predict(gram_test)
        accuracy = float(np.mean(preds == y_test))

    gram_latest = kernel.evaluate(x_vec=x_latest, y_vec=X_train)
    current = str(svc.predict(gram_latest)[0])
    decision = svc.decision_function(gram_latest)
    # Softmax over one-vs-one decision scores as a rough confidence proxy.
    if decision.ndim == 1:
        scores = np.array([-decision[0], decision[0]])
        classes = [svc.classes_[0], svc.classes_[-1]]
    else:
        scores = decision.ravel()
        classes = list(svc.classes_)
    probs = np.exp(scores - scores.max())
    probs = probs / probs.sum()
    class_probs = {str(c): float(p) for c, p in zip(classes, probs)}

    return {
        "method": "Quantum Kernel SVC (ZZFeatureMap, fidelity kernel)",
        "feature_map": {
            "type": "ZZFeatureMap",
            "n_qubits": int(n_qubits),
            "reps": int(reps),
            "entanglement": "linear",
        },
        "features_used": feat_cols,
        "train_points": int(split),
        "test_points": int(len(X_test)),
        "heldout_accuracy": accuracy,
        "current_regime": current,
        "class_probabilities": class_probs,
        "as_of": str(features.index[-1].date()) if hasattr(features.index[-1], "date") else str(features.index[-1]),
    }


def generate_quantum_kernel_features(
    X: np.ndarray,
    reference_size: int = 4,
    n_qubits: int = 2,
    reps: int = 1,
) -> np.ndarray:
    """Fidelity-kernel features of each row against a small reference set.

    Returns an (N, reference_size) matrix where entry (i, j) is the quantum-kernel
    fidelity |<psi(x_i)|psi(ref_j)>|^2 under a ZZFeatureMap. The reference set is
    chosen as `reference_size` equally-spaced points in the normalised input range,
    so the features capture "how similar is this input to archetypal regimes."

    Designed as an alternative exogenous feature source for ARIMAX/Prophet/BSTS
    that is defensibly quantum (full Hilbert-space fidelity kernel) rather than
    a single scalar observable.
    """
    from qiskit.circuit.library import ZZFeatureMap
    from qiskit_machine_learning.kernels import FidelityQuantumKernel

    X = np.asarray(X, dtype=float).reshape(-1)
    if X.size == 0:
        return np.zeros((0, reference_size))
    if X.max() == X.min():
        X_norm = np.zeros_like(X)
    else:
        X_norm = (X - X.min()) / (X.max() - X.min())
    # Replicate the scalar input across n_qubits so the feature map has enough dims.
    X_vec = np.tile(X_norm.reshape(-1, 1), (1, n_qubits))
    ref_scalar = np.linspace(0.05, 0.95, reference_size)
    ref_vec = np.tile(ref_scalar.reshape(-1, 1), (1, n_qubits))

    feature_map = ZZFeatureMap(feature_dimension=n_qubits, reps=reps, entanglement="linear")
    kernel = FidelityQuantumKernel(feature_map=feature_map)
    gram = kernel.evaluate(x_vec=X_vec, y_vec=ref_vec)  # shape (N, reference_size)
    return np.asarray(gram, dtype=float)
