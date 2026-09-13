"""Victim-facing and operator-facing message text.

Kept deterministic on purpose. The two-way loop has to work with no model
available, and a person in danger should receive a clear, honest status - not a
generated paragraph. Every message states what is actually known and, when
something is not known, says so.

Nepali strings are plain Devanagari text; they are stored in code (not in a
translation service) so the demo works offline.
"""

from __future__ import annotations

from typing import Any

from shared.enums import AssistanceStatus, EvidenceState

LABELS_EN: dict[str, str] = {
    AssistanceStatus.RECEIVED.value: "Received",
    AssistanceStatus.REVIEWING.value: "Being reviewed",
    AssistanceStatus.RESPONSE_TEAM_NOTIFIED.value: "Response team notified",
    AssistanceStatus.ASSIGNED.value: "Assigned to a team",
    AssistanceStatus.IN_PROGRESS.value: "In progress",
    AssistanceStatus.RESOLVED.value: "Resolved",
    AssistanceStatus.CANCELLED.value: "Cancelled",
}

LABELS_NE: dict[str, str] = {
    AssistanceStatus.RECEIVED.value: "पाइयो",
    AssistanceStatus.REVIEWING.value: "हेरिरहेको छ",
    AssistanceStatus.RESPONSE_TEAM_NOTIFIED.value: "टोलीलाई खबर गरियो",
    AssistanceStatus.ASSIGNED.value: "टोली तोकियो",
    AssistanceStatus.IN_PROGRESS.value: "सुरु भइरहेको छ",
    AssistanceStatus.RESOLVED.value: "समाधान भयो",
    AssistanceStatus.CANCELLED.value: "रद्द गरियो",
}

EVIDENCE_LABELS_EN: dict[str, str] = {
    EvidenceState.UNVERIFIED.value: "Unverified",
    EvidenceState.COMMUNITY_REPORTED.value: "Reported by people in the area",
    EvidenceState.CORROBORATED.value: "Corroborated by multiple reports and official data",
    EvidenceState.OFFICIALLY_REPORTED.value: "Appears in an official record",
    EvidenceState.OFFICIALLY_CONFIRMED.value: "Officially confirmed",
    EvidenceState.CONFLICTING.value: "Sources disagree - being resolved",
}

# What the next step means for the person who asked. Never a promise about time
# or outcome we cannot keep.
NEXT_STEP_EN: dict[str, str] = {
    AssistanceStatus.RECEIVED.value: "A response centre operator will read this shortly.",
    AssistanceStatus.REVIEWING.value: "Someone is reading your request now.",
    AssistanceStatus.RESPONSE_TEAM_NOTIFIED.value: "Nearby response teams have been told where you are.",
    AssistanceStatus.ASSIGNED.value: "A team is responsible for your request.",
    AssistanceStatus.IN_PROGRESS.value: "Help is on the way. Keep this phone reachable.",
    AssistanceStatus.RESOLVED.value: "This request is closed. If you still need help, send a new one.",
    AssistanceStatus.CANCELLED.value: "This request was cancelled. If that is wrong, send it again.",
}

NEXT_STEP_NE: dict[str, str] = {
    AssistanceStatus.RECEIVED.value: "केही समयमा नै जवाफ दिइनेछ।",
    AssistanceStatus.REVIEWING.value: "तपाईंको अनुरोध हेरिरहेको छ।",
    AssistanceStatus.RESPONSE_TEAM_NOTIFIED.value: "नजिकको टोलीलाई खबर गरिएको छ।",
    AssistanceStatus.ASSIGNED.value: "तपाईंको अनुरोधका लागि टोली तोकिनेछ।",
    AssistanceStatus.IN_PROGRESS.value: "सहयोग पठाइँदैछ। फोन पहुँचमा राख्नुहोस्।",
    AssistanceStatus.RESOLVED.value: "यो अनुरोध बन्द गरियो। अझै सहयोग चाहिएमा फेरि पठाउनुहोस्।",
    AssistanceStatus.CANCELLED.value: "यो अनुरोध रद्द गरियो। गलत भए फेरि पठाउनुहोस्।",
}


