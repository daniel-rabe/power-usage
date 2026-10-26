# Power widget

Tracks the power draw of a Windows **desktop** PC and logs it to SQLite so you
can look back at past usage. This is milestones 1 and 2: the sensor layer and
the background logger. The floating widget, charts, kWh/cost view and the
installer come next.

Stack: Python 3.11+, standard library plus `psutil`. The UI will use PySide6
and the app will be packaged with PyInstaller.

## Where the watts come from

A desktop has no battery, so Windows has no "system power" number. No
software can see the real wall draw. We add up what the sensors can measure
and a fixed amount for the rest. See [docs/power-sources.md](docs/power-sources.md)
for the full comparison.

| Part | Source | Accuracy |
|---|---|---|
| CPU package | **LibreHardwareMonitor** (primary) | Good. Read from the CPU's own energy counters (Intel RAPL, AMD SMU) |
| GPU board | LibreHardwareMonitor, or **NVML** for NVIDIA cards | Good. Reported by the GPU driver |
| Board, RAM, drives, fans, PSU loss | fixed `other_w` (default 40 W) | Rough. Tune it once with a wall meter |
| Fallback when no sensor answers | CPU load x TDP estimate | Poor. Every such sample is flagged `estimated` |

For exact numbers a smart plug with an API (Shelly, Tasmota) can be added later
as another source.

## Setup on Windows

1. Install Python 3.11+ and then, in this folder:
   `pip install -e .` (add `.[nvidia]` if you have an NVIDIA card).
2. Install [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases),
   run it **as administrator**, and turn on *Options > Remote Web Server > Run*
   (port 8085). Also tick *Options > Run On Windows Startup* and *Start Minimized*.
3. Check what works: `python -m powerwidget probe`
4. Print live watts: `python -m powerwidget now --watch`
5. Start logging: `python -m powerwidget log`
6. See history: `python -m powerwidget stats`

To log in the background from logon, without a console window:

```
schtasks /Create /TN "PowerWidget Logger" /SC ONLOGON /RL LIMITED ^
  /TR "\"%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe\" -m powerwidget log"
```

(Adjust the `pythonw.exe` path to your Python install.)

No hardware? Add `--mock` to any command to use a fake sensor.

## Settings

Optional `%APPDATA%\PowerWidget\config.toml`. Every key is optional:

```toml
sample_interval_s = 5
sources = ["lhm", "nvml", "estimate"]   # tried in order, per component
lhm_url = "http://localhost:8085/data.json"
other_w = 40          # board, RAM, drives, fans, PSU loss
cpu_tdp_w = 105       # only used by the estimate fallback
raw_retention_days = 7
minute_retention_days = 90
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

Hardware access sits behind the `PowerSource` interface in
`powerwidget/sensors/`, so the tests run on any OS with mock sources and
recorded LibreHardwareMonitor JSON.
