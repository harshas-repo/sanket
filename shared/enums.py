"""Shared enumerations used across backend, agent and ingestion layers.

These are intentionally plain `str` enums so they persist as readable text in
SQLite/Postgres and serialise directly to JSON for the frontend.
"""

from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    RESPONSE_CENTER = "response_center"
    COMMUNITY = "community"


class ResponseCenterRank(str, Enum):
    OPERATOR = "operator"
    COORDINATOR = "coordinator"
    ANALYST = "analyst"


class IncidentType(str, Enum):
    EARTHQUAKE = "earthquake"
    LANDSLIDE = "landslide"
    FLOOD = "flood"
    FIRE = "fire"
    ROAD_BLOCKAGE = "road_blockage"
    STORM = "storm"
    HEAVY_RAINFALL = "heavy_rainfall"
    LIGHTNING = "lightning"
    INFRASTRUCTURE_DAMAGE = "infrastructure_damage"
    OTHER = "other"

    @classmethod
    def from_source_label(cls, raw: str | None) -> IncidentType:
        """Map free-text labels coming from official portals onto our taxonomy.

        Purely deterministic keyword matching - no model involvement.
        """
        if not raw:
            return cls.OTHER
        text = raw.strip().lower()
        mapping = {
            cls.EARTHQUAKE: ("earthquake", "seismic", "tremor", "भूकम्प"),
            cls.LANDSLIDE: ("landslide", "land slip", "soil slip", "mass movement", "first slide"),
            cls.FLOOD: ("flood", "inundation", "flash water", "बाढ"),
            cls.FIRE: ("fire", "burning", "conflagration", "आगो"),
            cls.ROAD_BLOCKAGE: ("road", "highway", "bridge washed", "closure", "blocked"),
            cls.STORM: ("storm", "cyclone", "gale", "tornado", "microburst"),
            cls.HEAVY_RAINFALL: ("rain", "rainfall", "precipitation", "मुसल"),
            cls.LIGHTNING: ("lightning", "thunderbolt", "बज्र"),
            cls.INFRASTRUCTURE_DAMAGE: ("infrastructure", "building collaps", "school build", "health post"),
        }
        # Road/bridge wording frequently co-occurs with landslide reports; check the
        # more specific hazard terms first so "landslide blocking road" is a landslide.
        order = [
            cls.LANDSLIDE,
            cls.EARTHQUAKE,
            cls.LIGHTNING,
            cls.HEAVY_RAINFALL,
            cls.STORM,
            cls.FIRE,
            cls.FLOOD,
            cls.INFRASTRUCTURE_DAMAGE,
            cls.ROAD_BLOCKAGE,
        ]
        for itype in order:
            if any(k in text for k in mapping[itype]):
                return itype
        return cls.OTHER


