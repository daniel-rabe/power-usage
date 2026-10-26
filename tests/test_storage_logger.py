import pytest

from powerwidget.logger import PowerLogger
from powerwidget.sensors.base import PowerReading, SourceUnavailable
from powerwidget.storage import Storage

DAY = 86400
T0 = 1_760_000_400  # a whole hour (UTC)


def reading(ts, w, est=False):
    return PowerReading(timestamp=ts, total_w=w, cpu_w=w / 2, gpu_w=w / 4, other_w=w / 4,
                        estimated=est, sources={"cpu": "mock"})


@pytest.fixture
def db():
    s = Storage(":memory:", raw_retention_days=1, minute_retention_days=2)
    yield s
    s.close()


def fill(db, start, seconds, watts, step=5):
    for i in range(0, seconds, step):
        db.insert(reading(start + i, watts), step)


def test_energy_from_raw(db):
    fill(db, T0, 3600, 200)  # 200 W for an hour
    s = db.summary(T0, T0 + 3600)
    assert s.energy_wh == pytest.approx(200)
    assert s.avg_w == pytest.approx(200)
    assert s.resolution == "raw"


def test_rollup_preserves_energy_and_extremes(db):
    fill(db, T0, 1800, 100)
    fill(db, T0 + 1800, 1800, 300)
    db.maintain(now=T0 + 7200)
    minutes = db.series(T0, T0 + 3600, "minute")
    assert len(minutes) == 60 and minutes[0][1] == pytest.approx(100) and minutes[-1][1] == pytest.approx(300)
    hour = db.conn.execute("SELECT avg_w, min_w, max_w, energy_wh, samples FROM hour").fetchall()
    assert hour == [(pytest.approx(200), 100, 300, pytest.approx(200), 720)]


def test_incomplete_bucket_is_not_rolled_up_early(db):
    fill(db, T0, 30, 100)
    db.maintain(now=T0 + 30)
    assert db.series(T0, T0 + 60, "minute") == []
    fill(db, T0 + 30, 30, 100)
    db.maintain(now=T0 + 61)
    assert db.series(T0, T0 + 60, "minute") == [(T0, pytest.approx(100))]


def test_retention_keeps_totals_via_coarser_tables(db):
    fill(db, T0, 3600, 120)
    db.maintain(now=T0 + 3600 + 60)
    db.maintain(now=T0 + 10 * DAY)
    assert db.conn.execute("SELECT COUNT(*) FROM raw").fetchone()[0] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM minute").fetchone()[0] == 0
    s = db.summary(T0, T0 + DAY)
    assert s.resolution == "hour"
    assert s.energy_wh == pytest.approx(120)


def test_estimated_fraction(db):
    for i in range(10):
        db.insert(reading(T0 + i * 5, 100, est=i < 3), 5)
    assert db.summary(T0, T0 + 60).estimated_fraction == pytest.approx(0.3)


class FakeSource:
    def __init__(self, items):
        self.items = list(items)

    def read(self):
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_logger_caps_gap_after_sleep(db):
    src = FakeSource([reading(T0, 100), reading(T0 + 5, 100), reading(T0 + 3600, 100)])
    lg = PowerLogger(src, db, interval_s=5)
    for _ in range(3):
        assert lg.step()
    dts = [r[0] for r in db.conn.execute("SELECT dt_s FROM raw ORDER BY ts")]
    assert dts == [5, 5, 10]  # the hour asleep is not billed


def test_logger_survives_sensor_outage(db):
    src = FakeSource([reading(T0, 100), SourceUnavailable("gone"), reading(T0 + 10, 100)])
    lg = PowerLogger(src, db, interval_s=5)
    assert [lg.step(), lg.step(), lg.step()] == [True, False, True]
    assert db.conn.execute("SELECT COUNT(*) FROM raw").fetchone()[0] == 2


def test_run_loop_with_mock(tmp_path):
    from powerwidget.sensors.composite import CompositeSource
    from powerwidget.sensors.mock import MockSource
    storage = Storage(tmp_path / "p.db")
    PowerLogger(CompositeSource([MockSource()]), storage, interval_s=0.01).run(max_samples=5)
    assert storage.conn.execute("SELECT COUNT(*) FROM raw").fetchone()[0] == 5
    storage.close()
