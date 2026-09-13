"""Language tools that do not need a model.

The point of this file is that the risky half of language handling - deciding what
language something is in, what hazard a sentence describes, what a status is called in
the reader's language - is deterministic and works with no credentials. A model may use
these instead of guessing, and the fallback path uses them because it has no choice.

Translation and intent *classification of ambiguous text* are the parts that genuinely
need a model; those live in `agent/workflows`, which says plainly when it could not run.
"""

from __future__ import annotations

import json

from strands import tool

from backend.app.services import communication
from shared.enums import IncidentType

# Devanagari letter block. A text with any of these is treated as Nepali-script, which is
# the only language decision this system makes without a model.
_DEVANAGARI = range(0x0900, 0x097F)


def detect_language(text: str) -> str:
    characters = [ch for ch in (text or "") if not ch.isspace()]
    if characters and sum(1 for ch in characters if ord(ch) in _DEVANAGARI) / len(characters) > 0.3:
        return "ne"
    return "en"


def build_language_tools() -> list[tool]:
    @tool
    def language_of(text: str) -> str:
        """Detect Nepali-script vs English text deterministically. Use this rather than
        assuming from a person's location."""
        language = detect_language(text)
        return json.dumps(
            {"language": language, "method": "devanagari_share", "certainty": "deterministic"},
            ensure_ascii=False,
        )

    @tool
    def hazard_of(text: str) -> str:
        """Map a free-text description onto the hazard taxonomy the system uses. Keyword
        matching over a fixed table - it reports what the words say, nothing more."""
        hazard = IncidentType.from_source_label(text)
        return json.dumps(
            {
                "incident_type": hazard.value,
                "matched": hazard is not IncidentType.OTHER,
                "method": "keyword_table",
                "note": (
                    None
                    if hazard is not IncidentType.OTHER
                    else "No hazard keyword matched; the text stayed 'other' rather than being guessed"
                ),
            },
            ensure_ascii=False,
        )

    @tool
    def status_words(status: str, language: str = "en") -> str:
        """The label and the next step for a request status, in the reader's language.
        These are fixed strings so no two replies promise different things."""
        return json.dumps(
            {
                "status": status,
                "label": communication.status_label(status, language),
                "next_step": communication.next_step(status, language),
                "language": language,
            },
            ensure_ascii=False,
        )

    @tool
    def honest_no_data(what: str, language: str = "en") -> str:
        """The approved sentence for 'we do not know'. Use this instead of filling a gap
        with something plausible."""
        return json.dumps(
            {"text": communication.no_data_message(what, language), "use_when": "no record exists"}
        )

    return [language_of, hazard_of, status_words, honest_no_data]
