"""German number and time formatting for the UI."""

from __future__ import annotations


def num(value: float | None, decimals: int = 0) -> str:
    if value is None:
        return "–"
    s = f"{value:,.{decimals}f}"
    return s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def watts(value: float | None) -> str:
    return f"{num(value)} W"


def kwh(wh: float) -> str:
    return f"{num(wh / 1000, 2 if wh < 100_000 else 1)} kWh"


def money(amount: float, currency: str) -> str:
    return f"{num(amount, 2)} {currency}"


def duration(seconds: float) -> str:
    hours = seconds / 3600
    if hours < 1:
        return f"{num(seconds / 60)} min"
    if hours < 48:
        return f"{num(hours, 1)} h"
    return f"{num(hours / 24, 1)} Tage"
