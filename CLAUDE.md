# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Windows desktop power-usage tracker (Python 3.11+, PySide6, pyqtgraph, SQLite). It reads CPU/GPU watts,
adds a fixed `other_w` for the rest of the PC, logs samples to SQLite and shows a floating widget with a
history window. It ships as a single `PowerWidget.exe` built with PyInstaller. User-facing UI text (widget
menus, history window, `start.bat`) is in **German**; code, comments and docs are in English.

## Commands

```bash
pip install -e .[dev]            # add [nvidia] for NVML GPU readings
pytest                           # whole suite (runs on any OS; hardware is mocked)
pytest tests/test_storage_logger.py::test_name   # single test
python -m powerwidget --mock now --watch          # any command with a fake sensor
python -m powerwidget probe      # which sources work on this PC
python -m powerwidget selftest   # checks Qt, pyqtgraph and (Windows) LibreHardwareMonitorLib load
python packaging/build_exe.py    # build dist/PowerWidget.exe (needs .[nvidia] + pyinstaller, Windows)
python tools/fetch_lhm.py        # re-download vendored LHM DLLs from NuGet (version pinned in the script)
```

Other CLI commands: `log`, `stats`, `widget` (default with no command), `autostart on|off|status`,
`driver`; global flags `--mock`, `--db PATH`, `-v`. UI tests need `QT_QPA_PLATFORM=offscreen` on headless
machines (tests set it themselves; CI sets it for `selftest`). No linter is configured.

CI (`.github/workflows/build.yml`): pytest + `selftest` on Ubuntu and Windows, then builds the exe, runs
`PowerWidget.exe selftest --output selftest.txt` (windowed exe has no console, hence `--output`), and
publishes a GitHub release on `v*` tags.

## Architecture

**Sensor chain.** Every hardware source implements the `PowerSource` protocol in
`powerwidget/sensors/base.py`: `read()` returns a `ComponentReading` (cpu_w / gpu_w, either may be None) or
raises `SourceUnavailable`; constructors also raise `SourceUnavailable` when the source can't start.
`factory.build_composite()` instantiates the names in `Config.sources` (default order
`lhmlib, lhm, nvml, estimate`), silently skipping ones that fail to start and recording why in
`composite.skipped` (the widget shows `skipped["lhmlib"]` as a hint). `CompositeSource.read()` takes each
component from the **first** source that has it and adds `other_w` to form a `PowerReading`. Any estimated
component marks the whole sample `estimated`. To add a source: new module in `sensors/`, a branch in
`factory.make_source`, and a name in the config's `sources`.

- `lhmlib`: LibreHardwareMonitorLib loaded in-process via pythonnet (`netfx`) from the vendored DLLs in
  `powerwidget/vendor/lhm`. Needs admin rights and the PawnIO driver. It converts the .NET hardware tree into
  the same JSON shape the LHM web server publishes, so `sensors/lhm.parse_lhm()` parses both `lhmlib` and
  the legacy HTTP `lhm` source. Tests use recorded trees in `tests/fixtures/*.json`.
- `nvml`: NVIDIA GPU via `nvidia-ml-py`, no admin needed.
- `estimate`: CPU load × TDP fallback, flagged estimated.

**Single writer.** Only one process may write samples, or energy is double-counted. `lock.logger_lock()`
takes a non-blocking file lock on `<db>.lock`. Both `powerwidget log` and the widget's in-process
`ui/background.BackgroundLogger` (a thread running `PowerLogger`) try to acquire it; the widget only reads if
another logger holds it. A separate `<db>.widget.lock` keeps a second widget instance from starting.

**Energy accounting.** `PowerLogger.step()` stores each raw sample with `dt_s` = time since previous sample,
capped at 2 × interval and reset after a failed read, so sleep/shutdown gaps are not billed. Energy is
always `sum(total_w * dt_s) / 3600`.

**Storage** (`storage.py`): tables `raw` → `minute` → `hour`, rolled up and pruned by `maintain()` (every
10 min and on exit). Queries go through `_unified()`, a UNION over all three tables that picks the finest
resolution available for each time span without overlap; `summary`, `series` and `energy_by_day` build on
it. Keep retention cuts aligned to minute/hour boundaries or `_unified` will double-count or leave holes.

**Config** (`config.py`): dataclass loaded from `%APPDATA%\PowerWidget\config.toml` (all keys optional);
database and log in `%LOCALAPPDATA%\PowerWidget\` (`~/.config` / `~/.local/share` elsewhere).
`Config.save(keys)` writes back only the given keys (used by the settings dialog).

**UI** (`ui/`): `app.run()` wires the always-on-top `widget.PowerWidget`, tray icon, `history.HistoryWindow`
(pyqtgraph charts, ranges, CSV export) and `settings.SettingsDialog`. `winsetup.py` handles the Windows
autostart scheduled task (runs elevated without a UAC prompt) and PawnIO install via winget.

**Packaging**: `packaging/entry.py` is the PyInstaller entry (calls `cli.main`); `build_exe.py` builds a
one-file windowed exe with `--uac-admin`, bundles `vendor/lhm` and collects pythonnet/clr_loader. When the
exe runs windowed, `sys.stderr` is None and `cli.main` logs to `%LOCALAPPDATA%\PowerWidget\powerwidget.log`.

See `docs/power-sources.md` for why the numbers are component sums rather than wall power.