class Severity(str, Enum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    SEVERE = "severe"
    UNKNOWN = "unknown"


class Urgency(str, Enum):
    CRITICAL = "critical"
    URGENT = "urgent"
    ATTENTION = "attention"
    INFORMATION = "information"


class IncidentStatus(str, Enum):
    ACTIVE = "active"
    MONITORING = "monitoring"
    CONTAINED = "contained"
    RESOLVED = "resolved"
    ARCHIVED = "archived"


class EvidenceState(str, Enum):
    """Trust model. Promotion to OFFICIALLY_CONFIRMED is only ever performed by
    code that has seen an authoritative source record - never by the LLM."""

    UNVERIFIED = "unverified"
    COMMUNITY_REPORTED = "community_reported"
    CORROBORATED = "corroborated"
    OFFICIALLY_REPORTED = "officially_reported"
    OFFICIALLY_CONFIRMED = "officially_confirmed"
    CONFLICTING = "conflicting"

    @property
    def rank(self) -> int:
        return _EVIDENCE_RANK[self]


_EVIDENCE_RANK = {
    EvidenceState.UNVERIFIED: 0,
    EvidenceState.COMMUNITY_REPORTED: 1,
    EvidenceState.CORROBORATED: 2,
    EvidenceState.OFFICIALLY_REPORTED: 3,
    EvidenceState.OFFICIALLY_CONFIRMED: 4,
    EvidenceState.CONFLICTING: 0,
}


class FreshnessState(str, Enum):
    FRESH = "fresh"
    RECENT = "recent"
    AGING = "aging"
    STALE = "stale"
    UNKNOWN = "unknown"


class SourceStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILING = "failing"
    DISABLED = "disabled"
    NEVER_FETCHED = "never_fetched"


class ObservationKind(str, Enum):
    EARTHQUAKE = "earthquake"
    RAINFALL = "rainfall"
    RIVER_LEVEL = "river_level"
    OFFICIAL_ALERT = "official_alert"
    OFFICIAL_INCIDENT = "official_incident"
    ROAD_STATUS = "road_status"
    FELT_REPORT = "felt_report"


class RiverState(str, Enum):
    NORMAL = "normal"
    WATCH = "watch"
    WARNING = "warning"
    DANGER = "danger"
    STALE = "stale"


class ReportType(str, Enum):
    INCIDENT = "incident"
    CONDITION = "condition"
    DAMAGE = "damage"
    SOUGHT = "sought_person"
    OFFERED_HELP = "offered_help"


class VerificationStatus(str, Enum):
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"
    DUPLICATE = "duplicate"
    CONFLICTING = "conflicting"


class AssistanceType(str, Enum):
    MEDICAL = "medical"
    RESCUE = "rescue"
    FOOD = "food"
    WATER = "water"
    SHELTER = "shelter"
    TRANSPORT = "transport"
    INFORMATION = "information"
    OTHER = "other"


class AssistanceStatus(str, Enum):
    """Victim-visible lifecycle. Status may only move forward or to cancelled,
    which the service layer enforces server-side."""

    RECEIVED = "received"
    REVIEWING = "reviewing"
    RESPONSE_TEAM_NOTIFIED = "response_team_notified"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"


_STATUS_ORDER = [
    AssistanceStatus.RECEIVED,
    AssistanceStatus.REVIEWING,
    AssistanceStatus.RESPONSE_TEAM_NOTIFIED,
    AssistanceStatus.ASSIGNED,
    AssistanceStatus.IN_PROGRESS,
    AssistanceStatus.RESOLVED,
]


def status_progress(status: AssistanceStatus) -> int:
    if status == AssistanceStatus.CANCELLED:
        return -1
    return _STATUS_ORDER.index(status)


ALLOWED_STATUS_TRANSITIONS: dict[AssistanceStatus, set[AssistanceStatus]] = {
    AssistanceStatus.RECEIVED: {AssistanceStatus.REVIEWING, AssistanceStatus.CANCELLED},
    AssistanceStatus.REVIEWING: {
        AssistanceStatus.RESPONSE_TEAM_NOTIFIED,
        AssistanceStatus.ASSIGNED,
        AssistanceStatus.CANCELLED,
    },
    AssistanceStatus.RESPONSE_TEAM_NOTIFIED: {
        AssistanceStatus.ASSIGNED,
        AssistanceStatus.IN_PROGRESS,
        AssistanceStatus.CANCELLED,
    },
    AssistanceStatus.ASSIGNED: {
        AssistanceStatus.IN_PROGRESS,
        AssistanceStatus.RESPONSE_TEAM_NOTIFIED,
        AssistanceStatus.CANCELLED,
    },
    AssistanceStatus.IN_PROGRESS: {AssistanceStatus.RESOLVED, AssistanceStatus.CANCELLED},
    AssistanceStatus.RESOLVED: set(),
    AssistanceStatus.CANCELLED: set(),
}


class ResourceType(str, Enum):
    HOSPITAL = "hospital"
    HEALTH_POST = "health_post"
    AMBULANCE = "ambulance"
    SHELTER = "shelter"
    POLICE = "police"
    ARMY = "army"
    FIRE = "fire"
    WATER_SUPPLY = "water_supply"
    FOOD_DISTRIBUTION = "food_distribution"
    HELIPAD = "helipad"
    EMERGENCY_CONTACT = "emergency_contact"


class SignalLevel(str, Enum):
    NONE = "none"
    ELEVATED_CONCERN = "elevated_concern"
    HIGH_CONCERN = "high_concern"


class DataProvenance(str, Enum):
    """Every row is either live official data, community input, or clearly
    labelled demo data. They are never mixed silently."""

    OFFICIAL = "official"
    COMMUNITY = "community"
    DEMO = "demo"
    DERIVED = "derived"


class AuditAction(str, Enum):
    LOGIN = "login"
    ACKNOWLEDGE = "acknowledge"
    ASSIGN = "assign"
    STATUS_CHANGE = "status_change"
    VERIFY = "verify"
    REQUEST_VERIFICATION = "request_verification"
    LINK_REPORT = "link_report"
    MERGE_INCIDENTS = "merge_incidents"
    SPLIT_INCIDENT = "split_incident"
    VICTIM_UPDATE_SENT = "victim_update_sent"
    NOTE_ADDED = "note_added"
    ESCALATE = "escalate"
    RESOLVE = "resolve"
    RESOURCE_UPDATE = "resource_update"
    DEMO_INJECT = "demo_inject"
    AGENT_INVESTIGATION = "agent_investigation"


DRR_TO_SANKET_INCIDENT_TYPE = {
    1: IncidentType.EARTHQUAKE,
    2: IncidentType.FLOOD,
    3: IncidentType.LANDSLIDE,
    4: IncidentType.FIRE,
    14: IncidentType.HEAVY_RAINFALL,
    18: IncidentType.STORM,  # avalanche mapped to storm-family transport hazard
    25: IncidentType.OTHER,  # heat wave
    29: IncidentType.OTHER,  # drought
    39: IncidentType.FLOOD,  # flash flood
    41: IncidentType.OTHER,  # snake bite
}
