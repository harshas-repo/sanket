# Known issues, gaps and deferred work

This is the honest list. It is written to be read by whoever picks this up next, and every
entry says what is wrong, what it costs, and how to see it for yourself. Nothing here is a
secret and nothing here is polished into "future work".

Verified against a live run on 2026-09-13, and reproducible with `python scripts/report_state.py`
(the pollers move these counts every few minutes, so they are a snapshot, not an expectation):
82 incidents from 15,720 observations, 8 of 8 real sources healthy on their newest run (both `drr`
feeds answered after a run of HTTP 500s — that is item 12 being intermittent, not item 12 being
fixed), 1,217 facilities in the resource catalogue, 70 API paths, and three green
gates: `scripts/smoke_http.py` (71 checks, 0 issues), `scripts/check_resources.py` (OK) and
`scripts/smoke_agent_guardrails.py` (57 checks, 0 issues). `scripts/check_sources.py` parses all 8
adapters against their live endpoints (OK), and `probe/poll_twice.py` passes over every polled source.
`scripts/smoke_demo.py` was deleted with the rehearsal surface, so nothing gates that path any more.

Items 73-80 are that second pass: a report that "the dashboard is static, polling has stopped", which
measurement disproved — the poller never stopped, four feeds were rewriting their own rows every tick
and a fifth signal could not be read at all. See that section before trusting a `records_updated` count
from before 2026-09-13: it counted bookkeeping, not new information.

A Gemini key is configured now, so the agent's live path has been walked: `scripts/scenario_melamchi.py`
passes 8 of 8 completion criteria against a real model, which is what found the four defects in
"The first run with a real key" below. Item 72 records what still cannot be run on demand — the free
tier's daily budget is spent, so `smoke_http.py`'s agent section is currently the fallback's, and says
so on its own output line (`mode=deterministic`).

---

## Removed on 2026-09-13: the map screen and the rehearsal screen

Requested as a deletion rather than a fix, so the boundary of it is worth writing down.

**What went.** `pages/MapPage.tsx`, `components/map/*` and `map/*` (the layer registry, the
overlays, the colour scale, the hook); `pages/rc/DemoPage.tsx`; the `/map` and `/demo` routes in
both surfaces and their nav entries; the community home page's map card; `api.map` and `api.demo`
from the client and their payload types in `api/types.ts`; `backend/app/api/demo.py` and its mount,
which is why the API is 69 paths rather than 74; `scripts/smoke_demo.py`, which could only exercise
those endpoints; the map and rehearsal strings, `LAYER_KEYS` and `VECTOR_LAYER_KEYS`; and the
`maplibre-gl` dependency. `DemoModeBanner` became `DataConditionBanner` — it also rendered the
offline banner and the data-age line, which every screen still needs, so only its rehearsal half
was removed.

**What was left, deliberately.** The `/api/map/*` GeoJSON feeds and the `/geo` static mount are a
data API that scripts and probes read, not a screen — `probe/map_surface.py` and
`probe/map_feed_vs_detail.py` still work against them. `backend/app/services/demo.py` stays and can
still be driven from a script. `DemoChip` is provenance labelling on records that exist in the
database, used by 18 surviving screens; the instruction not to touch those screens covers it. The
seeded demo accounts on the sign-in screen, `demo_warning` on the incident detail, the `DEMO_INJECT`
audit label, the `demo:read` / `demo:control` permission entries and the `X-Sanket-Mode` header
behind `ApiMeta.mode` all predate the screen and are not controls for arming a rehearsal.

**Cost.** Rows an earlier rehearsal created are still in the database and still carry the chip, with
no screen left that can arm or clear them — `probe/clear_demo_direct.py` clears them through the
service layer. No gate exercises the rehearsal path any more.

---

## Blocking a real deployment

**1. No migrations.** `db.init_db()` calls `create_all`, which builds missing tables and never
alters an existing one. Add a column and the running database silently lacks it until
something raises `no such column`. Every schema change this session needed `reset_db` + a full
re-ingest.
*Cost:* no upgrade path for a deployment that has accumulated real cases.
*Fix:* Alembic with an initial autogenerate baseline, and a data-backfill story for
`location_precision` and any new JSON keys.

**2. Authentication is demo-grade by design.** Tokens are HMAC-signed payloads keyed by
`SANKET_SECRET_KEY`; when it is unset the app starts anyway with a development default and
only logs a warning. Passwords are PBKDF2-SHA256, which is fine, but there is no refresh, no
revocation list, no session store, no lockout, and no rate limit on `/auth/login`.
*Cost:* this server must not face the internet as it stands.
*Fix:* fail startup when `SANKET_ENVIRONMENT=production` and the key is default; add token
expiry bookkeeping and a login throttle.

**3. SMS / IVR / Viber / WhatsApp are stubs.** `services/communication.py` composes the real
bilingual message and writes a delivery record, but nothing sends it. A resident whose phone
has no data cannot reach SANKET today.
*Cost:* the "two-way" promise currently holds only for a user with a browser.
*Fix:* a provider adapter behind the existing record, plus inbound parsing — the surface is
built for it, the transport is not.

**4. No test suite.** There are three end-to-end smoke walks (`smoke_slice`, `smoke_loop`,
`smoke_http`) that catch regressions across the whole stack, and zero unit tests. The
correlation and scoring engines are exactly the kind of code that should be
pinned by table-driven tests — right now a weight change is only caught if a smoke script
happens to exercise that path.
*Fix:* pytest over `geo/`, `scoring/`, `assistance` transitions and `evidence` promotion.

**5. Bikram Sambat dates are dropped, not converted.** DRR rows and some DHM timestamps arrive
in BS. Where the conversion is ambiguous the row stays an observation and cannot anchor an
incident, so official Nepali casualty records can be under-counted in the register-backed
incidents.
*Cost:* the numbers in the register-derived incidents are a floor, not the real figure.
*Fix:* a tested BS→AD converter and a re-ingest of the last 45 days.

---

## Real defects found and NOT yet fixed

**6. DRR register rows can outrank an earthquake.** In the live run the top-ranked incident was
"Animal Incidents — Bideha Municipality, Dhanusha" at **24.57**, above the M4.9 Mustang quake at
**22.75**. The register carries fatality and damage counts that an hour-old seismic event does
not yet have, and the score has no notion of *needs a response right now*.
*Cost:* the first thing an operator sees is not the thing that needs them.
*Fix:* weight recency and open-request pressure more heavily than cumulative toll, or band the
queue by "actionable now" versus "record of damage".

**7. `needs_review=True` with no reason.** The dashboard counts incidents needing review; at
least one is flagged with an empty `review_reason`, because `_review_reason()` returns `None`
for states it did not anticipate (e.g. official-but-thin) while `needs_review` is set elsewhere.
*Cost:* an operator is told to look and given nothing to look for.
*Fix:* every path that sets the flag must return a reason; assert it in `recompute`.

**8. Nepali free text under-rates a report.** The same event rated the *request* `critical` (the
structured fields are explicit) and the *report* `attention`, because the report rules read
English keywords. Without a model there is no Nepali keyword table broad enough.
*Cost:* community volume on a Nepali-language event looks calmer than it is.
*Fix:* a Nepali signal vocabulary in `shared/`, and the intent classifier in `agent/` once a
model is configured.

**9. Notification pile-up.** One test user accumulated 70 notifications from three smoke runs.
Every attention-worthy report pushes to the Response Center audience, and there is no rollup,
dedupe window or expiry.
*Cost:* the inbox becomes noise, which is how a real system stops being read.
*Fix:* collapse by `(kind, district, incident)` within a window, and prune read notifications
older than N days.

**10. Risk signals go invisible when their evidence ages out.** `/map/signals.geojson` now
reports `meta.unplaced` so an empty layer explains itself, but the underlying behaviour is still
wrong for an operator: after a rebuild only the *national* roll-up was `active=1`, and it is the
one row that genuinely has no coordinates - so the three district signals that do have a point had
been switched off. All four also carry `province=None`.
*Cost:* the signal layer looks empty on a screen that is meant to be a early-warning surface.
*Fix:* a rebuild must not deactivate a district signal whose observations are merely older than
the last tick - compare against the freshness bands already in `shared/`, and derive `province`
from the same boundary index that gives the centroid.

**10b. Resource seeding is throttled by its upstream, and one kind has no data.** Overpass
answers `HTTP 429` to back-to-back nationwide bbox queries, so `seed_from_overpass` sleeps
20 s between facility kinds and retries 429/503/504 twice. A full 7-kind seed therefore takes
roughly two minutes and cannot be looped. Separately, `amenity=shelter` matched **one** facility
in all of Nepal: OSM simply does not tag emergency shelters here, so "nearest shelter" is often
an empty answer rather than a wrong one.
*Fix:* a Nepal-specific shelter query (ward offices / schools used as shelters) plus the
`data_ingestion/static_geo.py` list the spec calls for, seeded as `provenance='operator'` only
when a source document names them.

**11. Hydrology alerts carry no location.** The feed's alert bodies name districts in prose that
is not always parsed, so flood advisories land as `unlocated` observations and cannot raise a
district signal even when they name one.
*Fix:* district matching over `shared/nepal_places.py` against alert titles and bodies.

**12. `drr_highway` is degraded.** It answers `malformed: HTTP 500` on the publication listing
most of the time. The bulletin is a PDF anyway, so the fix is upstream of parsing: the listing
needs a fallback URL and a retry that does not spam.
*Intermittent, as stated:* on 2026-09-13 both DRR feeds ran clean (`drr` 60 items, `drr_highway` 2
updated), so a green `report_state.py` is not a fix and a red one is not proof of a code fault. Run
`python scripts/check_sources.py` twice before believing either reading.

---

## Incomplete by scope, not by oversight

**13. The resource catalogue has no detail route and no capacity.** ~1,190 real facilities are
seeded from OpenStreetMap and operator-editable, `match_resources` now returns actual hospitals
and police posts, and availability decays to `unknown` after 12 h. Still missing: `GET
/rc/resources/{resource_id}` (the list serializer is all there is, so a detail panel has nothing
to open), bed/vehicle capacity beyond a free-text `capacity_note`, and a real unit roster -
assignment still names a plausible unit from a built-in list rather than one from a roster.

**14. The agent is built, but only its deterministic half has ever run.** `/api/agent` serves
status, tools, investigate, investigations, chat and classify; 25 read-only tools in
`agent/tools/read.py` wrap the services that already exist (none of them re-implements a query),
4 language tools in `agent/tools/language.py` need no model, and every run is persisted to
`agent_investigations` with its provenance inherited from what it investigated, so a rehearsal run
cannot outlive the rehearsal. With no credentials the answer is assembled by retrieval and says so.
What has never executed: **a model call**. `mode="strands"`, the tool-calling loop, and the
`rejected_unverified_numbers` guardrail are untested code paths - `check_numbers` has never had a
sentence to reject. The first run with an API key must watch for the model being handed tools it
can loop on, and for wording that passes the number check while still reading a correlation as a
cause. Two smaller open calls: `POST /agent/chat` accepts a `language` field and ignores it (the
reply follows the question's script, then the saved preference - so a resident whose preference is
Nepali gets Nepali back even when they ask in English, which wants a product decision), and
`GET /rc/resources/{id}` does not exist so no agent tool can describe one facility in detail.

