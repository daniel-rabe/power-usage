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
