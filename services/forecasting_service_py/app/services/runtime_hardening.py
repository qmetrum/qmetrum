import os
from functools import lru_cache
from typing import Dict, Tuple


def _parse_version(raw: str) -> Tuple[int, int, int]:
    parts = (raw or "0.0.0").split(".")
    out = []
    for part in parts[:3]:
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits) if digits else 0)
    while len(out) < 3:
        out.append(0)
    return tuple(out)  # type: ignore[return-value]


def _compute_ml_runtime() -> Dict:
    """
    Detects common TensorFlow/protobuf mismatch issues early.
    """
    issues = []
    warnings = []
    versions = {}

    try:
        import tensorflow as tf  # noqa: F401
        tf_version = str(tf.__version__)
        versions["tensorflow"] = tf_version
    except Exception as e:
        return {
            "ok": False,
            "message": f"TensorFlow import failed: {str(e)}",
            "issues": ["TensorFlow import failure"],
            "warnings": [],
            "versions": versions,
        }

    try:
        import tensorflow_probability as tfp  # noqa: F401
        tfp_version = str(tfp.__version__)
        versions["tensorflow_probability"] = tfp_version
    except Exception as e:
        warnings.append(f"tensorflow_probability import failed: {str(e)}")
        tfp_version = "0.0.0"

    try:
        import google.protobuf  # noqa: F401
        protobuf_version = str(google.protobuf.__version__)
        versions["protobuf"] = protobuf_version
    except Exception as e:
        issues.append(f"protobuf import failed: {str(e)}")
        protobuf_version = "0.0.0"

    tf_v = _parse_version(tf_version)
    pb_v = _parse_version(protobuf_version)
    tfp_v = _parse_version(tfp_version)

    # TensorFlow 2.15.x is known to break with protobuf >= 5.
    if tf_v[:2] <= (2, 15) and pb_v[0] >= 5:
        issues.append(
            f"Incompatible versions: tensorflow={tf_version} with protobuf={protobuf_version}. "
            "Use protobuf < 5.0.0."
        )

    # This project currently pins tensorflow_probability 0.23.x.
    if tfp_v[:2] == (0, 23) and tf_v[:2] != (2, 15):
        warnings.append(
            f"tensorflow_probability={tfp_version} is usually paired with tensorflow 2.15.x "
            f"(detected {tf_version})."
        )

    if not issues:
        message = "ML runtime compatibility check passed."
    else:
        message = "ML runtime compatibility check failed: " + "; ".join(issues)

    return {
        "ok": len(issues) == 0,
        "message": message,
        "issues": issues,
        "warnings": warnings,
        "versions": versions,
        "strict_mode": os.getenv("ML_RUNTIME_STRICT", "false").strip().lower() in {"1", "true", "yes", "on"},
    }


@lru_cache(maxsize=1)
def _cached_ml_runtime() -> Dict:
    return _compute_ml_runtime()


def check_ml_runtime(refresh: bool = False) -> Dict:
    if refresh:
        _cached_ml_runtime.cache_clear()
    # Return a shallow copy so endpoint formatting does not mutate cache.
    return dict(_cached_ml_runtime())
