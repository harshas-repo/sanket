"""The tool set the agent may use, bound to one request.

`build_tools` and `build_respond_tools` are the only things outside this package should
call. Both return plain callables decorated with `strands.tool`, each closing over the
caller's `Session` and permission set - so a tool cannot be reused across a request to leak
another viewer's data.

The two sets are apart on purpose. `read.py` is the investigation surface: twenty-five ways
to look and no way to touch. `respond.py` is what one victim report needs: a smaller set of
lookups with the same names the product uses, plus the four guarded writes a report may end
in. Merging them would hand every investigation a write tool it has no business having.
"""

from __future__ import annotations

from typing import Any

from agent.tools.language import build_language_tools, detect_language
from agent.tools.read import build_read_tools
from agent.tools.respond import (
    ResponderContext,
    build_respond_tools,
    file_request,
    preliminary_reading,
    record_action,
)

__all__ = [
    "build_tools",
    "build_read_tools",
    "build_language_tools",
    "build_respond_tools",
    "ResponderContext",
    "file_request",
    "preliminary_reading",
    "record_action",
    "detect_language",
]


def build_tools(
    db: Any, permissions: set[str] | None = None, *, with_language: bool = True
) -> list[Any]:
    tools = build_read_tools(db, permissions)
    if with_language:
        tools = tools + build_language_tools()
    return tools
