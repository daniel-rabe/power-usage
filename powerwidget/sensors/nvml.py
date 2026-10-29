"""NVIDIA GPU board power via NVML (pip install nvidia-ml-py). No admin needed."""

from __future__ import annotations

from .base import ComponentReading, SourceUnavailable


class NvmlSource:
    name = "nvml"

    def __init__(self) -> None:
        try:
            import pynvml  # type: ignore[import-not-found]
        except ImportError as exc:
            raise SourceUnavailable("nvidia-ml-py is not installed") from exc
        try:
            pynvml.nvmlInit()
            count = pynvml.nvmlDeviceGetCount()
        except Exception as exc:  # NVMLError has many subclasses
            raise SourceUnavailable(f"NVML init failed: {exc}") from exc
        if count == 0:
            raise SourceUnavailable("no NVIDIA GPU found")
        self._nvml = pynvml
        self._handles = [pynvml.nvmlDeviceGetHandleByIndex(i) for i in range(count)]

    def read(self) -> ComponentReading:
        try:
            mw = sum(self._nvml.nvmlDeviceGetPowerUsage(h) for h in self._handles)
        except Exception as exc:
            raise SourceUnavailable(f"NVML read failed: {exc}") from exc
        return ComponentReading(gpu_w=mw / 1000.0)

    def close(self) -> None:
        try:
            self._nvml.nvmlShutdown()
        except Exception:
            pass
