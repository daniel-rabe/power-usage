"""Runs the sampling loop in a thread inside the widget process.

Only one process may log at a time (see lock.py). If a separate logger
already runs, the widget just reads the database, and takes over logging
if that logger stops.
"""

from __future__ import annotations

import logging
import threading

from ..config import Config
from ..factory import build_composite
from ..lock import logger_lock
from ..logger import PowerLogger
from ..sensors.base import SourceUnavailable
from ..storage import Storage

log = logging.getLogger(__name__)


class BackgroundLogger:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._lock = logger_lock(cfg.db_path)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.error: str | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def try_start(self) -> bool:
        """Start logging here unless another process already does. Returns True if we log."""
        if self.running:
            return True
        if not self._lock.acquire():
            return False
        try:
            source = build_composite(self.cfg)
        except SourceUnavailable as exc:
            self.error = str(exc)
            self._lock.release()
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, args=(source,), name="power-logger", daemon=True)
        self._thread.start()
        return True

    def _run(self, source) -> None:
        storage = Storage(self.cfg.db_path, self.cfg.raw_retention_days, self.cfg.minute_retention_days)
        try:
            PowerLogger(source, storage, self.cfg.sample_interval_s, self.cfg.maintenance_interval_s).run(self._stop)
        except Exception:
            log.exception("logger thread crashed")
        finally:
            source.close()
            storage.close()
            self._lock.release()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
