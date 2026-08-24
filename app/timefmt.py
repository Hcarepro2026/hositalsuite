"""How long something took — one clock for every screen and every voice.

Patients and staff were seeing a pile of minutes (256m). That is hard to
read. We always show hours:minutes, so 154 minutes is 2:34m and 1,465
minutes is 24:25m.

Spoken lines stay in words: "2 hours 34 minutes".
"""
from __future__ import annotations


def _minutes(value) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, str) and value.strip() in ("", "—", "-"):
        return None
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    return max(0, n)


def fmt_hm(value) -> str:
    """Compact clock: 154 → '2:34m', 45 → '0:45m', unknown → '—'."""
    n = _minutes(value)
    if n is None:
        return "—"
    hours, mins = divmod(n, 60)
    return f"{hours}:{mins:02d}m"


def say_hm(value) -> str:
    """Spoken / prose clock: 154 → '2 hours 34 minutes'."""
    n = _minutes(value)
    if n is None:
        return "—"
    if n == 0:
        return "0 minutes"
    hours, mins = divmod(n, 60)
    parts: list[str] = []
    if hours:
        parts.append("1 hour" if hours == 1 else f"{hours} hours")
    if mins:
        parts.append("1 minute" if mins == 1 else f"{mins} minutes")
    return " ".join(parts)
