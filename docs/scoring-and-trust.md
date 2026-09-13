# Scoring, trust and prioritization

Every number a Response Center operator sees is produced by a formula in this repository,
and every formula publishes its own inputs. If a screen cannot explain why it is at the
top of a queue, that is a defect — not a subtlety.

Nothing here is learned, inferred or generated. The language model does not touch these
calculations; at most it fills in the structured fields (is this a rescue need? does it
mention a collapse?) that the rules then read.

---

## Impact score

`backend/app/scoring/impact.py`

```
impact_score = 100 * clamp01( Σ (raw_i × weight_i) / MAX_TOTAL ) × freshness_multiplier
MAX_TOTAL = 1.20
```

| Component | Weight | Raw value |
|---|---|---|
| severity | 0.28 | low .18 · moderate .45 · high .78 · severe 1.0 · unknown 0 |
| fatalities | 0.25 | `log10(1 + deaths) / 2` |
| missing | 0.10 | `log10(1 + missing) / 1.7` |
| injured | 0.10 | `log10(1 + injured) / 2.3` |
| affected people | 0.08 | `log10(1 + affected) / 3.5` |
| houses damaged | 0.07 | `log10(1 + houses) / 2.7` |
| urgency | 0.12 | critical 1.0 · urgent .65 · attention .3 · information .05 |
| evidence state | 0.06 | confirmed 1.0 · officially reported .8 · corroborated .55 · community .3 · unverified 0 · conflicting .15 |
| community volume | 0.06 | `log10(1 + reports) / 2` |
| open assistance requests | 0.08 | `min(1, open / 8)` |

Three decisions in that table are worth defending:

**Population counters are log-scaled**, so ten deaths does not drown out a five-hundred
person affected population, and a flood and an earthquake stay comparable.

**Earthquakes override the severity label** with `clamp01((M − 3) / 5)` — M3 → 0, M8+ → 1.
A magnitude is a physical measurement; a severity word from a register is somebody's
impression.

**Freshness multiplies at the end**, so identical information that is three days old ranks
below the same information while it is live. It is applied last so it cannot distort the
relative shape of the components.

Bands drive colour and grouping, never ranking: `critical ≥ 70 · high ≥ 45 · moderate ≥ 25
· low > 0 · minimal 0`.

The API returns the whole arithmetic, not just the answer:

```json
"why_prioritized": {
  "score": 62.4,
  "formula": "100 * clamp01(sum(raw_i * weight_i) / max_total) * freshness_multiplier",
  "weights": { "severity": 0.28, "fatalities": 0.25, "...": 0 },
  "components": { "severity": {"raw": 0.78, "weight": 0.28, "contribution": 0.2184} },
  "freshness_state": "recent", "freshness_multiplier": 0.95
}
```

`scripts/inspect_incident.py <id>` prints the same breakdown for any incident.

---

## Freshness

`backend/app/scoring/freshness.py`

Data must never visually present itself as live when it is not. Freshness is measured
against the **event or observation time**, capped by the source's own staleness budget —
an hourly rainfall station is stale far sooner than a historical disaster register.

| State | Age, subject to the source budget | Score multiplier |
|---|---|---|
| `fresh` | ≤ min(15 min, budget/4) | 1.00 |
| `recent` | ≤ min(1 h, budget/2) | 0.95 |
| `aging` | ≤ min(6 h, budget) | 0.82 |
| `stale` | beyond the budget | 0.55 |
| `unknown` | no timestamp at all | 0.70 |

A `drr` register row gets a longer budget (at least 7 days) because disaster registers are
inherently retrospective: a three-day-old official record is still authoritative. An
unknown timestamp scores 0.70 rather than 1.0 — *not knowing* when something was said is
not the same as it being fresh, but it should not be buried either.

