# Power widget

Tracks the power draw of a Windows **desktop** PC and logs it to SQLite so you
can look back at past usage. It has a sensor layer, a background logger, and a
floating widget with a history window (charts, kWh and cost, raw samples,
CSV export). Packaging as a single .exe comes next.

Stack: Python 3.11+, `psutil`, PySide6 and pyqtgraph for the UI. Packaging
with PyInstaller is planned.

## Where the watts come from

A desktop has no battery, so Windows has no "system power" number. No
software can see the real wall draw. We add up what the sensors can measure
and a fixed amount for the rest. See [docs/power-sources.md](docs/power-sources.md)
for the full comparison.

| Part | Source | Accuracy |
|---|---|---|
| CPU package | **LibreHardwareMonitorLib**, built in (primary) | Good. Read from the CPU's own energy counters (Intel RAPL, AMD SMU) |
| GPU board | the same library, or **NVML** for NVIDIA cards | Good. Reported by the GPU driver |
| Board, RAM, drives, fans, PSU loss | fixed `other_w` (default 40 W) | Rough. Tune it once with a wall meter |
| Fallback when no sensor answers | CPU load x TDP estimate | Poor. Every such sample is flagged `estimated` |

For exact numbers a smart plug with an API (Shelly, Tasmota) can be added later
as another source.

## Download (no Python needed)

Every push builds `PowerWidget.exe` with GitHub Actions. Get it from the
latest [release](../../releases/latest) (made when a tag like `v0.1.0` is
pushed) or, for any other build, from the *Artifacts* of a run under the
Actions tab. Double-click it: Windows asks for administrator rights once, and
the widget opens. Everything else is in the widget's right-click menu:

- *Mit Windows starten*: autostart at logon, as administrator and without a prompt
- *CPU-Treiber (PawnIO) installieren*: one-time driver install through winget (shown only while missing)
- *Einstellungen*, *Verlauf und Diagramme*, *Datenordner öffnen*

The exe is not code-signed, so Windows SmartScreen may say "Unknown publisher"
(click *More info*, then *Run anyway*), and some virus scanners flag every
PyInstaller program. The release lists a SHA-256 checksum, and the exe is built
from this repository by the workflow in `.github/workflows/build.yml`, so you
can verify what is inside. A log is kept in `%LOCALAPPDATA%\PowerWidget\powerwidget.log`.

To cut a release: `git tag v0.1.0 && git push origin v0.1.0`.

## Setup on Windows from source

**Quick start:** install [Python 3.11+](https://www.python.org/downloads/)
(tick "Add python.exe to PATH"), then double-click **`start.bat`**. The first
run sets everything up in a `.venv` folder next to it, then shows a menu
(in German): open the widget, live watts in the console, usage history,
sensor check, and starting the widget automatically at Windows logon.

## The widget

A small always-on-top box with the current total watts, the CPU/GPU/rest
split and today's kWh and cost. Drag it anywhere; it remembers its place.

- **Double-click** (or tray icon > *Verlauf*) opens the history window:
  - range buttons: 1 hour, 24 hours, 7 days, 30 days, 1 year
  - totals: kWh, cost, average and peak watts, recorded time, share of estimated samples
  - tab *Leistung*: total, CPU and GPU watts over time (hover for values)
  - tab *Verbrauch*: energy bars per 5 minutes, hour or day
  - tab *Messwerte*: the individual 5-second samples
  - *CSV exportieren*: the chart data as a CSV that opens in German Excel
- **Right-click**: history, always-on-top on/off, settings (electricity price and currency), open data folder, quit.

The widget logs by itself. If a separate `powerwidget log` process already
runs, the widget only reads, so no sample is ever counted twice.

No other program has to run next to it. The LibreHardwareMonitor library is
included (`powerwidget/vendor/lhm`, MPL-2.0) and loaded directly. For real CPU
readings it needs two things, and `start.bat` takes care of both:

- **Administrator rights.** `start.bat` asks once per start. Menu item 5 sets
  up the autostart as a scheduled task with highest privileges, so there is
  no prompt at logon.
- **The PawnIO driver**, installed once (`winget install namazso.PawnIO`,
  menu item 7). It is a small signed driver that also LibreHardwareMonitor and
  FanControl use.

Without them the widget still works: NVIDIA GPU power comes from the driver
(no admin needed) and the CPU is estimated. The widget then says why.
The old way (a separately running LibreHardwareMonitor with its Remote Web
Server) still works as a fallback, source name `lhm`.

Manual use, from a terminal in this folder:

1. `pip install -e .[nvidia]`
2. Check what works: `python -m powerwidget probe`
3. Print live watts: `python -m powerwidget now --watch`
4. Start logging: `python -m powerwidget log`
5. See history: `python -m powerwidget stats`
6. Open the widget: `pythonw -m powerwidget widget`

No hardware? Add `--mock` to any command to use a fake sensor.

## Settings

Optional `%APPDATA%\PowerWidget\config.toml`. Every key is optional:

```toml
sample_interval_s = 5
sources = ["lhmlib", "lhm", "nvml", "estimate"]   # tried in order, per component
lhm_url = "http://localhost:8085/data.json"
other_w = 40          # board, RAM, drives, fans, PSU loss
cpu_tdp_w = 105       # only used by the estimate fallback
raw_retention_days = 7
minute_retention_days = 90
price_per_kwh = 0.30  # for the cost display
currency = "€"
```

## Storage

Database: `%LOCALAPPDATA%\PowerWidget\power.db`.

| Table | Resolution | Kept |
|---|---|---|
| `raw` | every sample (5 s) | 7 days |
| `minute` | 1 min avg/min/max/kWh | 90 days |
| `hour` | 1 h avg/min/max/kWh | forever (about 9k rows a year) |

Each raw sample stores the time it stands for (`dt_s`), capped at two
intervals, so sleep and shutdown gaps are not counted as energy used.
Downsampling and retention run every 10 minutes and on exit.

## Development

```
pip install -e .[dev]
pytest
```

To build the exe yourself on Windows: `pip install -e .[nvidia] pyinstaller`,
then `python packaging/build_exe.py` (result in `dist/`).

Hardware access sits behind the `PowerSource` interface in
`powerwidget/sensors/`, so the tests run on any OS with mock sources and
recorded LibreHardwareMonitor JSON.
