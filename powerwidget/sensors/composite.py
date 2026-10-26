"""Combine several sources into one whole-PC reading."""

from __future__ import annotations

import logging
from typing import Callable, Sequence

from .base import PowerReading, PowerSource, SourceUnavailable, now

log = logging.getLogger(__name__)


class CompositeSource:
    """Asks sources in priority order and takes each component from the first
    source that has it. A component no source covers is left as None and
    contributes 0 W. `other_w` covers board, RAM, drives, fans and PSU loss."""

    def __init__(self, sources: Sequence[PowerSource], other_w: float = 40.0,
                 clock: Callable[[], float] = now):
        self.sources = list(sources)
        self.other_w = other_w
        self._clock = clock
        self._last_error: dict[str, str] = {}

    def read(self) -> PowerReading:
        cpu = gpu = None
        used: dict[str, str] = {}
        estimated = False
        for src in self.sources:
            if cpu is not None and gpu is not None:
                break
            try:
                r = src.read()
            except SourceUnavailable as exc:
                if self._last_error.get(src.name) != str(exc):
                    log.warning("%s unavailable: %s", src.name, exc)
                    self._last_error[src.name] = str(exc)
                continue
            self._last_error.pop(src.name, None)
            if cpu is None and r.cpu_w is not None:
                cpu, used["cpu"] = r.cpu_w, src.name
                estimated |= r.estimated
            if gpu is None and r.gpu_w is not None:
                gpu, used["gpu"] = r.gpu_w, src.name
                estimated |= r.estimated
        if cpu is None and gpu is None:
            raise SourceUnavailable("no power source produced a reading")
        total = (cpu or 0.0) + (gpu or 0.0) + self.other_w
        return PowerReading(timestamp=self._clock(), total_w=round(total, 2), cpu_w=cpu, gpu_w=gpu,
                            other_w=self.other_w, estimated=estimated, sources=used)

    def close(self) -> None:
        for src in self.sources:
            src.close()