**15. Demo has no auto-advance and no UI.** Three scenarios replay through the real services
(`/api/demo`: scenarios, status, arm, advance, disarm) and a rehearsal leaves nothing behind. But
nothing fires a step on a wall-clock timer by itself - the client calls `/demo/advance`, so a
rehearsal needs the Response Center screen that is not built yet. Arming also **pauses live
ingestion** for as long as it is armed, which is deliberate (see the note under "Fixed") but means
a demo left armed overnight leaves the sources stale by morning.

**16. The frontend is a shell with no screens in it yet.** What exists and builds clean
(`npm run build`): the API client, the response types verified against live shapes, EN/NE i18n,
the auth context, the component set (chips, state panels), the app shell and sign-in. What does
not exist: every product screen. The router declares 26 paths and 23 of them render
`NotBuilt`, a component that says in words "this screen is not built yet" - deliberately, so
nobody reads an unbuilt panel as "no incidents here". Nothing in the map, the Response Center or
the community flow has been drawn once.

**17. No offline queue on the client side.** The server endpoint exists
(`POST /community/offline/flush`, which replays queued reports and requests and marks them
`submitted_offline`), and it is what a poor-signal client would use. Nothing implements the
local storage and replay UI.

**18. Voice input is not built.** `shared/` handles bilingual text end to end, and the report
schema carries `language`, so the server is ready; capture and on-device speech are frontend work.
The strings and the `bcp47` tag the recogniser needs are already in place
(`ne-NP` / `en-US`), so this is one component away, not a design question.

**19. Every incident currently lands on the strongest evidence label.** All 69 real incidents in
the working database read `officially_confirmed`, none `officially_reported`. The ladder is not
broken: `incidents.py` treats an observation whose kind is `official_incident` / `official_alert` /
`earthquake` as authoritative, and the DRR feed is the government's own incident register, so
"the state recorded this" really is confirmation of the event. The cost is that a reader cannot
distinguish "the district office logged one snake bite" from "two agencies and a seismic network
agree", and `/api/incidents` shows one label for both. Reproduce with `scripts/report_state.py`
(incidents by evidence state). The open question for the next pass: keep confirmation about *the
event happening* and add a separate field for *how much of its detail is corroborated*, rather
than moving the label down the ladder.

**20. The smoke walks leave test records behind.** `community_reports` (31) and
`assistance_requests` (18) in the working database are rows the HTTP smoke filed as ram.prasad,
correctly labelled by their own provenance but never reaped. They are real rows about a test
person, so a demo or a screenshot picks them up. Either the smoke should delete what it made, the
way `smoke_demo.py` reaps its rehearsal, or the seed script should be able to tell a tester
account's history from a resident's.

---

## Housekeeping

**21. `roles` table is dead.** It is created and never written to or read from — permissions live
in `deps.PERMISSIONS` keyed by rank. Delete the table or use it; a schema that lies about where
authorisation lives is worse than no schema.

**22. `backend/app/repositories/` is empty.** The spec's layering put queries there; they are in
the services today and that is working. Either populate it as the queries grow or delete the
directory.

**23. Stray directories in the repo root.** `probe/` holds the endpoint-discovery scripts from
the source-hunting phase (superseded by `scripts/check_sources.py`, though `api_shapes.py`,
`api_bodies.py`, `layer_limits.py` and `agent_read_aloud.py` are live tooling for the frontend
contract); `database/` and `Documents/sanket/backend/app/services/` are empty artifacts of a
mistyped path. The last two are safe to delete.

**24. `uvicorn --reload` is unreliable here.** On Windows the WatchFiles reloader detected a
change, logged `Reloading...`, and left no server listening — the smoke run then failed against a
dead port. Development should restart the process explicitly until that is understood. Finding the
listener needs `netstat -ano | Select-String ":8000"`: in this sandbox `Get-NetTCPConnection` and
`Get-CimInstance Win32_Process` both answer "nothing running" about a server that is replying 200.

**25. The database is shared between the API process and the smoke scripts.** Both open
`data/sanket.db`; WAL keeps it working, but `reset_db.py` while a server is running will fight it.
Stop the server before resetting.

**26. Devanagari in the Windows console, and UTF-16 in the log files.** `*>` redirection and
cp1252 mangle Nepali text in terminal output, and every `logs/*.log` written by a PowerShell
redirect is UTF-16 - so `io.open(..., encoding="utf-8")` fails on the file that holds the API
contract. The stored data and API responses are correct; read the logs with `encoding="utf-16"`
or write them with `Out-File -Encoding utf8`, and verify Nepali with `python -X utf8` rather than
trusting what the console shows.

**26b. No version control.** `git` is not on this machine's PATH, so nothing built here has ever
been committed: no diff to review, no way to revert a change that breaks something, and the
"fixed during this build" list below is the only record of what changed. Initialising a repository
is the first thing to do on the next pass.

**26c. A workspace-wide text search can report zero matches for text that is there.** Searching the
root for `updated_label` returned "Found 0 matches"; the same pattern scoped to `backend` or to
`frontend/src/api` returns several, including the field on `Incident` itself. *Cost:* a negative
result reads as proof that something does not exist, and that is how an earlier draft of item 40
below ended up claiming a server field was nowhere in the codebase when three files define it.
*Fix:* treat "0 matches" as unverified until a scoped search or an open file agrees, and never let
one justify deleting or documenting an absence.

---

## Found while building the frontend, not yet fixed

These turned up while wiring the client to the API, and every one of them is a place where the
two halves of the system agree in code but not in intent.

**27. The backend writes screen routes into its own responses.** `services/community.py:194`
emits `link=/response-center/reports/{id}`, `services/assistance.py` emits
`/requests/{ref_code}` and `/response-center/requests/{ref_code}`, and the source catalogue
publishes `url: "/community/report"`. `App.tsx` therefore has to define exactly those paths.
*Cost:* a route renamed on either side breaks silently, and no gate can catch it - the smoke suite
does not know the React route table. Links a user copies out of an SMS are the reason the routes
exist at all, so this cannot be fixed by moving them behind a client-side builder without also
building a redirect table.
*Fix:* emit `{kind, id}` and let each surface compose its own URL, keeping the current paths as
inbound redirects for messages already sent.

**28. A misspelled request field vanishes instead of failing.** Every request model inherits
`_Strict` in `backend/app/schemas/__init__.py`, and its `model_config` sets `extra="ignore"`.
*Cost:* a report posted with `location_text` typed as `locationTest` is stored with no location,
with a 201 and no warning - the failure appears later as an unplaced incident nobody can explain.
This is the single most dangerous line found tonight, because everything about the frontend was
written against a dump of these schemas.
*Fix:* `extra="forbid"` outside production (a 422 naming the unexpected key), or a
`model_validator` that reports unknown keys in the response while still accepting the request.

**29. `available_actions` means two different things.** Incident detail returns
`{action, label, method, path, permission}` per entry; request detail
(`api/response_center.py:155`) returns `{action, target}` with compound values like
`"status:reviewing"`. *Cost:* the action queue and the incident screen cannot share a component,
and the request shape carries no permission - so a screen cannot grey out what the API would
refuse without asking the server for the user's list again.
*Fix:* one shape for both, `label` and `permission` included, with `target` kept for status moves.

**30. A notification that points at a report cannot be opened.** The link is real, the route is
real, and there is no `GET /api/rc/reports/{report_id}` - only the list endpoint, which filters by
`district` or `incident_id`, never by report id. *Cost:* the report screen must page through
`/rc/reports?limit=500` and find one row by id, which is wrong the moment the database is a
real size. *Fix:* the single-report GET behind `reports:read`.

**31. Error sentences stay English on a Nepali screen.** `ApiError.detail` renders whatever the
server said, which is always English, and the client's own network/timeout sentences in
`api/client.ts` are hardcoded English. *Cost:* contradicts the rule stated at the top of
`i18n/strings.ts` - a resident whose report failed to send sees a screen that is half one language
and half the other, in the moment where that matters most. *Fix:* the client's own messages go
through `t()`; server details stay English but get labelled as the machine's sentence.

**32. The token lives in localStorage.** Written into `api/client.ts:118` where it is used.
Combined with item 2 - HMAC tokens, no expiry bookkeeping, no revocation list - one XSS buys an
attacker a coordinator session that cannot be cut off. *Fix:* httpOnly cookie plus a CSRF token,
and the session store item 2 asks for.

**33. An entity's audit trail does not need `audit:read`.** `GET /rc/audit` requires
`audit:read` (operator and coordinator); `GET /rc/audit/{entity_type}/{entity_id}` requires
`incidents:read`, which analysts have. *Cost:* the boundary `deps.PERMISSIONS` draws is not the
boundary the API enforces, and "who edited this" is exactly the kind of thing a supervisory role
is meant to keep to itself. *Fix:* decide which reading is intended and make the second route
agree with the first.

**34. `POST /api/auth/register` has no screen.** The endpoint works and is exercised by the smoke
walks; nothing in `frontend/src` calls it except the client definition. *Cost:* a real resident
cannot join SANKET at all - every community login in use is a demo account. *Fix:* belongs with
the community account screen, which is where name, phone, home district and language are asked for.

---

## Found while building the map, not yet fixed

The map is the spec's centrepiece (§15-17, §44-46), so these are the parts of it that are true on
screen but not yet finished, written down rather than quietly shipped.

**35. The basemap needs the internet, in the exact scenario where there is none.** `/api/map/layers`
publishes one basemap: OSM raster tiles, with an `offline` note the server already states. There is
no bundled tileset. *Cost:* during an outage the map draws markers, labels and the district outline
of Nepal on a flat dark ground with no roads, no settlements and no sense of distance - usable for
"where are the events" and poor for "how far is the nearest road". The mitigation that does exist
is real: `/geo/*.geojson` boundary polygons are served by this same server, so the shape of the
country and every district border still render with the tiles down. *Fix:* ship a Nepal-only
basemap (a bounded raster or a generalized vector tileset) alongside the boundary files and let
`/map/layers` publish both, defaulting to whichever answers.

**36. `/api/map/layers` is public; every URL inside it is not.** Verified anonymously:
`/api/map/layers` answers 200 JSON, while `/api/map/incidents.geojson`, `/signals.geojson` and
`/resources.geojson` all answer 401 (`probe/anonymous_surface.py`). *Cost:* the published map
contract is consumable only by a signed-in client, so no external dashboard, no embedded iframe on
a public information page, and no offline tile-caching job can take these URLs as given. The
frontend never notices because its client attaches the bearer token to everything. *Fix:* either
make the three geojson feeds anonymous reads of the *public projection* they already gate on
(`incidents:read_public`), or stop calling the catalogue public and move it behind the same
token - the current split is the worst of both, since it advertises URLs that refuse you.

**37. There is no dark command-centre theme.** Spec §45 asks for one; `tokens.css` ships a single
light palette and the map's `MAP_GROUND` is dark because a map canvas needs contrast, not because
the console has a night mode. *Cost:* a wall display in an operations room shows a light UI. This
was not fixed by inverting CSS, and it should not be: the urgency and hazard colours come from the
same custom properties as the surface, so inverting the stylesheet inverts or dulls the marker
colours and makes the map lie about severity. *Fix:* a second published basemap in
`/api/map/layers` plus a dark token set that re-declares only surfaces and text, with the status
palette copied across unchanged and checked pixel-for-pixel.

