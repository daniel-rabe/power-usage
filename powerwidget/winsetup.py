"""Windows setup tasks the app can do for itself: autostart and the PawnIO driver."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

TASK_NAME = "PowerWidget"
PAWNIO_ID = "namazso.PawnIO"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def available() -> bool:
    return os.name == "nt"


def launch_command() -> str:
    """Command line that starts the widget: the exe when frozen, else pythonw -m powerwidget."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    exe = sys.executable
    pythonw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    return f'"{pythonw if os.path.exists(pythonw) else exe}" -m powerwidget widget'


def _run(args: list[str], timeout: float = 120) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, creationflags=_NO_WINDOW)


def autostart_enabled() -> bool:
    if not available():
        return False
    try:
        return _run(["schtasks", "/Query", "/TN", TASK_NAME], 15).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def set_autostart(on: bool) -> tuple[bool, str]:
    """Create or remove a logon task that runs with highest privileges, so the
    widget starts as administrator without a UAC prompt. Needs an elevated process."""
    if not available():
        return False, "Nur unter Windows verfügbar."
    try:
        if on:
            _run(["schtasks", "/Delete", "/F", "/TN", "PowerWidget Logger"], 15)  # task name of an older version
            r = _run(["schtasks", "/Create", "/F", "/TN", TASK_NAME, "/SC", "ONLOGON", "/RL", "HIGHEST",
                      "/TR", launch_command()], 30)
        else:
            r = _run(["schtasks", "/Delete", "/F", "/TN", TASK_NAME], 30)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    if r.returncode != 0:
        return False, (r.stderr or r.stdout).strip() or f"schtasks Fehlercode {r.returncode}"
    return True, "Das Widget startet jetzt bei jeder Anmeldung." if on else "Automatischer Start entfernt."


def install_pawnio() -> tuple[bool, str]:
    """Install the PawnIO driver through winget (needs an elevated process)."""
    if not available():
        return False, "Nur unter Windows verfügbar."
    winget = shutil.which("winget")
    if not winget:
        return False, "winget wurde nicht gefunden. PawnIO bitte von https://pawnio.eu installieren."
    try:
        r = _run([winget, "install", "--id", PAWNIO_ID, "--exact", "--silent",
                  "--accept-package-agreements", "--accept-source-agreements"], 600)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    from .sensors.lhm_lib import pawnio_installed
    if r.returncode == 0 or pawnio_installed():
        return True, "PawnIO ist installiert. Bitte das Widget neu starten."
    return False, (r.stdout + r.stderr).strip()[-400:] or f"winget Fehlercode {r.returncode}"
