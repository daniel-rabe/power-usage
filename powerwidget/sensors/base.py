"""Common types for power sources.

A desktop PC has no battery, so there is no single "system watts" reading.
Each source reports the components it can measure (CPU package, GPU board),
and the composite source adds a configured constant for everything else
(motherboard, RAM, drives, fans, PSU losses).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol


class SourceUnavailable(Exception):
    """Raised when a source cannot produce a reading right now."""


@dataclass(frozen=True)
class ComponentReading:
    """What a single source measured. Missing components are None."""

    cpu_w: float | None = None
    gpu_w: float | None = None
    estimated: bool = False


@dataclass(frozen=True)
class PowerReading:
    """One combined sample of the whole PC."""

    timestamp: float
    total_w: float
    cpu_w: float | None
    gpu_w: float | None
    other_w: float
    estimated: bool
    sources: dict[str, str] = field(default_factory=dict)  # component -> source name

    @property
    def source_label(self) -> str:
        return ",".join(f"{k}={v}" for k, v in sorted(self.sources.items()))


class PowerSource(Protocol):
    name: str

    def read(self) -> ComponentReading:
        """Return the current reading or raise SourceUnavailable."""
        ...

    def close(self) -> None: ...


def now() -> float:
    return time.time()
