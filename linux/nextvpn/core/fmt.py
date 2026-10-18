"""
Every number the interface shows a user. Kept away from the view model so the
rounding and unit rules can be tested without a display.

Number formatting is invariant rather than locale-driven, so a value never comes
out as "1,5 MB" beside labels in another language. Only the unit names are
translated.
"""

from __future__ import annotations

import math
from datetime import timedelta

from .i18n import N_, _
from .regions import Regions

_BYTE_UNITS = (N_("B"), N_("KB"), N_("MB"), N_("GB"), N_("TB"))
_RATE_UNITS = (N_("B/s"), N_("KB/s"), N_("MB/s"), N_("GB/s"))

#: Placeholder for a value that does not exist yet. One em dash, everywhere.
EMPTY = "—"


def _one_decimal(v: float) -> str:
    # "0.#": at most one decimal, none when it would be zero.
    text = f"{math.floor(v * 10 + 0.5) / 10:.1f}"
    return text[:-2] if text.endswith(".0") else text


def _scaled(value: float, units: tuple[str, ...]) -> str:
    i = 0
    while value >= 1024 and i < len(units) - 1:
        value /= 1024
        i += 1

    # Bytes are whole things; everything above them reads better with one decimal.
    number = str(int(value)) if i == 0 else _one_decimal(value)
    return f"{number} {_(units[i])}"


def bytes_(count: int) -> str:
    if count <= 0:
        return f"0 {_(_BYTE_UNITS[0])}"
    return _scaled(float(count), _BYTE_UNITS)


def rate(bytes_per_second: float) -> str:
    if bytes_per_second is None or math.isnan(bytes_per_second) or bytes_per_second < 1:
        return f"0 {_(_RATE_UNITS[0])}"
    return _scaled(float(bytes_per_second), _RATE_UNITS)


def duration(t: timedelta) -> str:
    """
    Session length. Minutes and seconds until the first hour, then hours as well,
    so the field only ever changes width once in a session.
    """
    total = int(t.total_seconds())
    if total <= 0:
        return EMPTY

    hours, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def country(code: str | None) -> str:
    """"Germany (DE)", or the placeholder when the engine has not said yet."""
    if not code:
        return EMPTY
    return f"{Regions.name_of(code)} ({code.upper()})"


def ports(http_port: int, socks_port: int) -> str:
    """Local listener ports, or the placeholder before either one is open."""
    if http_port <= 0 and socks_port <= 0:
        return EMPTY
    if http_port <= 0:
        return f"SOCKS {socks_port}"
    if socks_port <= 0:
        return f"HTTP {http_port}"
    return f"HTTP {http_port} · SOCKS {socks_port}"
