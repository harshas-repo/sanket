"""A record of what the agent *did*, shaped so it is safe to show a human.

The line the spec draws is the one this file enforces: a model's reasoning is not a
product output. Nothing in here captures prompts, completions or tool payloads - only the
name of each action, the status it ended with, when it happened, and one short line about
what came back. That line is written by the tool that produced the result, because a tool
knows which of its numbers matter and a generic summariser does not.

Why the restriction is in code and not in a prompt: a timeline that leaked the model's
working would not just be ugly, it would invite an operator to argue with a chain of
guessed intermediate steps instead of with the evidence. So this class has no way to
record free-flowing model text - the widest string it accepts is a digest the caller had
to build out of its own data fields.
"""

from __future__ import annotations

from typing import Any

from shared.timeutils import iso, utcnow

# A run that called forty tools is a run nobody will read past the third line, and the
# timeline is stored in a JSON column on every investigation.
MAX_STEPS = 40
_MAX_DETAIL = 220


class ActivityTrace:
    """Append-only activity log for one agent run.

    `phase` is for the fixed spine steps the workflow performs itself (receiving a report,
    handing over to the model, finishing). `tool` is for a named tool the model chose to
    call. Both land in one list, in the order they happened, because the order *is* the
    explanation.
    """

    def __init__(self, subject: str = "") -> None:
        self.subject = subject
        self.steps: list[dict[str, Any]] = []
        # Counted by a real hook on the model, not inferred - "1-2 LLM calls per victim
        # interaction" is a target someone has to be able to check.
        self.model_calls = 0

    # ------------------------------------------------------------------ recording
    def phase(self, action: str, *, status: str = "ok", detail: str | None = None) -> None:
        self._add(action=action, kind="phase", status=status, detail=detail)

    def tool(
        self,
        action: str,
        *,
        status: str = "ok",
        detail: str | None = None,
        asked: dict[str, Any] | None = None,
    ) -> None:
        self._add(
            action=action,
            kind="tool",
            status=status,
            detail=detail,
            # Kept for the stored run, never rendered: which filters the agent chose is
            # part of auditing it, and part of nothing an operator needs on screen.
            asked=_flatten(asked),
        )

    def _add(self, **step: Any) -> None:
        if len(self.steps) >= MAX_STEPS:
            return
        detail = step.pop("detail", None)
        entry: dict[str, Any] = {
            "at": iso(utcnow()),
            "action": str(step["action"]).upper(),
            "kind": step["kind"],
            "status": step["status"],
        }
        if detail:
            entry["detail"] = str(detail)[:_MAX_DETAIL]
        if step.get("asked"):
            entry["asked"] = step["asked"]
        self.steps.append(entry)

    # ------------------------------------------------------------------ model accounting
    def attach(self, agent: Any) -> None:
        """Start counting this agent's model turns.

        Registered with the event named, rather than through `Agent(hooks=[...])`: that form
        infers which event to subscribe to by reading the callback's type hint, and refuses to
        construct the agent when the hint is not a `BaseHookEvent` subclass. Every hint in this
        file has to be loose, because strands is imported inside this method - importing it at
        module scope would make every API route depend on an optional SDK being installed. So
        the agent is built first and the counter is attached afterwards.

        Raised on a real run: with the inferred form, a configured model produced
        `ValueError: type hint must be a subclass of BaseHookEvent` before a single request left
        the process, which looks identical to a bad API key from the outside.
        """
        from strands.hooks import BeforeModelCallEvent

        agent.hooks.add_callback(BeforeModelCallEvent, self._count_model_call)

    def _count_model_call(self, event: Any) -> None:
        # Called for one event type only, so there is nothing to filter; `event` is unread on
        # purpose. The count is the fact being reported, not anything the event carries.
        self.model_calls += 1

    # ------------------------------------------------------------------ output
    def to_list(self) -> list[dict[str, Any]]:
        return [dict(step) for step in self.steps]

    def last_detail(self, action: str) -> str | None:
        wanted = action.upper()
        for step in reversed(self.steps):
            if step["action"] == wanted:
                return step.get("detail")
        return None


def _flatten(arguments: dict[str, Any] | None) -> dict[str, Any]:
    """Scalars only, trimmed. A long tool argument is the model's phrasing, and the trace
    does not store the model's phrasing - which is why an over-long string is dropped
    instead of truncated. Booleans and numbers stay: they are what the agent asked the
    deterministic rules to score."""
    if not arguments:
        return {}
    out: dict[str, Any] = {}
    for key, value in arguments.items():
        if not isinstance(value, (bool, int, float, str, list)):
            continue
        if isinstance(value, str):
            if len(value) > 80:
                continue
            out[str(key)] = value
        elif isinstance(value, list):
            out[str(key)] = [str(item)[:40] for item in value[:6]]
        else:
            out[str(key)] = value
    return out
