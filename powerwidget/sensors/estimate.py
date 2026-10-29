"""Utilization-based estimate. Used only when no real sensor answers.

cpu_w = idle + (tdp - idle) * utilization. This is rough (often off by 30%
or more) and every sample it produces is flagged as estimated.
"""

from __future__ import annotations

from .base import ComponentReading, SourceUnavailable


class EstimateSource:
    name = "estimate"

    def __init__(self, cpu_idle_w: float = 15.0, cpu_tdp_w: float = 105.0, gpu_idle_w: float = 15.0,
                 cpu_percent=None):
        self.cpu_idle_w = cpu_idle_w
        self.cpu_tdp_w = cpu_tdp_w
        self.gpu_idle_w = gpu_idle_w
        if cpu_percent is None:
            try:
                import psutil
            except ImportError as exc:
                raise SourceUnavailable("psutil is not installed") from exc
            psutil.cpu_percent(None)  # prime the counter; first call returns 0
            cpu_percent = lambda: psutil.cpu_percent(None)  # noqa: E731
        self._cpu_percent = cpu_percent

    def read(self) -> ComponentReading:
        util = max(0.0, min(100.0, float(self._cpu_percent()))) / 100.0
        cpu = self.cpu_idle_w + (self.cpu_tdp_w - self.cpu_idle_w) * util
        return ComponentReading(cpu_w=round(cpu, 1), gpu_w=self.gpu_idle_w, estimated=True)

    def close(self) -> None:
        pass
