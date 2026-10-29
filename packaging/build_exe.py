"""Build PowerWidget.exe with PyInstaller. Run from the repository root:

    python packaging/build_exe.py

Needs: pip install -e ".[nvidia]" pyinstaller. The exe asks for administrator
rights when started (reading CPU power needs them); the autostart task created
by the app runs it elevated without a prompt.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"


def main() -> int:
    BUILD.mkdir(exist_ok=True)
    icon = BUILD / "app.ico"
    subprocess.run([sys.executable, str(ROOT / "packaging" / "make_icon.py"), str(icon)], check=True,
                   env={**os.environ, "PYTHONPATH": str(ROOT)})

    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
           "--name", "PowerWidget", "--icon", str(icon),
           "--distpath", str(ROOT / "dist"), "--workpath", str(BUILD / "pyinstaller"), "--specpath", str(BUILD),
           "--add-data", f"{ROOT / 'powerwidget' / 'vendor' / 'lhm'}{os.pathsep}powerwidget/vendor/lhm"]
    if sys.platform == "win32":
        cmd += ["--uac-admin", "--collect-all", "pythonnet", "--collect-all", "clr_loader"]
    cmd.append(str(ROOT / "packaging" / "entry.py"))
    return subprocess.run(cmd, cwd=ROOT).returncode


if __name__ == "__main__":
    sys.exit(main())
