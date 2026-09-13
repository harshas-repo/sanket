"""Trust & evidence layer.

Never treat every report as equal. The evidence state of an incident is computed
from *what actually backs it*, and promotion to OFFICIALLY_CONFIRMED can only be
performed by code that has seen an authoritative source record or an accountable
operator - never by the language model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shared.enums import EvidenceState

# Only these actors may set an official state. 'agent' is deliberately absent.
OFFICIAL_PROMOTION_ACTORS = frozenset({"system:ingestion", "operator", "coordinator", "system"})

# Observation kinds that mean "an official body has a record of this event". A
# seismic agency catalogue entry counts: the network detection *is* the official
# record. Whether the details are CONFIRMED is a separate, stricter step.
AUTHORITATIVE_CONFIRMATION_KINDS = frozenset({"official_alert", "official_incident", "earthquake"})

# Relative weight of each official source when cross-validating.
SOURCE_AUTHORITY: dict[str, float] = {
    "nemrc": 0.95,  # national earthquake authority for Nepal
    "usgs": 0.85,  # global authority, used for cross-validation
    "dhm": 0.95,  # rainfall / river / flood warnings
    "hydrology": 0.95,  # flood forecasting service
    "drr": 0.9,  # official national disaster incident register
    "dor": 0.7,  # road status; PDF-only, lowest machine confidence
    "community": 0.15,
    "demo": 0.0,
}


def authority_of(source_code: str | None) -> float:
    if not source_code:
        return 0.0
    return SOURCE_AUTHORITY.get(source_code.lower(), 0.5)


@dataclass
class EvidenceInputs:
    official_observation_kinds: list[str] = field(default_factory=list)
    official_sources: list[str] = field(default_factory=list)
    supporting_signal_kinds: list[str] = field(default_factory=list)
    community_report_count: int = 0
    unique_reporter_count: int = 0
    conflicting_count: int = 0
    authoritative_confirmation: bool = False
    operator_verified: bool = False
    provenance: str = "official"
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def has_direct_official_record(self) -> bool:
        return any(k in AUTHORITATIVE_CONFIRMATION_KINDS for k in self.official_observation_kinds)

    @property
    def has_supporting_official_signal(self) -> bool:
        return bool(self.supporting_signal_kinds)


def compute_state(inputs: EvidenceInputs) -> tuple[EvidenceState, list[str]]:
    """Deterministic state machine. Returns the state plus the human-readable
    justification that is displayed verbatim in the Evidence panel."""
    reasons: list[str] = []

    if inputs.conflicting_count > 0:
        reasons.append(
            f"{inputs.conflicting_count} source(s) disagree with the current picture"
        )
        reasons.append("Resolution requires an authoritative source or an operator decision")
        return EvidenceState.CONFLICTING, reasons

    if inputs.provenance == "demo":
        reasons.append("Demo scenario data - explicitly not official information")
        return EvidenceState.UNVERIFIED, reasons

    if inputs.authoritative_confirmation:
        src = ", ".join(sorted(set(inputs.official_sources))) or "authoritative source"
        reasons.append(f"Confirmed by official source record ({src})")
        return EvidenceState.OFFICIALLY_CONFIRMED, reasons

    if inputs.operator_verified:
        reasons.append("Verified on duty by a Response Center operator")
        return EvidenceState.OFFICIALLY_CONFIRMED, reasons

    if inputs.has_direct_official_record:
        src = ", ".join(sorted(set(inputs.official_sources))) or "official source"
        reasons.append(f"Appears in an official register ({src})")
        if inputs.community_report_count:
            reasons.append(
                f"{inputs.community_report_count} community report(s) consistent with the official record"
            )
        return EvidenceState.OFFICIALLY_REPORTED, reasons

    if inputs.community_report_count >= 2 and inputs.has_supporting_official_signal:
        reasons.append(
            f"{inputs.unique_reporter_count or inputs.community_report_count} independent community reports"
        )
        signals = ", ".join(sorted(set(inputs.supporting_signal_kinds)))
        reasons.append(f"Consistent with official {signals} data")
        return EvidenceState.CORROBORATED, reasons

    if inputs.community_report_count >= 2:
        reasons.append(
            f"{inputs.unique_reporter_count or inputs.community_report_count} independent community reports"
        )
        reasons.append("No official source yet covers this location")
        return EvidenceState.COMMUNITY_REPORTED, reasons

    if inputs.community_report_count == 1:
        reasons.append("Single community report, not yet corroborated")
        return EvidenceState.COMMUNITY_REPORTED, reasons

    reasons.append("No evidence linked to this incident yet")
    return EvidenceState.UNVERIFIED, reasons


def can_actor_promote_official(actor_kind: str | None) -> bool:
    return (actor_kind or "") in OFFICIAL_PROMOTION_ACTORS


def promotion_guard(actor_kind: str | None, target: EvidenceState) -> str | None:
    """Return an error string when an actor is not allowed to claim a state."""
    if target not in {EvidenceState.OFFICIALLY_CONFIRMED, EvidenceState.OFFICIALLY_REPORTED}:
        return None
    if can_actor_promote_official(actor_kind):
        return None
    return (
        f"'{actor_kind}' cannot mark information as {target.value}. Official status only comes "
        "from an authoritative source record or an accountable operator."
    )


def state_meta(state: EvidenceState) -> dict[str, str]:
    return {
        EvidenceState.UNVERIFIED: {
            "label": "Unverified",
            "meaning": "No evidence has been linked to this yet.",
        },
        EvidenceState.COMMUNITY_REPORTED: {
            "label": "Community reported",
            "meaning": "People on the ground have reported this; no official source confirms it.",
        },
        EvidenceState.CORROBORATED: {
            "label": "Corroborated",
            "meaning": "Multiple independent reports agree with official environmental data.",
        },
        EvidenceState.OFFICIALLY_REPORTED: {
            "label": "Officially reported",
            "meaning": "An official register contains this event.",
        },
        EvidenceState.OFFICIALLY_CONFIRMED: {
            "label": "Officially confirmed",
            "meaning": "An authoritative source or accountable operator has confirmed the details.",
        },
        EvidenceState.CONFLICTING: {
            "label": "Conflicting",
            "meaning": "Sources disagree. Needs review before acting on it.",
        },
    }[state]
