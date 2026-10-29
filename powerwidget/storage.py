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
from datetime import date, datetime
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


@dataclass(frozen=True)
class Point:
    """One chart bucket."""

    ts: float
    avg_w: float
    min_w: float
    max_w: float
    cpu_w: float | None
    gpu_w: float | None
    energy_wh: float
    covered_s: float


class Storage:
    def __init__(self, path: str | Path, raw_retention_days: int = 7, minute_retention_days: int = 90):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), timeout=10, check_same_thread=False)
        # The widget and the logger may open a brand-new file at the same moment;
        # switching to WAL ignores the busy timeout, so retry briefly.
        for attempt in range(50):
            try:
                if self.conn.execute("PRAGMA journal_mode").fetchone()[0].lower() != "wal":
                    self.conn.execute("PRAGMA journal_mode=WAL")
                self.conn.executescript(SCHEMA + "".join(AGG_SCHEMA.format(t=t) for t in RESOLUTIONS))
                break
            except sqlite3.OperationalError:
                if attempt == 49:
                    raise
                time.sleep(0.1)
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

    def _unified(self, start: float, end: float) -> tuple[str, dict]:
        """A subquery over all three tables that uses the finest data available
        for each stretch of time: raw where it still exists, minute rows before
        that, hour rows before those. Retention cuts on minute/hour boundaries,
        so the stretches neither overlap nor leave holes."""
        oldest_raw = self._oldest("raw", "ts")
        oldest_min = self._oldest("minute", "bucket")
        raw_from = (oldest_raw // 60) * 60 if oldest_raw is not None else float("inf")
        min_from = (oldest_min // 3600) * 3600 if oldest_min is not None else raw_from
        sql = """
            SELECT ts AS t, dt_s AS cov, total_w AS w, total_w AS wmin, total_w AS wmax,
                   cpu_w AS cpu, gpu_w AS gpu, 1 AS n, estimated AS est
            FROM raw WHERE ts >= :start AND ts < :end
            UNION ALL
            SELECT bucket, covered_s, avg_w, min_w, max_w, avg_cpu_w, avg_gpu_w, samples, estimated_samples
            FROM minute WHERE bucket >= :start AND bucket < :end AND bucket >= :min_from AND bucket < :raw_from
            UNION ALL
            SELECT bucket, covered_s, avg_w, min_w, max_w, avg_cpu_w, avg_gpu_w, samples, estimated_samples
            FROM hour WHERE bucket >= :start AND bucket < :end AND bucket < :min_from
        """
        return sql, {"start": start, "end": end, "raw_from": raw_from, "min_from": min_from}

    def _oldest(self, table: str, col: str) -> float | None:
        return self.conn.execute(f"SELECT MIN({col}) FROM {table}").fetchone()[0]

    def summary(self, start: float, end: float) -> Summary:
        """Energy and power stats for [start, end)."""
        sub, params = self._unified(start, end)
        energy, avg, mn, mx, covered, n, est = self.conn.execute(
            f"""SELECT COALESCE(SUM(w*cov)/3600.0, 0), SUM(w*cov)/NULLIF(SUM(cov), 0), MIN(wmin), MAX(wmax),
                       COALESCE(SUM(cov), 0), COALESCE(SUM(n), 0), COALESCE(SUM(est), 0)
                FROM ({sub})""", params).fetchone()
        return Summary(energy_wh=energy, avg_w=avg, min_w=mn, max_w=mx, covered_s=covered,
                       estimated_fraction=(est / n) if n else 0.0)

    def series(self, start: float, end: float, bin_s: int = 60) -> list[Point]:
        """Chart points for [start, end), averaged into `bin_s` buckets."""
        sub, params = self._unified(start, end)
        params["bin"] = int(bin_s)
        rows = self.conn.execute(
            f"""SELECT CAST(t / :bin AS INTEGER) * :bin AS b,
                       SUM(w*cov)/SUM(cov), MIN(wmin), MAX(wmax),
                       SUM(cpu*cov)/NULLIF(SUM(CASE WHEN cpu IS NOT NULL THEN cov END), 0),
                       SUM(gpu*cov)/NULLIF(SUM(CASE WHEN gpu IS NOT NULL THEN cov END), 0),
                       SUM(w*cov)/3600.0, SUM(cov)
                FROM ({sub}) GROUP BY b HAVING SUM(cov) > 0 ORDER BY b""", params)
        return [Point(*r) for r in rows]

    def energy_by_day(self, start: float, end: float) -> list[tuple[date, float]]:
        """(local date, Wh) for each day in [start, end) that has data."""
        days: dict[date, float] = {}
        for p in self.series(start, end, 3600):
            d = datetime.fromtimestamp(p.ts).date()
            days[d] = days.get(d, 0.0) + p.energy_wh
        return sorted(days.items())

    def latest(self) -> PowerReading | None:
        row = self.conn.execute(
            "SELECT ts, total_w, cpu_w, gpu_w, other_w, estimated, source FROM raw ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        ts, total, cpu, gpu, other, est, source = row
        sources = dict(part.split("=", 1) for part in source.split(",") if "=" in part)
        return PowerReading(ts, total, cpu, gpu, other, bool(est), sources)

    def recent(self, start: float, end: float, limit: int = 2000) -> list[tuple]:
        """Raw samples, newest first: (ts, total, cpu, gpu, other, estimated, source)."""
        return self.conn.execute(
            """SELECT ts, total_w, cpu_w, gpu_w, other_w, estimated, source FROM raw
               WHERE ts >= ? AND ts < ? ORDER BY ts DESC LIMIT ?""", (start, end, limit)).fetchall()
