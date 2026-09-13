"""The two community-facing agent jobs, both of which work without a model.

`classify` reads one piece of community text and says what it appears to be. The
deterministic half already exists in the intake code (hazard keywords, urgency from
structured fields), so this adds a model's judgement only on top, and reports
`method="deterministic"` when there is no model to add it. It never overrides a
structured field a person filled in themselves.

`chat` answers a resident's question. With no model it composes the answer from the same
feed the community screen shows - which is the honest shape of the thing: Sanket knows
what is official, what is nearby and what it has not heard.
"""

from __future__ import annotations

import json
from typing import Any

from agent.tools.language import detect_language
from backend.app.models.core import User
from backend.app.services import communication
from backend.app.services import community as community_service
from backend.app.services import state as system_state
from shared.enums import IncidentType


def classify_text(text: str) -> dict[str, Any]:
    """Deterministic reading of one message: language, hazard, whether help is asked for."""
    lowered = (text or "").lower()
    hazard = IncidentType.from_source_label(text)
    help_cues = (
        "help", "rescue", "urgent", "stuck", "trapped", "injured", "bleeding", "can't",
        "cannot", "please", "chha", "chhaina", "bhari", "uddhar", "medic", " pani ",
    )
    asks = any(cue in lowered for cue in help_cues) or any(
        cue in text for cue in ("मद्दत", "उद्धार", "अस्पत", "घाइते", "फसे")
    )
    return {
        "method": "deterministic",
        "language": detect_language(text),
        "hazard": hazard.value,
        "hazard_matched": hazard is not IncidentType.OTHER,
        "needs_help": asks,
        "confidence": 0.4 if asks else 0.2,
        "quote": (text or "")[:160],
        "note": (
            "Keyword reading only. A structured field filled in by the reporter outranks this, "
            "and so does an operator."
        ),
    }


def classify(db: Any, text: str, *, with_model: bool = False) -> dict[str, Any]:
    """Classify community text. `with_model` is opt-in because a request that a resident
    is waiting on must not pay a model round-trip for a keyword answer."""
    answer = classify_text(text)
    if not with_model:
        return answer
    from agent import model as model_module

    built = model_module.build_model()
    if built is None:
        answer["model_note"] = "No model configured; the keyword reading is all there is."
        return answer
    try:
        from strands import Agent

        from agent.prompts import CLASSIFY

        raw = str(Agent(model=built, system_prompt=CLASSIFY)(f"Text: {text[:1200]}"))
        parsed = json.loads(raw[raw.find("{") : raw.rfind("}") + 1])
    except Exception as exc:  # noqa: BLE001 - a bad model answer must not break intake
        db.rollback()
        answer["model_note"] = f"Model answer unusable ({type(exc).__name__}); keyword reading kept."
        return answer
    # The model may only sharpen the judgement, and the quote has to be real.
    if str(parsed.get("quote") or "")[:40] not in (text or ""):
        answer["model_note"] = "Model returned a quote that is not in the text; discarded."
        return answer
    answer.update({key: value for key, value in parsed.items() if key in {"hazard", "urgency", "needs_help", "confidence", "quote"}})
    answer["method"] = "strands+keyword"
    return answer


def answer_question(
    db: Any, user: User | None, question: str, *, district: str | None = None
) -> dict[str, Any]:
    """Answer a resident. Deterministic wording unless a model is configured to rephrase it.

    The facts come from the same `local_feed` the community screen reads, so the answer and
    the screen cannot disagree.
    """
    language = detect_language(question)
    # A resident writing in Latin script may still want Nepali back; their stated
    # preference wins unless the question itself was Nepali.
    if user is not None and language == "en" and user.preferred_language == "ne":
        language = "ne"
    # An explicit district beats the saved home area: someone asking about their
    # village while in Kathmandu wants the answer about the village.
    area = district or (user.home_district if user else None)
    feed = community_service.local_feed(
        db,
        user=user,
        district=area,
        language=language,
    )
    alerts = feed.get("alerts") or []
    signals = feed.get("signals") or []
    incidents = feed.get("incidents") or []
    mode = system_state.system_mode(db).get("mode", "live")

    lines: list[str] = []
    if language == "ne":
        lines.append("तपाईंको क्षेत्रको अवस्था:")
        if mode == "demo":
            lines.append("सुचेत: यो अभ्यास मोड छ; तलका केही घटनाहरू काल्पनिक छन्।")
        if alerts:
            for alert in alerts[:3]:
                lines.append("आधिकारिक सूचना: " + communication.alert_message(alert, "ne"))
        else:
            lines.append(communication.no_data_message("official alerts for your area", "ne"))
        for incident in incidents[:3]:
            lines.append(f"{incident.get('title')} - {incident.get('district') or ''}".strip())
        if not incidents and not signals:
            lines.append(communication.no_data_message("any confirmed incident near you", "ne"))
        lines.append("तपाईंले पठाएको प्रतिवेदन सिधै Response Center पुग्छ।")
    else:
        lines.append(f"Situation for {area or 'your area'}:")
        if mode == "demo":
            lines.append("Heads up: demo mode is on, so some situations below are scripted.")
        if alerts:
            for alert in alerts[:3]:
                lines.append("Official alert: " + communication.alert_message(alert, "en"))
        else:
            lines.append(communication.no_data_message("official alerts for your area", "en"))
        for incident in incidents[:3]:
            lines.append(
                f"{incident.get('title')}"
                + (f" ({incident.get('district')})" if incident.get("district") else "")
            )
        if not incidents and not signals:
            lines.append(communication.no_data_message("any confirmed incident near you", "en"))
        lines.append("Anything you report reaches the Response Center directly.")

    result: dict[str, Any] = {
        "mode": "deterministic",
        "language": language,
        "response_text": "\n".join(line for line in lines if line),
        "based_on": {
            "alerts": len(alerts),
            "signals": len(signals),
            "incidents": len(incidents),
            "district": area,
        },
        "asked": question[:500],
        "note": (
            "Assembled from retrieved records with no language model. Nothing here is generated "
            "text."
        ),
    }

    from agent import model as model_module

    if model_module.build_model() is None:
        return result
    try:
        from strands import Agent

        from agent.prompts import COMMUNITY_CHAT

        agent = Agent(model=model_module.build_model(), system_prompt=COMMUNITY_CHAT)
        rephrased = str(
            agent(
                "Answer this resident in their language using only the records below.\n\n"
                + json.dumps(result["based_on"] | {"alerts": alerts[:5], "incidents": incidents[:5]},
                             ensure_ascii=False, default=str)[:6000]
            )
        )
        if rephrased.strip():
            result["mode"] = "strands"
            result["deterministic_text"] = result["response_text"]
            result["response_text"] = rephrased
            result["note"] = None
    except Exception as exc:  # noqa: BLE001 - never lose the answer because the model failed
        db.rollback()
        result["note"] = f"Model unavailable ({type(exc).__name__}); replying from records only."
    return result