Negative ages (a source's clock ahead of ours) count as fresh and never as stale.

Flood gauges are classified against the source's own official thresholds, never against an
invented number: level ≥ danger → `DANGER`, ≥ warning → `WARNING`, ≥ 0.9 × warning →
`WATCH`, and a stale gauge reads `STALE` rather than `NORMAL` — an unread sensor must not
look like an all-clear.

---

## Urgency and SLA

`backend/app/scoring/urgency.py`

Rules, evaluated in order, **first match wins**, and the matching rule's sentence is
surfaced verbatim to the operator as `urgency_reasons`. A reason string is never
reconstructed after the fact — if the reason is missing, the classification is wrong.

```
critical   immediate danger + a life-safety need (rescue or medical)
critical   trapped and unable to self-evacuate
critical   medical need with explicit severe-injury words in the text
critical   medical need involving minors or elderly/disabled persons
urgent     medical need, or a rescue request without declared immediate danger
attention  food / water / shelter, transport, road blockage
information  everything else
```

Response targets, in minutes before an unacknowledged request is a breach:

| critical | urgent | attention | information |
|---|---|---|---|
| 15 | 45 | 240 | 1440 |

An unknown location does not lower urgency — it adds a separate reason, *"Location not
established — responders cannot be dispatched yet"*, because those are different problems
and conflating them hides the one that is blocking a dispatch.

Re-sending a plea that is still open escalates the existing case by one step and records
*"The person reported again — still waiting for help"* on its public timeline. It does
**not** restart the SLA clock: the wait started when they first asked.

`escalate_from_volume()` promotes an incident as it gathers attention (≥ 1 open request,
≥ 5 open requests, ≥ 6 or ≥ 15 reports). Like the rest of an incident's derived fields it
is recomputed by code rather than set by hand, and where a promotion changes what an
operator sees it is recorded as a `system` action in the audit log.

---

## Trust and evidence states

`backend/app/scoring/evidence.py`

Six states, computed from what actually backs the incident. The justification strings are
returned with the state and displayed verbatim.

| State | Reached when |
|---|---|
| `conflicting` | any linked source disagrees with the current picture |
| `officially_confirmed` | an authoritative source record confirms it, **or** an accountable operator verified it |
| `officially_reported` | it appears in an official register |
| `corroborated` | ≥ 2 independent community reports, consistent with official environmental data |
| `community_reported` | community reports, no official source yet |
| `unverified` | nothing linked, or the row is demo data |

`conflicting` is evaluated first and `demo` second: demo data can never climb the ladder,
and a disagreement freezes promotion until it is resolved.

**Who may say "official".**

```python
OFFICIAL_PROMOTION_ACTORS = {"system:ingestion", "operator", "coordinator", "system"}
```

`agent` is absent on purpose. `promotion_guard()` refuses an attempt by any other actor to
claim an official state and returns the sentence *"Official status only comes from an
authoritative source record or an accountable operator."* An operator verification is a
real event: it is written to the audit log with the person's name, and the incident is
labelled *operator-verified*, never *government-confirmed*.

Source authority, used when cross-validating one record against another:

```
nemrc 0.95   dhm 0.95   hydrology 0.95   drr 0.90   usgs 0.85   dor 0.70   community 0.15   demo 0.00
```

Nepali authorities outrank the global catalogue for Nepali events; the Department of Roads
sits lowest of the official sources because its road status arrives as a PDF and is parsed
with the least confidence. An unrecognised source gets 0.5 rather than a flattering default.

---

## Correlation

`backend/app/geo/correlation.py`

```
score = Σ (component × weight) / Σ (weights of the components present)
```

| Component | Weight | Shape |
|---|---|---|
| distance | 0.40 | `(1 − d/radius)^1.5`, so adjacent villages in one valley are not one point |
| time | 0.20 | `1 − gap/36 h`, zero beyond 36 hours |
| hazard type | 0.25 | same 1.0 · downstream of each other 0.7 · unrelated 0.05 · unknown 0.35 |
| administrative | 0.10 | same municipality 1.0 · same district 0.75 · different district 0 |
| wording | 0.05 | token overlap, deliberately a minor signal |

`MATCH_THRESHOLD = 0.72` merges. `AMBIGUOUS_LOW = 0.50` to 0.72 is recorded as ambiguous
and passed to the agent as a **proposal** that an operator or a later official record must
accept — the score is a suggestion engine, never a silent rewriter.

**Missing components are dropped from the denominator, not counted as zero.** Sparse
official register rows have no coordinates and no usable time, and treating an unknown as
a disagreement would make them permanently un-correlatable. When that happens,
`weight_used` is returned alongside the score so the caller can see how thin the basis was.

Hazard affinity encodes physical reality: a landslide and a road blockage on the same
corridor at the same moment are one event; a flood and heavy rainfall are one event; an
earthquake and infrastructure damage are one event.

**Reports from residents are scored differently from source records.** An official record
sits *at* the event; a person reports from where they are standing. So the report pass uses
`REPORT_RADIUS_KM` (earthquake 120 km — the felt area, not the epicentre; flood and heavy
rain 30; landslide and road 20; storm 25; infrastructure 15; lightning 10; fire 5) and
skips the time component entirely, because a report's timestamp records when somebody typed,
not when the ground shook. A resident 11 km from an M4.9 epicentre, describing it four days
later, is a *good* match — under the observation radii they were not, which is the exact
failure this exists to prevent.

Clustering is greedy single-linkage over time-ordered records, with earthquakes promoted
ahead of district-centroid register rows so a precisely-located event anchors the cluster.

---

## Where to tune, and what not to touch

Tune weights in one place each: `impact.WEIGHTS`, `freshness.classify_age`, `urgency.SLA_MINUTES`
and the rule order, `correlation.MATCH_THRESHOLD` / `REPORT_RADIUS_KM`. Nothing reads a
magic number from a service or a router.

Do not add a path where a score, an evidence state or a status transition is written from
a model response, a UI default, or a demo scenario. The state machine in
`assistance.ALLOWED_STATUS_TRANSITIONS` and `promotion_guard()` are the only doors, and
both were built so that an eager integration cannot quietly open them.
