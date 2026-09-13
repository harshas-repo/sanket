"""Background ingestion worker.

A single daemon thread - not a job framework. It asks the ingestion service which
sources are due, polls only those, and rebuilds the district risk signals after a
successful pass. Any exception is caught per cycle: a government portal being down
must never take the API with it.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

from shared.timeutils import humanize_age, iso, utcnow

logger = logging.getLogger("sanket.scheduler")


class IngestionWorker:
    def __init__(
        self,
        session_factory: Callable[[], Any],
        tick_seconds: int = 15,
    ) -> None:
        self._session_factory = session_factory
        self._tick = max(5, tick_seconds)
        self._stop = threading.Event()
        # Woken by `request_refresh()` and by `stop()`. One event for both, because the loop only
        # has to know that its wait is over; which of the two it was is decided by `_stop`.
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_cycle: dict[str, Any] | None = None
        # A forced pass ignores every source's own `refresh_interval_seconds` and puts a live
        # request on all eight agency servers at once. The console asks for one every time its
        # front screen mounts, so without a floor a busy shift would poll those feeds more often
        # than they publish, and the portals answer an impatient client with HTTP 500.
        self.force_floor_seconds = 60
        self._last_forced: float | None = None
        self._requested_force = False
        # Availability decay is a sweep over the whole resource table, so it runs on a
        # much slower clock than ingestion. A facility's "open" badge going stale is
        # measured in hours; checking it every 15s would be pure churn.
        self._decay_seconds = 900
        self._last_decay: float = 0.0
        self._cycles = 0
        self._last_cycle_at: datetime | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._wake.clear()
        self._thread = threading.Thread(target=self._loop, name="sanket-ingestion", daemon=True)
        self._thread.start()
        logger.info("ingestion worker started (tick %ss)", self._tick)

    def stop(self) -> None:
        self._stop.set()
        # The loop waits on `_wake`, so a stop has to wake it as well as flag it.
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("ingestion worker stopped")

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _loop(self) -> None:
        # The first pass happens immediately so a restart does not sit idle until the
        # next tick; after that the wait is interruptible, so both shutdown and an operator
        # asking for the newest official records take effect at once rather than on the tick.
        while not self._stop.is_set():
            forced = self._requested_force
            self._requested_force = False
            self._wake.clear()
            try:
                self.last_cycle = self._cycle(force=forced)
            except Exception:  # noqa: BLE001 - the worker must survive any single pass
                logger.exception("ingestion cycle failed")
            self._cycles += 1
            self._last_cycle_at = utcnow()
            self._wake.wait(self._tick)

    def _cycle(self, *, force: bool = False) -> dict[str, Any]:
        from backend.app.services import ingestion
        from backend.app.services import signals as signal_service
        from backend.app.services import state as system_state

        db = self._session_factory()
        try:
            if system_state.system_mode(db).get("mode") == "demo":
                # Live polling stops while a scenario is armed. The simulated clock drives
                # every timestamp in this process, so a real bulletin fetched now would be
                # stored with a fictional time on it - the one mixing of live and demo the
                # spec rules out. Sources go stale during a rehearsal and say so.
                return {"ran": False, "paused": "demo mode is armed", "detail": None}
            ingestion.ensure_sources(db)
            result = ingestion.run_due_sources(db, force=force)
            if result:
                signal_service.rebuild_signals(db)
            decayed = self._decay_once(db)
            return {"ran": bool(result), "forced": force, "detail": result, "availability_decayed": decayed}
        finally:
            db.close()

    def _decay_once(self, db: Any) -> int:
        from backend.app.services import resources as resource_service

        now = time.monotonic()
        if now - self._last_decay < self._decay_seconds:
            return 0
        self._last_decay = now
        count = resource_service.decay_stale_availability(db)
        if count:
            logger.info("marked %s resource(s) availability-unknown (unconfirmed)", count)
        return count

    def run_now(self) -> dict[str, Any]:
        """Force a cycle (used by the /sources/run endpoints and tests)."""
        return self._cycle()

    def request_refresh(self) -> dict[str, Any]:
        """Poll the official sources at the end of this lap, ignoring their own intervals.

        Answers before the pass happens, and says so: eight agency servers, one of them an HTML
        bulletin the size of a chapter, do not fit inside a screen's wait - a request that held the
        connection open until they had all answered would time out and show an error over data that
        arrived a second later. The caller watches `cycles` from `status()` to learn when the pass
        it asked for has been done: a counter, not a timestamp, because comparing a browser's clock
        to the server's is its own class of bug.
        """
        if not self.running:
            # Never started and died on the way are different stories, but the same honest answer
            # for whoever pressed the button: nothing is going to fetch on this request.
            return {
                "triggered": False,
                "forced": False,
                "reason": "the ingestion worker is not running in this process",
                "cycles": self._cycles,
                "floor_seconds": self.force_floor_seconds,
            }
        now = time.monotonic()
        since_forced = None if self._last_forced is None else now - self._last_forced
        forced = since_forced is None or since_forced >= self.force_floor_seconds
        if forced:
            self._last_forced = now
        # A forced request already in the queue outranks a cadence-keeping one.
        self._requested_force = forced or self._requested_force
        self._wake.set()
        return {
            "triggered": True,
            "forced": forced,
            "reason": (
                None
                if forced
                else f"a forced poll ran {int(since_forced or 0)}s ago, so this one keeps each "
                f"source's own interval instead"
            ),
            "cycles": self._cycles,
            "floor_seconds": self.force_floor_seconds,
        }

    def status(self) -> dict[str, Any]:
        """What this worker will report to the API.

        Asked of the process rather than inferred from the age of the newest ingestion run: a
        thread that died and a source whose upstream has gone quiet both leave a run table that
        stopped moving, and telling them apart by eye is the reason this whole question had to be
        answered from the database with a script. `running` is the thread's own liveness.
        """
        paused = (self.last_cycle or {}).get("paused")
        return {
            "running": self.running,
            "reason": None
            if self.running
            else ("paused while a demo scenario is armed" if paused else "thread is not running"),
            "tick_seconds": self._tick,
            "cycles": self._cycles,
            "last_cycle_at": iso(self._last_cycle_at),
            "last_cycle_label": humanize_age(self._last_cycle_at) if self._last_cycle_at else None,
            "paused": paused,
        }


def report(worker: "IngestionWorker | None") -> dict[str, Any]:
    """`worker.status()`, or an honest answer for a process that has no worker at all.

    `main.py` puts one on `app.state` inside the lifespan; a test client that never runs the
    lifespan has none, and reporting that as `running: false` would blame the code under test for
    something that was never started. `None` means "this process does not know".
    """
    if worker is None:
        return {
            "running": None,
            "reason": "no ingestion worker in this process",
            "tick_seconds": None,
            "cycles": 0,
            "last_cycle_at": None,
            "last_cycle_label": None,
            "paused": None,
        }
    return worker.status()