**38. Server strings stay English on a Nepali screen.** `/api/map/layers` supplies each overlay's
`label`, `note` and `provenance`, plus the legend text and each boundary file's `provenance`; the
client translates only the keys it owns. *Cost:* a Nepali screen shows a Nepali sidebar next to a
layer list that says "Active incidents - official and derived events". Same root cause as item 31,
different code, and it is wider than the map: `humanize_age()` in `shared/timeutils.py` writes the
relative-time labels that `services/response_center.py:296`, `services/community.py:368` and
`services/ingestion.py:327` all put straight into responses, so `updated_label` reads "1 min ago"
in English on a Nepali incident and a Nepali community feed. A request's `status_label` *is*
Nepali ("पाइयो"), so the same payload mixes both languages in adjacent rows and nobody can tell
which fields are safe to display unedited. *Fix:* the catalogue publishes `label_key`/`note_key`
and the client owns the words; `humanize_age` takes a language and the response states which one
it answered in.

**39. Nothing is drawn as text inside the canvas.** The style declares no `glyphs` URL on purpose,
because MapLibre renders symbol text from a glyph server that would carry Latin only, while every
label in this product can be Nepali. So all map text - titles, statuses, the legend - is DOM
(`FeatureDetail.tsx`, `MapControls.tsx`). *Cost:* cluster counts appear on hover instead of on the
marker, permanent labels next to features are not possible, and a very dense zoom level shows dots
with no words at all until someone clicks. *Fix:* ship a Noto Sans Devanagari + Latin glyph range
with the app and add `glyphs` to the style, then move only the cluster count into the canvas.

**40. The map's feed drops the two labels every other incident payload sends.** An `Incident` in a
detail response carries server-computed `updated_label` ("1 min ago") and `event_time_label`
("yesterday") next to the raw `last_updated_at`/`event_time`; `/api/map/incidents.geojson` sends
only the raw stamps (`probe/map_feed_vs_detail.py` prints both side by side). *Cost:*
`FeatureDetail.tsx:75` builds its own `Intl.DateTimeFormat` and the same incident reads "1 min ago"
on the incident screen and "Sep 12, 2026, 8:57 PM" on the map - two different answers to "how old is
this", which is the question the freshness rules exist to make unmissable. It is also the only date
formatter in `frontend/src` today, so the Response Center screens have nothing to share it with yet.
*Fix:* add both labels to the map feature properties - they come from the same serializer - and
drop the inline formatter, then make one `utils/time.ts` for the dates no payload labels.

**41. `urgency: critical` sits on a `score_band: moderate` marker.** The top incident on the live
map right now (`INC-20260912-0013-2788`, 1 death, 5 affected, `impact_score` 31.21) is drawn in
red because urgency is critical, and drawn small because its impact score is moderate. Both fields
are honest and neither is wrong - §15 colours by urgency and §16 sizes by impact. *Cost:* the two
encodings disagree out loud, and a dispatcher reading size as importance will rank this below a
larger yellow dot. Whether that is the right trade-off is a design decision being made by
accident. *Fix:* decide it - either size the marker by urgency too, or keep the split and put the
impact score as text in the hover line so the disagreement is explained where it is seen.

**42. The map's pixels and pointer behaviour are unverified in this environment.** Every data path
the map depends on was confirmed twice - through `smoke_http.py` and through a real browser session
that logged in, mounted the map, and saw all six feeds, the published boundary files and six OSM
tiles return 200 with an entirely empty console. What could not be observed: marker colour and size
on screen, hover following the cursor, click-to-detail, cluster expansion, and the ≤1100px
single-column collapse. The browser tool reported `NATIVE_BROWSER_VIEWPORT_UNAVAILABLE` (window
minimized, page `hidden`), so WebGL never drew a frame. This is an environment limit, not a known
defect - but it means nobody has looked at the map yet. *Fix:* twenty minutes in a real browser,
working down the §15 colour legend and the §17 hover contents.

---

## Found while building the Response Center, not yet fixed

**43. Action buttons are the server's English, except the status moves.** An incident's
`available_actions` are built in `services/response_center.py:515-533` with the label written
there as prose ("Attach a community report as evidence", "Send for official verification"), and
only `set_status` is generic enough to rebuild client-side from its `target` - which is what
`Actions.tsx:90-93` does. *Cost:* a Nepali console shows a Nepali header above an English action
bar, and the one translated label in the list proves the others could have been. Same root cause
as item 38. *Fix:* the server publishes `label_key` next to `label` and the client owns the
sentence; the `label` stays as the fallback for a key nobody mapped.

**44. The review queue has no door out that an operator can press.** `/api/rc/incidents/{id}/review`
is a live, working endpoint, but `available_actions()` never lists it, so the console renders no
button for it. `needs_review` is set True by the scorer (`services/incidents.py:440`) and by
"Send for official verification", and cleared only by that unsurfaced endpoint or by the next
recompute deciding the conditions have changed. *Cost:* an incident sits in the "needs review"
bucket of the queue and the dashboard count until it is archived or merged - an operator who has
just verified it by hand cannot get it out of the list, which teaches dispatchers to ignore the
queue. *Fix:* publish `review` in the action surface with the flag as a field, or give `verify`
brightness to clear it and say so in the label.

**45. The client already has a form for an action that can never arrive.** `INCIDENT_FIELDS.review`
(`Actions.tsx:43`) and `if (tail === "review") out.needs_review = values.needs_review === "on"` are
dead code while item 44 stands, and they are wrong-shaped: an unchecked checkbox sends
`needs_review: false`, so the day the action is published, the form labelled "reason" silently
clears the flag it was never asked to clear. *Fix:* when wiring 44, make it a checkbox with an
explicit default from `incident.needs_review`, not an absent field.

**46. A record cannot be opened on the map.** The spec makes the map the primary surface, but
every path into it is a sidebar link: `MapPage` reads no query parameters, so there is nothing to
link *to*. The `open_on_map` string is written and deliberately unused. *Cost:* a dispatcher who
wants to see whether six incidents are one landslide or six must eyeball the district column.
*Fix:* `/map?incident=<id>` (and `?report=`) must fly to the coordinate, select the feature and
open the detail panel - the pieces all exist inside `MapPage`, they are just not addressable.

**47. Nepali dates are still Gregorian dates in Latin letters.** `utils/time.ts` formats through
`Intl` with the reader's `ne-NP` tag, and the runtime answers "Sep 12, 2026" - an English month
name inside a Nepali sentence - while the unit abbreviations this build introduced (`5 h 27 min`,
`40 min`) are Latin-only by construction. *Cost:* the console's one date column is half-translated,
and BS is not even attempted (see item 5, which is the server-side version of the same failure).
*Fix:* `calendar: 'nepali'` is available in modern ICU but is not what most operators expect from a
control room, so decide it - Devanagari numerals and Gregorian months, or a real BS conversion.

**48. `humanize_age(None)` answers "no timestamp".** `shared/timeutils.py:97-101` returns that
English sentence rather than `None`, so `age`, `updated_label`, `availability_age` and
`last_change_label` can carry a piece of system prose into a slot the UI treats as a timestamp, on
a Nepali screen, in the same string list as "2 min ago". `api/incidents.py:210-222` already works
around it by nulling the label before the call; the other eight call sites do not. *Cost:* a
missing stamp reads as a fact about the record instead of a hole in the data. *Fix:* return `None`
and let each caller choose its own "unknown", which is what the two labels in the incident payload
already do.

---

## Found while building the community surface, not yet fixed

**49. A help request nobody counted is filed as one person.** `AssistanceRequestIn.people_count` is
`int = Field(default=1, ge=1, le=100000)` (`schemas/__init__.py:99`), while the report schema above
it gets the same field right — `int | None = Field(default=None, ...)` (`:70`). `assistance.create()`
then repeats the assumption twice, at `services/assistance.py:167` (into `classify_request()`, so it
reaches the urgency, not just the display) and at `:195` (`max(1, int(people_count or 1))`). The
phone agrees with it: `HelpPage.tsx:54` opens the field at `1`, and `people_count: people ?? 1` at
`:74` turns a cleared box back into a stated count. *Cost:* a rescuer cannot tell "there is one of
us" from "nobody was asked", which is §20's rule about not inventing facts about people, and every
dashboard count of people-in-need includes the invented ones. *Fix:* `int | None` on the request
schema with the same `ge=1` bound for a value that *is* stated, no `or 1` in the service, and
"not stated" wherever the count is rendered.

**50. Two vocabularies share `location_precision`, and the published legend describes neither of
them cleanly.** The column is documented (`models/core.py:195-196`) and published as a legend
(`api/incidents.py:398-405`) as `source_coordinate | named_place | local_level | district_centroid |
user_shared | unlocated`. Four writers feed it: the creation default `source_coordinate`
(`services/incidents.py:211-212`), `"user_shared"` on an incident built from a help request
(`services/response_center.py:769`), `district_centroid`/`unlocated` for signal-derived observations
(`services/signals.py:137-141`, reaching the incident at `:320`), and - the leak -
`report.location_confidence` written into the derived observation at `services/incidents.py:793`,
whose family is `high|medium|low|text_only|inferred_home_district|unknown`
(`services/assistance.py:86-117`). `probe/precision_vocab.py` against the live database: 40 incidents
read `district_centroid`, 17 `unlocated`, 10 `local_level`, 2 `source_coordinate`; 55 observations
carry `high` or `inferred_home_district` inside `normalized_data.location_precision`; none has
`named_place` or `user_shared`. *Cost:* an incident first placed by a community report ends up with a
value no rule knows. The map's `opacity_rule` matches only the literal `district_centroid`
(`api/incidents.py:248`), and so do the review reason "Location is a district centroid, not a
surveyed coordinate" (`incidents.py:611`) and its five-report trigger (`:601`) - which is exactly the
condition a report located only by its sender's home district produces, arriving instead as
`inferred_home_district`. The platform's softest location evidence is therefore drawn and filed as if
it carried no softness, and a reader building a legend from the API's own list will meet codes that
are not on it. *Fix:* one vocabulary - map confidence onto precision at `:793`
(`inferred_home_district`, or any confidence with no coordinate, is `district_centroid`), keep the
confidence in its own field, which the community screens now render (`LOCATION_CONFIDENCE_KEYS`), and
generate the published legend from the enum so it cannot drift from what the code writes.

**51. The one list a resident reads for "what has happened to me" is still labelled with internal
codes.** `assistance.timeline(..., victim_view=True)` emits `kind` values (`status_change`,
`message`, …) with no published label list, so `MyRequestPage.tsx:62-65` prints them small and
monospaced rather than inventing words for them. The states either side of a `status_change` *are*
translated at `:74`. *Cost:* the timeline's own heading is the one line on the screen a Nepali
reader has to guess at, on the surface the spec says is for someone with a cracked phone in the
rain. *Fix:* the server owns this vocabulary and already composes `next_step` for the same audience —
publish `kind_label` beside `kind`, or map the handful of codes client-side and echo unknowns.

