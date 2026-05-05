import logging
import os
import time
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

RISK_SERVICE_URL = os.getenv("RISK_SERVICE_URL", "http://127.0.0.1:8001").rstrip("/")
RISK_TIMEOUT_SECONDS = float(os.getenv("RISK_SERVICE_TIMEOUT_SECONDS", "15"))
RISK_MAX_RETRIES = int(os.getenv("RISK_SERVICE_MAX_RETRIES", "2"))
RISK_BACKOFF_SECONDS = float(os.getenv("RISK_SERVICE_BACKOFF_SECONDS", "0.5"))

_SESSION = requests.Session()


def ping_risk_service(timeout_seconds: float = 2.5) -> Dict:
    """
    Best-effort health probe for the R risk service.
    """
    health_url = f"{RISK_SERVICE_URL}/health"
    started = time.perf_counter()
    try:
        response = _SESSION.get(health_url, timeout=timeout_seconds)
        if response.status_code == 200:
            payload = response.json() if response.text else {}
            latency_ms = int((time.perf_counter() - started) * 1000)
            return {
                "ok": True,
                "url": RISK_SERVICE_URL,
                "latency_ms": latency_ms,
                "details": payload,
            }
    except Exception:
        # Fallback to legacy probe below when /health is missing.
        pass

    legacy_probe_payload = {
        "prices": [100.0 + float(i) for i in range(140)],
        "horizon": 5,
        "n_paths": 20,
    }
    try:
        response = _SESSION.post(
            f"{RISK_SERVICE_URL}/calculate_risk",
            json=legacy_probe_payload,
            timeout=timeout_seconds,
        )
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, dict) and "error" not in data:
                latency_ms = int((time.perf_counter() - started) * 1000)
                return {
                    "ok": True,
                    "url": RISK_SERVICE_URL,
                    "latency_ms": latency_ms,
                    "details": {"probe": "legacy_calculate_risk"},
                }
            if isinstance(data, dict) and str(data.get("error", "")).lower().startswith("garch model failed"):
                # Service is reachable; this can happen on synthetic probe data.
                latency_ms = int((time.perf_counter() - started) * 1000)
                return {
                    "ok": True,
                    "url": RISK_SERVICE_URL,
                    "latency_ms": latency_ms,
                    "details": {"probe": "legacy_calculate_risk", "warning": data.get("error")},
                }
        return {
            "ok": False,
            "url": RISK_SERVICE_URL,
            "message": f"Risk service probe failed (HTTP {response.status_code})",
        }
    except Exception as e:
        return {
            "ok": False,
            "url": RISK_SERVICE_URL,
            "message": f"Risk service probe failed: {str(e)}",
        }


def calculate_risk(
    prices: List[float],
    horizon: int = 90,
    n_paths: int = 1000,
    require_success: bool = False,
) -> Optional[Dict]:
    """
    Calls the R risk service with retry/backoff.
    Returns None on failure when require_success=False.
    """
    if not prices:
        if require_success:
            raise RuntimeError("No prices provided for risk calculation")
        return None

    payload = {
        "prices": [float(p) for p in prices],
        "horizon": int(horizon),
        "n_paths": int(n_paths),
    }

    attempts = max(1, RISK_MAX_RETRIES + 1)
    errors = []
    for attempt in range(1, attempts + 1):
        try:
            response = _SESSION.post(
                f"{RISK_SERVICE_URL}/calculate_risk",
                json=payload,
                timeout=RISK_TIMEOUT_SECONDS,
            )
            if response.status_code != 200:
                raise RuntimeError(f"Risk service HTTP {response.status_code}")

            data = response.json()
            if not isinstance(data, dict):
                raise RuntimeError("Risk service returned invalid JSON payload")
            if "error" in data:
                raise RuntimeError(str(data["error"]))
            return data
        except Exception as e:
            errors.append(str(e))
            if attempt < attempts:
                sleep_for = RISK_BACKOFF_SECONDS * attempt
                time.sleep(max(0.0, sleep_for))

    message = f"Risk service call failed after {attempts} attempt(s): {errors[-1]}"
    if require_success:
        raise RuntimeError(message)
    logger.warning(message)
    return None
