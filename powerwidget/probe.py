"""Milestone 1 feasibility check: which power sources work on this PC?"""

from __future__ import annotations

import os
import subprocess

from .config import Config
from .factory import make_source
from .sensors.base import SourceUnavailable


def energy_meter_available() -> str:
    """Windows 'Energy Meter' perf counters (EMI). Mostly present on laptops and
    some Surface/ARM devices; rare on desktops. Reported for information only."""
    if os.name != "nt":
        return "not Windows"
    try:
        out = subprocess.run(["typeperf", "-qx", "Energy Meter"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"could not run typeperf: {exc}"
    lines = [l for l in out.stdout.splitlines() if "Energy Meter" in l]
    return f"{len(lines)} counters found" if lines else "no Energy Meter counters"


def probe(cfg: Config) -> list[tuple[str, str]]:
    results = []
    for name in ("lhmlib", "lhm", "nvml", "estimate"):
        try:
            src = make_source(name, cfg)
            r = src.read()
            src.close()
            parts = [f"CPU {r.cpu_w:.1f} W" if r.cpu_w is not None else "CPU -",
                     f"GPU {r.gpu_w:.1f} W" if r.gpu_w is not None else "GPU -"]
            results.append((name, "OK  " + ", ".join(parts) + ("  (estimated)" if r.estimated else "")))
        except SourceUnavailable as exc:
            results.append((name, f"no  {exc}"))
    results.append(("energy_meter", energy_meter_available()))
    return results
