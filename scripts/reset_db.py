"""Recreate all tables from the SQLAlchemy models.

This is a development reset, not a migration: it drops and rebuilds the schema,
so every row (including ingested observations) is lost and will be re-pulled from
the official sources on the next ingestion run. Alembic is not wired up yet -
see docs/ISSUES.md.

Usage:  python scripts/reset_db.py
"""

from __future__ import annotations

import sys

from _bootstrap import prepare

prepare()

from backend.app import models  # noqa: F401,E402  (register mappers)
from backend.app.db import Base, engine, init_db  # noqa: E402


def main() -> int:
    print(f"dropping and recreating schema on {engine.url}")
    Base.metadata.drop_all(bind=engine)
    init_db()
    print(f"{len(Base.metadata.tables)} tables rebuilt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
