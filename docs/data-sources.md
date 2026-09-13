# Data sources

Everything SANKET knows about a disaster starts here. The rule that governs this layer is
absolute: **an unreachable source is a visible failure, never an empty map.**

Ten entries are registered at startup — eight real feeds and two internal ones that
exist so community and demo traffic can be attributed to *something* in the same
provenance column as the official rows.

| Code | What it gives | Where it comes from | Official | Machine readable |
|---|---|---|---|---|
| `usgs` | Global seismic events: magnitude, epicentre, depth, felt reports | `earthquake.usgs.gov/fdsnws/event/1/query` | yes | yes (JSON) |
| `nemrc` | Nepal's own seismic catalogue — the National Centre for GNSS & Seismology | `seismonepal.gov.np/en/earthquakes/map` | yes | yes (embedded JSON) |
| `dhm_rainfall` | Station rainfall totals by district and basin | `dhm.gov.np/hydrology/getRainfallFilter` | yes | yes (JSON) |
| `dhm_rivers` | River gauges: water level against warning and danger thresholds | `dhm.gov.np/hydrology/river-watch` | yes | yes (JSON) |
| `hydrology_alerts` | Flood and river advisories as issued | `hydrology.gov.np/cm/api-public/alerts` | yes | yes (JSON) |
| `drr` | The incident register: deaths, missing, injured, houses, districts | `drrportal.gov.np/incidentreport/index_ajax` | yes | partly (HTML table) |
| `drr_highway` | Daily highway/road status bulletin | `drrportal.gov.np/publication` | yes | **no** (PDF) |
| `dor` | Department of Roads notices | `dor.gov.np/home/notices` | yes | **no** (HTML → PDF) |
| `community` | Reports and help requests from residents | in-app | no | yes |
| `demo` | Scripted scenario traffic, only in demo mode | in-app | no | yes |

What each source is answering **right now** is never stated in this document, because it
would be out of date the first time a feed hiccups. Ask the running system:

```bash
python scripts/check_sources.py      # raw probe of every adapter, no database involved
curl http://127.0.0.1:8000/api/sources -H "Authorization: Bearer <token>"
```

`GET /api/sources` returns, per source: `status` (`healthy` · `degraded` · `failing` ·
`never_fetched`), `freshness_state` (`fresh` · `recent` · `aging` · `stale` · `unknown`),
the timestamp of the newest *data* it saw, the time of the last successful *fetch*, when
it last failed and why, and the two timestamps that matter for trust — `official` and
`machine_readable`.

---

## What "degraded" means, concretely

Statuses are not decorations. Each one is set from what the last fetch actually did:

- **healthy** — fetched, parsed, and produced at least one usable record.
- **degraded** — reached and understood, but the answer is thinner than the source's
  purpose implies. `drr_highway` is degraded because the only routinely-updated official
  road-status product is a PDF: the adapter records the document's existence, title, date
  and link, and says in as many words that it could not structure it.
- **failing** — the fetch or the parse errored. The last error text is kept and shown.
- **never_fetched** — registered, not yet polled. `community` and `demo` stay here
  permanently: nothing polls them, they are written to by users. A `never_fetched` row is
  *not* a failure and is never counted in `sources_failing`.

`degraded` also covers "the site is up but changed shape" — a parser that finds zero
records in a source that normally yields hundreds reports it rather than silently
returning an empty list.

---

## Access notes worth knowing before debugging

These are the awkward realities discovered while building the adapters. They are the
first things to check when a source goes quiet.

**drrportal.gov.np** is a CodeIgniter application. HTTPS fails the TLS handshake, so the
adapter uses plain HTTP. The incident register is reached through
`/incidentreport/index_ajax` with a JSON filter as POST parameters, which returns an HTML
table fragment of 27 columns and roughly 63,000 historical rows. PHP notices are
*prepended to the response body* and have to be stripped before parsing. District and
incident-type vocabularies were scraped from the search form into
`shared/nepal_places.py` because the server rejects values it does not recognise.

**Nepal calendars.** DRR rows and some DHM timestamps arrive in Bikram Sambat. BS dates
are converted where the conversion is unambiguous; where it is not, the row is kept as an
observation with the original string and is **not** allowed to anchor an incident.

**seismonepal.gov.np** publishes an HTML map page whose event list is embedded as JSON.
It is the Nepali authority on Nepali earthquakes, so an event's `official_confirmation`
comes from here or from a matching USGS record — never from an operator's judgement.

**Department of Roads** publishes notices, not data. There is no road-status API. The
adapter emits observations from notice metadata that can be parsed and reports the rest as
unavailable. A related host, `ssrn.dor.gov.np`, was unreachable from the development
network and still needs re-testing from inside Nepal.

**Rate and politeness.** Refresh intervals are per source and are set to what the source
plausibly updates at: 5 minutes for USGS, 10 for NEMRC, 15 for river levels, 30 for
rainfall, 2 hours for the register, 6 hours for the bulletin, 24 hours for DoR notices. A
source that is behind is retried on the next tick, never hammered, and every attempt
writes an `ingestion_runs` row — success or failure.

---

## How a source row becomes an incident

```
source record ──▶ Observation (immutable, provenance attached, raw payload kept)
              ──▶ correlation: geo + time + hazard + admin + wording, scored
              ──▶ Incident  … the normalized thing the Response Center works on
```

Two records join when their score clears `MATCH_THRESHOLD = 0.72`. Between `0.50` and
`0.72` the pair is recorded as *ambiguous* and handed to the agent as a correlation
**proposal** with its provenance — a proposal never rewrites evidence state on its own; an
operator or a later official record has to accept it.

Reports from residents use their own footprint (`REPORT_RADIUS_KM` in
`geo/correlation.py`), because a person reports from where they are standing: shaking is
routinely described a hundred kilometres from an epicentre, while a fire is described from
next door. Using the observation radius for reports silently drops the exact signal this
product exists to catch.

---

## Adding a source

1. Write the adapter in `data_ingestion/sources/<code>.py`; return
   `NormalizedObservation` rows and nothing else. It must report a clear error rather
   than an empty list when it understands nothing.
2. Register a `SourceSpec` in `catalog.py` — including `official`, `machine_readable`,
   `refresh_interval_seconds`, `stale_after_seconds`, `access_notes` and `portal_url`,
   because the UI quotes those strings to explain itself.
3. Map the code to its class in `sources/__init__.py:ADAPTER_CLASSES`.
4. Run `python scripts/check_sources.py`, then restart the API. The first poll records
   the run, and `GET /api/sources` shows it. No database edit and no UI change is needed:
   source health, freshness and the map layers are driven by the catalogue.

Facilities, teams and contacts are a different kind of source — see
`docs/known-issues.md` for exactly how much of that exists today.