def status_label(status: str, language: str = "en") -> str:
    table = LABELS_NE if language == "ne" else LABELS_EN
    return table.get(status, status.replace("_", " ").title())


def next_step(status: str, language: str = "en") -> str:
    table = NEXT_STEP_NE if language == "ne" else NEXT_STEP_EN
    return table.get(status, "")


def receipt_message(
    *,
    ref_code: str,
    status: str,
    urgency: str,
    language: str = "en",
    location_known: bool = True,
) -> str:
    """The message a person sees the moment their request is filed."""
    if language == "ne":
        lines = [
            f"तपाईंको अनुरोध दर्ता भयो। सन्दर्भ: {ref_code}",
            f"अवस्था: {status_label(status, 'ne')}",
        ]
        if not location_known:
            lines.append("ठेगाना थाहा छैन - नजिकको स्थान वा गाउँ/नगरको नाम लेख्नुहोस्।")
        lines.append(next_step(status, "ne"))
        return "\n".join(lines)
    lines = [
        f"Request received. Reference {ref_code}.",
        f"Status: {status_label(status, 'en')}.",
    ]
    if not location_known:
        lines.append(
            "We do not have your location yet - reply with the nearest named place so a "
            "team can reach you."
        )
    if urgency == "critical":
        lines.append("This is marked critical, so it is at the top of the response queue.")
    lines.append(next_step(status, "en"))
    return " ".join(lines)


def status_change_message(
    *,
    ref_code: str,
    from_status: str,
    to_status: str,
    language: str = "en",
    operator_note: str = "",
) -> str:
    if language == "ne":
        base = f"अनुरोध {ref_code}: अवस्था {status_label(from_status, 'ne')} बाट {status_label(to_status, 'ne')} भयो।"
    else:
        base = (
            f"Update on {ref_code}: status moved from {status_label(from_status, 'en')} to "
            f"{status_label(to_status, 'en')}."
        )
    step = next_step(to_status, language)
    return " ".join(part for part in (base, step, operator_note.strip()) if part)


def alert_message(alert: dict[str, Any], language: str = "en") -> str:
    """Official alert text is quoted, never rewritten into something stronger."""
    title = str(alert.get("title") or "").strip()
    source = str(alert.get("source_name") or alert.get("source") or "official source")
    district = alert.get("district")
    where = f" for {district}" if district else ""
    if language == "ne":
        return f"{source} को सूचना{where}: {title}"
    return f"{source} alert{where}: {title}"


def evidence_sentence(state: str, language: str = "en") -> str:
    label = EVIDENCE_LABELS_EN.get(state, state)
    if language == "ne":
        return f"स्रोत: {label}।"
    return f"Evidence: {label}."


# What a caller means by the empty thing, in the reader's own language. Callers pass the
# English phrase because that is the key; without this table a Nepali reader gets an English
# noun dropped into the middle of a Nepali sentence.
NO_DATA_SUBJECT_NE: dict[str, str] = {
    "official alerts for your area": "तपाईंको क्षेत्रको आधिकारिक सूचना",
    "any confirmed incident near you": "तपाईंको नजिक पुष्टि भएको कुनै घटना",
    "the current situation there": "त्यहाँको हालको अवस्था",
    "any open help request from your area": "तपाईंको क्षेत्रबाट कुनै खुल्ला सहयोग अनुरोध",
}


def no_data_message(what: str, language: str = "en") -> str:
    """Honest emptiness. Used instead of inventing an answer."""
    key = (what or "").strip().lower()
    subject = NO_DATA_SUBJECT_NE.get(key, what) if language == "ne" else what
    if language == "ne":
        return f"हामीसँग अहिले {subject} सम्बन्धी कुनै पुष्ट तथ्य छैन।"
    return f"We do not have any confirmed information about {subject} right now."
