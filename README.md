# SANKET — disaster intelligence and two-way community response for Nepal

SANKET reads the official Nepali data sources during a disaster, turns them into a
single prioritised picture for a Response Center, and keeps a real two-way channel
open with the people living through it.

It is one application with thirteen modules, not a microservice fleet, and it runs on
a laptop with no keys and no Postgres.

---

## What is real here, and what is not

This matters more than any feature list, so it is stated first.

| | |
|---|---|
| **Earthquakes** | Live. USGS FDSN service and the NEMRC / Seismo Nepal map page. |
| **Rainfall, river levels, flood alerts** | Live. Department of Hydrology and Meteorology (`dhm.gov.np`, `hydrology.gov.np`). |
| **Incident register (deaths, damage, districts)** | Live. Nepal Disaster Risk Reduction Portal (MoHA). |
| **Road status** | Partial. The Department of Roads publishes PDFs; the DRR daily highway bulletin is a PDF too. Sanket records what it can parse and marks the rest **not machine readable**. |
| **Community reports and help requests** | Real objects in a real database with a real lifecycle. |
| **Facilities, teams, contacts** | Facilities: **real, ~1,200 of them.** `POST /api/rc/resources/seed` (or `python scripts/seed_resources.py`) pulls hospitals, health posts, police posts, helipads, fire stations and water points out of OpenStreetMap over Overpass, keyed by OSM id so re-seeding updates instead of duplicating. Availability is operator-asserted and decays to `unknown` after 12 h; the map layer never emits an unconfirmed `contact`. Teams and rosters: **not built** — dispatch names a plausible unit from a built-in list and labels it as such. |
| **Language model** | Optional. `LLM_PROVIDER=gemini` plus a `GEMINI_API_KEY` runs the real Strands agent; the model is `gemini-3.6-flash`, because the `gemini-2.5-flash` the plan named is no longer callable with a key issued today (known issues, "The first run with a real key"). With no key the agent runs a deterministic fallback that quotes retrieved data and says so. Free-tier keys get roughly 20 model requests a **day** (known issues, item 72 — the error's own "retry in 22s" says otherwise), so the live agent paths are verified by hand once and are in no gate; a throttled run reports the provider's error instead of substituting an answer. The key stays in the backend; the frontend never receives it. |

Nothing in Sanket fabricates a situation. If a source is unreachable, the source panel
shows it failing. Demo data exists to demonstrate the product and is labelled
`Demo Data` everywhere it appears, on a surface that is never silently mixed with live
rows.

**Provenance is not optional.** Every incident, report, signal and alert in an API
response carries where it came from, when it was recorded, when it was last updated and
whether that answer is fresh, ageing or stale.

---

## Run it

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows   (source .venv/bin/activate on macOS/Linux)
pip install -r requirements.txt

copy .env.example .env            # optional - the defaults already work

# terminal 1 - API on http://127.0.0.1:8123
python -m uvicorn backend.app.main:app --port 8123     # no --reload, see the note below

# terminal 2 - UI on http://localhost:5173
cd frontend && npm install && npm run dev
```

8123, not 8000: it is the port `.env.example`, `frontend/.env.example`, the Vite proxy and every
smoke script already agree on. Starting the API somewhere else does not fail loudly — the dev
server proxies to a port nobody is listening on, and the UI reports "cannot reach the server".

`--reload` is left off on purpose: on Windows the reloader here has been seen to log
`Reloading...` and leave no server listening (docs/known-issues.md, item 24). Restart the process
when you change backend code — `smoke_http.py` now refuses to report green if a second server is
answering on the other port, because verifying a stale process is worse than not verifying.

`npm run dev` proxies `/api` and `/geo` to port 8123, so the browser and the API stay same-origin.
`npm run build` type-checks and writes `frontend/dist`, which the API then serves itself at
http://127.0.0.1:8123 — one process, no CORS in any mode.

Interactive API documentation: **http://127.0.0.1:8123/api/docs**

The first start creates the SQLite schema at `data/sanket.db`, registers the data
catalogue, downloads the boundary files if they are missing, seeds the demo accounts and
begins polling the official sources.

### Demo accounts

Password for all five: `sanket123` (see `SANKET_ALLOW_DEMO_ACCOUNTS`). The sign-in screen reads
`GET /api/auth/demo-accounts` and offers them as one tap, so no password has to be typed from this
file — and if you turn that setting off, the screen stops offering them.

| Username | Surface | Rank |
|---|---|---|
| `sunita.rc` | Response Center | operator |
| `rajesh.rc` | Response Center | coordinator |
| `analyst.rc` | Response Center | analyst |
| `ram.prasad` | Community | resident (Nepali, Mustang) |
| `sita.dev` | Community | resident (Nepali, Sindhupalchok) |

### Prove it works without opening the UI

```bash
python scripts/check_sources.py     # what every official source answers right now
python scripts/smoke_slice.py       # real data -> normalized incidents -> counts
python scripts/smoke_loop.py        # report -> link -> request -> queue -> lifecycle -> audit
python scripts/smoke_http.py        # the same walk over HTTP, with role checks
python scripts/smoke_agent_guardrails.py  # the agent's write tools, with a model's arguments - no key needed
python scripts/scenario_melamchi.py       # the plan's test sentence through the real agent - needs a key, says which criteria it could not check
python scripts/check_resources.py   # facility routes and query shape, no network needed
python scripts/seed_resources.py    # pull real facilities from OpenStreetMap (--show for counts)
python scripts/report_state.py      # what is actually in the database right now, by source
python scripts/inspect_incident.py  # one incident's evidence, links and score breakdown
python scripts/reset_db.py          # drop and rebuild the schema (see "Schema changes" below)
```

**"The data looks stale" is three different questions**, and they get answered from the database rather
than from the screen. `python probe/ingestion_cadence.py` prints every source against its own
`refresh_interval_seconds`, its run tally for the window, what the adapters failed on, and the
`system_state` row that can pause polling; `python probe/poll_twice.py` runs two real polls back to
back and says whether a source is still rewriting rows that have not changed — which is exactly what
items 73-76 of the known-issues list were. Whether the worker thread is alive is now an answer and not
an inference: `GET /api/sources` carries a `worker` object, the sources screen renders it, and
`smoke_http.py` gates it.

**Rehearsal mode is no longer reachable.** The scripted-scenario screen, the map screen and the
`/api/demo/*` endpoints were removed, so nothing over HTTP arms a scenario any more;
`backend/app/services/demo.py` is left in place and can still be driven from a script.
The `/api/map/*` GeoJSON feeds stay - they are a data API, not a screen.

**Schema changes.** The models create tables on first start but never alter them, so a
new column needs `python scripts/reset_db.py` and then a re-ingest. There is no
migration tool yet - it is on the known-issues list, not an oversight to paper over.

---

## The two surfaces

**Response Center** (never "admin") is a dark command centre: an action queue ordered by a
published formula rather than by
whoever shouted last, and an incident view that always answers *why is this here* —
score components, weights, evidence state, freshness, and every source record behind it.
Operators acknowledge, assign, escalate, verify, merge, split and message. Every one of
those moves is written to an audit log with actor, timestamp and reason.

**Community** is mobile-first and works on a bad signal. Five actions: **ASK**,
**REPORT SOMETHING**, **I NEED HELP**, **LOCAL ALERTS**, **MY REQUESTS**. English and
Nepali, voice input, and an offline queue that replays when the signal returns without
losing anything. The person who asked can see the same lifecycle the operator drives:
received → reviewing → team notified → assigned → in progress → resolved, with the words
generated by code so nobody is promised something the system cannot deliver.

Two of the sentences above describe a product that does not exist yet, and they are worth naming so
nobody reads them as shipped: there is **no dark theme** (the console is light, and inverting the
stylesheet would invert the urgency colours and make them lie — known issues 37), and the
**offline queue and voice input stop at the edge of the phone** — `POST /api/community/offline/flush`
and its `submitted_offline` / `voice_transcript` flags are real and tested, and the strings for a
mic button are translated, but nothing on the client stores a report or records audio yet. What is
true today is an offline *banner* that says so rather than showing an empty list, the lifecycle
its words come from, and the audit log behind every move.

---

## Where the judgement lives

Code, deliberately, for everything that can be computed:

coordinates and district lookup · distances · timestamps and freshness budgets ·
impact score (documented formula, published weights, per-component breakdown) ·
urgency and SLA deadlines · duplicates and clustering · evidence state and who is
authoritative to change it · status transitions · provenance.

The language model, for everything that is language:

understanding what a resident wrote in either language · grouping similar reports ·
drafting an operator's message · turning a situation into a short answer with citations.

It never predicts, never invents a facility or a phone number, never declares something
officially confirmed, and is never the only source for a number on the screen. Chain of
thought is not shown to any user.

Read [docs/architecture.md](docs/architecture.md),
[docs/data-sources.md](docs/data-sources.md) and
[docs/scoring-and-trust.md](docs/scoring-and-trust.md) before changing any of it.

---

## Layout

```
backend/app/          FastAPI app, models, services, deterministic engines
  api/                auth, community, incidents, response_center, operations
  models/core.py      SOURCE / OBSERVATION / INCIDENT / REPORT / REQUEST / RESOURCE
  schemas/            request bodies, all strict (unknown fields ignored, not trusted)
  services/           users, ingestion, incidents, community, assistance, response_center,
                      signals, alerts, notifications, audit, communication
  geo/                boundaries (district lookup), correlation
  scoring/            evidence, freshness, impact, urgency
  repositories/       reserved - the queries currently live in the services
  config.py db.py deps.py security.py scheduler.py main.py
data_ingestion/       http_fetch, static_geo, normalizers/observation,
  sources/            catalog + one adapter per official source
                      (usgs, nemrc, dhm, hydrology, drr, roads)
shared/               enums, geo, timeutils, nepal_places  (importable by every layer)
agent/                Strands tools, prompts, workflows
frontend/             Vite + React + TypeScript
scripts/              source checks and the end-to-end smoke walks
docs/                 architecture, sources, scoring, known issues
data/                 SQLite file and downloaded boundary files (gitignored)
```

Import direction is one way: `shared` <- `data_ingestion` <- `backend/app` <- `api`.
A service never imports from `backend.app.api`, and it never imports the web layer to
learn who is asking - the router hands it a permission set instead.

---

## Status

The backend data path is complete and wired: real ingestion, normalization, correlation,
trust, scoring, the facility catalogue and its dispatch matching, the community lifecycle, the
Response Center queue, audit, notifications, the agent layer (40 tools in
two sets — an investigation set that can only read, and a response set that additionally files
cases, leaves internal notes and sends victim updates; every run persisted and auditable) and the
HTTP API (70 paths) — all exercised against live Nepali data by the scripts above, in-process and
over HTTP.

That path was re-checked on 2026-09-13 after a report that polling had stopped. It had not — every
source was keeping its own interval and all 8 adapters parsed their live endpoints. Four feeds were
instead rewriting their own unchanged rows on every poll, which moved the dashboard's "last change"
stamp onto days-old data (known issues, items 73-76), and nothing in the API could say whether the
worker thread was alive (item 77). So a `records_updated` count from before that date measured
bookkeeping, not new information.

On the frontend the foundation is built and type-checks clean — the API client with every path
verified against the running OpenAPI document, EN/NE strings, auth and surface guards, the app
shell and sign-in. Both consoles are routed and rendered against a live server: every Response
Center screen (overview, queue, incidents, reports, requests, resources, sources, activity, audit,
assistant) and the community flow (feed, ask, report, help, my requests, account).

Not finished, in the order that matters. **What only a person can judge:** pixels and pointer behaviour
past the renders that were done (known issues, item 42), and the two gaps in what an operator can see
about an agent run — a write refused for permission leaves no trace of the attempt (item 71), and an
investigation's tool rows carry no detail line (item 68, whose emptiness is fixed). **What one key
cannot cover:** the free-tier quota (item 72) is 20 model requests a day, and today's went into the
responder scenario, so the live agent paths are each verified once by hand and are in no gate — a green
`smoke_http.py` agent section may be the fallback's, and `mode` is the field that says which. The one
code path with no live run behind it is the investigation route's widened number guard;
`python probe/live_investigation_check.py` closes it on a day that has requests left. **Two ingestion
loose ends, both measured and neither ours to fix cheaply:** `drr_highway` rewrites 2 observation rows
every poll because the upstream page alternates its own link label (item 79 — no incident is touched, so
the register is unaffected), and a leftover `system_mode=demo` row would pause live polling with no HTTP
route able to clear it, since the screen that did so was removed (item 80 — not the cause of the report
above, where the row reads `live`).

Details, costs and repro commands are in [docs/known-issues.md](docs/known-issues.md) — read that
before trusting any summary here.
