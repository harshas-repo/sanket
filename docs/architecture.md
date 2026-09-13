# Architecture

SANKET is one application split into thirteen modules that talk in one direction. It is
not a distributed system, and it is not meant to become one: a disaster cell needs a
laptop that works, not an orchestrator.

```
                          ┌─────────────────────────────┐
   Response Center UI ────┤                             │
                          │   FastAPI  /api  (backend/) │
   Community UI ──────────┤   auth · surfaces · routes  │
                          └──────────────┬──────────────┘
                                         │ permission sets, never raw requests
                          ┌──────────────▼──────────────┐
                          │        services/            │  the only place that writes
                          │  ingestion incidents community │
                          │  assistance response_center   │
                          │  signals alerts notifications  │
                          │  audit users communication    │
                          └───┬──────────┬──────────┬────┘
                              │          │          │
                    ┌─────────▼──┐ ┌─────▼─────┐ ┌──▼──────────┐
                    │  geo/ +    │ │ scoring/  │ │   models/   │
                    │ correlation│ │freshness  │ │ SQLAlchemy  │
                    │ boundaries │ │impact     │ │ 17 tables   │
                    │            │ │urgency    │ │             │
                    │            │ │evidence   │ │             │
                    └─────────▲──┘ └───────────┘ └─────────────┘
                              │
                    ┌─────────┴──────────┐
                    │   data_ingestion/  │  one adapter per official source
                    │ catalog · fetchers │  normalizes into Observation
                    └─────────▲──────────┘
                              │
              USGS · NEMRC · DHM rainfall · DHM rivers · hydrology alerts
              DRR incident register · DRR highway bulletin · Department of Roads
```

`shared/` (enums, timeutils, geo, place names) sits underneath all of it and imports
nothing from inside the project.

The import rule is enforced by convention and by review, not by a framework:

`shared` ← `data_ingestion` ← `backend/app/{models,geo,scoring,services}` ← `backend/app/api`

A service does not import the web layer. When the Response Center needs to know which
buttons the current viewer may press, the router hands the service a **permission set**
as plain data (`deps.granted_permissions(user)`), so `services/response_center.py` can
filter an action surface without knowing what an HTTP request looks like.

---

## The thirteen layers

| # | Layer | Lives in | Owns |
|---|---|---|---|
| 1 | Ingestion | `data_ingestion/sources`, `services/ingestion.py` | Polling, retries, run records, source health |
| 2 | Normalization | `data_ingestion/normalizers` | One row shape: `Observation` + provenance |
| 3 | Geo | `geo/boundaries.py` | Coordinates → district/province via real boundary files |
| 4 | Correlation | `geo/correlation.py` | What counts as the same event, and at what confidence |
| 5 | Trust | `scoring/evidence.py` | The six evidence states and who may move them |
| 6 | Prioritization | `scoring/{impact,freshness,urgency}.py` | Scores, staleness, SLA deadlines |
| 7 | Incident ledger | `services/incidents.py` | Incident lifecycle, merging, recompute |
| 8 | Community intake | `services/community.py` | Reports, duplicates, translation of intent |
| 9 | Assistance | `services/assistance.py` | Requests, the lifecycle, victim-visible updates |
| 10 | Operations | `services/{response_center,signals,alerts}.py` | Queue, dashboard, risk signals, advisories |
| 11 | Communication | `services/{communication,notifications}.py` | Every sentence shown to a victim; delivery |
| 12 | Agent | `agent/` | Language work only: understand, group, draft, explain |
| 13 | API + surfaces | `backend/app/api`, `frontend/` | Auth, role-scoped reads, the two UIs |

---

## Data model

Seventeen tables, six of which are the spine named in the specification:

**SOURCE** (`sources`) — a registered feed, its official-ness, and whether it is
currently answering. `status ∈ {healthy, degraded, failing, never_fetched}`.

**OBSERVATION** (`observations`) — one immutable record from one source, exactly as that
source expressed it, plus the raw payload. Never edited after the fact; when a source
corrects itself, a new observation arrives and correlation decides what it means.
`incident_observations` is the many-to-many link with the incident it was folded into.

