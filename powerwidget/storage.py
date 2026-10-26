"""SQLite storage with three resolutions.

raw     every sample (~5 s), kept `raw_retention_days`
minute  1-minute aggregates, kept `minute_retention_days`
hour    1-hour aggregates, kept forever (~9k rows per year)

Each raw row stores dt_s, the time it stands for (gap to the previous sample,
capped), so energy stays right across sleep/shutdown gaps:
energy_wh = sum(total_w * dt_s) / 3600.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from .sensors.base import PowerReading

SCHEMA = """
CREATE TABLE IF NOT EXISTS raw (
    ts REAL PRIMARY KEY,
    total_w REAL NOT NULL,
    cpu_w REAL,
    gpu_w REAL,
    other_w REAL NOT NULL,
    dt_s REAL NOT NULL,
    estimated INTEGER NOT NULL,
    source TEXT NOT NULL
);
"""

AGG_SCHEMA = """
CREATE TABLE IF NOT EXISTS {t} (
    bucket INTEGER PRIMARY KEY,   -- unix seconds at bucket start (UTC)
    avg_w REAL NOT NULL,
    min_w REAL NOT NULL,
    max_w REAL NOT NULL,
    avg_cpu_w REAL,
    avg_gpu_w REAL,
    energy_wh REAL NOT NULL,
    covered_s REAL NOT NULL,      -- seconds of the bucket we have data for
    samples INTEGER NOT NULL,
    estimated_samples INTEGER NOT NULL
);
"""

RESOLUTIONS = {"minute": 60, "hour": 3600}


@dataclass(frozen=True)
class Summary:
    energy_wh: float
    avg_w: float | None
    min_w: float | None
    max_w: float | None
    covered_s: float
    estimated_fraction: float
    resolution: str


class Storage:
    def __init__(self, path: str | Path, raw_retention_days: int = 7, minute_retention_days: int = 90):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA + "".join(AGG_SCHEMA.format(t=t) for t in RESOLUTIONS))
        self.raw_retention_s = raw_retention_days * 86400
        self.minute_retention_s = minute_retention_days * 86400

    def close(self) -> None:
        self.conn.close()

    def insert(self, r: PowerReading, dt_s: float) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO raw VALUES (?,?,?,?,?,?,?,?)",
                (r.timestamp, r.total_w, r.cpu_w, r.gpu_w, r.other_w, dt_s, int(r.estimated), r.source_label),
            )

    def last_timestamp(self) -> float | None:
        row = self.conn.execute("SELECT MAX(ts) FROM raw").fetchone()
        return row[0]

    # --- downsampling and retention ---------------------------------------

    def _rollup_raw_to_minute(self, until: float) -> None:
        start = self.conn.execute("SELECT COALESCE(MAX(bucket), 0) FROM minute").fetchone()[0]
        # Re-aggregate the newest stored bucket too, in case it was written while incomplete.
        self.conn.execute(
            """
            INSERT OR REPLACE INTO minute
            SELECT CAST(ts / 60 AS INTEGER) * 60 AS b,
                   SUM(total_w * dt_s) / SUM(dt_s), MIN(total_w), MAX(total_w),
                   SUM(cpu_w * dt_s) / NULLIF(SUM(CASE WHEN cpu_w IS NOT NULL THEN dt_s END), 0),
                   SUM(gpu_w * dt_s) / NULLIF(SUM(CASE WHEN gpu_w IS NOT NULL THEN dt_s END), 0),
                   SUM(total_w * dt_s) / 3600.0, SUM(dt_s), COUNT(*), SUM(estimated)
            FROM raw WHERE ts >= ? AND ts < ?
            GROUP BY b
            """,
            (start, (until // 60) * 60),
        )

    def _rollup_minute_to_hour(self, until: float) -> None:
        start = self.conn.execute("SELECT COALESCE(MAX(bucket), 0) FROM hour").fetchone()[0]
        self.conn.execute(
            """
            INSERT OR REPLACE INTO hour
            SELECT (bucket / 3600) * 3600 AS b,
                   SUM(energy_wh) * 3600.0 / SUM(covered_s), MIN(min_w), MAX(max_w),
                   SUM(avg_cpu_w * covered_s) / NULLIF(SUM(CASE WHEN avg_cpu_w IS NOT NULL THEN covered_s END), 0),
                   SUM(avg_gpu_w * covered_s) / NULLIF(SUM(CASE WHEN avg_gpu_w IS NOT NULL THEN covered_s END), 0),
                   SUM(energy_wh), SUM(covered_s), SUM(samples), SUM(estimated_samples)
            FROM minute WHERE bucket >= ? AND bucket < ?
            GROUP BY b
            """,
            (start, (int(until) // 3600) * 3600),
        )

    def maintain(self, now: float | None = None) -> None:
        """Roll up completed buckets, then delete rows past retention."""
        now = time.time() if now is None else now
        with self.conn:
            self._rollup_raw_to_minute(now)
            self._rollup_minute_to_hour(now)
            # Cut on bucket boundaries so a rollup never re-reads a half-deleted bucket.
            raw_cut = ((now - self.raw_retention_s) // 60) * 60
            self.conn.execute("DELETE FROM raw WHERE ts < ?", (raw_cut,))
            minute_cut = ((now - self.minute_retention_s) // 3600) * 3600
            self.conn.execute("DELETE FROM minute WHERE bucket < ?", (minute_cut,))

    # --- queries ------------------------------------------------------------

    def _oldest(self, table: str, col: str) -> float | None:
        return self.conn.execute(f"SELECT MIN({col}) FROM {table}").fetchone()[0]

    def summary(self, start: float, end: float) -> Summary:
        """Energy and power stats for [start, end), from the finest table that
        still holds data back to `start`."""
        oldest_raw = self._oldest("raw", "ts")
        oldest_min = self._oldest("minute", "bucket")
        if oldest_raw is not None and oldest_raw <= start + 60:
            res = "raw"
            row = self.conn.execute(
                """SELECT COALESCE(SUM(total_w*dt_s)/3600.0, 0), SUM(total_w*dt_s)/NULLIF(SUM(dt_s), 0),
                          MIN(total_w), MAX(total_w), COALESCE(SUM(dt_s), 0), COUNT(*), COALESCE(SUM(estimated), 0)
                   FROM raw WHERE ts >= ? AND ts < ?""", (start, end)).fetchone()
        else:
            res = "minute" if oldest_min is not None and oldest_min <= start + 3600 else "hour"
            row = self.conn.execute(
                f"""SELECT COALESCE(SUM(energy_wh), 0), SUM(energy_wh)*3600.0/NULLIF(SUM(covered_s), 0),
                           MIN(min_w), MAX(max_w), COALESCE(SUM(covered_s), 0), COALESCE(SUM(samples), 0),
                           COALESCE(SUM(estimated_samples), 0)
                    FROM {res} WHERE bucket >= ? AND bucket < ?""", (start, end)).fetchone()
        energy, avg, mn, mx, covered, n, est = row
        return Summary(energy_wh=energy, avg_w=avg, min_w=mn, max_w=mx, covered_s=covered,
                       estimated_fraction=(est / n) if n else 0.0, resolution=res)

    def series(self, start: float, end: float, resolution: str = "minute") -> list[tuple[float, float]]:
        """(timestamp, avg watts) points for charts."""
        if resolution == "raw":
            sql = "SELECT ts, total_w FROM raw WHERE ts >= ? AND ts < ? ORDER BY ts"
        elif resolution in RESOLUTIONS:
            sql = f"SELECT bucket, avg_w FROM {resolution} WHERE bucket >= ? AND bucket < ? ORDER BY bucket"
        else:
            raise ValueError(f"unknown resolution {resolution!r}")
        return [tuple(r) for r in self.conn.execute(sql, (start, end))]
