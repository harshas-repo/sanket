/**
 * The console's front door: how big is this, and who is waiting.
 *
 * Every figure here is copied from `/api/rc/dashboard` or `/api/rc/queue`, both of which are
 * computed from the stored records by deterministic code. Nothing on this screen is written by a
 * language model, and the intro says so, because an operator who believes a number came from a
 * model will discount it at exactly the wrong moment.
 *
 * The queue is fetched twice-over: once for its three headline counts (open, unacknowledged
 * critical, past deadline), and once as a five-row preview so the screen can point at something
 * specific. The preview asks the server for `include_information=false` so the fourth urgency -
 * the one that is not an action - does not push the real items off the page.
 *
 * Opening this screen also asks the server to poll the official feeds, rather than only re-reading
 * what the last poll stored (`api.sources.pollNow`). Two things follow from that, and both are the
 * point of the design: the fetch happens on the worker and not inside this request, so the screen
 * paints from what it held on the last visit while the new records are being fetched and replaces
 * them when they land; and the wait is watched on the worker's own cycle counter, because a
 * browser clock compared to a server clock is not a fact about data arriving.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../../api/client";
import type { QueueItem } from "../../api/types";
import { DemoChip, EvidenceChip, UrgencyTag } from "../../components/Chips";
import { Panel } from "../../components/StatePanel";
import { DataTable, MetaStrip, RefreshRow, Screen, Stat, SubSection } from "../../components/rc/parts";
import { useAsync, usePolling } from "../../hooks/useAsync";
import { useI18n } from "../../i18n/I18nContext";
import { HAZARD_KEYS, QUEUE_KIND_KEYS } from "../../i18n/strings";
import { serverLabel } from "../../utils/time";

const URGENCY_ORDER = ["critical", "urgent", "attention", "information"] as const;

/** Ceiling on waiting for a requested pass to land. Eight agency servers is minutes of other
 *  people's computers, so this is generous by design - and it is a ceiling, not a delay: the
 *  figures are re-read the moment the worker's counter moves, and once at the end either way. */
const POLL_DEADLINE_MS = 4 * 60_000;

/** How often to ask whether that pass has landed. Each check reads the source table - the fetching
 *  already happened on the server - so this costs the feeds nothing. */
const POLL_CHECK_MS = 5_000;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

/** Where a queue row's `kind` sends the reader. The two values are the server's, not ours. */
function queueHref(item: QueueItem): string {
  return item.kind === "incident_review"
    ? `/response-center/incidents/${encodeURIComponent(item.id)}`
    : `/response-center/requests/${encodeURIComponent(item.ref_code)}`;
}