**INCIDENT** (`incidents`) — the normalized event the system actually works on: type,
place, coordinates, time window, severity, evidence state, impact score and its
breakdown, acknowledgement and resolution state.

**COMMUNITY_REPORT** (`community_reports`) — what somebody said, in their words, with
their language, their location precision, and the duplicate/corroboration chain.

**ASSISTANCE_REQUEST** (`assistance_requests`) — a case with a reference code, an
urgency, an SLA clock, an owner, and `assistance_updates`: the victim-visible
transcript of everything that happened to it.

**RESOURCE** (`resources`) — teams, shelters, hospitals, equipment, supplies: capacity,
status, location, and whether the fact came from OSM, an operator, or an official list.

Supporting: `users`, `roles`, `notifications`, `audit_events`, `ingestion_runs`,
`risk_signals`, `agent_investigations`, `demo_events`, `system_state`.

Every table that surfaces a fact carries `provenance` and timestamps for *recorded* and
*last updated*. There is no query path that returns a number without them.

---

## Determinism, and where the model is allowed to speak

The rule is not "AI does the clever parts". It is: **anything that can be computed is
computed, and only what cannot be computed is generated.**

Code owns coordinates, distances, timestamps, freshness budgets, the impact score and
its published weights, urgency ordering and SLA clocks, duplicate detection, clustering,
evidence state, status transitions, and provenance. Each of those has a formula or a
table in `geo/` and `scoring/`, and each one is reproducible from the record alone.

The model owns language: reading a resident's message in either language, deciding what
kind of need it expresses, grouping reports that describe the same thing in different
words, drafting an operator's message, and turning a situation into a short answer that
cites the records behind it.

It is never allowed to: invent an incident, facility, coordinate, phone number or count;
declare something officially confirmed; be the sole source of any number on a screen;
decide a status transition; or show its reasoning to a user.

When no model credentials exist, `agent/` runs a deterministic fallback that retrieves
the real records and quotes them, and says that is what it is doing. The product must
not go quiet without a language model, and it must not get more confident either.

---

## Two surfaces, one set of objects

**Response Center** (`/api/rc/*`, requires `Role=response_center`) sees everything,
including community-only evidence, and every one of its writes is audited with actor,
timestamp and reason. Its queue is ordered by the impact score and the urgency rules,
not by arrival.

**Community** (`/api/community/*`, `Role=community`) sees its own cases in full and the
public situation in a narrower form. A resident's report of something with no official
backing is *not* echoed back to other residents as fact — that is how rumours become
panics. `GET /incidents/{id}` returns a reduced public shape for that reason, and the
public shape carries no action surface at all.

The API enforces this twice: once through the permission dependency, and again inside
the query, so a bug in one cannot expose the other.

---

## Concurrency and the freshness loop

The scheduler ticks every `SANKET_INGESTION_INTERVAL_SECONDS` and runs due sources; each
run writes an `ingestion_runs` row whether it succeeded or failed, because a silent
failure is the worst thing an ingestion system can do. Incidents are recomputed from
their evidence when evidence changes — scores are not patched incrementally, so a
recompute after a schema or formula change cannot leave stale numbers behind.

`system_state` holds the demo/live mode and the simulation clock. Live and demo rows are
never mixed in one response: a demo row carries `demo=true` and the mode is reported on
every envelope and in the `x-sanket-mode` header.

---

## Deliberate limits, so nobody is surprised later

- **SQLite by default.** The engine is SQLAlchemy, so Postgres is a connection string
  away, but the shipping configuration is a single file on a laptop.
- **No migrations yet.** `create_all` builds tables and never alters them. A new column
  means `scripts/reset_db.py` and a re-ingest. This is the first thing a real deployment
  must replace.
- **No background worker process.** Ingestion runs inside the API process. It survives
  one operator and one laptop; it is not a multi-node design.
- **SMS/IVR/Viber are stubs.** `services/communication.py` writes a provider record and
  logs what it would have sent. Nothing pretends a message was delivered.
- **Alerts do not decide who is at risk.** `risk_signals` converges district-level
  indicators into an advisory state; the map and the queue show *why*, and an operator
  still decides what to dispatch.