**52. `MY REQUESTS` has no filter, no paging, and a ceiling of fifty.**
`GET /api/community/requests` (`api/community.py:216-233`) takes no parameter whatsoever — own cases,
newest first, `.limit(50)`, open and closed in one list. *Cost:* the person on their sixty-first
message cannot see the case a team is currently working, and the screen has to explain in prose why
a cancelled request appears under a heading about help (`MinePage.tsx:154-156`). *Fix:* `?status=`
and `?before=<created_at>`, both applied after the `user_id` scoping that the docstring already
argues for, so widening the query never widens whose cases are in it.

**53. A dictated rescue plea is indistinguishable from a typed one.** `ReportIn` carries
`voice_transcript` and the report form sends it; `AssistanceRequestIn` has no such field, so the
microphone on the help form produces a description with no record of how it was made
(`HelpPage.tsx:142-145`). *Cost:* §38 exists because some people cannot type while running, and the
one fact that tells a dispatcher the sender was speaking hands-free is thrown away at the boundary.
*Fix:* one optional boolean on the request schema, set by the same control the report path already
uses.

**54. The assistant keeps no thread.** `ChatIn.history` is accepted by `POST /api/agent/chat` and
`answer_question()` never reads it, so a follow-up is answered from the records and not from what
was just said (`AskPage.tsx:10-14`, which is why that screen has no conversation view). *Cost:*
"is it still safe in [the place named in the previous answer]" cannot be answered, and a resident who
asks twice gets two unconnected replies — which is the pattern that makes people phone a relative
instead. *Fix:* either feed the last few turns in, or delete `history` from the schema so the next
person does not build a chat UI on a field that goes nowhere.

**55. A district named in the question is not the district the answer is about.**
`agent/workflows/community.py:100` is `area = district or (user.home_district if user else None)`:
the only thing that moves the lookup is the free-text box on the ask screen
(`AskPage.tsx:120-126`, whose placeholder is the account's home district). Nothing parses a district
out of the question text. *Cost:* "flooding in Siraha?" from a caller registered in Kathmandu
answers about Kathmandu, from records the reader has no way to see are the wrong ones. *Fix:* match
the question against the district list `Boundaries.district_names()` already holds and, when it
disagrees with the profile, ask which one the person meant — §20's rule about not inventing a
location applies to a question's subject too.

**56. Home district is free text because no endpoint publishes the list.**
`Boundaries.district_names()` exists and is served by nothing, so both the account form and the ask
form take typed text (`AccountPage.tsx:17-19`, where the note under the field says what a misspelling
costs). *Cost:* the profile district is what `resolve_location()` falls back to when a request has no
coordinate and no place in its text (`services/assistance.py:114-117`), so a typo made once in
settings becomes an `inferred_home_district` position on a rescue request with nothing on screen to
trace it back.

---

## Found while building the last Response Center screens, not yet fixed

**57. An omitted field on the verify form confirms a report and logs it as rejected.**
`VerifyIn.state: str = Field(default="officially_confirmed", max_length=40)`
(`schemas/__init__.py:163`) writes straight into `verification_status` with no validation
(`services/community.py`: `report.verification_status = status`), and that value is not a member of
`VerificationStatus` (`shared/enums.py`: pending, verified, rejected, duplicate, conflicting) — it
belongs to the *evidence* vocabulary. Worse, the same function chooses the audit action as
`"verify" if status == "verified" else "report_rejected"`, so the default path files an operator as
having **rejected** the report it just confirmed. The schema is shared by three routes and only
`/reports/{id}/verify` reads `state`: `/incidents/{id}/verify` and
`/incidents/{id}/request-verification` (`api/response_center.py:369-393`) take it and ignore it.
*Cost:* `ReportDetailPage` sends the field explicitly and is safe; every other client is one omitted
key away inverting a report's standing and its own audit trail. *Fix:* `Literal[VerificationStatus]`
with no default on a dedicated `VerifyReportIn`, leave the two incident routes with the `reason`-only
shape they actually use, and derive the audit action from a transition table rather than one string
comparison.

**58. The reports list cannot be filtered by verification state.** `GET /api/rc/reports` takes
district, incident and a duplicates flag — not `verification_status` — so "show me everything still
unverified" is a dashboard number and not a view (`ReportsPage.tsx:1-13`, which says so rather than
filtering the hundred rows it happened to receive). *Cost:* an operator works down page after page
to find messages nobody has checked, which is the queue that actually decides whether a report ever
becomes evidence. *Fix:* one server-side `state=` filter on the same query that already filters by
district.

**59. The activity feed and the audit log are one query behind two contracts.**
`activity_feed()` (`services/response_center.py:866-897`) builds every row from the same audit
events, but `/rc/activity` accepts **only** `limit` (≤200) while `/rc/audit` takes `entity_type`,
`entity_id`, `actor_kind` and `limit` (≤500). `ActivityPage` states the relationship
(`activity_is_audit`) instead of presenting them as two feeds. *Cost:* the more readable of the two
is the one that cannot be filtered, so "what did this operator do to this incident" means switching
screens and losing the summary sentences. *Fix:* give `/rc/activity` the audit filters, or retire it
and let the audit screen render `summary`.

**60. `/rc/audit` ignores `entity_id` unless `entity_type` arrives with it, and never says so.**
The service applies the id only within a type, so a request with an id and no type answers 200 with
the unfiltered log. *Cost:* a search for a reference code with no entity selected looks like a result
set, and "nothing matches this id" is indistinguishable from "the filter did not apply". `AuditPage`
warns in a `role="note"` band (`audit_entity_id_hint`) precisely because a 200 cannot be argued with
on screen. *Fix:* 400 when `entity_id` comes alone, or honour it across types — the column is a
string and the ids and ref codes never overlap by shape.

**61. Two things the agent contract carries and never fills.** `agent_investigations.tool_calls` is
a stored JSON column (`models/core.py:482`) that `services/agent.py:65` fills from
`outcome.get("tool_calls") or []`, and no workflow under `app/agent/` ever puts that key in an
outcome — so every run stores `[]` and every response publishes it. Separately,
`GET /api/agent/investigations` requires an `incident_id` (`api/agent.py:74-77`), which is the only
listing there is. *Cost:* the spec asks an answer to say which tools produced it, and the tool
*inventory* is published (`/api/agent/tools`), so the empty column reads as a report of zero tool
calls rather than of a field nobody writes; and because the listing needs an incident, nothing in the
console can show what the assistant told a resident, whose questions are the runs most likely to need
reviewing. `AssistantPage` prints the count only when it is non-empty, which is the honest rendering
but not a fix. *Fix:* have the runner append each tool call as it happens, and make `incident_id`
optional with the `subject_type` the stored row already carries.

**62. `/demo/status` never says that arming pauses live ingestion.** `scheduler.py:74-79` returns
`{"ran": False, "paused": "demo mode is armed"}` on every tick while a rehearsal is armed — the
pause is correct and deliberate — but `status()` (`services/demo.py:784-820`) has no field for it, so
the screen that arms the rehearsal and the screen that reports freshness do not know about each
other. `services/state.py:39 is_demo()` is the one-line helper that would have connected them and is
called by nothing; the guard was written inline instead. *Cost:* an operator arms a scenario, opens
Data sources twenty minutes later, and finds every feed going stale with nothing linking it to the
button they pressed — on a platform whose whole claim is knowing where its data came from.
*Fix:* put `ingestion_paused` on the status payload and let the sources page render the reason from
it. The Demo screen says the same thing in prose (`demo_pauses_ingestion`) for now, which is a
sentence and not a contract.

**63. Console routes are guarded by the navigation, not by the routes.** `AppShell.tsx:44` filters
links by permission and `App.tsx` sends a resident away from `/response-center/*` entirely, but every
console route mounts for every staff account — an analyst who reaches `/response-center/audit` by
bookmark gets a screen that loads and then reports the server's 403. *Cost:* a role boundary reads as
a platform failure, and the three screens an analyst cannot see (`audit`, `demo`, plus
resources/sources for a different account) are discovered by typing. Nothing leaks: the server is what
enforces. *Fix:* one `<RequirePermission>` wrapper fed by the `permission` field `RC_NAV` already
carries, so the nav and the route cannot drift.

---

## Found by rendering the console against a live server

**64. The Data sources "Notes" column is the adapter's engineering documentation.**
`access_notes` on each catalog entry is written for whoever maintains the adapter — NEMRC's says
"No public JSON endpoint. The map page embeds `const earthquakes = [...]` with BS + AD dates, UTC
time, ML magnitude, epicentre and survey" (`data_ingestion/sources/catalog.py:68-72`), and USGS's
says "Used as a secondary/cross-validation seismic source and as fallback when NEMRC is
unreachable" (`:47-50`). `services/ingestion.py:64` copies it verbatim into `source.notes`, `:328`
puts it on the payload, and the sources table renders it under a column headed "Notes" in the
reader's own language. *Cost:* an operator scanning which feeds are trustworthy gets backticked
JavaScript identifiers, English prose on a Nepali interface, and the word "fallback" describing a
chain nobody on shift can see — the one place a real judgement about a source could be made is
filled with maintenance trivia. The facts a person needs from that row are already there in other
columns (`source_type`, `machine_readable`, freshness, failures). *Fix:* either label the column for
what it is ("Access notes — for whoever maintains the feed") or add a second, operator-facing note
field to the spec, since the current one was never written for them.

**65. The audit diff prints database words, and its own comment promises otherwise.**
`Delta` (`frontend/src/components/rc/parts.tsx:321-335`) renders every changed field as
`key=JSON.stringify(value)` in mono, so an audit row reads
`status=in_progress; evidence_state=officially_confirmed; updated_at=2026-09-12T14:57:24Z`. The
docstring one line above it says `{"status": "in_progress"}` becomes `status: In progress` — nothing
in the component translates a key or a value, so the file documents a behaviour that does not exist.
*Cost:* the audit trail is what a coordinator reads after the fact to find out who changed what, and
it is legible only to someone who already knows the column names and the enum spellings; every
other console surface maps these same values through `i18n/strings.ts`, so the screen that is
supposed to be the permanent record is the one that assumes the reader wrote the schema. *Fix:*
implement the promised mapping (the field and enum vocabularies are all published), or say plainly
that this column is raw; and check the payloads where `previous`/`new` are whole-record snapshots,
since those rows are dozens of keys wide.

**66. A closed case still shows a running clock on the console.**
`services/assistance.py:811` sets `"minutes_remaining": None if acknowledged else ...`, so an
acknowledged case loses its countdown while keeping `due_at`, and
`frontend/src/pages/rc/RequestDetailPage.tsx:89-107` renders the SLA block whenever `due_at` exists
— it never asks whether the case is over. *Cost:* a Resolved request still reads "Deadline: 12 Sep
2026, 20:57" as though something were pending, on the same platform whose resident screen was fixed
this week to stop saying exactly that to the person who asked for help (see the community rendering
group below), so the two sides of one case disagree about whether it has finished. *Fix:* share one
"is this case terminal" test between the two screens, or stop sending `due_at` from a server that
already knows the status.

