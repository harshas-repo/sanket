"""Shared bootstrap for command-line scripts.

Windows terminals default to cp1252, which cannot encode Devanagari text coming
straight out of the Nepali official portals. Rather than lose those rows, every
script reconfigures stdout/stderr to UTF-8 with replacement.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def prepare(level: int = logging.INFO) -> Path:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):  # pragma: no cover - redirected streams
            pass
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    return ROOT
