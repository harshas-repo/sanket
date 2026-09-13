"""Request bodies. Deliberately thin: validation of *shape* only.

Anything that is a judgement - urgency, evidence state, location resolution, SLA -
is computed by the service layer, never accepted from the client. A caller cannot
POST `urgency: critical` and jump the queue, and cannot POST `official: true`.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
class RegisterIn(_Strict):
    username: str = Field(min_length=3, max_length=60)
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(default="", max_length=120)
    preferred_language: Literal["en", "ne"] = "en"
    home_district: str | None = Field(default=None, max_length=64)
    phone: str | None = Field(default=None, max_length=32)
    # Only ever honoured when SANKET_ALLOW_DEMO_ACCOUNTS is on; community accounts
    # cannot self-issue Response Center access.
    role: Literal["community", "response_center"] = "community"
    rank: Literal["operator", "coordinator", "analyst"] | None = None


class LoginIn(_Strict):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=128)


class ProfilePatch(_Strict):
    display_name: str | None = Field(default=None, max_length=120)
    preferred_language: Literal["en", "ne"] | None = None
    home_district: str | None = Field(default=None, max_length=64)
    phone: str | None = Field(default=None, max_length=32)


# --------------------------------------------------------------------------- #
# Community
# --------------------------------------------------------------------------- #
class AttachmentIn(_Strict):
    kind: str = "photo"
    url: str = ""
    name: str = ""
    label: str = ""

    @field_validator("url")
    @classmethod
    def _no_data_dump(cls, value: str) -> str:
        # V1 stores a URL or a short label only; uploading bytes is not wired yet.
        return value[:500]


class ReportIn(_Strict):
    message: str = Field(min_length=3, max_length=4000)
    report_type: str = Field(default="incident", max_length=32)
    incident_type: str | None = Field(default=None, max_length=32)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    location_text: str | None = Field(default=None, max_length=300)
    people_count: int | None = Field(default=None, ge=1, le=100000)
    medical_need: bool = False
    injuries: int = Field(default=0, ge=0, le=100000)
    language: Literal["en", "ne"] = "en"
    attachments: list[AttachmentIn] = Field(default_factory=list, max_length=6)
    client_timestamp: str | None = Field(default=None, max_length=40)
    submitted_offline: bool = False
    needs_help: bool = False
    help_types: list[str] = Field(default_factory=list, max_length=6)
    incident_id: str | None = Field(default=None, max_length=36)
    immediate_danger: bool = False
    voice_transcript: bool = False

    @field_validator("language", mode="before")
    @classmethod
    def _default_language(cls, value: Any) -> Any:
        """A phone keyboard may send 'ne-NP' or nothing at all."""
        if not value:
            return "en"
        return str(value).lower().split("-")[0][:2]


class AssistanceRequestIn(_Strict):
    description: str = Field(min_length=3, max_length=4000)
    request_type: str = Field(default="other", max_length=32)
    assistance_types: list[str] = Field(default_factory=list, max_length=6)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    location_text: str | None = Field(default=None, max_length=300)
    people_count: int = Field(default=1, ge=1, le=100000)
    medical_need: bool = False
    immediate_danger: bool = False
    trapped: bool = False
    minors_involved: bool = False
    elderly_or_disabled_involved: bool = False
    language: Literal["en", "ne"] = "en"
    attachments: list[AttachmentIn] = Field(default_factory=list, max_length=6)
    incident_id: str | None = Field(default=None, max_length=36)
    report_id: str | None = Field(default=None, max_length=36)
    submitted_offline: bool = False
    client_timestamp: str | None = Field(default=None, max_length=40)


class CancelIn(_Strict):
    reason: str = Field(default="", max_length=500)


class OfflineItemIn(_Strict):
    """One queued item from a phone that was out of coverage."""

    kind: Literal["report", "request"]
    client_ref: str = Field(default="", max_length=60)
    payload: dict[str, Any] = Field(default_factory=dict)


class OfflineFlushIn(_Strict):
    items: list[OfflineItemIn] = Field(default_factory=list, max_length=50)


# --------------------------------------------------------------------------- #
# Response Center operations
# --------------------------------------------------------------------------- #
class AcknowledgeIn(_Strict):
    note: str = Field(default="", max_length=500)


class AssignIn(_Strict):
    team: str = Field(min_length=2, max_length=200)
    assigned_to: str | None = Field(default=None, max_length=120)
    note: str = Field(default="", max_length=500)
    share_note_with_requester: bool = False


class StatusIn(_Strict):
    status: str = Field(min_length=3, max_length=40)
    note: str = Field(default="", max_length=500)


class EscalateIn(_Strict):
    reason: str = Field(min_length=3, max_length=500)


class VictimMessageIn(_Strict):
    message: str = Field(min_length=1, max_length=1000)


class NoteIn(_Strict):
    note: str = Field(min_length=1, max_length=2000)
    visible_to_requester: bool = False


class VerifyIn(_Strict):
    reason: str = Field(min_length=5, max_length=500)
    state: str = Field(default="officially_confirmed", max_length=40)


class LinkIn(_Strict):
    report_id: str | None = Field(default=None, max_length=36)
    observation_id: str | None = Field(default=None, max_length=36)


class MergeIn(_Strict):
    duplicate_id: str = Field(min_length=1, max_length=36)
    reason: str = Field(default="", max_length=500)


class SplitIn(_Strict):
    """Reports to move out of the current grouping into an incident of their own."""

    report_ids: list[str] = Field(min_length=1, max_length=200)
    reason: str = Field(default="", max_length=500)


class IncidentStatusIn(_Strict):
    status: str = Field(min_length=3, max_length=40)
    reason: str = Field(default="", max_length=500)


class ReviewIn(_Strict):
    needs_review: bool
    reason: str = Field(default="", max_length=300)


# --------------------------------------------------------------------------- #
# Resources
# --------------------------------------------------------------------------- #
class ResourceCreateIn(_Strict):
    # Both fields are Literal, not free text: a facility typed "avliable" would sit in the
    # catalogue unnoticed and never match the availability filter an operator relies on.
    resource_type: Literal[
        "hospital",
        "health_post",
        "ambulance",
        "shelter",
        "police",
        "army",
        "fire",
        "water_supply",
        "food_distribution",
        "helipad",
        "emergency_contact",
    ]
    name: str = Field(min_length=2, max_length=256)
    description: str = Field(default="", max_length=1000)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    address: str | None = Field(default=None, max_length=256)
    district: str | None = Field(default=None, max_length=64)
    contact: str | None = Field(default=None, max_length=64)
    capacity: int | None = Field(default=None, ge=0, le=1_000_000)
    availability: Literal["unknown", "available", "limited", "closed"] = "unknown"


class ResourceAvailabilityIn(_Strict):
    availability: Literal["unknown", "available", "limited", "closed"]
    capacity: int | None = Field(default=None, ge=0, le=1_000_000)
    contact_verified: bool | None = None
    reason: str = Field(default="", max_length=500)


class ResourceSeedIn(_Strict):
    """Which kinds to pull. An empty list means every kind the catalogue knows."""

    types: list[str] = Field(default_factory=list, max_length=10)


class ReasonIn(_Strict):
    """Body for a write whose only input is why. Required by the audit log, optional for
    the operator - but an unexplained retirement is what a later review cannot read."""

    reason: str = Field(default="", max_length=500)


# --------------------------------------------------------------------------- #
# Agent / demo
# --------------------------------------------------------------------------- #
class ChatIn(_Strict):
    message: str = Field(min_length=1, max_length=2000)
    language: Literal["en", "ne"] = "en"
    district: str | None = Field(default=None, max_length=64)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    incident_id: str | None = Field(default=None, max_length=36)
    history: list[dict[str, Any]] = Field(default_factory=list, max_length=20)


class AgentInvestigateIn(_Strict):
    """One incident, named either way an operator has of naming it."""

    incident_id: str | None = Field(default=None, max_length=36)
    ref_code: str | None = Field(default=None, max_length=24)


class AgentRespondIn(_Strict):
    """One victim report, in the reporter's words.

    `report_id` is the only way a run gets attached to a person: the server reads the
    reporter off that row. There is deliberately no `user_id` or `victim` field - an endpoint
    that accepted one would let anyone file a request as anyone.
    """

    text: str = Field(min_length=5, max_length=4000)
    report_id: str | None = Field(default=None, max_length=36)
    incident_id: str | None = Field(default=None, max_length=36)


class AgentClassifyIn(_Strict):
    text: str = Field(min_length=1, max_length=4000)
    # Off by default: intake is deterministic and instant, and a resident waiting on a
    # report should not pay a model round-trip for a label the keyword table already gives.
    use_model: bool = False


class DemoArmIn(_Strict):
    scenario_id: str = Field(min_length=1, max_length=60)
    speed: float = Field(default=1.0, gt=0, le=600)


class DemoAdvanceIn(_Strict):
    """Move the scenario clock. `seconds` is a jump from the moment the scenario was
    armed, not from where it stands now, so two presenters pressing the same button twice
    see the same steps - a relative jump would make the rehearsal unreproducible."""

    seconds: float | None = Field(default=None, ge=0, le=86_400)