**67. The assistant answers in codes the platform has names for.**
The charter tells it to: rule 3 says every fact carries a provenance and a freshness state "in the
data you are given. Repeat them", and rule 5 says keep names "exactly as the data has them"
(`agent/prompts/__init__.py:23-28`). The data it is given holds `state: "officially_confirmed"` and
`source: "dhm_rainfall"` (`agent/tools/read.py:122-130`), while the human words sit one file away —
`catalog.py:79-81` carries a display name on the same spec as the code, and
`services/communication.py:43` already maps every evidence state to "Officially confirmed" for
messages. `COMMUNITY_CHAT:60-61` adds "no internal state names"; `INVESTIGATE` and the response-center
chat do not. *Cost:* an answer a resident or an operator reads ends with "(dhm_rainfall, drr)" and
"officially_confirmed", which on this platform reads as an unverified internal marker attached to a
fact about flooding. The fix cannot be to instruct the model harder: rule 5 is deliberately there to
stop it renaming districts, hazards and reference codes. *Fix:* put the label in the payload the tool
returns (`name`, `state_label`) so the only word available for the model to repeat is the human one —
which also makes rule 3 do what it was meant to do.
*Still open for the investigation route; the responder's own digest had two instances of it and they
were fixed by calling the existing label function rather than printing the enum (see the fixed list).*

*Not defects, recorded so the next rendering pass does not re-report them:* two complaints that fields
"run together with no separator" (the demo-account card's name and username, a dispatch table's
cells) came from reading `textContent` of a flex layout, and `.row`, `.row-between` and `.stack-sm`
all set a `gap`. Extracted text has no separators; rendered text does.

---

## Found while connecting the agent to a live model

**68. An investigation run records no activity timeline, so its "checks made" column lies.**
*Fixed on the first run with a live key* — see "The first run with a real key" below, since the hook
that credits the model's own tool results is the same hook that writes these rows. What remains open
here is the shape, not the emptiness: the tool rows on this route carry no `detail` line, because the
watcher writing them is not the tool and cannot know which figures in a result matter. *Repro:*
`python probe/live_investigation_check.py` prints the recorded `(tool, status)` pairs for one real
investigation, and says out loud when a run proved nothing because the model never answered.

**69. "Melamchi" belongs to two districts depending on which file is believed.**
`shared/nepal_places.py` records Melamchi in Sindhupalchok; `boundary_index.resolve_point` puts its
centroid (28.0667, 85.4167) inside the Nuwakot polygon. The town and the Melamchi Khola sit on that
district line, so this is a data question, not a code bug. *Cost:* the same sentence resolves to
Sindhupalchok from the gazetteer and to Nuwakot from a shared pin two streets away, and dispatch
matching, the queue's district filter and the advisory targeting all follow whichever the record
carries. *Repro:* `python scripts/scenario_melamchi.py` prints the resolved district and confidence;
`probe/precision_vocab.py` prints the confidence families across the stored rows.

**70. A server started from the machine Python cannot reach a model, and says it has no key.**
`strands` and `google-genai` are installed in `.venv` only. Booting with
`C:\Users\...\Python312\python.exe -m uvicorn` answers every request normally and logs `model
provider NOT CONFIGURED (deterministic fallback only)` — the same line a missing `GEMINI_API_KEY`
produces. *Cost:* a key can be pasted into `.env`, the server restarted, and nothing changes, because
the process cannot import the SDK that would read it. *Repro:* `Get-CimInstance Win32_Process
-Filter "Name='python.exe'" | Select-Object ProcessId, CommandLine` and compare the interpreter
against `.venv\Scripts\python.exe`. Restart explicitly, not with `--reload` (item 24).
*Check the cheaper thing first:* `python probe/which_key.py` prints, without spending a request, what
`.env` holds and what `settings` resolved, so "the key is wrong" and "this process never read the
key" stop being the same symptom.

**71. A write refused for lack of permission leaves no trace of the attempt.**
All eleven `return refused(permission)` guards in `agent/tools/respond.py` answer the model and
stop, without passing through `record_action`, so nothing lands in the activity timeline. Every
*other* refusal in the same file - no named operator, a fabricated reference, an ungrounded figure -
is recorded with `status="refused"`, because a refusal is something that happened.
*Cost:* an operator watching an agent run sees `CREATE_ASSISTANCE_REQUEST` never appear, which reads
as "the model decided not to file" rather than "it tried and this account may not". The permission
model is doing its job; only the audit trail is missing the evidence, and a run stored that way
cannot be re-judged later.
*Fix:* route `refused()` through `record_action(..., status="refused")`, which also gives the read
tools' permission refusals a trace. `scripts/smoke_agent_guardrails.py` prints the current
behaviour as a note rather than a failure, so the day it changes the gate says so.

**72. The free tier is 20 model requests a DAY, and the error message says "retry in 22s".**
The key configured here is free tier. Its sentence is *"You exceeded your current quota… Quota exceeded
for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 20,
model: gemini-3.6-flash. Please retry in 22s."* — which reads as a 20-per-minute window with a short
backoff. The structured part of the same response says something else:
`QuotaFailure.violations[].quotaId = GenerateRequestsPerDayPerProjectPerModel-FreeTier`,
`quotaValue = 20`. **Per day, per project, per model.** The `RetryInfo.retryDelay` is not the reset
horizon, so waiting it out is a waste: the first attempt of a run twenty minutes after the last one was
refused, and stayed refused, because that budget is spent until the day rolls over. *Cost:* a free key
gets about twenty model requests, and an agent run spends one per turn (the spec's own test scenario
charged 2; a run that calls five tools will cost around six, and one throttled run charged six attempts
before giving up), so verifying the live paths once — which is what this session did — leaves the rest
of the day unable to re-run them, and every gate that follows
exercises the fallback while looking like it exercised a model. It also burns hours: "retry in 22s"
invites a retry loop against a daily cap. *Repro, and the way to read a quota error here:* make one
call outside strands, which retries and hides the structure —
`python -c "import os,google.genai as g;from dotenv import load_dotenv;load_dotenv();
print(g.Client(api_key=os.environ['GEMINI_API_KEY']).models.generate_content(model='gemini-3.6-flash',
contents='ok').text)"` — and the raised `ClientError` prints the `quotaId` that names the real bucket.
Strands' own wrapper buries the same text two exception names deep
(`ModelThrottledException: You exceeded your current quota…`), after six attempts.
*What it proved anyway:* the throttled run reported the provider's own error, degraded to
`mode=deterministic`, still filed the case, and an operator worked and resolved it — the "show the
actual error, do not fake a response" rule observed on the real thing rather than in a test.
*Fix, if ever:* a paid project, or budget the day (one scenario, one investigation, then stop).
Because the bucket is per project, a second key from the same account buys nothing —
`python probe/which_key.py --ping` is the one-request way to tell a bad key from a spent day.
Until then, read `mode` before believing any agent result in any gate, and assume a green
`smoke_http.py` agent section is the fallback's unless it says otherwise.

---

## Found chasing "the dashboard is static, polling has stopped"

Reported as: the poller has stopped or the USGS / DHM / DRR adapters are failing to fetch, so nothing
new reaches the dashboards. Measured before anything was changed, the premise is false and the symptom
is real. `python probe/ingestion_cadence.py` showed `mode=live`, every enabled source inside its own
`refresh_interval_seconds` (`usgs` logged 09:36:28, 09:41:40, 09:46:54, 09:52:06, 09:57:11, 10:02:15 on
its 300 s interval), and `scripts/check_sources.py` parsed 8 of 8 adapters against their live endpoints.
What was broken is the *freshness* signal. `Incident.last_updated_at` is what the console prints as
"last change" and orders the register by, and four independent defects were rewriting it on data that
had not moved — so a genuinely quiet feed (the newest M3+ event in the region was 107.9 h old) was
indistinguishable from a dead poller, and `records_updated` in the run table counted bookkeeping rather
than new information. All four are fixed, plus two display gaps that made the question unanswerable
from the UI. Two things are left open on purpose (79, 80).

**73. An unchanged poll looked changed: a `JsonDict` column hands back a string where Python had a `datetime`. (FIXED)**
`upsert_observations` compared its freshly built payload against the ORM attribute with `!=`. That
column's own encoding is lossy in one direction — `JsonDict._coerce` writes `datetime.isoformat()` and
`process_result_value` returns the stored value untouched — so a dict holding a `datetime` never equals
the dict read back from the column. Every field differed on every poll, so every poll counted as an
update, moved `received_at`, re-entered `absorb()`, and stamped `Incident.last_updated_at`.
*Measured before:* `usgs` 167 runs in 24 h, found 167, **new 1 / updated 166** — one M4.9 earthquake
from four and a half days earlier restamped 166 times. *Fixed:* `db.as_stored_json()` reproduces the
shape the column will store, and `ingestion.changed_fields()` — shared by the writer and by the probe,
so they cannot drift apart — applies it only to the payload columns. *Two traps for whoever edits this
next:* normalising a real `DateTime` column the same way manufactures the mirror-image bug (the column
gives back the `datetime` it was handed, so an ISO *string* always differs — that regression was written
here and caught by measurement, not by reading); and a hand-maintained list of columns silently opts
out the day someone adds a payload column, hence `_PAYLOAD_COLUMNS` being derived from the model with
`isinstance(column.type, JsonDict)`. *Repro:* `python probe/poll_twice.py [code]` runs the real
`run_source` twice back to back and verdicts each source; `python probe/why_it_reupdates.py [code]`
prints the field pairs that differ, and now says which comparison it used.

**74. `dhm_rainfall` dated every row with the instant it was fetched. (FIXED)**
The endpoint returns `{status, data}` and a station row is `{"id": 40, ..., "value": 0, "interval": 24,
"blink": false}` — no date field anywhere. So `_observed_at` was always `None`, the fallback
`datetime.utcnow()` became the row's `event_time`, and the hour bucket inside `external_id` re-keyed
every station every hour as though the rainfall were a new observation. *Measured:* 367 found,
**367 updated on every pass**, second after second — and invisible in a 24 h tally, because the hourly
re-key made the `new` column look honest. *Fixed:* the fallback is the current UTC hour floored
(`minute=0, second=0`), the bucket goes through the new `_utc_hour()`, and the row records which basis
it used (`normalized_data["timing_basis"] = "official" | "fetch_hour"`) so a reader can tell the
station's own timestamp from our bookkeeping. `_utc_hour()` corrects a second, quieter defect: calling
`.timestamp()` on a naive datetime assumes the *machine's* zone, which here (Nepal, UTC+5:45) slid
every bucket away from the hour its rows are named for. *Verified:* `new=367, updated=0` on a first
pass, `new=0, updated=0, incidents_touched=0` on the next.

**75. Two road sources stamped undated pages with the scrape instant. (FIXED)**
`dor` set `event_time` from `utcnow()` unconditionally; `drr_highway` used the same fallback when a
bulletin title carries no date. `incidents.py` already treats `event_time` as nullable everywhere
(`obs.event_time or obs.received_at`), so "no event time" is the supported answer — that is what both
store now, with the basis recorded. Measured, then *deliberately left alone*: `dhm_rivers`, where 0 of
172 gauges lack a parseable `datetime`, and whose `updated` counts (121 of 172 in one pass) are real
gauge movement. Fixing a churn bug by flattening a source that is actually reporting would have been
the worse error.

