from powerwidget.lock import InstanceLock
from powerwidget.ui import fmt


def test_only_one_logger(tmp_path):
    a, b = InstanceLock(tmp_path / "x.lock"), InstanceLock(tmp_path / "x.lock")
    assert a.acquire()
    assert not b.acquire()
    a.release()
    assert b.acquire()
    b.release()


def test_german_formatting():
    assert fmt.num(1234.5, 1) == "1.234,5"
    assert fmt.watts(None) == "– W"
    assert fmt.kwh(1530) == "1,53 kWh"
    assert fmt.money(0.456, "€") == "0,46 €"
    assert fmt.duration(5400) == "1,5 h"


def test_config_save_keeps_other_settings(tmp_path):
    from powerwidget.config import Config
    path = tmp_path / "config.toml"
    path.write_text('other_w = 55.0\nsources = ["lhm", "estimate"]\n', encoding="utf-8")
    cfg = Config.load(path)
    cfg.price_per_kwh, cfg.currency, cfg.db_path = 0.3512, "CHF", "/somewhere/else.db"
    cfg.save(["price_per_kwh", "currency"], path)
    again = Config.load(path)
    assert (again.price_per_kwh, again.currency, again.other_w) == (0.3512, "CHF", 55.0)
    assert again.sources == ["lhm", "estimate"]
    assert again.db_path != "/somewhere/else.db"  # only the requested keys are written
