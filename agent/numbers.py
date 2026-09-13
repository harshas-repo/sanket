"""The number guardrail, in one place.

A language model that has read six tool results will still, occasionally, write a figure
that came from none of them. In a disaster system that is the expensive kind of mistake: a
fabricated distance sends a team somewhere, a fabricated casualty count gets repeated by a
newspaper. So every number in a model-written answer is checked against the evidence the run
actually had, and anything unexplained rejects the answer rather than being quietly kept.

It is a check, not a proof. A number that happens to appear somewhere in the evidence passes
even if the model used it in a different sense - which is why it is paired with prompts that
forbid it and with a timeline that shows which tools ran. It catches invented quantities, not
every misuse of a real one.
"""

from __future__ import annotations

import re

# Every run of digits, not every *word* of digits. Word boundaries were the original form and
# they did not survive contact with a live model: the evidence is JSON, where numbers are glued to
# letters - `"at": "2026-09-12T13:26:59Z"`, `"age": "4h 45m ago"` - and a digit sitting between two
# word characters has no boundary, so 12, 13, 59, 4 and 45 were invisible in the corpus while the
# prose that restates them ("at 13:26", "about 4 hours away") showed them plainly. The first live
# investigation was rejected for exactly that. The same asymmetry also sits in front of
# `send_victim_update`, where it can refuse a message for repeating an age the tool handed it.
# Both sides now read digits the same way, glued or not.
NUMBER = re.compile(r"\d+(?:\.\d+)?")


def _key(token: str) -> str:
    """The figure, with its zero-padding taken out.

    `09:12` in a timestamp and "9 minutes" in a sentence are the same number written two ways, and
    making the model write the padded form to be believed is not a check on the evidence. Leading
    zeros in the whole part go; the decimal half stays, because `3.20` and `3.2` are the same
    reading while `3` and `3.2` are not.
    """
    whole, dot, fraction = token.partition(".")
    whole = whole.lstrip("0") or "0"
    return f"{whole}.{fraction}" if dot else whole


def ungrounded_numbers(corpus: str, text: str) -> list[str]:
    """Numbers asserted in `text` that appear nowhere in `corpus`, sorted and deduplicated.

    Reported as the answer spelled them, so the rejected list is readable against the sentence
    that got refused. This is deliberately generous about *small* numbers: a run of digits in the
    evidence grounds the same run anywhere in the answer, so "12" is credited by a timestamp's
    day as much as by a distance. What it catches is a quantity that is in no record at all -
    which is the mistake that sends a team somewhere. Note that this replaces a blanket pardon
    for 19-26 that let those two-digit claims through whether or not the evidence held them.
    """
    allowed = {_key(token) for token in NUMBER.findall(corpus or "")}
    return sorted({value for value in NUMBER.findall(text or "") if _key(value) not in allowed})
