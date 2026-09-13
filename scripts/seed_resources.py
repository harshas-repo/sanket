"""Fill the facility catalogue from OpenStreetMap (Overpass).

    python scripts/seed_resources.py                  # every kind, whole country
    python scripts/seed_resources.py hospital police  # only these kinds
    python scripts/seed_resources.py --show           # what is in the catalogue now

This is the same code path as POST /api/rc/resources/seed, run from a terminal so a
seed can be watched line by line. It talks to the real Overpass API and reports the
real outcome - if a kind is unreachable it says which one and exits non-zero, because
a facility map that quietly lost all the fire stations is worse than one that admits
it did not finish.
"""

from __future__ import annotations

import sys

from _bootstrap import prepare

prepare()

from backend.app.db import SessionLocal, init_db  # noqa: E402
from backend.app.services import resources as resource_service  # noqa: E402


def show() -> int:
    db = SessionLocal()
    try:
        totals = resource_service.counts(db)
        print(f"facilities in catalogue: {totals['total']}")
        if totals["empty"]:
            print("  (empty - run this script without --show to seed from OpenStreetMap)")
            return 0
        for resource_type, total in sorted(totals["by_type"].items(), key=lambda kv: -kv[1]):
            print(f"  {resource_type:<14} {total}")
        print("availability:")
        for availability, total in sorted(totals["by_availability"].items()):
            print(f"  {availability:<12} {total}")
        print(f"last change: {totals['last_change']} ({totals['last_change_age']})")
        return 0
    finally:
        db.close()


def seed(types: list[str]) -> int:
    known = {row[0] for row in resource_service.TYPE_QUERIES}
    unknown = [t for t in types if t not in known]
    if unknown:
        print(f"unknown facility kind(s): {', '.join(unknown)}")
        print(f"available: {', '.join(sorted(known))}")
        return 2

    init_db()
    db = SessionLocal()
    try:
        print(f"querying Overpass for: {', '.join(types) if types else 'all kinds'}")
        print("a nationwide pull takes a few minutes; one request per kind, in order\n")
        outcome = resource_service.seed_from_overpass(db, types=types or None)
        for row in outcome["failures"]:
            print(f"  FAILED {row['resource_type']}: {row['error']}")
        for resource_type, stat in outcome["per_type"].items():
            print(
                f"  {resource_type:<14} +{stat['created']:<5} "
                f"~{stat['updated']:<5} skipped={stat['skipped']}"
            )
        print(
            f"\ncreated {outcome['created']}  updated {outcome['updated']}  "
            f"skipped {outcome['skipped']} (of {outcome['attempted']} kinds attempted)"
        )
        skipped_reason = "unnamed or unlocated OSM elements are refused, never guessed at"
        print(f"skipped means: {skipped_reason}")
        if not outcome["ok"]:
            print(
                f"INCOMPLETE: {len(outcome['failures'])} kind(s) failed. "
                "The catalogue holds what arrived; re-run to retry the rest."
            )
            return 1
        return 0
    finally:
        db.close()


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    if "--show" in argv:
        return show()
    return seed(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
