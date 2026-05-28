"""Cron expression parser and next-run calculator (no external deps)."""
from __future__ import annotations
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional


_MONTH_NAMES = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_DOW_NAMES = {
    "sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6,
}

_NAMED_SCHEDULES = {
    "@yearly":   "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
    "@monthly":  "0 0 1 * *",
    "@weekly":   "0 0 * * 0",
    "@daily":    "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@hourly":   "0 * * * *",
}


def _expand_field(field: str, lo: int, hi: int) -> List[int]:
    """Expand one cron field into a sorted list of matching values."""
    field = field.strip()
    # Aliases
    for name, val in {**_MONTH_NAMES, **_DOW_NAMES}.items():
        field = re.sub(rf"\b{name}\b", str(val), field, flags=re.IGNORECASE)

    if field == "*":
        return list(range(lo, hi + 1))

    values: set[int] = set()
    for part in field.split(","):
        if "/" in part:
            base, step = part.split("/", 1)
            step = int(step)
            if base == "*":
                rng = range(lo, hi + 1, step)
            elif "-" in base:
                a, b = base.split("-", 1)
                rng = range(int(a), int(b) + 1, step)
            else:
                rng = range(int(base), hi + 1, step)
            values.update(rng)
        elif "-" in part:
            a, b = part.split("-", 1)
            values.update(range(int(a), int(b) + 1))
        else:
            values.add(int(part))

    return sorted(v for v in values if lo <= v <= hi)


class CronSchedule:
    """
    Parses a 5-field cron expression and computes the next scheduled time.

    Fields: minute hour day-of-month month day-of-week
    """

    def __init__(self, expression: str) -> None:
        expr = _NAMED_SCHEDULES.get(expression.strip().lower(), expression.strip())
        parts = expr.split()
        if len(parts) != 5:
            raise ValueError(f"Expected 5-field cron expression, got: {expression!r}")
        self.expression = expression
        self._minute  = _expand_field(parts[0],  0,  59)
        self._hour    = _expand_field(parts[1],  0,  23)
        self._dom     = _expand_field(parts[2],  1,  31)
        self._month   = _expand_field(parts[3],  1,  12)
        self._dow     = _expand_field(parts[4],  0,   6)  # 0=Sun

    def next_after(self, dt: datetime) -> datetime:
        """Return the next fire time strictly after *dt* (UTC-aware)."""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        # Advance by 1 minute, then find next matching slot
        candidate = dt.replace(second=0, microsecond=0) + timedelta(minutes=1)

        # Safety cap: don't loop more than 4 years
        limit = candidate + timedelta(days=366 * 4)
        while candidate < limit:
            if candidate.month not in self._month:
                # jump to next valid month
                candidate = candidate.replace(day=1, hour=0, minute=0)
                candidate += timedelta(days=32)
                candidate = candidate.replace(day=1)
                continue

            dom_match = candidate.day in self._dom
            dow_match = (candidate.weekday() + 1) % 7 in self._dow  # Python Mon=0, cron Sun=0

            if not (dom_match and dow_match):
                candidate = candidate.replace(hour=0, minute=0) + timedelta(days=1)
                continue

            if candidate.hour not in self._hour:
                candidate = candidate.replace(minute=0) + timedelta(hours=1)
                continue

            if candidate.minute not in self._minute:
                candidate += timedelta(minutes=1)
                continue

            return candidate

        raise RuntimeError(f"Could not find next fire time for {self.expression!r}")

    def expected_before(self, now: datetime, grace_seconds: int = 60) -> datetime:
        """Return the most recent scheduled time before *now* minus grace."""
        target = now - timedelta(seconds=grace_seconds)
        # Walk back: find the last fire before target
        # We compute next_after(target - 1 year) then iterate forward
        probe = target - timedelta(days=366)
        last = None
        limit_iters = 100_000
        i = 0
        t = probe
        while i < limit_iters:
            t = self.next_after(t)
            if t >= target:
                break
            last = t
            i += 1
        return last  # type: ignore[return-value]