export function OverviewPage() {
  const { t, enumLabel, bcp47 } = useI18n();
  // Both panels are aggregate counts with nothing personal in them, which is what makes them
  // worth holding on the device: the screen opens on the last answer it got and updates from here.
  const board = useAsync((signal) => api.rc.dashboard(signal), [], "rc.overview.dashboard");
  const queue = useAsync(
    (signal) => api.rc.queue({ include_information: false, limit_per_bucket: 5 }, signal),
    [],
    "rc.overview.queue",
  );
  // One timer for both panels. The queue preview used to be fetched once when the screen mounted
  // and never again, so a request that arrived afterwards stayed off the list until a reload of the
  // whole page - which is what made a live register read as a static one.
  const reloadAll = useCallback(() => {
    board.reload();
    queue.reload();
  }, [board.reload, queue.reload]);
  const paused = usePolling(reloadAll, 60_000);

  // `waiting`: a poll was asked for and has not landed. `refused`: the server said it would not
  // fetch - which is said out loud rather than left as a spinner that will stop on its own.
  const [poll, setPoll] = useState<{ waiting: boolean; refused: boolean }>({
    waiting: false,
    refused: false,
  });
  const run = useRef(0);
  useEffect(
    () => () => {
      // Retires whatever loop this screen started. A state update on an unmounted panel is not
      // dangerous here and is not worth checking a flag against on every await.
      run.current += 1;
    },
    [],
  );

  const refresh = useCallback(async () => {
    const token = ++run.current;
    const alive = () => token === run.current;
    setPoll({ waiting: true, refused: false });

    let cyclesAtRequest: number | null = null;
    try {
      const ack = await api.sources.pollNow();
      if (!alive()) return;
      cyclesAtRequest = ack.refresh.triggered ? ack.refresh.cycles : null;
      setPoll({ waiting: ack.refresh.triggered, refused: !ack.refresh.triggered });
    } catch {
      // An account without `sources:run`, or a server that is not answering. The reload at the end
      // still brings this screen whatever the API does have, so Refresh is never a dead end for the
      // person who cannot trigger a fetch.
      if (!alive()) return;
      setPoll({ waiting: false, refused: false });
    }

    if (cyclesAtRequest !== null) {
      const deadline = Date.now() + POLL_DEADLINE_MS;
      while (alive() && Date.now() < deadline) {
        await sleep(POLL_CHECK_MS);
        if (!alive()) return;
        try {
          const sources = await api.sources.list();
          if (!alive()) return;
          if (sources.worker.cycles > cyclesAtRequest) break;
        } catch {
          // One failed check is not the end of the wait; the deadline is.
        }
      }
      if (!alive()) return;
      setPoll({ waiting: false, refused: false });
    }
    reloadAll();
  }, [reloadAll]);

  useEffect(() => {
    // Once per mount, not once per render: this is the fetch that answers "is the console looking at
    // the newest official records right now", and re-running it on an identity change would ask the
    // agency servers again for no reason. The server keeps its own floor on repeated forced passes.
    void refresh();
  }, [refresh]);

  const preview = queue.data
    ? URGENCY_ORDER.flatMap((level) => (queue.data?.buckets[level] ?? []).slice(0, 3).map((item) => ({ ...item, urgency: level })))
    : [];

  return (
    <Screen
      title={t("nav_overview")}
      intro={t("overview_intro")}
      actions={
        <Link className="button small primary" to="/response-center/queue">
          {t("open_queue")}
        </Link>
      }
    >
      <RefreshRow
        generatedAt={board.data?.generated_at}
        onRefresh={() => void refresh()}
        paused={paused}
        busy={poll.waiting}
        busyLabel={t("refreshing")}
        note={
          poll.refused
            ? t("poll_not_started")
            : poll.waiting
              ? t("refreshing_official")
              : board.cached || queue.cached
                ? t("cached_note")
                : null
        }
      />

      <Panel state={board}>
        {(data) => {
          const types = Object.entries(data.incidents.by_type).sort(
            (a, b) => b[1] - a[1] || a[0].localeCompare(b[0]),
          );
          return (
            <>
              <section className="card">
                <div className="stat-grid">
                  <Stat label={t("active_incidents")} value={data.incidents.total_active} />
                  <Stat label={t("new_24h")} value={data.incidents.new_last_24h} />
                  <Stat label={t("cross_validated")} value={data.incidents.cross_validated} />
                  <Stat
                    label={t("needs_review")}
                    value={data.incidents.needs_review}
                    urgency={data.incidents.needs_review ? "attention" : undefined}
                  />
                  <Stat label={t("open_requests")} value={data.assistance.open} />
                  <Stat
                    label={t("critical_open")}
                    value={data.assistance.critical}
                    urgency={data.assistance.critical ? "critical" : undefined}
                  />
                  <Stat label={t("reports_24h")} value={data.community.reports_last_24h} />
                  <Stat
                    label={t("pending_verification")}
                    value={data.community.unverified_pending}
                    urgency={data.community.unverified_pending ? "urgent" : undefined}
                  />
                </div>
                <p className="meta">
                  {t("last_change")}:{" "}
                  {serverLabel(data.last_change, data.last_change_label, bcp47) ?? "—"}
                </p>
              </section>

              <SubSection title={t("by_type")} count={types.length}>
                {types.length ? (
                  <DataTable
                    columns={[
                      {
                        id: "type",
                        label: t("filter_type"),
                        cell: (row: [string, number]) => enumLabel(HAZARD_KEYS, row[0]),
                      },
                      {
                        id: "count",
                        label: t("col_count"),
                        numeric: true,
                        cell: (row: [string, number]) => row[1],
                      },
                    ]}
                    rows={types}
                    keyOf={(row) => row[0]}
                  />
                ) : (
                  <p className="meta">{t("bucket_empty")}</p>
                )}
              </SubSection>
            </>
          );
        }}
      </Panel>

      <SubSection title={t("queue_title")} count={queue.data?.total_open_requests}>
        <MetaStrip generatedAt={queue.data?.generated_at} stale={Boolean(queue.error)} />
        <Panel state={queue} isEmpty={() => preview.length === 0} emptyTitle={t("queue_is_empty")}>
          {() => (
            <DataTable
              columns={[
                {
                  id: "item",
                  label: t("col_incident"),
                  cell: (row: QueueItem) => (
                    <span className="row">
                      {row.demo ? <DemoChip /> : null}
                      <Link to={queueHref(row)}>{row.title}</Link>
                    </span>
                  ),
                },
                {
                  id: "kind",
                  label: t("details"),
                  cell: (row: QueueItem) => (
                    <span className="meta">{enumLabel(QUEUE_KIND_KEYS, row.kind)}</span>
                  ),
                },
                {
                  id: "chips",
                  label: t("col_urgency"),
                  cell: (row: QueueItem) => (
                    <span className="row">
                      <UrgencyTag value={row.urgency} />
                      {row.evidence_state ? <EvidenceChip value={row.evidence_state} /> : null}
                    </span>
                  ),
                },
                {
                  id: "age",
                  label: t("age"),
                  cell: (row: QueueItem) => (
                    <span className="meta">{serverLabel(row.at, row.age, bcp47) ?? "—"}</span>
                  ),
                },
              ]}
              rows={preview}
              keyOf={(row) => `${row.kind}-${row.id}`}
            />
          )}
        </Panel>
      </SubSection>
    </Screen>
  );
}