**76. The DRR register minted a duplicate row for every undated line at midnight. (FIXED)**
Its `external_id` embedded the *fetch date*, so an undated register row had a new identity each day — 18
of the feed's 60 rows had accumulated a daily twin, each re-touching its incident once a day for
nothing. Undated lines now key on the literal `"undated"` with `sno` / district / incident label, which
keeps them distinct and stable.

**77. Nothing in the API could answer "is the worker polling?" (FIXED)**
`main.py` puts the worker on `app.state.worker` and nothing had ever read it back, so the only evidence
available to an operator or a gate was the age of the newest row — and a dead thread and a quiet
upstream look identical from that. `IngestionWorker.status()` now reports the thread's own liveness
with `tick_seconds`, a cycle count and a humanised last-cycle age; `scheduler.report()` answers
`running: None` plus `"no ingestion worker in this process"` for a test client that never ran the
lifespan, rather than blaming the code under test for a worker that was never started. Exposed as
`worker` on `/api/sources` and `ingestion_worker` on `/api/system/status`, rendered as a third Stat on
the sources screen (`urgency="critical"` when it says it is down), and gated by a 71st
`smoke_http.py` check that fails if the field disappears.

**78. The Response Center overview fetched its request queue once and never again. (FIXED)**
`usePolling` drove the board only; the queue preview was a one-shot `useAsync` on mount, and its manual
refresh button refreshed just that panel. A request filed after the screen opened stayed off the list
until a full page reload — which reads exactly like "ingestion has stopped". One `reloadAll` callback
now drives both panels, so the shared timer and the button do the same thing.

**79. `drr_highway` still updates its 2 rows on every poll, because the upstream page rewrites itself. (OPEN, not ours)**
The DRR publication page alternates its own anchor label between `... राजमार्ग विवरण ।` and
`... राजमार्ग विवरण । ( Date: 2026-09-12 )` from one request to the next, so `title`,
`raw_data.label` and `timing_basis` genuinely differ each pass and the rows genuinely changed.
*Measured:* `incidents_touched=0` — no incident is restamped, so the register is unaffected; this is
churn in the observation table and in the run tally, nothing more. *Cost:* the one non-zero
`records_updated` in an otherwise quiet hour, which is the number a future reader of this document will
want to mistrust; `probe/poll_twice.py` names it as "row-only churn (upstream text itself differs)"
rather than lumping it with the four defects above. *Fix, if it were ours:* key the row on the link's
href rather than its label text — worth doing only if this starts touching incidents.

**80. A `system_mode=demo` row pauses live polling, and no route can set or clear it. (OPEN, latent)**
`scheduler._cycle()` returns `{"ran": false, "paused": "demo mode is armed"}` while
`state.system_mode(db)` says `demo` — correct behaviour for a rehearsal, which drives every timestamp in
the process. But `api/__init__.py` mounts auth, community, operations, incidents, response_center and
agent, and *no* demo router, so after the rehearsal screen was removed nothing over HTTP can arm or
clear that row: a leftover value would stop ingestion with no control to notice it. Measured here, the
row is `{"mode": "live", "scenario_id": null, "sim_clock": null}` and ingestion is not paused — this is
not the cause of the report above. *Cost:* a latent single point of failure, and `probe/clear_demo_direct.py`
is currently the only way out. *Partial mitigation now in place:* `paused` is a field in the worker
status that both 77's Stat and the smoke check print, so a paused worker at least says so. *Fix:* either
let `mode` be cleared from the operations screens, or delete the pause and make the rehearsal service
refuse to run while the worker is live.

---

## Fixed during this build, recorded so nobody re-introduces them

- Community reports were scored with observation-merge semantics (12 km / 36 h), so a legitimate
  "I felt it" report 11 km and four days from an official quake was discarded. Reports now use a
  hazard-specific radius and skip the time component.
- A repeated help request was silently suppressed as a duplicate. It now escalates the open case,
  records a bilingual update, re-notifies the Response Center, and refuses to restart the SLA clock.
- Duplicate reports pointed at the **oldest** match, so a repeat plea could land on a case closed
  hours earlier; the lookup now follows the chain to the newest match and walks through carried
  reports.
- Risk signals with no observation coordinate were invisible on the map (`/map/signals.geojson`
  returned zero features while `/signals` returned five) — district-centroid fallback plus an
  explicit `location_precision`.
- `GET /community/requests` did not exist, so the "MY REQUESTS" tab had nothing to read.
- `sources_healthy` compared a `Source.status` against the string `"ok"` — a *run* result, not a
  source state — so it always reported zero.
- `GET /notifications/unread-count` was called by the UI contract and never implemented.
- The audit log could be read one entity at a time but not as a list, so operators could not see
  their own collective actions; `/rc/audit` now filters by entity and by actor kind.
- An incident's action surface listed only status moves. It now lists every endpoint the server
  accepts for that incident, filtered to what the viewer is permitted to press — so a resident's
  view offers no buttons at all.
- **`http_fetch.fetch` built its header dict and never attached it to the `httpx.Client`.** Every
  adapter's `User-Agent` and `Accept` had been silently dropped since the build started, which is
  why Overpass answered `HTTP 406` to a request that worked in a browser. A per-source header set
  that is not sent is a per-source header set that does not exist.
- Overpass answered `HTTP 400 parse error: ';' expected` for every facility query: a statement
  inside a union block needs its own terminator (`(nwr[...](bbox););out center N;`). The seed now
  also strips Overpass's XHTML so a failure reports the server's sentence instead of `HTTP 400` —
  `SourceMalformed.sample` was never reaching `str()`.
- Clearing a rehearsal died on `FOREIGN KEY constraint failed` and rolled the whole transaction
  back, leaving demo incidents on the live map. `db.delete()` leaves flush ordering to the unit of
  work, which does not know `incidents` is a parent via a bare foreign key; the cleanup now issues
  ordered `delete()` statements and, for a *real* report that correlated with a scripted incident,
  sets `incident_id` back to NULL instead of deleting evidence.
- An observation derived from a community report was hardcoded `provenance="community"`, so a demo
  report left a looks-real observation behind after cleanup. It now inherits the report's
  provenance.
- The demo clock measured itself: `utcnow()` returns the simulated clock, so computing "seconds
  since arming" from it would have frozen every scenario where it last stood.
  `shared/timeutils.real_utcnow()` is the wall clock, and wall-clock arithmetic is the only thing
  allowed to produce simulated time.
- Live ingestion now stops while a scenario is armed. A real bulletin fetched under a simulated
  clock would be stored with a fictional timestamp on it — the one mixing of live and demo data the
  spec forbids. Sources go stale during a rehearsal and say so on `/sources/health`.
- The scenario scripts were wrong, not the lifecycle: `received` cannot jump to `in_progress`. The
  Gorkha rehearsal now walks `reviewing → response_team_notified → in_progress`, so what it
  demonstrates is the real transition table refusing a shortcut.
- `db.add()` does not hand a row its id when that id comes from a column default - SQLAlchemy
  applies it while writing. An agent run filed its own audit entry against `row.id` immediately
  after `add()`, got `entity_id=None`, and the NOT NULL constraint on `audit_events` turned a
  successful investigation into an HTTP 500. Flush before referencing it.
- Serializing the stored row and returning that as the response quietly dropped the fields that
  only exist in the run's outcome (`language`, `note`, `known`, `unknown`): the answer a resident
  saw said nothing about which language it had chosen or that no model wrote it. A response now
  carries both the stored row and the reply-only fields.
- A Nepali sentence built by dropping an English noun into a template read
  "हामीसँग अहिले official alerts for your area सम्बन्धी…". `communication.NO_DATA_SUBJECT_NE`
  now translates the system's own phrases; quoted source text (a USGS alert title) stays
  untranslated on purpose, because rewriting an official sentence is worse than an English one.
- An agent run about a demo incident was stored as `provenance="derived"` and `subject_id` carries
  no foreign key, so disarm left findings describing an incident that no longer existed. Runs now
  inherit the subject's provenance and disarm deletes them with it.
- `/api/map/layers` published the alerts overlay as `/api/alerts?limit=200` against an endpoint
  whose own ceiling is `le=100`, so the layer a map would build itself from answered 422 and the
  map simply had no alerts. A layer URL that does not answer is worse than no URL at all, and the
  smoke suite now compares every published `?limit=` against the OpenAPI bound for that parameter.
- Map features and the public incident payload called their own API endpoint `detail_url`, which
  reads exactly like the field a map navigates to - and would have taken a user to raw JSON at
  `/api/incidents/inc_…`. Both are now `api_url`, and the screen route is composed by whichever
  surface is drawing, because one layer feeds both. `/api/incidents/{id}` answers for a community
  account too (as the official-only public projection), so the rename is not hiding a dead link.
- `probe/api_shapes.py` truncated every response at 2,600 characters and dived only two levels
  deep, so the first draft of `api/types.ts` was written against cut-off shapes and invented half
  of them - `sla`, `response_plan`, `TimelineEvent`, `Alert`, `available_actions`. The probe now
  prints whole responses three levels deep, and the types were rewritten against it.
- The community boot sequence used to end with `status="signed_in"` and `user=null` whenever the
  server was unreachable, i.e. a spinner forever on a phone with no signal. An unreachable server
  now says so and keeps the stored token, so coming back into coverage restores the session
  without asking for a password the phone already has.
- **An unknown `/api/*` path answered 200 with the built frontend's `index.html`.** The SPA
  catch-all in `main.py` sits *behind* the API router and returns the root document for anything
  it has not seen, so a misspelled endpoint looked like a healthy request whose JSON happened to
  fail to parse - and in a browser, like a layer that simply has nothing in it. `probe/`
  experiments tripped over this twice in one night before it was noticed. Unknown paths under
  `/api/` now return 404 with `{"detail": "No API route at …"}`; non-`/api` paths still fall
  through to the router, which is what client-side routing needs.
- The incident cluster layer had no `filter`, so it redrew every unclustered point a second time,
  larger, underneath the marker you could see: an area of six small orange events looked like one
  red blob at low zoom. `CLUSTERED` was already defined and never used; a lint warning about an
  unread constant is worth reading as a design warning.
- A cluster was coloured by a malformed `reduce` cluster property that evaluated to its initial
  value, i.e. every cluster was red. It now aggregates `worst_urgency` with `["max", ["match"…]]`,
  so a group containing one critical event is red and a group of four informational ones is blue:
  a cluster never looks calmer than its worst member.
- Adding MapLibre pushed the single JS chunk to 1,028.93 kB, i.e. every login screen downloaded a
  renderer it does not use. `MapPage` is now a `React.lazy` route behind one `MapRoute` boundary:
  200.61 kB up front, 826.01 kB only when someone opens the map.
- `/api/map/incidents.geojson` claimed `colored_by: "incident_type"` while the map colours by
  urgency, because that is what §15 says. A claim about the rendering that the rendering does not
  honour is worse than no claim, since someone will eventually build a legend from it.

- **The queue's Impact column rendered `NaN` for every help request.** `action_queue()` returns one
  list built from two record shapes: request rows carry `acknowledged`/`sla`/`incident_id` and never
  an `impact_score` or `evidence_state`, which only `incident_review` rows have. `QueueItem` typed
  all of them as always present, so the type promised a number the endpoint does not send. The type
  now states which key belongs to which `kind`, the impact cell falls back to the SLA sentence, and
  the evidence chip is guarded - found only by looking at the screen.
