"""LibreHardwareMonitorLib loaded in-process through pythonnet.

No separate LibreHardwareMonitor program is needed. The DLLs ship in
powerwidget/vendor/lhm (see tools/fetch_lhm.py). Two things must be true on
the PC, otherwise this source reports itself unavailable and the next one in
the chain takes over:

* the process runs as administrator (reading CPU power needs a kernel driver)
* the PawnIO driver is installed once (`winget install namazso.PawnIO`);
  the library carries its own PawnIO modules, only the driver itself is separate.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .base import ComponentReading, SourceUnavailable
from .lhm import parse_lhm

VENDOR_DIR = Path(__file__).resolve().parent.parent / "vendor" / "lhm"


def is_admin() -> bool:
    if os.name != "nt":
        return False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def pawnio_installed() -> bool:
    if os.name != "nt":
        return False
    try:
        import winreg
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                       r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\PawnIO"))
        return True
    except OSError:
        pass
    try:  # 32-bit registry view
        import winreg
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                       r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\PawnIO", 0,
                                       winreg.KEY_READ | winreg.KEY_WOW64_32KEY))
        return True
    except OSError:
        return False


def hardware_to_tree(hardware: Any, sensor_type_power: Any) -> dict[str, Any]:
    """Turn LHM hardware objects into the same tree the web server publishes,
    so parse_lhm() handles both. Only power sensors are kept."""

    def node(hw) -> dict[str, Any]:
        hw.Update()
        sensors = [
            {"Text": str(s.Name), "Value": f"{float(s.Value):.1f} W", "SensorId": str(s.Identifier), "Children": []}
            for s in hw.Sensors if s.SensorType == sensor_type_power and s.Value is not None
        ]
        return {"Text": str(hw.Name), "HardwareId": str(hw.Identifier), "Value": "",
                "Children": sensors + [node(sub) for sub in hw.SubHardware]}

    return {"Text": "Sensor", "Value": "", "Children": [node(hw) for hw in hardware]}


def _load_clr(vendor_dir: Path):
    import sys
    import pythonnet
    pythonnet.load("netfx")
    import clr  # type: ignore[import-not-found]
    sys.path.append(str(vendor_dir))
    clr.AddReference(str(vendor_dir / "LibreHardwareMonitorLib.dll"))
    return clr


def self_test(vendor_dir: Path = VENDOR_DIR) -> str:
    """Load the .NET library and create a Computer without opening it (no driver or admin needed).
    Proves that pythonnet, the DLLs and their dependencies are all in place."""
    _load_clr(vendor_dir)
    from LibreHardwareMonitor.Hardware import Computer  # type: ignore[import-not-found]
    computer = Computer()
    computer.IsCpuEnabled = True
    return f"LibreHardwareMonitorLib loaded ({type(computer).__module__}.{type(computer).__name__})"


class LhmLibSource:
    name = "lhmlib"

    def __init__(self, vendor_dir: Path = VENDOR_DIR):
        if os.name != "nt":
            raise SourceUnavailable("LibreHardwareMonitorLib only runs on Windows")
        if not is_admin():
            raise SourceUnavailable("needs administrator rights to read CPU power")
        if not pawnio_installed():
            raise SourceUnavailable("PawnIO driver not installed (run: winget install namazso.PawnIO)")
        dll = vendor_dir / "LibreHardwareMonitorLib.dll"
        if not dll.exists():
            raise SourceUnavailable(f"{dll} is missing (run tools/fetch_lhm.py)")
        try:
            _load_clr(vendor_dir)
            from LibreHardwareMonitor.Hardware import Computer, SensorType  # type: ignore[import-not-found]
            self._power = SensorType.Power
            self._computer = Computer()
            self._computer.IsCpuEnabled = True
            self._computer.IsGpuEnabled = True
            self._computer.Open()
        except Exception as exc:
            raise SourceUnavailable(f"LibreHardwareMonitorLib failed to open: {exc}") from exc

    def read(self) -> ComponentReading:
        try:
            tree = hardware_to_tree(self._computer.Hardware, self._power)
        except Exception as exc:
            raise SourceUnavailable(f"LibreHardwareMonitorLib read failed: {exc}") from exc
        return parse_lhm(tree)

    def close(self) -> None:
        try:
            self._computer.Close()
        except Exception:
            pass
