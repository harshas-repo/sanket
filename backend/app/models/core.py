"""Persistence models - the normalized data model.

Every externally sourced row carries: source_id, external_id (idempotent upsert),
timestamp (when the world happened), received_at (when Sanket saw it) and
provenance (official / community / demo / derived). Nothing that reaches the map
is allowed to skip those columns.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db import Base, JsonDict


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


# --------------------------------------------------------------------------- #
# Identity
# --------------------------------------------------------------------------- #
class Role(TimestampMixin, Base):
    __tablename__ = "roles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: new_id("role"))
    name: Mapped[str] = mapped_column(String(64), unique=True)  # response_center | community
    description: Mapped[str] = mapped_column(Text, default="")
    permissions: Mapped[list[str]] = mapped_column(JsonDict, default=list)


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: new_id("usr"))
    username: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128), default="")
    password_hash: Mapped[str] = mapped_column(String(255), default="")
    role: Mapped[str] = mapped_column(String(32), index=True)  # response_center | community
    rank: Mapped[str | None] = mapped_column(String(32), nullable=True)  # operator/...
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    preferred_language: Mapped[str] = mapped_column(String(8), default="en")
    home_district: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Community users get a stable alias so responders never see personal identity.
    alias: Mapped[str] = mapped_column(String(64), default="")


# --------------------------------------------------------------------------- #
# Official data layer
# --------------------------------------------------------------------------- #
class Source(TimestampMixin, Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: new_id("src"))
    code: Mapped[str] = mapped_column(String(32), unique=True)  # usgs / nemrc / dhm / drr / dor
    name: Mapped[str] = mapped_column(String(128))
    organization: Mapped[str] = mapped_column(String(256), default="")
    source_type: Mapped[str] = mapped_column(String(32))  # api | html | inline_json | pdf
    official: Mapped[bool] = mapped_column(Boolean, default=True)
    url: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="never_fetched")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    refresh_interval_seconds: Mapped[int] = mapped_column(Integer, default=300)
    # Freshness budget for *data* from this source, distinct from fetch cadence.
    stale_after_seconds: Mapped[int] = mapped_column(Integer, default=86400)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_data_timestamp: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_fetch_count: Mapped[int] = mapped_column(Integer, default=0)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    machine_readable: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str] = mapped_column(Text, default="")


class IngestionRun(Base):
    """Audit trail of every pull - backs the System Health screen and makes
    'source temporarily unavailable' an evidenced statement."""

    __tablename__ = "ingestion_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: new_id("run"))
    source_code: Mapped[str] = mapped_column(String(32), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="running")  # ok|error|skipped
    records_found: Mapped[int] = mapped_column(Integer, default=0)
    records_new: Mapped[int] = mapped_column(Integer, default=0)
    records_updated: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JsonDict, default=dict)


class Observation(TimestampMixin, Base):
    """One atomic fact from a source: an earthquake, a rainfall reading, a river
    gauge, an official incident record, a road status entry."""

    __tablename__ = "observations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: new_id("obs"))
    source_id: Mapped[str | None] = mapped_column(ForeignKey("sources.code"), index=True)
    external_id: Mapped[str] = mapped_column(String(128), index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    subtype: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Hazard this observation describes, in Sanket's own vocabulary. Derived by the
    # adapter from official labels - it is what lets an earthquake row and a
    # landslide row be recognised as the same situation.
    incident_type: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(512), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    location_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    district: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    province: Mapped[str | None] = mapped_column(String(64), nullable=True)
    local_municipality: Mapped[str | None] = mapped_column(String(128), nullable=True)
    within_nepal: Mapped[bool] = mapped_column(Boolean, default=False)
    event_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True
    )  # noqa: E501
    severity: Mapped[str | None] = mapped_column(String(16), nullable=True)
    magnitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    depth_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Generic numeric payload: rainfall mm, river level m, warning/danger levels...
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(16), nullable=True)
    threshold_state: Mapped[str | None] = mapped_column(String(16), nullable=True)
    trend: Mapped[str | None] = mapped_column(String(16), nullable=True)
    raw_data: Mapped[dict[str, Any]] = mapped_column(JsonDict, default=dict)
    normalized_data: Mapped[dict[str, Any]] = mapped_column(JsonDict, default=dict)
    provenance: Mapped[str] = mapped_column(String(16), default="official", index=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Impact counters pulled from official reports (deaths/missing/injured/...).
    deaths: Mapped[int] = mapped_column(Integer, default=0)
    missing: Mapped[int] = mapped_column(Integer, default=0)
    injured: Mapped[int] = mapped_column(Integer, default=0)
    affected_people: Mapped[int] = mapped_column(Integer, default=0)
    houses_damaged: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_obs_source_external"),
        Index("ix_obs_kind_time", "kind", "event_time"),
    )

    source: Mapped[Source | None] = relationship("Source", lazy="joined")


# --------------------------------------------------------------------------- #
# Incident layer
# --------------------------------------------------------------------------- #
class Incident(TimestampMixin, Base):
    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: new_id("inc"))
    ref_code: Mapped[str] = mapped_column(String(24), unique=True, index=True)  # INC-2026-0142
    incident_type: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(512))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    severity: Mapped[str] = mapped_column(String(16), default="unknown")
    urgency: Mapped[str] = mapped_column(String(16), default="information")
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    location_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    district: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    province: Mapped[str | None] = mapped_column(String(64), nullable=True)
    local_municipality: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # How the coordinate was obtained: named_place | local_level | district_centroid |
    # user_shared | surveyed. Drives the "approximate location" badge on the map.
    location_precision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Regional events (an M7.0 across the border) are real and relevant, but the
    # map and the queue must be able to tell "inside Nepal" from "felt here".
    within_nepal: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    magnitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    depth_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    first_detected_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True
    )  # noqa: E501
    last_updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True
    )  # noqa: E501
    event_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    evidence_state: Mapped[str] = mapped_column(String(32), default="unverified", index=True)
    official_confirmation: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    confirmed_by_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Explicit, audited operator verification. Kept separate from the derived
    # `official_confirmation` flag so recomputation cannot promote itself.
    verified_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    impact: Mapped[dict[str, Any]] = mapped_column(JsonDict, default=dict)
    prioritization_reasons: Mapped[list[str]] = mapped_column(JsonDict, default=list)
    impact_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    score_breakdown: Mapped[dict[str, Any]] = mapped_column(JsonDict, default=dict)
    cluster_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    duplicate_of: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    provenance: Mapped[str] = mapped_column(String(16), default="official", index=True)
    demo_scenario_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    # Community-sourced counters (denormalised for fast map/markers).
    community_report_count: Mapped[int] = mapped_column(Integer, default=0)
    assistance_request_count: Mapped[int] = mapped_column(Integer, default=0)
    open_assistance_count: Mapped[int] = mapped_column(Integer, default=0)
    supporting_signal_count: Mapped[int] = mapped_column(Integer, default=0)
    conflicting_signal_count: Mapped[int] = mapped_column(Integer, default=0)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    review_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    operator_notes: Mapped[list[dict[str, Any]]] = mapped_column(JsonDict, default=list)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    observations: Mapped[list[IncidentObservation]] = relationship(
        "IncidentObservation", back_populates="incident", cascade="all, delete-orphan"
    )


class IncidentObservation(Base):
    """Link table = the provenance graph. Which official observations and which
    community reports actually back this incident, and what role each played."""

    __tablename__ = "incident_observations"

    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), primary_key=True)
    observation_id: Mapped[str] = mapped_column(ForeignKey("observations.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(24), default="supporting")  # primary|supporting|conflicting
    linked_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    link_source: Mapped[str] = mapped_column(String(24), default="system")  # system|operator|agent

    incident: Mapped[Incident] = relationship("Incident", back_populates="observations")
    observation: Mapped[Observation] = relationship("Observation", lazy="joined")


class RiskSignal(TimestampMixin, Base):
    """Deterministic risk/signal state for an area. Deliberately separate from
    Incident: a river approaching warning level is a SIGNAL, a flooded village is
    an INCIDENT. The UI never merges them."""

    __tablename__ = "risk_signals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: new_id("sig"))
    code: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    hazard: Mapped[str] = mapped_column(String(32), index=True)  # flood|landslide|rainfall|seismic
    level: Mapped[str] = mapped_column(String(32), default="elevated_concern")
    label: Mapped[str] = mapped_column(String(128), default="Elevated concern")
    statement: Mapped[str] = mapped_column(Text, default="")
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    # observation_point | district_centroid | unlocated. A signal is an area condition,
    # so a district centroid is an honest placement - but it must be labelled.
    location_precision: Mapped[str] = mapped_column(String(32), default="unlocated")
    district: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    province: Mapped[str | None] = mapped_column(String(64), nullable=True)
    contributing_factors: Mapped[list[dict[str, Any]]] = mapped_column(JsonDict, default=list)
    freshness_state: Mapped[str] = mapped_column(String(16), default="unknown")
    observed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    provenance: Mapped[str] = mapped_column(String(16), default="derived", index=True)
    demo_scenario_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    __table_args__ = (Index("ix_signal_hazard_district", "hazard", "district"),)


# --------------------------------------------------------------------------- #
# Community / victim layer
# --------------------------------------------------------------------------- #
class CommunityReport(TimestampMixin, Base):
    __tablename__ = "community_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: new_id("rep"))
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    incident_id: Mapped[str | None] = mapped_column(
        ForeignKey("incidents.id"), nullable=True, index=True
    )
    report_type: Mapped[str] = mapped_column(String(24), default="incident")
    message: Mapped[str] = mapped_column(Text)
    structured: Mapped[dict[str, Any]] = mapped_column(JsonDict, default=dict)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    location_text: Mapped[str | None] = mapped_column(String(320), nullable=True)
    # The widths in this file are a contract, not decoration: SQLite stores an over-long
    # string without comment and Postgres refuses the INSERT. `location_confidence` carries
    # the longest name `resolve_location` can produce (`inferred_home_district`).
    location_confidence: Mapped[str] = mapped_column(String(32), default="unknown")
    district: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    province: Mapped[str | None] = mapped_column(String(64), nullable=True)
    incident_type: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    severity: Mapped[str | None] = mapped_column(String(16), nullable=True)
    urgency: Mapped[str] = mapped_column(String(16), default="information")
    people_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    medical_need: Mapped[bool] = mapped_column(Boolean, default=False)
    attachments: Mapped[list[dict[str, Any]]] = mapped_column(JsonDict, default=list)
    verification_status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    duplicate_status: Mapped[str] = mapped_column(String(16), default="unique", index=True)
    duplicate_of_report_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    corroborating_report_ids: Mapped[list[str]] = mapped_column(JsonDict, default=list)
    distance_to_incident_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    language: Mapped[str] = mapped_column(String(8), default="en")
    client_timestamp: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    submitted_offline: Mapped[bool] = mapped_column(Boolean, default=False)
    provenance: Mapped[str] = mapped_column(String(16), default="community", index=True)
    demo_scenario_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True
    )  # noqa: E501
    agent_reviewed: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped[User | None] = relationship("User", lazy="joined")


class AssistanceRequest(TimestampMixin, Base):
    __tablename__ = "assistance_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: new_id("asr"))
    ref_code: Mapped[str] = mapped_column(String(24), unique=True, index=True)  # REQ-2026-0007
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    incident_id: Mapped[str | None] = mapped_column(
        ForeignKey("incidents.id"), nullable=True, index=True
    )
    report_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    request_type: Mapped[str] = mapped_column(String(32), default="other", index=True)
    assistance_types: Mapped[list[str]] = mapped_column(JsonDict, default=list)
    description: Mapped[str] = mapped_column(Text, default="")
    raw_message: Mapped[str] = mapped_column(Text, default="")
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    location_text: Mapped[str | None] = mapped_column(String(320), nullable=True)
    location_confidence: Mapped[str] = mapped_column(String(32), default="unknown")
    district: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    province: Mapped[str | None] = mapped_column(String(64), nullable=True)
    urgency: Mapped[str] = mapped_column(String(16), default="attention", index=True)
    people_count: Mapped[int] = mapped_column(Integer, default=1)
    medical_need: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    immediate_danger: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="received", index=True)
    assigned_to: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    # `assign()` deliberately keeps 200 characters of a team name an operator types, so the
    # column has to be able to hold 200.
    assigned_team: Mapped[str | None] = mapped_column(String(200), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    acknowledged_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sla_due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    attachments: Mapped[list[dict[str, Any]]] = mapped_column(JsonDict, default=list)
    structured: Mapped[dict[str, Any]] = mapped_column(JsonDict, default=dict)
    urgency_reasons: Mapped[list[str]] = mapped_column(JsonDict, default=list)
    evidence_state: Mapped[str] = mapped_column(String(32), default="community_reported")
    matched_resource_ids: Mapped[list[str]] = mapped_column(JsonDict, default=list)
    response_plan: Mapped[dict[str, Any]] = mapped_column(JsonDict, default=dict)
    language: Mapped[str] = mapped_column(String(8), default="en")
    provenance: Mapped[str] = mapped_column(String(16), default="community", index=True)
    demo_scenario_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True
    )  # noqa: E501
    last_victim_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped[User | None] = relationship("User", lazy="joined")


class AssistanceUpdate(TimestampMixin, Base):
    """The case timeline. Both directions of the two-way loop land here so the
    victim view and the operator view read the same truth."""

    __tablename__ = "assistance_updates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: new_id("upd"))
    request_id: Mapped[str] = mapped_column(ForeignKey("assistance_requests.id"), index=True)
    actor_type: Mapped[str] = mapped_column(String(16))  # victim|operator|system|agent
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    actor_label: Mapped[str] = mapped_column(String(64), default="Sanket")
    kind: Mapped[str] = mapped_column(String(32))  # status|message|assignment|note|evidence
    message: Mapped[str] = mapped_column(Text, default="")
    visible_to_victim: Mapped[bool] = mapped_column(Boolean, default=True)
    from_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True
    )  # noqa: E501
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JsonDict, default=dict)


class Resource(TimestampMixin, Base):
    __tablename__ = "resources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: new_id("res"))
    resource_type: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(256))
    description: Mapped[str] = mapped_column(Text, default="")
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    address: Mapped[str | None] = mapped_column(String(256), nullable=True)
    district: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    province: Mapped[str | None] = mapped_column(String(64), nullable=True)
    contact: Mapped[str | None] = mapped_column(String(64), nullable=True)
    contact_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    availability: Mapped[str] = mapped_column(String(24), default="unknown", index=True)
    availability_verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source: Mapped[str] = mapped_column(String(64), default="unregistered")
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    provenance: Mapped[str] = mapped_column(String(16), default="official", index=True)
    attributes: Mapped[dict[str, Any]] = mapped_column(JsonDict, default=dict)
    last_updated: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True
    )  # noqa: E501
    demo_scenario_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class Notification(TimestampMixin, Base):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: new_id("ntf"))
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    audience: Mapped[str] = mapped_column(String(24), default="community", index=True)
    title: Mapped[str] = mapped_column(String(256), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(32), default="info")  # status|alert|proactive|system
    severity: Mapped[str] = mapped_column(String(16), default="information")
    link: Mapped[str | None] = mapped_column(String(256), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    incident_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    district: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    provenance: Mapped[str] = mapped_column(String(16), default="derived", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True
    )  # noqa: E501


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: new_id("aud"))
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    actor_label: Mapped[str] = mapped_column(String(64), default="system")
    actor_kind: Mapped[str] = mapped_column(String(16), default="system")  # operator|victim|system|agent
    action: Mapped[str] = mapped_column(String(48), index=True)
    entity_type: Mapped[str] = mapped_column(String(32), index=True)
    entity_id: Mapped[str] = mapped_column(String(36), index=True)
    previous_value: Mapped[dict[str, Any] | None] = mapped_column(JsonDict, nullable=True)
    new_value: Mapped[dict[str, Any] | None] = mapped_column(JsonDict, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True
    )  # noqa: E501


class AgentInvestigation(TimestampMixin, Base):
    """Persistent record of each Strands run: which tools it actually called,
    what they returned, and the conclusion. Makes agent behaviour auditable."""

    __tablename__ = "agent_investigations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: new_id("inv"))
    trigger: Mapped[str] = mapped_column(String(32), default="report")  # report|incident|chat|queue
    subject_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    subject_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    prompt: Mapped[str] = mapped_column(Text, default="")
    mode: Mapped[str] = mapped_column(String(24), default="strands")  # strands|deterministic
    # Includes the guardrail outcomes (`rejected_unverified_numbers`), which are status names
    # rather than statuses, and are longer than anything the enum holds.
    status: Mapped[str] = mapped_column(String(48), default="completed")
    tool_calls: Mapped[list[dict[str, Any]]] = mapped_column(JsonDict, default=list)
    findings: Mapped[dict[str, Any]] = mapped_column(JsonDict, default=dict)
    response_text: Mapped[str] = mapped_column(Text, default="")
    model_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provenance: Mapped[str] = mapped_column(String(16), default="derived")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True
    )  # noqa: E501


class DemoEvent(Base):
    """Scripted scenario steps, so arming a scenario replays deterministically."""

    __tablename__ = "demo_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: new_id("dme"))
    scenario_id: Mapped[str] = mapped_column(String(36), index=True)
    step_index: Mapped[int] = mapped_column(Integer, default=0)
    at_offset_seconds: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String(32))  # signal|report|request|official_update|status
    payload: Mapped[dict[str, Any]] = mapped_column(JsonDict, default=dict)
    fired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    label: Mapped[str] = mapped_column(String(256), default="")


class SystemState(Base):
    """Single-row table holding the live/demo mode switch and simulated clock."""

    __tablename__ = "system_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JsonDict, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


Index("ix_incidents_active_type", Incident.incident_type, Incident.archived)
Index("ix_requests_status_urgency", AssistanceRequest.status, AssistanceRequest.urgency)
Index("ix_reports_incident_time", CommunityReport.incident_id, CommunityReport.created_at)
