"""Agent workflows: the jobs the language layer is asked to do.

Each one has a deterministic spine and an optional model on top, so an outage or a
missing key changes the wording available, never the facts on screen.
"""

from __future__ import annotations

from agent.workflows.community import answer_question, classify, classify_text
from agent.workflows.investigate import (
    check_numbers,
    gather_findings,
    investigate,
    render_findings,
)
from agent.workflows.respond import respond

__all__ = [
    "investigate",
    "gather_findings",
    "render_findings",
    "check_numbers",
    "classify",
    "classify_text",
    "answer_question",
    "respond",
]
