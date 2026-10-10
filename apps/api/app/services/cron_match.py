"""Minimal 5-field cron matcher (minute hour dom month dow).

Supports ``*``, integers, lists (``1,2``), ranges (``1-5``), and steps
(``*/15``, ``1-10/2``). Day-of-week uses Sunday=0 … Saturday=6 (7 also means Sunday).
When both day-of-month and day-of-week are restricted, either may match (Vixie-style).
"""

from __future__ import annotations

from datetime import datetime


def _parse_field(field: str, minimum: int, maximum: int) -> set[int]:
    values: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if not part:
            raise ValueError("empty cron field part")
        step = 1
        if "/" in part:
            base, step_s = part.split("/", 1)
            step = int(step_s)
            if step < 1:
                raise ValueError("cron step must be >= 1")
            part = base or "*"
        if part == "*":
            start, end = minimum, maximum
        elif "-" in part:
            a, b = part.split("-", 1)
            start, end = int(a), int(b)
        else:
            start = end = int(part)
        if start > end:
            raise ValueError("cron range start > end")
        for n in range(start, end + 1, step):
            if minimum <= n <= maximum:
                values.add(n)
    return values


def _dow_values(field: str) -> set[int]:
    raw = _parse_field(field, 0, 7)
    # 7 == Sunday in some cron dialects
    if 7 in raw:
        raw.discard(7)
        raw.add(0)
    return raw


def cron_matches(expr: str, when: datetime) -> bool:
    """Return True if ``when`` falls on the cron expression (second ignored)."""
    parts = expr.strip().split()
    if len(parts) != 5:
        raise ValueError("schedule must be 5-field cron")
    minute_f, hour_f, dom_f, month_f, dow_f = parts

    if when.minute not in _parse_field(minute_f, 0, 59):
        return False
    if when.hour not in _parse_field(hour_f, 0, 23):
        return False
    if when.month not in _parse_field(month_f, 1, 12):
        return False

    dom_star = dom_f == "*"
    dow_star = dow_f == "*"
    dom_ok = when.day in _parse_field(dom_f, 1, 31)
    # datetime: Mon=0 … Sun=6 → cron: Sun=0, Mon=1 … Sat=6
    cron_dow = (when.weekday() + 1) % 7
    dow_ok = cron_dow in _dow_values(dow_f)

    if dom_star and dow_star:
        return True
    if not dom_star and dow_star:
        return dom_ok
    if dom_star and not dow_star:
        return dow_ok
    return dom_ok or dow_ok
