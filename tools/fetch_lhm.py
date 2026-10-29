"""Download LibreHardwareMonitorLib and its dependencies from NuGet into
powerwidget/vendor/lhm/ (the .NET Framework 4.7.2 build, which runs on the
.NET Framework that ships with Windows 10/11, so no extra runtime is needed).

Run on any OS:  python tools/fetch_lhm.py
"""

from __future__ import annotations

import io
import re
import shutil
import sys
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = "LibreHardwareMonitorLib"
VERSION = "0.9.6"
TARGET = Path(__file__).resolve().parent.parent / "powerwidget" / "vendor" / "lhm"
# Best match first, for a .NET Framework 4.7.2 process.
TFMS = ["net472", "net471", "net47", "net462", "net461", "net46", "net452", "net45", "netstandard2.0", "netstandard1.6"]
# Part of .NET Framework itself or not needed at runtime.
SKIP = {"netstandard.library", "microsoft.netcore.platforms"}


def fetch(pkg: str, version: str) -> zipfile.ZipFile:
    url = f"https://api.nuget.org/v3-flatcontainer/{pkg.lower()}/{version.lower()}/{pkg.lower()}.{version.lower()}.nupkg"
    with urllib.request.urlopen(url, timeout=60) as r:
        return zipfile.ZipFile(io.BytesIO(r.read()))


def pick_group(nuspec: str) -> list[tuple[str, str]]:
    root = ET.fromstring(nuspec.lstrip("﻿"))
    ns = {"n": root.tag.split("}")[0].strip("{")}
    groups = root.findall(".//n:dependencies/n:group", ns)
    by_tfm = {}
    for g in groups:
        tfm = (g.get("targetFramework") or "").lower().replace(".netframework", "net").replace(".", "")
        tfm = re.sub(r"^netstandard(\d)(\d)$", r"netstandard\1.\2", tfm)
        by_tfm[tfm] = [(d.get("id"), d.get("version", "").strip("[]()").split(",")[0]) for d in
                       g.findall("n:dependency", ns)]
    for tfm in TFMS:
        if tfm in by_tfm:
            return by_tfm[tfm]
    return next(iter(by_tfm.values()), []) if by_tfm else []


def pick_dlls(z: zipfile.ZipFile) -> list[str]:
    names = z.namelist()
    for tfm in TFMS:
        found = [n for n in names if n.startswith(f"lib/{tfm}/") and n.endswith(".dll")]
        if found:
            return found
    return []


def main() -> int:
    if TARGET.exists():
        shutil.rmtree(TARGET)
    TARGET.mkdir(parents=True)
    seen: dict[str, str] = {}
    queue = [(ROOT, VERSION)]
    licenses = []
    while queue:
        pkg, ver = queue.pop(0)
        if pkg.lower() in seen or pkg.lower() in SKIP:
            continue
        seen[pkg.lower()] = ver
        z = fetch(pkg, ver)
        nuspec = next(n for n in z.namelist() if n.endswith(".nuspec"))
        spec = z.read(nuspec).decode("utf-8")
        lic = re.search(r"<license[^>]*>([^<]*)</license>", spec)
        licenses.append(f"{pkg} {ver}: {lic.group(1) if lic else 'see package'}")
        dlls = pick_dlls(z) if pkg != ROOT else [n for n in z.namelist() if n.startswith("runtimes/win-x64/lib/net472/") and n.endswith(".dll")]
        for n in dlls:
            (TARGET / Path(n).name).write_bytes(z.read(n))
            print(f"{pkg} {ver}: {Path(n).name}")
        queue += pick_group(spec)
    (TARGET / "PACKAGES.txt").write_text(
        "Downloaded by tools/fetch_lhm.py from nuget.org. LibreHardwareMonitorLib is MPL-2.0.\n\n"
        + "\n".join(licenses) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
