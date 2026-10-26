"""Build the configured source chain, skipping sources that can't start."""

from __future__ import annotations

import logging

from .config import Config
from .sensors.base import PowerSource, SourceUnavailable
from .sensors.composite import CompositeSource

log = logging.getLogger(__name__)


def make_source(name: str, cfg: Config) -> PowerSource:
    if name == "lhm":
        from .sensors.lhm import LhmSource
        return LhmSource(cfg.lhm_url)
    if name == "nvml":
        from .sensors.nvml import NvmlSource
        return NvmlSource()
    if name == "estimate":
        from .sensors.estimate import EstimateSource
        return EstimateSource(cfg.cpu_idle_w, cfg.cpu_tdp_w, cfg.gpu_idle_w)
    if name == "mock":
        from .sensors.mock import MockSource
        return MockSource()
    raise ValueError(f"unknown source {name!r}")


def build_composite(cfg: Config) -> CompositeSource:
    sources = []
    for name in cfg.sources:
        try:
            sources.append(make_source(name, cfg))
        except SourceUnavailable as exc:
            log.info("skipping %s: %s", name, exc)
    if not sources:
        raise SourceUnavailable("none of the configured sources could start")
    return CompositeSource(sources, other_w=cfg.other_w)