- **Every incident action button 422'd, and every one of them said "no form for this action".**
  `tailOf()` sliced one character past the id marker, so `status` became `tatus`, no field list
  matched, and the request went out with an empty body the server rejected as `{status: Field
  required}`. A form the client cannot find and a form the server refuses look identical on screen,
  which is why it took a browser pass to notice both symptoms were one character.
- **A help request's status rendered in Devanagari on an English console.** `communication.status_label()`
  follows the *requester's* language, because it was written for the victim's phone. The console now
  builds its own label from `enumLabel(ASSISTANCE_STATUS_KEYS, row.status)` at all three call sites
  and leaves `status_label` to the surface it belongs to - the general rule (item 38) is still open.
- **"Overdue by 5 h 27 min min".** `minutesText()` and the `sla_overdue` template each appended a
  unit. The unit now lives in the value only, which also fixes it in Nepali, where the suffix was
  "मिनेट" doubled.
- **A completed action gave no feedback at all** - the panel just quietly reloaded. Both action rows
  now hold a `done` state and render "Action recorded" with `role="status"`, so the confirmation is
  announced as well as shown.

### The community surface, found by rendering it

- **A required single choice could not be changed.** `ChoiceGrid` treated `max` as a ceiling only:
  with `max={1}` and a value preselected, every alternative rendered disabled, so the account's
  language, the report type and the hazard type were all frozen at whatever arrived - a Nepali
  account could never become English without deleting and re-registering. `min` is now the other half
  of the control (`components/community/parts.tsx:250-260`), and the four call sites move a selection
  instead of toggling it away, because a language that silently becomes empty falls back to a default
  the person never picked.
- **Internal location codes were printed to the person they describe.** `resolve_location()` answers
  `high|medium|low|text_only|inferred_home_district|unknown`, which is a different family from the
  map's precision scale, and `enumLabel` deliberately echoes anything it does not recognise - so
  `inferred_home_district` appeared verbatim on a rescue request's receipt. There is now a
  `LOCATION_CONFIDENCE_KEYS` vocabulary and both the report outcome and the case screen render it
  (`MyRequestPage.tsx:206-210`), including "Inferred from your home district", which is a fact the
  sender is entitled to.
- **A closed case still showed its deadline.** `sla.minutes_remaining` on a cancelled request reads
  "this is overdue" to the person who cancelled it. The block is now withheld for terminal states and
  a `case_closed_note` says why the record is finished.
- **The resident's own status chip spoke the wrong language.** It came from `status_label`, which is
  written in the language the *case* was filed in, so checking an English request from a Nepali phone
  showed Devanagari on an English screen. It is rebuilt from `ASSISTANCE_STATUS_KEYS` in the reader's
  language, while `next_step` is still the server's sentence rendered as it arrived
  (`MyRequestPage.tsx:11-17`).
- **Cancelling erased the SLA block.** `POST /community/requests/{ref}/cancel` answers with the case
  and its timeline but not the `sla` object, and merging the answer over the loaded detail dropped
  the deadline to nothing (`MyRequestPage.tsx:101-105` keeps it).
- **"MY REQUESTS" counted open cases and listed every case.** The endpoint has no status filter, so
  the heading now counts what is on screen and the server's open tally is stated separately rather
  than a cancelled case sitting under a heading that said "open".
- **One server-side Nepali word used a non-standard Devanagari cluster** that no client produced,
  so the same term was spelled two ways on one screen; the server now matches the client.
- `GET /` answered the API's JSON pointer (`{"name": "SANKET", "frontend": "served here"}`) even
  once the frontend was built, because the root route is registered before the SPA catch-all - the
  built app was reachable only at `/index.html`. It now serves the app when the build exists and
  keeps the pointer for a backend-only deployment.

### The console, found by rendering it

- **Every filter `<label>` on the console was unassociated**, so a screen reader announced
  "combo box, blank" for all of them at once — the one control on the screen that could not be
  named. `EnumSelect` and `TextFilter` now take an id from `useId`: not a slug of the label, which
  would change with the interface language and collide the moment two filters on one screen shared
  a word.
- **The sources table printed `healthy`, `never_fetched`, `ok` and `error` in mono** behind a comment
  claiming the value had no published vocabulary. `SourceStatus` (`shared/enums.py:131-136`) *is*
  that vocabulary; the two now map through `SOURCE_STATUS_KEYS` and `RUN_STATUS_KEYS`, kept apart on
  purpose because a healthy source has failing runs and a failing source has runs that succeeded.
- **"Every 0s"** was shown for a source whose `refresh_interval_seconds` is 0, which means every
  scheduler tick (`services/ingestion.py:283`) — the opposite of what a zero reads as. Intervals go
  through `secondsText` now, so the table says "1 h" rather than "Every 3600s".
- **The rehearsal table reused the fetch-interval string**, printing "Every 3600s" under a "Time
  taken" heading: one string doing two unrelated jobs.
- **The report detail labelled a severity as "Status"**, showed the requester's language as `en`,
  and used the resident's confidence wording — "Inferred from your home district" — on a screen an
  operator reads, addressing a person who is not there. `SEVERITY_KEYS`, `LANGUAGE_NAME_KEYS` and
  `LOCATION_CONFIDENCE_KEYS_STAFF` now cover the console; the resident map is unchanged, because it
  was written for the resident.
- **The demo arm column's bare dash** to an operator account is the permission model working
  (`demo:control` belongs to the coordinator, and `smoke_demo.py:100` asserts an operator cannot
  arm), but an unexplained dash reads as a broken button, so the reason is stated once above the
  table instead of six times inside it.
- **A file-editing tool that reports failure after having applied part of the change** duplicated two
  blocks in `i18n/strings.ts`. `tsc --noEmit` caught it ("an object literal cannot have multiple
  properties with the same name"), and the removal was done by line index with every anchor asserted
  first, because Devanagari text is not reliably matchable by eye in this environment. Recorded so
  nobody "repairs" that file by diffing it by hand.
- **Two console headings were words written for someone else.** The report detail labelled the
  location-confidence row with the community form's question — "Where are you?" — and the error
  columns of the fetch and rehearsal tables reused the error panel's heading, "This did not load",
  as a column name, so a table of stored failures had a header that read as a complaint about the
  page. The console now says "Location confidence" and "Error"; the resident's question stays on the
  resident's form, where it was always correct.

### The agent's response route, found by running it and then rendering it

- **A place named in prose was filed at the confidence of a shared GPS pin.** `file_request` handed
  the gazetteer's coordinates to `assistance.create`, which resolves a lat/lng through the boundary
  polygon and reports `location_confidence: "high"` — the branch that means "someone told us where
  they are by pointing". The run's own timeline said Sindhupalchok / low in the same breath, and the
  stored priority carried "Location not established" while the row it described claimed high
  confidence. It now passes `location_text` only, so one resolution runs, through the branch that
  matches how the place was learned.
- **A record claimed the model filed a case that the rules filed.** `structured["model"]` was set
  from `"strands" if ctx.trace is not None else None`, and a trace always exists on this route, so
  every case said the agent chose to file it. The key is now `filing_route`, with the two values that
  are actually distinguishable: `model_called_the_tool` or `deterministic_rules`. Nobody reading an
  audit trail can tell an always-true expression from a real attribution, which is why it survived a
  full review pass and died on the first run.
- **A configured model refused to start, and blamed the key.** `Agent(hooks=[trace.hook()])` passed a
  callback annotated `event: Any`, because strands is imported inside the method and a real class name
  in that hint cannot be resolved at module scope. Strands infers which lifecycle event to subscribe
  to from exactly that hint, so it raised
  `ValueError: parameter=<event>, type=<typing.Any> | type hint must be a subclass of BaseHookEvent`
  from the agent constructor - before any request reached the provider. The run reported that as a
  model error, which is what a reader will mistake for a bad key. The counter is now attached after
  construction with the event named (`trace.attach(agent)`), and the same invalid-key check answers
  with Google's own `API_KEY_INVALID` and one counted model call. *Cost of not testing this without a
  key:* every criterion that needs the model would have failed on a machine that has one.
- **The activity timeline rendered nothing, because the frontend type invented a key the API never
  sends.** `AgentRun` was given an `activity?: AgentActivityStep[]` alongside the real `tool_calls`,
  and the screen read `filed.activity`. Optional, so `tsc` had nothing to object to: every run showed
  "This run recorded no steps. It did not read or change anything." while its own HTTP response
  carried seven steps proving it had read and written. The steps now have exactly one home —
  `tool_calls`, typed as the activity rows it actually holds — which makes the next rename a compile
  error instead of an empty panel. No gate could have caught this one; the API was right and the
  screen was wrong, and only opening the screen says so.
- **The filed case's link pointed at a route that does not exist.** `/rc/requests/…` is the *API*
  prefix; the console's own routes are `/response-center/…`. The link landed on the catch-all, which
  answered "This screen is not built yet" — the wrong report for a broken link, because it reads as
  an unfinished product rather than a wrong string in a finished one.
- **A status that only appears when it is bad.** The section promises names, time, status and result;
  the row drew no chip when the status was `ok` (a list of green badges being noise), which made a
  succeeded step indistinguishable from a step recorded without a status. Every row states its status
  now, and only the unclean ones are coloured.
- **The run's own prose said "status received" and "at confidence low"** — database values wearing a
  sentence's clothes. They now use the words the platform already shows a person ("status Received",
  "(low confidence)"), which is issue 67's defect in a new place. The tool names in the same
  paragraph stay exactly as the server spells them: those are the actions an operator is being shown,
  not vocabulary the screen should paraphrase.

### The write tools, found by calling them for the first time

The four writers had never executed - `scripts/scenario_melamchi.py` cannot reach them without a
model, and the deterministic route files through `file_request` directly. Calling them with the
arguments a model is allowed to send found three things in one sitting:

- **Three of the four write tools could not find the case the fourth had just filed.**
  `_request_by_ref` and `_incident_by_ref` upper-cased the reference before comparing it to the
  column, and `new_ref_code` ends in four *lowercase* hex characters - so the lookup matched only
  the roughly one reference in seven whose suffix happened to be all digits. `update_assistance_request`
  and `send_victim_update` answered `not_found` about a case named in the tool reply one step
  earlier, and `get_incident_details` told the model an incident it had just been shown did not
  exist. Both helpers now fold case on both sides of the comparison (`_ref_matches`), which still
  requires the reference to be complete. This is the phase's central promise broken quietly: an
  agent that read the report correctly could not finish the job, and reported a database with no
  case in it. Re-introducing it fails 7 checks in `scripts/smoke_agent_guardrails.py`, which files
  cases until it gets a reference with a letter in it, because an all-digit suffix passes either way.
- **A notice aimed at a case that did not exist was filed anyway**, attached to nothing: the queue
  got a real alert whose `request_id` and `link` were `NULL`, so the defect above produced not just
  a refusal but a plausible-looking record with its provenance removed. A `request_ref` or
  `incident_ref` that does not resolve now refuses the call. Filing a *case* over a bad reference
  still goes ahead - dropping a plea for help to be tidy about a link trades a real harm for a small
  one - but the reply says `incident_not_attached`, so the run learns it at the moment it matters.
