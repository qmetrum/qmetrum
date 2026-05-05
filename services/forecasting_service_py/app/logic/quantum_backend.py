"""Unified quantum execution backend.

Selects a qiskit primitive (Sampler / Estimator) based on environment:
  QUANTUM_BACKEND=local         (default) — statevector simulator, no credentials
  QUANTUM_BACKEND=ibm_runtime   — real QPU via IBM Quantum; requires IBM_QUANTUM_TOKEN
  QUANTUM_BACKEND=ibm_simulator — IBM Runtime managed simulator; requires IBM_QUANTUM_TOKEN

Env:
  IBM_QUANTUM_TOKEN      IBM Quantum API token
  IBM_QUANTUM_INSTANCE   Hub/group/project (e.g. "ibm-q/open/main")
  IBM_BACKEND_NAME       Specific backend (e.g. "ibm_brisbane"); auto-picked if unset
  QUANTUM_SHOTS          Shots per circuit (default 4096)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class BackendInfo:
    kind: str              # "local" | "ibm_runtime" | "ibm_simulator"
    name: str              # Human-readable backend name
    shots: int
    hardware: bool         # True iff this is a real QPU
    sampler: Any           # qiskit primitive Sampler (V1 or V2)


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    val = os.getenv(name, default)
    return val.strip() if isinstance(val, str) else val


def get_backend() -> BackendInfo:
    """Return a configured qiskit Sampler and metadata for marketing/telemetry."""
    kind = (_env("QUANTUM_BACKEND", "local") or "local").lower()
    shots = int(_env("QUANTUM_SHOTS", "4096") or 4096)

    if kind in {"ibm_runtime", "ibm_simulator"}:
        token = _env("IBM_QUANTUM_TOKEN")
        if not token:
            logger.warning("QUANTUM_BACKEND=%s but IBM_QUANTUM_TOKEN not set; falling back to local", kind)
            kind = "local"

    if kind == "local":
        from qiskit.primitives import Sampler
        return BackendInfo(
            kind="local",
            name="qiskit.primitives.Sampler (statevector)",
            shots=shots,
            hardware=False,
            sampler=Sampler(options={"shots": shots}),
        )

    # IBM Runtime path (real QPU or managed simulator)
    from qiskit_ibm_runtime import QiskitRuntimeService, SamplerV2

    service = QiskitRuntimeService(
        channel="ibm_quantum",
        token=_env("IBM_QUANTUM_TOKEN"),
        instance=_env("IBM_QUANTUM_INSTANCE"),
    )

    backend_name = _env("IBM_BACKEND_NAME")
    if backend_name:
        backend = service.backend(backend_name)
    elif kind == "ibm_simulator":
        backend = service.least_busy(simulator=True)
    else:
        backend = service.least_busy(simulator=False, operational=True)

    sampler = SamplerV2(mode=backend)
    sampler.options.default_shots = shots

    return BackendInfo(
        kind=kind,
        name=str(backend.name),
        shots=shots,
        hardware=(kind == "ibm_runtime"),
        sampler=sampler,
    )
