"""Database engine and session plumbing."""

from __future__ import annotations

import datetime as _dt
import decimal
import json
from collections.abc import Iterator
from typing import Any

from sqlalchemy import JSON, create_engine, event, types
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.app.config import settings


class JsonDict(types.TypeDecorator):
    """JSON column that tolerates the messy values real source payloads contain.

    Adapters legitimately stash `datetime` and `Decimal` objects inside
    `raw_data` / `normalized_data` (that is what the official feeds return), and
    plain `JSON` would raise at flush time. Coercing to ISO strings / numbers
    here keeps the column lossless-enough for display and provenance without
    forcing every adapter to pre-serialise.
    """

    impl = JSON
    cache_ok = True

    @staticmethod
    def _coerce(value: Any) -> str | float | None:
        if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
            return value.isoformat()
        if isinstance(value, _dt.timedelta):
            return value.total_seconds()
        if isinstance(value, decimal.Decimal):
            return float(value)
        if isinstance(value, (set, frozenset, tuple)):
            return list(value)
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)

    def process_bind_param(self, value: Any, dialect) -> Any:
        if value is None:
            return None
        try:
            json.dumps(value, ensure_ascii=False)
            return value
        except (TypeError, ValueError):
            return json.loads(
                json.dumps(value, default=self._coerce, ensure_ascii=False)
            )

    def process_result_value(self, value: Any, dialect) -> Any:
        return value


def as_stored_json(value: Any) -> Any:
    """What a `JsonDict` column will hand back for `value`, without writing it first.

    The column coerces anything plain JSON cannot serialise (a `datetime`, a `Decimal`, a `set`)
    into a serialisable form on the way in and `process_result_value` never converts it back, and
    the JSON text itself turns tuples into lists and non-string keys into strings. So a freshly
    built dict is generally *not* equal to the dict that comes out of the column even when the
    source said exactly the same thing twice - which is how an unchanged poll ends up rewriting
    its own row. Compare against this instead of against the raw Python object.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return json.loads(json.dumps(value, default=JsonDict._coerce, ensure_ascii=False))


class Base(DeclarativeBase):
    pass


def _is_sqlite() -> bool:
    return settings.database_url.startswith("sqlite")


# SQLite and a hosted database need opposite things from the engine, and the split is made
# once here rather than at call sites.
#  * SQLite: one file, many threads -> `check_same_thread=False`, plus a busy timeout.
#  * Anything over a network: `pool_pre_ping` is an *engine* argument. Passed to the DBAPI as
#    a connect argument it is not a connection option at all, and psycopg refuses it. The
#    recycle matters just as much: a hosted Postgres (or the pooler in front of it) closes an
#    idle connection whenever it likes, and the app's ingestion thread holds one across a
#    whole poll interval. Without the ping and the recycle that shows up as the first query
#    after a quiet stretch failing on a half-open socket.
_SQLITE = _is_sqlite()

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False, "timeout": 30} if _SQLITE else {},
    pool_pre_ping=_SQLITE is False,
    pool_recycle=300 if _SQLITE is False else -1,
    future=True,
    echo=False,
)

if _SQLITE:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - driver hook
        cursor = dbapi_connection.cursor()
        # WAL keeps the ingestion scheduler and API workers from blocking each other.
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

else:

    @event.listens_for(engine, "connect")
    def _pin_search_path(dbapi_connection, _record):  # pragma: no cover - driver hook
        """Put every unqualified name in one known schema, on every connection.

        Hosted providers set a default `search_path` of `"$user", public`, and a role named
        `postgres` alongside a `postgres` schema - which is Supabase's shape - means an
        unqualified `CREATE TABLE` can land in a schema no dashboard shows. The models declare
        no schema, so the only safe answer is to make the resolution explicit and identical on
        every connection, rather than trusting whichever one the app happens to open.
        """
        cursor = dbapi_connection.cursor()
        cursor.execute("SET search_path = public")
        cursor.close()
        # Commit, rather than leaving the connection as it is. psycopg starts a transaction around
        # that SET (its default is autocommit off), and in Postgres a SET that is not `LOCAL` is
        # still transactional: the first rollback discards it. There is always a first rollback -
        # the pool rolls a connection back before handing it out again, and the pre-ping does too
        # - so without this the schema pin would hold only until the connection made one round
        # through the pool, and afterwards every name would resolve by the provider's default.
        dbapi_connection.commit()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


def session_scope() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from backend.app import models  # noqa: F401  (register mappers)

    Base.metadata.create_all(bind=engine)
