import pytest

from powerwidget.config import Config
from powerwidget.factory import build_composite
from powerwidget.sensors.base import SourceUnavailable
from powerwidget.sensors.lhm import parse_lhm
from powerwidget.sensors.lhm_lib import LhmLibSource, hardware_to_tree

POWER = object()
TEMP = object()


class Id:
    def __init__(self, s):
        self.s = s

    def __str__(self):
        return self.s


class Sensor:
    def __init__(self, name, value, kind, ident):
        self.Name, self.Value, self.SensorType, self.Identifier = name, value, kind, Id(ident)


class Hardware:
    def __init__(self, name, ident, sensors, sub=()):
        self.Name, self.Identifier, self.Sensors, self.SubHardware = name, Id(ident), sensors, list(sub)
        self.updates = 0

    def Update(self):
        self.updates += 1


def test_tree_from_dotnet_objects_feeds_the_same_parser():
    cpu = Hardware("Intel Core i7", "/intelcpu/0", [
        Sensor("CPU Package", 87.43, POWER, "/intelcpu/0/power/0"),
        Sensor("CPU Package", 64.0, TEMP, "/intelcpu/0/temperature/0"),
        Sensor("CPU Cores", None, POWER, "/intelcpu/0/power/1"),
    ])
    igpu = Hardware("UHD 770", "/gpu-intel-integrated/0", [Sensor("GPU Power", 1.3, POWER, "x")])
    gpu = Hardware("RTX 4070", "/gpu-nvidia/0", [Sensor("GPU Package", 142.6, POWER, "y")])
    tree = hardware_to_tree([cpu, igpu, gpu], POWER)
    assert cpu.updates == 1 and gpu.updates == 1
    r = parse_lhm(tree)
    assert r.cpu_w == pytest.approx(87.4)
    assert r.gpu_w == pytest.approx(142.6)


def test_subhardware_is_walked():
    sub = Hardware("Core", "/amdcpu/0/sub", [Sensor("Package", 55.0, POWER, "z")])
    cpu = Hardware("Ryzen", "/amdcpu/0", [], sub=[sub])
    assert parse_lhm(hardware_to_tree([cpu], POWER)).cpu_w == pytest.approx(55.0)


def test_source_unavailable_off_windows_with_reason():
    with pytest.raises(SourceUnavailable, match="Windows"):
        LhmLibSource()


def test_factory_reports_why_a_source_was_skipped():
    cfg = Config(sources=["lhmlib", "estimate"])
    composite = build_composite(cfg)
    assert "lhmlib" in composite.skipped
    assert [s.name for s in composite.sources] == ["estimate"]
