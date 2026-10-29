"""LibreHardwareMonitor via its built-in web server (Options > Remote Web Server).

LHM reads CPU package power from the RAPL / SMU registers and GPU power from
the vendor driver. It needs admin rights for the CPU part, which is why we
talk to the running LHM app over HTTP instead of loading its driver ourselves.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any, Iterator

from .base import ComponentReading, SourceUnavailable

DEFAULT_URL = "http://localhost:8085/data.json"

CPU_NAMES = ("CPU Package", "Package")
GPU_NAMES = ("GPU Package", "GPU Board Power", "GPU Power", "GPU PPT", "GPU Total")

_VALUE_RE = re.compile(r"^\s*(-?[0-9]+(?:[.,][0-9]+)?)\s*W\s*$")


def parse_watts(value: str) -> float | None:
    m = _VALUE_RE.match(value or "")
    return float(m.group(1).replace(",", ".")) if m else None


def _hardware_kind(node: dict[str, Any]) -> str | None:
    """Classify a hardware node as 'cpu', 'gpu' or None."""
    ident = (node.get("HardwareId") or node.get("SensorId") or "").lower()
    image = (node.get("ImageURL") or "").lower()
    # Intel iGPU power is already inside the CPU package, so skip it.
    if "gpu-intel" in ident or "intelgpu" in ident:
        return None
    if "cpu" in ident or image.endswith("cpu.png"):
        return "cpu"
    if any(k in ident for k in ("gpu", "nvidia", "ati")) or any(
        image.endswith(k) for k in ("nvidia.png", "ati.png", "amd.png")
    ):
        return "gpu"
    return None


def _power_sensors(node: dict[str, Any]) -> Iterator[tuple[str, float]]:
    for child in node.get("Children", []):
        watts = parse_watts(child.get("Value", "")) if not child.get("Children") else None
        if watts is not None:
            yield child.get("Text", ""), watts
        yield from _power_sensors(child)


def _pick(sensors: list[tuple[str, float]], preferred: tuple[str, ...]) -> float | None:
    by_name = dict(sensors)
    for name in preferred:
        if name in by_name:
            return by_name[name]
    return None


def _first_sensor_id(node: dict[str, Any]) -> str:
    for child in node.get("Children", []):
        if child.get("SensorId"):
            return child["SensorId"]
        found = _first_sensor_id(child)
        if found:
            return found
    return ""


def _hardware_nodes(node: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    for child in node.get("Children", []):
        probe = dict(child)
        if not probe.get("HardwareId") and not probe.get("SensorId"):
            # Older LHM builds only put SensorId on leaves; borrow the first one.
            probe["HardwareId"] = _first_sensor_id(child)
        kind = _hardware_kind(probe)
        if kind:
            yield kind, child
        else:
            yield from _hardware_nodes(child)


def parse_lhm(data: dict[str, Any]) -> ComponentReading:
    cpu_total: float | None = None
    gpu_total: float | None = None
    for kind, hw in _hardware_nodes(data):
        sensors = list(_power_sensors(hw))
        if kind == "cpu":
            watts = _pick(sensors, CPU_NAMES)
            if watts is not None:
                cpu_total = (cpu_total or 0.0) + watts
        else:
            watts = _pick(sensors, GPU_NAMES)
            if watts is not None:
                gpu_total = (gpu_total or 0.0) + watts
    if cpu_total is None and gpu_total is None:
        raise SourceUnavailable("LibreHardwareMonitor reports no CPU or GPU power sensors")
    return ComponentReading(cpu_w=cpu_total, gpu_w=gpu_total)


class LhmSource:
    name = "lhm"

    def __init__(self, url: str = DEFAULT_URL, timeout: float = 2.0):
        self.url = url
        self.timeout = timeout

    def read(self) -> ComponentReading:
        try:
            with urllib.request.urlopen(self.url, timeout=self.timeout) as resp:
                data = json.load(resp)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise SourceUnavailable(f"LibreHardwareMonitor not reachable at {self.url}: {exc}") from exc
        return parse_lhm(data)

    def close(self) -> None:
        pass