- **A risk flag is stored in one of two places, and only one is a column.** `medical_need` and
  `immediate_danger` are columns on `assistance_requests`; `trapped`, `minors_involved` and
  `elderly_or_disabled_involved` are keys inside `structured`, because `assistance.create` takes all
  five and persists three of them into a JSON dict. Nothing was wrong; the gate's first draft read
  `request.trapped` and crashed, and the same mistake made in a screen instead of a script would
  read as "not trapped" rather than as an error. `scripts/smoke_agent_guardrails.py` reads them
  through one helper and asserts the five flags on the row equal the five the tool answered.

### The first run with a real key

Everything above this point was built against `LLM_PROVIDER` unset and the deterministic fallback, and
five things turned out to be wrong in ways a fallback cannot show. A key was pasted, `--reload` left
off, and the model was called.

- **The model id the phase asked for has been retired, and the error blames the key.**
  `gemini-2.5-flash` answered `404 NOT_FOUND … this model models/gemini-2.5-flash is no longer
  available to new users. Please update your code to use models/gemini-3.6-flash`. The message names a
  replacement, but a message is a string, so what this key may actually call was listed
  (`genai.Client(api_key=…).models.list()`, which is `GET /v1beta/models`): `gemini-2.5-flash` is not
  in it, `gemini-3.5/3.6/3.7/3.8-flash` and `gemini-flash-latest` are. `.env`, `.env.example` and the
  `strands_model` default in `backend/app/config.py` now say `gemini-3.6-flash`, which is deliberately
  *not* the id in the specification — the specified one cannot be called by a key issued today.
  *Cost:* a correctly configured key looks broken, because a retired model id arrives as a model
  failure and the banner does not distinguish them. Model ids expire; check the list before debugging
  a 404.
- **The investigation guard called the platform's own numbers invented.** `check_numbers` compared the
  model's answer against the findings bundle it was handed and nothing else, so figures the model
  retrieved with its own tools were refused as invention. On `INC-20260912-0013-2788` that meant the
  incident's *real stored coordinate*, `26.792, 85.912`, which `gather_findings` leaves out on purpose
  (its `unknown` list only warns that a coordinate is a district centre, not the event). The guard now
  reads every tool result the run retrieved, collected on an `AfterToolCallEvent` hook attached by
  name — the constructor form is still invalid, see the `Agent(hooks=[…])` entry above. The responder
  route needed no change and was the model for the fix: its tools file their own payloads into
  `ctx.evidence`, so its corpus was never starting-state only. *Cost:* a red gate accusing a correct
  agent of lying, on the check whose entire job is to catch lying. `gather_findings` was deliberately
  not widened to include the coordinates, because the omission is a truthful statement about precision.
  `scripts/smoke_agent_guardrails.py` now pins this in both directions — a fetched coordinate is
  credited, and an invented `411` is still refused.
- **The number extractor could not read the evidence it was given.** `agent/numbers.py` matched
  `\b\d+(?:\.\d+)?\b`, which needs a word boundary, but digits in JSON are glued to letters: measured
  against `{"at": "2026-09-12T13:26:59Z", …}`, the old corpus yielded `2026`, `09` and `26` from that
  string and nothing else — `12`, `13` and `59` are each fused to a letter, so they are invisible —
  while the same moment written as prose, "reported at 13:26", shows all three. So an answer was
  refused for `13`, a figure the evidence does hold, spelled where the extractor could not see it.
  `"4h 45m ago"` hides `4` and `45` exactly the same way, and the findings bundle hands over that shape
  itself (`investigate.py:83`, "the newest word is *4h 45m* old"). Two mistakes in one: a truthful
  restatement could be refused, and the code hid a second behind an unconditional pardon of 19–26,
  which let *any* claim of 19 through. Both sides now
  read digit runs identically (`\d+(?:\.\d+)?`) with leading zeros normalised, so `09` is `9` and
  `0.7` is still `0.7`, and the pardon is gone. The same asymmetry sits in front of
  `send_victim_update`, so one file covered two guards. *Repro:*
  `scripts/smoke_agent_guardrails.py`, three assertions.
- **A slow agent run was reported as a dead server, in the test and once in the product.**
  `smoke_http.py`'s client used `timeout=30.0` while the frontend already grants that route
  `AGENT_RUN_TIMEOUT_MS = 180_000` (`client.ts:420-427, 536-543`). A real model needs more than 30 s
  for six tool calls; the test raised `httpx.ReadTimeout`, which the report renders as a server fault,
  so the test was fixed. The same walk then timed out on `/agent/chat`, and there the shortage was
  real: that route asks the model a resident's question and was still on the 30 s default, so the Ask
  screen would have shown "cannot reach the server" over a reply that was written and stored one
  request later. It takes the same leash now, which is the third route of four; `classify` stays at
  30 s because it is deterministic unless a caller explicitly asks it to use the model.
  Same section, same run: the numbers check dumped ~30 KB of JSON to say a figure was refused and did
  not say whether the refused figure survived into the answer the operator reads, so it now names the
  values and the tools called, and asserts that a rejected number cannot appear as a whole token in
  `response_text`.

What the live run stood behind: `scripts/scenario_melamchi.py` reported `8 of 8` criteria, `mode
strands`, 2 counted model calls, 18.5 s, the model choosing `get_road_status` /
`find_medical_resources` / `find_related_reports` and filing the case through the tool
(`filing_route: model_called_the_tool`), quoting only grounded figures and naming the blocked road as
"an unconfirmed claim from the caller" because no machine-readable road feed exists. What it did not
stand behind: the investigation route has never completed under a live model — both attempts were
throttled, and the daily budget was spent by then (item 72) — so its widened corpus is verified
deterministically, not by the model whose behaviour it was written for.
`python probe/live_investigation_check.py` is the run that would close that, on a day that has requests
left; it prints which of the two it got.

---

## Verified by a gate, so a change can re-check it

- `scripts/check_resources.py` — no network: the routes exist in `app.openapi()["paths"]` (FastAPI
  keeps included routers lazy, so `app.routes` shows 6 and lies), the Overpass query terminates
  every statement, and the refuse-to-guess guards hold.
- `scripts/smoke_http.py` — 70 checks against the live server, including that the facility layer
  never emits a `contact` field, that an empty catalogue says why, and that the agent reports
  "no model" instead of inventing one and refuses a community account every `agent:run` route. Two
  of them exist because of tonight's frontend work: every path literal in
  `frontend/src/api/client.ts` has to match a real OpenAPI template (an invented path 404s and
  looks like an empty country), and every `?limit=` in a published layer URL has to sit inside the
  ceiling that endpoint itself publishes. The responder checks assert a shape rather than a result,
  so they hold with or without a key: a step may only carry a time, a name, a kind, a status and one
  line of detail (that is the "no chain-of-thought" rule as something a machine can fail), the risk
  flags must be attributed to the keyword table, a place named in prose must not read as a pin, and
  the case must reach the queue still waiting for a human — then be workable by one. The investigation
  check names the refused figures, the tools called and whether any refused figure survived into the
  answer, and grants that route the 180 s the frontend already grants it. Read `mode` before trusting
  any of it: with a free-tier key a green agent section can be a throttled one (item 72).
- `scripts/smoke_demo.py` was deleted with the `/api/demo/*` endpoints it armed, replayed and
  cleared; nothing else runs the rehearsal path from a gate.
- `scripts/smoke_slice.py` — the deterministic chain against live sources: real earthquake data in,
  normalized incident out, then evidence / impact / freshness, with DRR, DHM and the signal pass
  exercised in the same run. `--offline` skips the fetching.
- `scripts/smoke_loop.py` — the two-way loop on that same live data: community report, incident
  linkage, assistance request, operator actions, and the timeline the requester can see. It
  synthesises nothing — if no real Nepal incident exists to attach to, it says so and stops — so it
  has to run after `smoke_slice.py`.
- `probe/agent_read_aloud.py` — no gate, no assertion: prints one real investigation answer and two
  resident replies so a person can judge whether the claims are ones the system can stand behind.
- `probe/which_key.py` — no gate, no network unless asked: what `.env` assigns to `GEMINI_API_KEY`
  (line number, length, three-character prefix, never the value) against what `settings` resolved, so a
  key that "does not work" can be told apart from a server reading a different file or started from the
  wrong interpreter. `--ping` spends one real request per key to answer the remaining case.
- `probe/live_investigation_check.py` — no gate, needs a key: one real investigation through the
  workflow, then the question the number guard turns on — which figures in the answer came from a tool
  the model called for itself. It recomputes the pre-fix corpus (findings only) over the same answer and
  prints what the old guard would have rejected, so a run that passed without exercising the widened
  part cannot be mistaken for one that did. It returns 2 and says so when the model never answered,
  rather than scoring the fallback's wording.
- `scripts/scenario_melamchi.py` — the spec's own test sentence through the same function
  `POST /api/agent/respond` calls, then a PASS/FAIL line for each of the eight completion criteria.
  It is written so that a missing model cannot make it look green: criteria 1-5 and 8 report FAIL
  with the provider's own words rather than passing on the fallback's behaviour, and criterion 3 only
  counts a tool from the investigation set, so the rules filing a case cannot be mistaken for the
  model choosing to. `--cleanup` deletes exactly the rows that run wrote, matched by their ids and not
  by "looks like agent data" — a verification script that deletes by subject type would take a real
  responder's case with it.
- `scripts/smoke_agent_guardrails.py` — 57 checks, no network and no model: the four write tools
  called directly, with arguments a model can send. It is the only gate that reaches them without a
  provider, because a model's entire influence over a writer is its arguments. What it holds: an
  asserted risk flag the report's words do not carry is refused however confidently it is stated, a
  flag the model missed is still applied, a help type stands only on a quote copied out of the report
  and falls without one, no writer takes an urgency / status / description / coordinate / identity
  parameter at all (read off the schemas strands would hand to the model, so a new parameter cannot
  widen the surface unnoticed), a note stays internal and moves no status, a notice dispatches nobody,
  a victim message stating a figure nothing returned is refused, and an empty permission set writes
  no row anywhere. The strongest line files the same report twice - once with no proposal, once with a
  model's wrong one - and requires both cases to come out with the same priority and the same reasons,
  which is the only way "the LLM is not the source of truth" can be checked by someone else. The
  reference-code guard was mutation-tested by reintroducing the bug: 7 checks failed, across all four
  writers. The others are asserted by calling the tool and reading what came back, which is weaker —
  none of them has had its guard removed and re-run.
- `scripts/smoke_http.py` now also holds the map to account for two things that are invisible from
  the client: an unknown `/api/*` path must fail as `404 json` rather than `200` with the app shell
  (see the fixed list — this was how a wrong path hid), and the layer catalogue stays public while
  the feeds it names require a token, which is a decision worth noticing when it changes.
- `probe/map_surface.py` and `probe/anonymous_surface.py` — not gates, prints: the whole
  `/api/map/layers` contract with a sample feature per feed, and who may read each map URL without
  credentials. `probe/map_feed_vs_detail.py` compares the properties the map is handed against what
  the incident detail returns, which is how the timestamp and `urgency`/`score_band` questions
  above were found. Re-run these before changing anything the map draws.
