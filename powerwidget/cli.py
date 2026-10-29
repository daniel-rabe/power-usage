"""Command line entry point: python -m powerwidget [widget|now|probe|log|stats|autostart|driver|selftest]."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from .config import Config, default_db_path
from .factory import build_composite
from .sensors.base import PowerReading, SourceUnavailable


def fmt(r: PowerReading) -> str:
    def w(v):
        return f"{v:6.1f} W" if v is not None else "     - "
    flag = "  ESTIMATED" if r.estimated else ""
    stamp = datetime.fromtimestamp(r.timestamp).strftime("%H:%M:%S")
    return (f"{stamp}  total {r.total_w:6.1f} W   cpu {w(r.cpu_w)}   gpu {w(r.gpu_w)}   "
            f"other {r.other_w:.0f} W   [{r.source_label}]{flag}")


def cmd_now(cfg: Config, args) -> int:
    src = build_composite(cfg)
    try:
        while True:
            try:
                print(fmt(src.read()), flush=True)
            except SourceUnavailable as exc:
                print(f"no reading: {exc}", file=sys.stderr)
            if not args.watch:
                return 0
            time.sleep(cfg.sample_interval_s)
    except KeyboardInterrupt:
        return 0
    finally:
        src.close()


def cmd_probe(cfg: Config, args) -> int:
    from .probe import probe
    for name, status in probe(cfg):
        print(f"{name:13} {status}")
    print(f"\nother components (fixed): {cfg.other_w:.0f} W  -- set other_w in the config to adjust")
    return 0


def cmd_log(cfg: Config, args) -> int:
    from .lock import logger_lock
    from .logger import PowerLogger
    from .storage import Storage
    lock = logger_lock(cfg.db_path)
    if not lock.acquire():
        print("The logger is already running (or the widget is logging).", file=sys.stderr)
        return 1
    storage = Storage(cfg.db_path, cfg.raw_retention_days, cfg.minute_retention_days)
    src = build_composite(cfg)
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    logging.info("logging every %.0fs to %s", cfg.sample_interval_s, cfg.db_path)
    try:
        PowerLogger(src, storage, cfg.sample_interval_s, cfg.maintenance_interval_s).run(stop)
    finally:
        src.close()
        storage.close()
        lock.release()
    return 0


def cmd_stats(cfg: Config, args) -> int:
    from .storage import Storage
    storage = Storage(cfg.db_path, cfg.raw_retention_days, cfg.minute_retention_days)
    storage.maintain()
    now = time.time()
    for label, seconds in (("last hour", 3600), ("last 24 h", 86400), ("last 7 days", 7 * 86400),
                           ("last 30 days", 30 * 86400)):
        s = storage.summary(now - seconds, now)
        if not s.covered_s:
            print(f"{label:13} no data")
            continue
        est = f"  ({s.estimated_fraction:.0%} estimated)" if s.estimated_fraction else ""
        print(f"{label:13} {s.energy_wh / 1000:7.3f} kWh   avg {s.avg_w:6.1f} W   "
              f"min {s.min_w:6.1f}   max {s.max_w:6.1f}   on {s.covered_s / 3600:5.1f} h{est}")
    storage.close()
    return 0


def cmd_autostart(cfg: Config, args) -> int:
    from . import winsetup
    if args.state == "status":
        print("on" if winsetup.autostart_enabled() else "off")
        return 0
    ok, msg = winsetup.set_autostart(args.state == "on")
    print(msg, file=sys.stdout if ok else sys.stderr)
    return 0 if ok else 1


def cmd_driver(cfg: Config, args) -> int:
    from . import winsetup
    ok, msg = winsetup.install_pawnio()
    print(msg, file=sys.stdout if ok else sys.stderr)
    return 0 if ok else 1


def cmd_selftest(cfg: Config, args) -> int:
    """Check that everything the packaged app needs can be loaded. Used by CI on the built exe."""
    import importlib
    lines, ok = [], True
    for mod in ("PySide6.QtWidgets", "pyqtgraph", "psutil", "powerwidget.ui.app", "powerwidget.ui.history"):
        try:
            importlib.import_module(mod)
            lines.append(f"ok    import {mod}")
        except Exception as exc:
            ok = False
            lines.append(f"FAIL  import {mod}: {exc!r}")
    if os.name == "nt":
        from .sensors.lhm_lib import self_test
        try:
            lines.append("ok    " + self_test())
        except Exception as exc:
            ok = False
            lines.append(f"FAIL  LibreHardwareMonitorLib: {exc!r}")
    text = "\n".join(lines) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if ok else 1


def cmd_widget(cfg: Config, args) -> int:
    from .ui.app import run
    return run(cfg)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="powerwidget", description="Track desktop PC power usage.")
    p.add_argument("--mock", action="store_true", help="use a fake sensor (no hardware needed)")
    p.add_argument("--db", help="database path (overrides config)")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd")  # no command: open the widget
    now = sub.add_parser("now", help="print current watts")
    now.add_argument("-w", "--watch", action="store_true", help="keep printing every interval")
    sub.add_parser("probe", help="check which power sources work on this PC")
    sub.add_parser("log", help="run the background logger")
    sub.add_parser("stats", help="show energy used over recent periods")
    sub.add_parser("widget", help="open the floating widget (default; logs too, unless a logger already runs)")
    auto = sub.add_parser("autostart", help="start the widget at Windows logon (run as administrator)")
    auto.add_argument("state", choices=["on", "off", "status"])
    sub.add_parser("driver", help="install the PawnIO driver (Windows, run as administrator)")
    st = sub.add_parser("selftest", help="check that the app's components load")
    st.add_argument("--output", help="also write the result to this file")
    args = p.parse_args(argv)

    level = logging.DEBUG if args.verbose else logging.INFO
    log_format = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    if sys.stderr is None:  # windowed exe: there is no console, so keep a log file
        log_file = Path(default_db_path()).with_name("powerwidget.log")
        log_file.parent.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(level=level, format=log_format, filename=log_file, encoding="utf-8")
    else:
        logging.basicConfig(level=level, format=log_format)
    cfg = Config.load()
    args.cmd = args.cmd or "widget"
    if args.mock:
        cfg.sources = ["mock"]
    if args.db:
        cfg.db_path = args.db
    handler = {"now": cmd_now, "probe": cmd_probe, "log": cmd_log, "stats": cmd_stats, "widget": cmd_widget,
               "autostart": cmd_autostart, "driver": cmd_driver, "selftest": cmd_selftest}[args.cmd]
    try:
        return handler(cfg, args)
    except SourceUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
