"""Deterministic data-freshness classification.

Rule: data must never visually present itself as live when it is not. Freshness
is derived from the *event/observation* time relative to now, bounded by the
source's own staleness budget - a rainfall station that reports hourly is stale
far sooner than a historical disaster register.
"""

from __future__ import annotations

from datetime import datetime

from shared.enums import FreshnessState, RiverState
from shared.timeutils import age_seconds

# Absolute ceilings (seconds) applied before the source-specific budget.
_FRESH_SECONDS = 15 * 60
_RECENT_SECONDS = 60 * 60
_AGING_SECONDS = 6 * 60 * 60

_RANK = {
    FreshnessState.FRESH: 0,
    FreshnessState.RECENT: 1,
    FreshnessState.AGING: 2,
    FreshnessState.STALE: 3,
    FreshnessState.UNKNOWN: 4,
}


def classify_age(age_secs: float | None, stale_after_seconds: int = 86_400) -> FreshnessState:
    if age_secs is None:
        return FreshnessState.UNKNOWN
    if age_secs < 0:
        # Clock skew between the source and Sanket; treat as fresh but never as stale.
        return FreshnessState.FRESH
    budget = max(60, int(stale_after_seconds))
    if age_secs <= min(_FRESH_SECONDS, budget / 4):
        return FreshnessState.FRESH
    if age_secs <= min(_RECENT_SECONDS, budget / 2):
        return FreshnessState.RECENT
    if age_secs <= min(_AGING_SECONDS, budget):
        return FreshnessState.AGING
    return FreshnessState.STALE


def classify(
    moment: datetime | None,
    stale_after_seconds: int = 86_400,
    now: datetime | None = None,
) -> FreshnessState:
    return classify_age(age_seconds(moment, now), stale_after_seconds)


def of_observation(
    kind: str,
    event_time: datetime | None,
    received_at: datetime | None,
    source_stale_after: int,
    now: datetime | None = None,
) -> FreshnessState:
    """Prefer the real event time; fall back to when we received it."""
    moment = event_time or received_at
    budget = source_stale_after
    if kind == "official_incident":
        # Disaster registers are inherently retrospective - a 3-day-old official
        # record is still authoritative, so it gets a longer budget.
        budget = max(budget, 7 * 86_400)
    return classify(moment, budget, now)


def is_stale(state: FreshnessState) -> bool:
    return state == FreshnessState.STALE


def worse(a: FreshnessState, b: FreshnessState) -> FreshnessState:
    return a if _RANK[a] >= _RANK[b] else b


def freshness_multiplier(state: FreshnessState) -> float:
    """Used by the impact score - stale information must not dominate the queue."""
    return {
        FreshnessState.FRESH: 1.0,
        FreshnessState.RECENT: 0.95,
        FreshnessState.AGING: 0.82,
        FreshnessState.STALE: 0.55,
        FreshnessState.UNKNOWN: 0.7,
    }[state]


def river_state(
    level: float | None,
    warning_level: float | None,
    danger_level: float | None,
    freshness: FreshnessState,
) -> RiverState:
    """Deterministic flood gauge classification against official thresholds."""
    if freshness == FreshnessState.STALE:
        return RiverState.STALE
    if level is None:
        return RiverState.NORMAL
    if danger_level is not None and level >= danger_level:
        return RiverState.DANGER
    if warning_level is not None and level >= warning_level:
        return RiverState.WARNING
    if warning_level is not None and level >= warning_level * 0.9:
        return RiverState.WATCH
    return RiverState.NORMAL
