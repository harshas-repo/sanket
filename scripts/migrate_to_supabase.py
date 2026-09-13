"""Copy the local SQLite database into the Postgres database `DATABASE_URL` points at.

Why a script rather than `pgloader`/CSV export: the value has to cross a type boundary in both
directions - SQLite's JSON is TEXT and Postgres' is a parsed document, SQLite stores datetimes
as formatted strings, booleans as 0/1 - and the single place that knows both representations is
the SQLAlchemy `MetaData` the app itself uses. Reading through `Base.metadata` on the source
hands back Python objects; inserting through the same `Base.metadata` on the target writes them
as Postgres values. Nothing in between is stringified, so there is no CSV quoting, no NULL versus
empty-string ambiguity, and no date format to negotiate.

Safety properties, in order of how much they matter:
  * The source is copied out through `VACUUM INTO` first, which is SQLite's atomic snapshot: the
    ingestion worker can keep polling, because the thing being read is a private, frozen file.
    Without this, the verifier compares a finished target against a database still being edited
    and reports differences that are not migration errors. (Tried first: one long read
    transaction. pysqlite does not hold a snapshot that way, so it did not work.)
  * The snapshot is opened `PRAGMA query_only`, so nothing here can corrupt the file it read.
  * The target write is ONE transaction: any failure leaves an empty schema, never half a queue.
  * An existing target with rows is refused unless `--replace` is passed explicitly.
  * Nothing is declared migrated until `verify` says the row counts, per-column aggregates and a
    random per-row field-by-field diff all agree.

Usage:
    python scripts/migrate_to_supabase.py                # copy + verify (uses DATABASE_URL)
    python scripts/migrate_to_supabase.py --verify-only  # re-check without writing
    python scripts/migrate_to_supabase.py --replace      # drop target tables first
    python scripts/migrate_to_supabase.py --keep-snapshot  # leave data/_migration_snapshot.db
    python scripts/migrate_to_supabase.py --to sqlite:///data/selftest.db --allow-sqlite-target
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from _bootstrap import prepare

prepare()

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import (  # noqa: E402
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Table,
    Text,
    cast,
    create_engine,
    event,
    func,
    inspect,
    make_url,
    select,
    text,
    tuple_,
)
from sqlalchemy.engine import Connection, Engine  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402

from backend.app import models  # noqa: E402,F401  (register mappers)
from backend.app.config import DATA_DIR, settings  # noqa: E402
from backend.app.db import Base, JsonDict  # noqa: E402

SAMPLE_ROWS = 25
BATCH = 500


def shown(url: object) -> str:
    """A URL safe to print: the password never appears."""
    return str(url).split("@")[-1] if "@" in str(url) else str(url)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--from", dest="source", default=f"sqlite:///{DATA_DIR / 'sanket.db'}",
                   help="source URL (default: the app's SQLite file)")
    p.add_argument("--to", dest="target", default=settings.database_url,
                   help="target URL (default: $DATABASE_URL as the app reads it)")
    p.add_argument("--batch", type=int, default=BATCH, help="rows per INSERT executemany")
    p.add_argument("--replace", action="store_true", help="drop and recreate target tables first")
    p.add_argument("--no-rls", action="store_true", help="skip ENABLE ROW LEVEL SECURITY")
    p.add_argument("--verify-only", action="store_true", help="compare both sides, write nothing")
    p.add_argument("--keep-snapshot", action="store_true",
                   help="leave data/_migration_snapshot.db behind instead of deleting it")
    p.add_argument("--allow-sqlite-target", action="store_true",
                   help="let the target be SQLite (for self-testing this script's own logic)")
    return p.parse_args()


SNAPSHOT = DATA_DIR / "_migration_snapshot.db"


def take_snapshot(source_url: str) -> str | None:
    """Freeze a SQLite source with `VACUUM INTO`, and return the snapshot's URL.

    This is the step that makes the verification meaningful. The worker polls every fifteen
    seconds and rewrites rows as official feeds land, so reading the live file while writing the
    target means the two sides are compared across a moving database: the copy would be correct
    and the report would still say DIFFERS. `VACUUM INTO` is one consistent transaction inside
    SQLite itself, takes a brief shared lock rather than a long one, and leaves a file no one
    else can touch. Non-SQLite sources are already servers with their own isolation.
    """
    if not source_url.startswith("sqlite"):
        return None
    live = make_url(source_url).database
    if not live or not Path(live).is_file():
        print(f"  no SQLite file at {live!r}")
        return None
    SNAPSHOT.unlink(missing_ok=True)
    engine = create_engine(source_url, future=True)
    try:
        with engine.connect() as conn:
            # Quoting a path is the whole escaping problem: SQLite string literals have no
            # backslash escapes, so only a doubled apostrophe is meaningful.
            quoted = SNAPSHOT.as_posix().replace("'", "''")
            conn.exec_driver_sql(f"VACUUM INTO '{quoted}'")
    finally:
        engine.dispose()
    size = SNAPSHOT.stat().st_size
    print(f"  snapshot: {SNAPSHOT.name}, {size / 1024 / 1024:.1f} MiB, read from {Path(live).name}")
    return f"sqlite:///{SNAPSHOT.as_posix()}"


# --------------------------------------------------------------------------- #
# pre-flight
# --------------------------------------------------------------------------- #
def check_source_columns(src: Engine) -> list[str]:
    """The file being read must still match the models that describe it.

    There are no migrations in this project, so the schema can only have drifted by someone
    editing `core.py` without rebuilding the file. A missing column here would not fail loudly:
    the copy would simply never look for it, and the migrated database would be quietly short of
    whatever the running app expects to read.
    """
    problems: list[str] = []
    insp = inspect(src)
    present_tables = set(insp.get_table_names())
    for name, table in Base.metadata.tables.items():
        if name not in present_tables:
            problems.append(f"{name}: table missing from the source")
            continue
        present = {c["name"] for c in insp.get_columns(name)}
        for col in table.columns:
            if col.name not in present:
                problems.append(f"{name}.{col.name}: in the models, missing from the source")
    return problems


def target_state(tgt: Engine) -> dict[str, int]:
    insp = inspect(tgt)
    existing = set(insp.get_table_names())
    counts: dict[str, int] = {}
    with tgt.connect() as conn:
        for name, table in Base.metadata.tables.items():
            if name in existing:
                counts[name] = conn.execute(
                    select(func.count()).select_from(table)
                ).scalar_one()
    return counts


# --------------------------------------------------------------------------- #
# copy
# --------------------------------------------------------------------------- #
def copy_all(src_conn: Connection, tgt_conn: Connection, batch: int) -> dict[str, int]:
    """Read every table through `src_conn`, write it through `tgt_conn`.

    Both connections arrive with their transaction already open, and that is the whole design:
    the caller decides where the snapshot starts and ends, so the copy and the verification that
    follows it can be made to look at the same instant. A transaction left open on the source
    while the target is written is also what keeps a still-running ingestion worker from making
    the two sides disagree about a moving database.
    """
    copied: dict[str, int] = {}
    for table in Base.metadata.sorted_tables:
        rows = 0
        result = src_conn.execute(select(table))
        while True:
            chunk = result.fetchmany(batch)
            if not chunk:
                break
            payload = [dict(r._mapping) for r in chunk]
            tgt_conn.execute(table.insert(), payload)
            rows += len(payload)
        copied[table.name] = rows
        print(f"  {table.name:26} {rows:>7,} rows copied", flush=True)
    return copied


def sync_sequences(tgt: Engine) -> None:
    """Move any identity/serial counter past the highest copied value.

    An INSERT that names the column does not advance a sequence, so the first insert after the
    migration would collide with a migrated row. Every primary key in this schema is a string
    UUID, so the honest expectation is that this finds nothing - and it says so rather than
    staying silent, because "nothing to do" and "did not look" are different claims.
    """
    if tgt.dialect.name != "postgresql":
        print("  (sequence sync is Postgres-only; skipped)")
        return
    insp = inspect(tgt)
    fixed: list[str] = []
    with tgt.begin() as conn:
        for name in Base.metadata.tables:
            if name not in insp.get_table_names():
                continue
            for col in insp.get_columns(name):
                if "nextval" not in str(col.get("default") or ""):
                    continue
                seq = conn.execute(
                    text("select pg_get_serial_sequence(:t, :c)"),
                    {"t": f"public.{name}", "c": col["name"]},
                ).scalar_one()
                if not seq:
                    continue
                highest = conn.execute(
                    text(f'select coalesce(max("{col["name"]}"), 0) from public."{name}"')
                ).scalar_one()
                conn.execute(text("select setval(:s, :v, :present)"),
                             {"s": seq, "v": max(int(highest), 1), "present": int(highest) > 0})
                fixed.append(f"{name}.{col['name']} -> {highest}")
    print("  no identity/serial columns: nothing to setval" if not fixed
          else f"  setval: {fixed}")


def enable_rls(tgt: Engine) -> None:
    """Row Level Security with no policies: nobody can read these tables through PostgREST,
    and the app is unaffected because it connects as the table owner, and owners bypass RLS
    unless it is FORCEd."""
    if tgt.dialect.name != "postgresql":
        print("  (RLS is a Postgres feature; skipped)")
        return
    with tgt.begin() as conn:
        for name in Base.metadata.tables:
            conn.execute(text(f'ALTER TABLE public."{name}" ENABLE ROW LEVEL SECURITY'))
    print(f"  RLS enabled, no policies, on {len(Base.metadata.tables)} tables")


# --------------------------------------------------------------------------- #
# verification
# --------------------------------------------------------------------------- #
def normalise(value: object) -> object:
    """A comparison form that survives two different storage engines."""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, memoryview):
        return value.tobytes().hex()
    return value


def close_enough(a: object, b: object) -> bool:
    if isinstance(a, float) or isinstance(b, float):
        try:
            x, y = float(a), float(b)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return False
        # Different engines sum a double-precision column in a different order. Everything else
        # in this comparison is exact; this one needs the epsilon that means "same number".
        return abs(x - y) <= max(1e-9, abs(x) * 1e-12 + abs(y) * 1e-12)
    return normalise(a) == normalise(b)


def column_fingerprint(col: Column) -> list[object] | None:
    """Aggregate expressions whose agreement is strong evidence the column crossed intact.

    Chosen per type because the interesting failure differs: for text, whether the *characters*
    survived (length sum catches a mangled encoding, a dropped accent, a truncated tail); for
    numbers, whether the values and their range survived; for timestamps, the same in min/max;
    for JSON, whether the stored document is still the same text.
    """
    if isinstance(col.type, JsonDict):
        return [func.count(col), func.sum(func.length(cast(col, Text)))]
    if isinstance(col.type, DateTime):
        return [func.count(col), func.min(col), func.max(col)]
    if isinstance(col.type, (Float, Numeric, Integer, BigInteger, SmallInteger)):
        return [func.count(col), func.sum(col), func.min(col), func.max(col)]
    if isinstance(col.type, Boolean):
        return [func.count(col), func.sum(cast(col, Integer))]
    if isinstance(col.type, (String, Text)):
        # Deliberately no min()/max() here: SQLite compares text by bytes and Postgres by the
        # database collation, which for real strings (mixed case, Devanagari) puts a different
        # row first. The length sum is collation-free and still catches truncation or corruption.
        return [func.count(col), func.sum(func.length(col))]
    return None


def aggregate_query(table: Table) -> tuple[object, list[tuple[Column, int, int]]]:
    """One SELECT carrying the row count and every column's fingerprint.

    The first version issued a query per column per side, which against a hosted database is
    hundreds of round-trips across a high-latency link - enough that the connection was dropped
    partway through verification. Folding them together also means Postgres scans each table
    once rather than once per aggregate.

    Returns the statement and a layout of (column, offset, width) to slice the row back apart.
    """
    exprs: list[object] = [func.count()]
    layout: list[tuple[Column, int, int]] = []
    offset = 1
    for col in table.columns:
        found = column_fingerprint(col)
        if not found:
            continue
        layout.append((col, offset, len(found)))
        exprs.extend(found)
        offset += len(found)
    return select(*exprs).select_from(table), layout


def verify(src_conn: Connection, tgt: Engine) -> bool:
    ok = True
    print(f"\n{'table':26} {'sqlite':>8} {'target':>8}  {'columns':>9}  {'sample':>7}")
    print("-" * 70)
    for table in Base.metadata.sorted_tables:
        for attempt in (1, 2):
            try:
                ok = verify_table(src_conn, tgt, table) and ok
                break
            except SQLAlchemyError as exc:
                # A connection over the internet can be cut by anything in between: a laptop
                # changing networks, an idle proxy, a pooler restart. Retrying the single table
                # on a fresh connection is the difference between a finished migration and a
                # script that dies 14 tables into reporting.
                first = str(exc).strip().splitlines()[0][:140]
                if attempt == 2:
                    ok = False
                    print(f"{table.name:26} {'':>8} {'':>8}  {'n/a':>9}  {'ABORTED':>7}")
                    print(f"    ! {table.name}: could not be verified ({first})")
                else:
                    print(f"    ~ {table.name}: connection lost mid-check ({first}); retrying")
    return ok


def verify_table(src_conn: Connection, tgt: Engine, table: Table) -> bool:
    """Check one table. Opens and closes its own target connection so a dead connection is
    replaced here rather than poisoning every table after it."""
    stmt, layout = aggregate_query(table)
    with tgt.connect() as tgt_conn:
        a_row = src_conn.execute(stmt).one()
        b_row = tgt_conn.execute(stmt).one()
        a, b = a_row[0], b_row[0]
        ok = a == b
        if not ok:
            print(f"    ! {table.name}: row count {a:,} vs {b:,}")

        bad = 0
        for col, offset, width in layout:
            a_v = tuple(a_row[offset:offset + width])
            b_v = tuple(b_row[offset:offset + width])
            if not all(close_enough(x, y) for x, y in zip(a_v, b_v)):
                bad += 1
                ok = False
                print(f"    ! {table.name}.{col.name}: {tuple(str(v) for v in a_v)} vs "
                      f"{tuple(str(v) for v in b_v)}")

        sample_ok = sample_diff(src_conn, tgt_conn, table, min(a, b))
        ok = ok and sample_ok
        print(f"{table.name:26} {a:>8,} {b:>8,}  "
              f"{f'{len(layout) - bad}/{len(layout)}':>9}  {'ok' if sample_ok else 'DIFFERS':>7}")
    return ok


def sample_diff(
    src_conn: Connection, tgt_conn: Connection, table: Table, total: int
) -> bool:
    """Pull a handful of complete rows from each side and compare field by field.

    Counts and aggregates can agree while individual rows are scrambled - a pair of columns
    swapped during a transform leaves every sum intact. This is the check that catches it, and
    it is the only one that reads the JSON documents as parsed values rather than as text.

    Two queries regardless of sample size: the keys are fetched from the source, then both sides
    are asked for that key set in one `IN`. Fetching row by row made this the slowest part of a
    migration over a WAN.
    """
    pk_cols = list(table.primary_key.columns)
    if not pk_cols or not total:
        return True
    keys = src_conn.execute(
        select(*pk_cols).order_by(func.random()).limit(min(SAMPLE_ROWS, total))
    ).all()
    if not keys:
        return True
    if len(pk_cols) == 1:
        cond = pk_cols[0].in_([k[0] for k in keys])
    else:
        cond = tuple_(*pk_cols).in_([tuple(k) for k in keys])

    def by_key(conn: Connection) -> dict[tuple[object, ...], object]:
        rows = conn.execute(select(table).where(cond)).mappings()
        return {tuple(r[c.name] for c in pk_cols): r for r in rows}

    a_map = by_key(src_conn)
    b_map = by_key(tgt_conn)
    bad = 0
    for key, a in a_map.items():
        b = b_map.get(key)
        if b is None:
            bad += 1
            print(f"    ! {table.name}: key {tuple(key)} exists on one side only")
            continue
        for col in table.columns:
            if not close_enough(a[col.name], b[col.name]):
                bad += 1
                print(f"    ! {table.name}.{col.name} for {tuple(key)}: "
                      f"{str(a[col.name])[:60]!r} vs {str(b[col.name])[:60]!r}")
    for key in b_map:
        if key not in a_map:
            bad += 1
            print(f"    ! {table.name}: key {tuple(key)} on the target but not the source")
    return bad == 0


def drop_snapshot(url: str | None, keep: bool) -> None:
    """Remove the frozen copy, unless it was asked for. Every exit path calls this, because a
    stale snapshot in `data/` is 26 MiB of live production data sitting in a directory the app
    also reads - and `data/*.db` is gitignored, which makes it easy to forget entirely."""
    if url and not keep and SNAPSHOT.is_file():
        SNAPSHOT.unlink(missing_ok=True)


def describe_blockers(tgt: Engine) -> None:
    """Print whichever sessions hold locks on the tables this migration is waiting behind.

    A timeout on its own is unactionable. This names the pid, how long it has been sitting, and
    the last query it ran - which is normally a crashed script's own backend that a 30-minute
    keepalive has not reaped yet. Only sessions with a granted lock on `public` are listed, so
    Supabase's own housekeeping (pg_cron, PostgREST, the metrics exporter) stays out of the way.
    """
    if tgt.dialect.name != "postgresql":
        return
    try:
        with tgt.connect() as conn:
            rows = conn.execute(text("""
                select a.pid, coalesce(a.usename, '-'), coalesce(a.state, '-'),
                       coalesce(extract(epoch from now() - a.state_change)::int::text, '?') as secs,
                       count(*) as locks,
                       left(regexp_replace(a.query, chr(10), ' ', 'g'), 70) as query
                from pg_locks l
                join pg_class c on c.oid = l.relation
                join pg_namespace ns on ns.oid = c.relnamespace
                join pg_stat_activity a on a.pid = l.pid
                where l.granted and ns.nspname = 'public' and a.pid <> pg_backend_pid()
                group by 1, 2, 3, 4, 6
                order by min(a.state_change) nulls first
            """)).all()
    except SQLAlchemyError as exc:
        # Print the failure rather than swallowing it. A diagnostic that quietly produces nothing
        # is worse than no diagnostic: it reads as "no blockers" when it means "could not look".
        print(f"  (could not read pg_stat_activity: {type(exc).__name__}: "
              f"{str(exc).strip().splitlines()[0][:120]})")
        return
    if not rows:
        print("  (no other session holds a lock on public - the wait was something transient)")
        return
    print("  sessions holding locks on the tables being dropped:")
    for pid, usename, state, secs, locks, query in rows:
        print(f"    pid {pid} {state!r} as {usename}, {secs}s, {locks} lock(s) :: {query!r}")


def clear_orphaned_sessions(tgt: Engine) -> int:
    """Terminate this role's abandoned idle-in-transaction backends. Returns how many.

    When a script dies, Postgres does not notice: it waits for `tcp_keepalives_idle`, which
    Supabase sets to 1800 seconds, and meanwhile the orphan keeps every lock its last
    transaction had taken. `DROP TABLE` then queues behind a process that no longer exists, and
    the only way out is to end it from the outside.

    Deliberately narrow: same database, same role, `idle in transaction`, and quiet for over a
    minute. A session meeting all four is not doing work. Everything killed is printed with the
    query it stopped on, so the decision can be audited after the fact.
    """
    if tgt.dialect.name != "postgresql":
        return 0
    try:
        with tgt.connect() as conn:
            rows = conn.execute(text("""
                select a.pid,
                       coalesce(extract(epoch from now() - a.state_change)::int, 0) as secs,
                       left(regexp_replace(a.query, chr(10), ' ', 'g'), 70) as query,
                       pg_terminate_backend(a.pid) as killed
                from pg_stat_activity a
                where a.datname = current_database()
                  and a.pid <> pg_backend_pid()
                  and a.usename = current_user
                  and a.state = 'idle in transaction'
                  and now() - a.state_change > interval '60 seconds'
            """)).all()
            conn.commit()
    except SQLAlchemyError as exc:
        # Recovery must not become a second failure. If this cannot run, the caller still has the
        # blocker report above and can decide what to do; it should not lose the migration.
        print(f"  (could not clear orphaned sessions: {type(exc).__name__}: "
              f"{str(exc).strip().splitlines()[0][:120]})")
        return 0
    for pid, secs, query, killed in rows:
        print(f"    ended pid {pid} (idle in transaction {secs}s) after: {query!r} -> {killed}")
    return len(rows)


def drop_target(tgt: Engine) -> bool:
    """Drop the existing target schema, recovering once from a lock that will never be released."""
    try:
        Base.metadata.drop_all(bind=tgt)
        return True
    except SQLAlchemyError as exc:
        print(f"  x drop failed: {str(exc).strip().splitlines()[0][:160]}")
        describe_blockers(tgt)

    print("  clearing abandoned sessions of this role, then retrying once")
    if not clear_orphaned_sessions(tgt):
        print("  x nothing qualified as abandoned; refusing to kill live sessions. "
              "Close whatever holds those locks and re-run.")
        return False
    # The pool's connections have just had a cancelled transaction; start clean, and let the
    # re-connect listener re-apply the session settings.
    tgt.dispose()
    try:
        Base.metadata.drop_all(bind=tgt)
        print("  drop succeeded on the retry")
        return True
    except SQLAlchemyError as exc:
        print(f"  x drop still failing: {str(exc).strip().splitlines()[0][:160]}")
        describe_blockers(tgt)
        return False


# --------------------------------------------------------------------------- #
def main() -> int:
    args = parse_args()
    if args.target.startswith("sqlite") and not args.allow_sqlite_target:
        print(f"target is SQLite ({shown(args.target)}).\n"
              "Set DATABASE_URL to the Supabase Postgres URI first, or pass --allow-sqlite-target "
              "to exercise this script against a scratch file.")
        return 2

    print("\n== source ==")
    snapshot_url = take_snapshot(args.source)

    src = create_engine(snapshot_url or args.source, future=True)
    # pre_ping matters more against a hosted database than a local one: the pool keeps a
    # connection open between phases, and anything between here and Supabase is free to close it.
    # Without the ping the next statement is delivered into a dead socket.
    tgt = create_engine(args.target, future=True, pool_pre_ping=True, pool_recycle=300)
    if tgt.dialect.name == "postgresql":
        @event.listens_for(tgt, "connect")
        def _public(dbapi_connection, _record):  # noqa: E301 - see backend/app/db.py
            cursor = dbapi_connection.cursor()
            for statement in (
                "SET search_path = public",
                # Supabase ships `statement_timeout = 120000`. A migration is the one job where
                # that default is actively wrong: a `DROP TABLE` waiting on a lock is not slow,
                # it is blocked, and after 120s Postgres cancels it with a message that blames
                # the duration. `lock_timeout` instead gives 15 seconds and then an error naming
                # the wait, which `describe_blockers` turns into the pid and query that hold it.
                "SET statement_timeout = 0",
                "SET lock_timeout = '15s'",
                # This one is about the next run, not this one. Postgres cannot tell that a dead
                # client is dead until `tcp_keepalives_idle` expires - Supabase sets it to 1800 -
                # and an orphaned backend keeps taking out locks, which is what cancelled the
                # first two `--replace` attempts here. Two minutes means a crash stops becoming
                # someone else's mystery timeout. Session level, not `SET LOCAL`: the commit
                # below ends the transaction this listener runs inside, and a LOCAL setting
                # would be discarded with it.
                "SET idle_in_transaction_session_timeout = '120s'",
            ):
                cursor.execute(statement)
            cursor.close()
            # See backend/app/db.py: psycopg wrapped those SETs in a transaction, and an
            # uncommitted SET is thrown away by the pool's next rollback. This is why the first
            # run of this script still reported a 120-second statement timeout - the setting that
            # was supposed to prevent it had already been undone.
            dbapi_connection.commit()

    print(f"reading: {shown(src.url)}")
    print(f"writing: {shown(tgt.url)}")
    with tgt.connect() as conn:
        pg = tgt.dialect.name == "postgresql"
        info = {
            "server": conn.execute(text(
                "select version()" if pg else "select sqlite_version()"
            )).scalar_one(),
            "schema": conn.execute(text(
                "select current_schema()" if pg else "select 'main'"
            )).scalar_one(),
        }
    print(f"        {info['server'].splitlines()[0][:70]}")
    print(f"        tables will resolve in schema: {info['schema']}")

    problems = check_source_columns(src)
    for problem in problems:
        print(f"  x {problem}")
    if problems:
        print("  the source does not match the models it is being read through; "
              "probe/pg_preflight.py explains the drift")
        drop_snapshot(snapshot_url, args.keep_snapshot)
        return 4

    # One read connection for the copy and the verification. The isolation itself comes from the
    # snapshot file; this connection exists so both halves read the same frozen thing.
    src_conn = src.connect()
    src_txn = src_conn.begin()
    if src.dialect.name == "sqlite":
        # Set inside the transaction rather than before it: executing anything on a fresh
        # connection starts an implicit transaction, and the explicit begin() above would then
        # be refused.
        src_conn.exec_driver_sql("PRAGMA query_only=ON")
    try:
        if args.verify_only:
            return 0 if verify(src_conn, tgt) else 1

        existing = {n: c for n, c in target_state(tgt).items() if c}
        if existing and not args.replace:
            total = sum(existing.values())
            print(f"\nrefusing to overwrite: the target already holds {total:,} rows across "
                  f"{len(existing)} table(s).\nRe-run with --replace to drop and rebuild it.")
            return 3

        print("\n== schema ==")
        if args.replace:
            print("  dropping existing target tables")
            if not drop_target(tgt):
                return 5
        Base.metadata.create_all(bind=tgt)
        print(f"  {len(Base.metadata.tables)} tables present")
        if tgt.dialect.name == "postgresql":
            # Read back from a connection checked out *after* several have already been returned
            # to the pool. A session setting printed on the connection that set it proves nothing;
            # one that survived the pool's rollbacks proves the whole mechanism.
            with tgt.connect() as conn:
                got = conn.execute(text(
                    "select current_setting('search_path'), current_setting('statement_timeout'), "
                    "current_setting('lock_timeout')"
                )).one()
            print(f"  session: search_path={got[0]!r} statement_timeout={got[1]} "
                  f"lock_timeout={got[2]}")

        print("\n== copy ==")
        with tgt.begin() as tgt_conn:
            copied = copy_all(src_conn, tgt_conn, args.batch)
        print(f"  {sum(copied.values()):,} rows in total, in one transaction")

        print("\n== sequences ==")
        sync_sequences(tgt)

        print("\n== security ==")
        if not args.no_rls:
            enable_rls(tgt)

        ok = verify(src_conn, tgt)
        print("\n" + ("VERIFIED - target matches the source." if ok else
                      "NOT VERIFIED - differences above. "
                      "The app has NOT been pointed at the target."))
        return 0 if ok else 1
    finally:
        src_txn.rollback()  # read-only: this ends the read, nothing else
        src_conn.close()
        src.dispose()
        tgt.dispose()
        drop_snapshot(snapshot_url, args.keep_snapshot)


if __name__ == "__main__":
    sys.exit(main())
