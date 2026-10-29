"""Fake source for tests and for running on machines without sensors."""

from __future__ import annotations

import math
from typing import Callable, Iterable, Iterator

from .base import ComponentReading, SourceUnavailable


class MockSource:
    def __init__(self, readings: Iterable[ComponentReading | Exception] | None = None,
                 name: str = "mock", clock: Callable[[], float] | None = None):
        self.name = name
        self._iter: Iterator[ComponentReading | Exception] | None = iter(readings) if readings is not None else None
        self._clock = clock
        self._n = 0
        self.closed = False

    def read(self) -> ComponentReading:
        if self._iter is None:
            # Smooth fake load curve: CPU 30-90 W, GPU 20-180 W.
            self._n += 1
            t = self._n / 12.0
            return ComponentReading(cpu_w=round(60 + 30 * math.sin(t), 1),
                                    gpu_w=round(100 + 80 * math.sin(t / 3), 1))
        try:
            item = next(self._iter)
        except StopIteration:
            raise SourceUnavailable("mock exhausted")
        if isinstance(item, Exception):
            raise item
        return item

    def close(self) -> None:
        self.closed = True
