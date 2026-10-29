import json
from pathlib import Path

import pytest

from powerwidget.sensors.base import ComponentReading, SourceUnavailable
from powerwidget.sensors.composite import CompositeSource
from powerwidget.sensors.estimate import EstimateSource
from powerwidget.sensors.lhm import LhmSource, parse_lhm, parse_watts
from powerwidget.sensors.mock import MockSource

FIX = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("text,expected", [("87.4 W", 87.4), ("87,4 W", 87.4), ("12 W", 12.0),
                                           ("64.0 °C", None), ("", None), ("1,152 V", None)])
def test_parse_watts(text, expected):
    assert parse_watts(text) == expected


def test_lhm_intel_nvidia_skips_igpu_and_picks_package():
    r = parse_lhm(load("lhm_intel_nvidia.json"))
    assert r.cpu_w == pytest.approx(87.4)
    assert r.gpu_w == pytest.approx(142.6)  # iGPU 1.3 W not added: it's inside the CPU package
    assert not r.estimated


def test_lhm_old_format_without_ids():
    r = parse_lhm(load("lhm_amd_old.json"))
    assert r.cpu_w == pytest.approx(55.0)
    assert r.gpu_w == pytest.approx(180.5)


def test_lhm_no_power_sensors():
    with pytest.raises(SourceUnavailable):
        parse_lhm({"Children": [{"Text": "PC", "Children": []}]})


def test_lhm_unreachable():
    with pytest.raises(SourceUnavailable):
        LhmSource("http://127.0.0.1:9/data.json", timeout=0.5).read()


def test_estimate_scales_with_utilization():
    util = iter([0.0, 50.0, 100.0])
    src = EstimateSource(cpu_idle_w=10, cpu_tdp_w=110, gpu_idle_w=20, cpu_percent=lambda: next(util))
    assert [src.read().cpu_w for _ in range(3)] == [10, 60, 110]
    assert EstimateSource(cpu_percent=lambda: 0).read().estimated


def test_composite_takes_each_component_from_first_source():
    lhm = MockSource([ComponentReading(cpu_w=80.0)], name="lhm")
    nvml = MockSource([ComponentReading(gpu_w=150.0)], name="nvml")
    est = MockSource([ComponentReading(cpu_w=1, gpu_w=1, estimated=True)], name="estimate")
    r = CompositeSource([lhm, nvml, est], other_w=40, clock=lambda: 1000.0).read()
    assert (r.cpu_w, r.gpu_w, r.total_w) == (80.0, 150.0, 270.0)
    assert not r.estimated
    assert r.sources == {"cpu": "lhm", "gpu": "nvml"}


def test_composite_falls_back_to_estimate_and_flags_it():
    lhm = MockSource([SourceUnavailable("LHM not running")], name="lhm")
    nvml = MockSource([ComponentReading(gpu_w=100.0)], name="nvml")
    est = MockSource([ComponentReading(cpu_w=50.0, gpu_w=15.0, estimated=True)], name="estimate")
    r = CompositeSource([lhm, nvml, est], other_w=40).read()
    assert (r.cpu_w, r.gpu_w, r.total_w) == (50.0, 100.0, 190.0)
    assert r.estimated
    assert r.sources == {"cpu": "estimate", "gpu": "nvml"}


def test_composite_all_fail():
    with pytest.raises(SourceUnavailable):
        CompositeSource([MockSource([SourceUnavailable("x")])]).read()
