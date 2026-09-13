/**
 * The action queue: the records the server says need a person next, grouped by how soon.
 *
 * The grouping is the server's, not ours - `/api/rc/queue` answers with four buckets keyed by
 * urgency and a `why` list per row that quotes the scoring formula's own reasons. This screen
 * adds no ranking of its own, and the intro says the order comes from the published formula and
 * the response deadlines rather than from who reported last, because an operator who thinks the
 * list is chronological will work the wrong end of it.
 *
 * The informational bucket is off by default and the switch is labelled as a switch, not hidden:
 * it is legitimately where the "nothing to do yet" records go, and an operator who cannot see it
 * at all will assume the queue is dropping records.
 */

import { useState } from "react";

import { Link } from "react-router-dom";

import { api } from "../../api/client";
import type { QueueItem, Urgency } from "../../api/types";
import { DemoChip, EvidenceChip, Score, UrgencyTag } from "../../components/Chips";
import { Empty, Panel } from "../../components/StatePanel";
import { DataTable, RefreshRow, ReasonList, Screen, Stat, SubSection } from "../../components/rc/parts";
import { useAsync, usePolling } from "../../hooks/useAsync";
import { useI18n } from "../../i18n/I18nContext";
import { QUEUE_KIND_KEYS, URGENCY_KEYS } from "../../i18n/strings";
import { minutesText, serverLabel } from "../../utils/time";

const BUCKET_ORDER: Urgency[] = ["critical", "urgent", "attention", "information"];

/** Same rule as the overview: an incident review opens the incident, a request opens the request. */
function hrefFor(item: QueueItem): string {
  return item.kind === "incident_review"
    ? `/response-center/incidents/${encodeURIComponent(item.id)}`
    : `/response-center/requests/${encodeURIComponent(item.ref_code)}`;
}

export function QueuePage() {
  const { t, enumLabel, bcp47 } = useI18n();
  const [includeInformation, setIncludeInformation] = useState(false);

  const state = useAsync(
    (signal) =>
      api.rc.queue({ include_information: includeInformation, limit_per_bucket: 50 }, signal),
    [includeInformation],
  );
  const paused = usePolling(state.reload, 45_000);

  return (
    <Screen title={t("queue_title")} intro={t("queue_intro")}>
      <RefreshRow generatedAt={state.data?.generated_at} onRefresh={state.reload} seconds={45} paused={paused} />

      <label className="checkbox-row">
        <input
          type="checkbox"
          checked={includeInformation}
          onChange={(event) => setIncludeInformation(event.target.checked)}
        />
        <span>{t("queue_show_information")}</span>
      </label>

      <Panel state={state}>
        {(data) => (
          <>
            <section className="card">
              <div className="stat-grid">
                <Stat label={t("open_requests")} value={data.total_open_requests} />
                <Stat
                  label={t("unacknowledged_critical")}
                  value={data.unacknowledged_critical}
                  urgency={data.unacknowledged_critical ? "critical" : undefined}
                />
                <Stat
                  label={t("sla_breaches")}
                  value={data.sla_breaches}
                  urgency={data.sla_breaches ? "urgent" : undefined}
                />
              </div>
              <p className="meta">{t("queue_total", { count: BUCKET_ORDER.reduce((sum, level) => sum + (data.buckets[level]?.length ?? 0), 0) })}</p>
            </section>

            {BUCKET_ORDER.filter((level) => level !== "information" || includeInformation).map((level) => {
              const rows = data.buckets[level] ?? [];
              return (
                <SubSection
                  key={level}
                  title={enumLabel(URGENCY_KEYS, level)}
                  count={data.counts[level] ?? rows.length}
                >
                  {rows.length ? (
                    <DataTable
                      caption={enumLabel(URGENCY_KEYS, level)}
                      columns={[
                        {
                          id: "item",
                          label: t("col_incident"),
                          cell: (row: QueueItem) => (
                            <div className="stack-sm">
                              <span className="row">
                                {row.demo ? <DemoChip /> : null}
                                <Link to={hrefFor(row)}>{row.title}</Link>
                              </span>
                              <span className="row">
                                <span className="mono">{row.ref_code}</span>
                                <span className="meta">{enumLabel(QUEUE_KIND_KEYS, row.kind)}</span>
                                {row.district ? <span className="meta">{row.district}</span> : null}
                              </span>
                              {row.why.length ? <ReasonList items={row.why} className="compact" /> : null}
                            </div>
                          ),
                        },
                        {
                          id: "chips",
                          label: t("col_urgency"),
                          cell: (row: QueueItem) => (
                            <div className="row">
                              <UrgencyTag value={row.urgency} />
                              {/* Only an incident review has an evidence state; a request's own
                                  record is the one that carries it. */}
                              {row.evidence_state ? <EvidenceChip value={row.evidence_state} /> : null}
                            </div>
                          ),
                        },
                        {
                          id: "score",
                          label: t("col_score"),
                          numeric: true,
                          /**
                           * A help request has no impact score - the number that decides its place
                           * in this list is its deadline, so that is what goes in this cell.
                           */
                          cell: (row: QueueItem) => {
                            if (row.impact_score !== null && row.impact_score !== undefined) {
                              return <Score value={row.impact_score} />;
                            }
                            const sla = row.sla;
                            if (!sla) return <span className="meta">—</span>;
                            if (sla.minutes_remaining === null || sla.minutes_remaining === undefined) {
                              return <span className="meta">{t("acknowledged")}</span>;
                            }
                            return (
                              <span className={sla.breached ? "meta breach" : "meta"}>
                                {sla.breached
                                  ? t("sla_overdue", { minutes: minutesText(sla.minutes_remaining) ?? "" })
                                  : t("sla_remaining", { minutes: minutesText(sla.minutes_remaining) ?? "" })}
                              </span>
                            );
                          },
                        },
                        {
                          id: "age",
                          label: t("age"),
                          cell: (row: QueueItem) => serverLabel(row.at, row.age, bcp47) ?? "—",
                        },
                        {
                          id: "open",
                          label: t("col_action"),
                          cell: (row: QueueItem) => (
                            <Link className="button small" to={hrefFor(row)}>
                              {t("open_record")}
                            </Link>
                          ),
                        },
                      ]}
                      rows={rows}
                      keyOf={(row) => `${row.kind}-${row.id}`}
                    />
                  ) : (
                    <Empty title={t("bucket_empty")} />
                  )}
                </SubSection>
              );
            })}
          </>
        )}
      </Panel>
    </Screen>
  );
}
