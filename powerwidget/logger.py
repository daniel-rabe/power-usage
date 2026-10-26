"""Background sampling loop: read sensors every few seconds, write to SQLite."""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from .sensors.base import SourceUnavailable
from .sensors.composite import CompositeSource
from .storage import Storage

log = logging.getLogger(__name__)


class PowerLogger:
    def __init__(self, source: CompositeSource, storage: Storage, interval_s: float = 5.0,
                 maintenance_interval_s: float = 600.0, monotonic: Callable[[], float] = time.monotonic):
        self.source = source
        self.storage = storage
        self.interval_s = interval_s
        self.maintenance_interval_s = maintenance_interval_s
        self._monotonic = monotonic
        self._prev_ts: float | None = None
        self._last_maintenance = float("-inf")

    def step(self) -> bool:
        """Take one sample. Returns False if no source answered."""
        try:
            reading = self.source.read()
        except SourceUnavailable as exc:
            log.warning("no sample: %s", exc)
            self._prev_ts = None  # don't bill the gap
            return False
        if self._prev_ts is None:
            dt = self.interval_s
        else:
            # Cap so a sleep/hibernate gap is not counted as consumed energy.
            dt = min(max(reading.timestamp - self._prev_ts, 0.0), 2 * self.interval_s)
        self._prev_ts = reading.timestamp
        self.storage.insert(reading, dt)
        return True

    def maybe_maintain(self) -> None:
        t = self._monotonic()
        if t - self._last_maintenance >= self.maintenance_interval_s:
            self._last_maintenance = t
            self.storage.maintain()

    def run(self, stop: threading.Event | None = None, max_samples: int | None = None) -> None:
        stop = stop or threading.Event()
        next_at = self._monotonic()
        n = 0
        while not stop.is_set():
            self.step()
            self.maybe_maintain()
            n += 1
            if max_samples is not None and n >= max_samples:
                break
            next_at += self.interval_s
            delay = next_at - self._monotonic()
            if delay < 0:  # fell behind (e.g. after sleep): resync instead of bursting
                next_at = self._monotonic()
                delay = 0
            stop.wait(delay)
        self.storage.maintain()
