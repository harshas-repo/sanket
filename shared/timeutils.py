"""Time helpers.

All persisted timestamps are UTC. SQLite has no timezone support, so we store
naive UTC datetimes and convert at the edges. Never call `datetime.now()`
directly in domain code - go through `utcnow()` so demo-mode time acceleration
can override the clock in one place.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

_MINUTE = 60
_HOUR = 3600
_DAY = 86400

# Set by the demo engine when a simulated clock is active. It is reported as data rather than as a
# UI label - the `mode`/`sim_clock` row behind /api/system/status and the `X-Sanket-Mode` header -
# since the banner that named it went with the rehearsal screen. No screen reads either today.
_sim_clock: datetime | None = None


def set_simulated_clock(dt: datetime | None) -> None:
    global _sim_clock
    _sim_clock = dt


def get_simulated_clock() -> datetime | None:
    return _sim_clock


def utcnow() -> datetime:
    """Current UTC time, or the demo clock when scenario time is being driven."""
    if _sim_clock is not None:
        return _sim_clock
    return datetime.now(UTC).replace(tzinfo=None)


def real_utcnow() -> datetime:
    """Wall-clock UTC, never the demo clock.

    The scenario engine has to know how much *real* time has passed since it was armed to
    decide how much scenario time that is. Using `utcnow()` there would have the demo
    clock measure itself, and a scenario would freeze wherever it last stood.
    """
    return datetime.now(UTC).replace(tzinfo=None)


def to_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(UTC).replace(tzinfo=None)


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.replace(microsecond=0).isoformat() + "Z"


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%d %b %Y", "%d/%m/%Y"):
            try:
                dt = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            return None
    return to_utc(dt)


def epoch_ms_to_utc(ms: int | float | None) -> datetime | None:
    if ms is None:
        return None
    try:
        return datetime.fromtimestamp(float(ms) / 1000, tz=UTC).replace(tzinfo=None)
    except (OverflowError, OSError, ValueError):
        return None


def age_seconds(dt: datetime | None, now: datetime | None = None) -> float | None:
    if dt is None:
        return None
    return max(0.0, (to_utc(now or utcnow()) - to_utc(dt)).total_seconds())


def humanize_age(dt: datetime | None, now: datetime | None = None) -> str:
    """'Updated 4 min ago' / 'Last official update: 2h 14m ago' style strings."""
    secs = age_seconds(dt, now)
    if secs is None:
        return "no timestamp"
    if secs < 45:
        return "just now"
    if secs < _HOUR:
        return f"{int(secs // _MINUTE)} min ago"
    if secs < _DAY:
        mins = int(secs // _MINUTE)
        return f"{mins // 60}h {mins % 60:02d}m ago"
    days = int(secs // _DAY)
    if days == 1:
        return "yesterday"
    if days < 30:
        return f"{days} days ago"
    months = days // 30
    if months < 12:
        return f"{months} month{'s' if months != 1 else ''} ago"
    years = days // 365
    return f"{years} year{'s' if years != 1 else ''} ago"


def hhmm(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def day_label(dt: datetime) -> str:
    return dt.strftime("%d %b %Y")


def timedelta_since(dt: datetime | None, now: datetime | None = None) -> timedelta | None:
    secs = age_seconds(dt, now)
    return None if secs is None else timedelta(seconds=secs)
