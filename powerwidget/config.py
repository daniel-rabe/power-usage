"""Settings, loaded from config.toml with sensible defaults.

Windows: %APPDATA%\\PowerWidget\\config.toml, database in %LOCALAPPDATA%\\PowerWidget.
Elsewhere: ~/.config/powerwidget and ~/.local/share/powerwidget.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path


def _dir(win_env: str, fallback: str) -> Path:
    if os.name == "nt" and os.environ.get(win_env):
        return Path(os.environ[win_env]) / "PowerWidget"
    return Path.home() / fallback / "powerwidget"


def config_path() -> Path:
    return _dir("APPDATA", ".config") / "config.toml"


def default_db_path() -> str:
    return str(_dir("LOCALAPPDATA", ".local/share") / "power.db")


@dataclass
class Config:
    sample_interval_s: float = 5.0
    # Sources tried in this order; each component comes from the first that has it.
    sources: list[str] = field(default_factory=lambda: ["lhm", "nvml", "estimate"])
    lhm_url: str = "http://localhost:8085/data.json"
    # Everything the sensors cannot see: board, RAM, drives, fans, PSU loss.
    other_w: float = 40.0
    # Only used by the estimate fallback.
    cpu_idle_w: float = 15.0
    cpu_tdp_w: float = 105.0
    gpu_idle_w: float = 15.0
    db_path: str = field(default_factory=default_db_path)
    raw_retention_days: int = 7
    minute_retention_days: int = 90  # hourly rows are kept forever
    maintenance_interval_s: float = 600.0

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        path = path or config_path()
        if not path.exists():
            return cls()
        with path.open("rb") as fh:
            data = tomllib.load(fh)
        known = {f.name for f in fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown settings in {path}: {', '.join(sorted(unknown))}")
        return cls(**data)
