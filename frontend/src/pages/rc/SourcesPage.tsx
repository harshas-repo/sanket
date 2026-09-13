/**
 * SOURCES - where every fact on the map came from, and whether the feed still works.
 *
 * §6 is the reason this screen exists as a first-class tab rather than a footnote: a platform that
 * claims to know the situation has to be able to say which of its inputs is failing right now. A
 * source that stopped three days ago still shows its last successful fetch, its consecutive failure
 * count and its own error text, so "the map looks fine" can never be confused with "the map is
 * being fed".
 *
 * Freshness is rendered with the server's own `updated_label` where it sent one. This screen does
 * not compute an age from a timestamp: the ingest clock is the server's, and in a rehearsal it is
 * deliberately not the wall clock.
 *
 * "Fetch now" and "fetch everything due" are operator actions (`sources:run`), not reader ones, so
 * they are hidden from a role that would only get a 403 for tapping them.
 */

import { useState } from "react";

import { api } from "../../api/client";
import type { IngestionRunRow, SourceHealth } from "../../api/types";
import { FreshnessChip } from "../../components/Chips";
import { Panel } from "../../components/StatePanel";
import {
  DataTable,
  MetaStrip,
  RefreshRow,
  Screen,
  Stat,
  SubSection,
} from "../../components/rc/parts";
import { useAuth } from "../../auth/AuthContext";
import { useAsync, usePolling } from "../../hooks/useAsync";
import { useI18n } from "../../i18n/I18nContext";
import { RUN_STATUS_KEYS, SOURCE_STATUS_KEYS } from "../../i18n/strings";
import { formatStamp, secondsText, serverLabel } from "../../utils/time";

export function SourcesPage() {
  const { t, enumLabel, bcp47 } = useI18n();
  const { can } = useAuth();

  const sources = useAsync(() => api.sources.list(), []);
  const runs = useAsync(() => api.sources.runs(50), []);
  const paused = usePolling(sources.reload, 60_000);

  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  /** A manual fetch is a write in everything but method: it hits a live agency's server. It gets
   *  its own busy marker per source so one slow feed cannot look like the whole board is stuck. */
  const runOne = async (code: string) => {
    setBusy(code);
    setError(null);
    try {
      await api.sources.run(code);
      await Promise.all([sources.reload(), runs.reload()]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(null);
    }
  };

  const runDue = async () => {
    setBusy("*");
    setError(null);
    try {
      await api.sources.runDue();
      await Promise.all([sources.reload(), runs.reload()]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(null);
    }
  };

  const canRun = can("sources:run");
  const items = sources.data?.items ?? [];
  const failing = items.filter((row) => row.consecutive_failures > 0).length;
  const worker = sources.data?.worker;

  return (
    <Screen
      title={t("nav_sources")}
      intro={t("sources_intro")}
      actions={
        canRun ? (
          <button type="button" className="button small" disabled={busy !== null} onClick={() => void runDue()}>
            {busy === "*" ? t("sending") : t("run_due")}
          </button>
        ) : null
      }
    >
      <RefreshRow generatedAt={sources.data?.generated_at} onRefresh={sources.reload} seconds={60} paused={paused} />

      <div className="stat-grid">
        <Stat label={t("total")} value={items.length} />
        <Stat
          label={t("consecutive_failures")}
          value={failing}
          note={failing ? t("stale_warning") : null}
        />
        {/* Asked of the worker thread itself rather than read off the "Last check" column below. A
            table where every check is old has two possible causes - the poller stopped, or the
            agencies have nothing new - and only the first one is this platform's fault. */}
        {worker ? (
          <Stat
            label={t("ingestion_worker")}
            value={
              worker.running === true
                ? t("worker_running")
                : worker.running === false
                  ? t("worker_stopped")
                  : t("worker_unknown")
            }
            note={
              worker.running
                ? worker.last_cycle_label
                  ? t("worker_last_cycle", { age: worker.last_cycle_label })
                  : null
                : worker.reason
            }
            urgency={worker.running ? undefined : "critical"}
          />
        ) : null}
      </div>

      {error ? (
        <p className="field-hint breach" role="alert">
          {error}
        </p>
      ) : null}

      <Panel state={sources} isEmpty={(data) => data.items.length === 0} emptyTitle={t("bucket_empty")}>
        {(data) => (
          <section className="card">
            <DataTable
              columns={[
                {
                  id: "source",
                  label: t("source"),
                  cell: (row: SourceHealth) => (
                    <div className="stack-sm">
                      <span className="row">
                        <strong>{row.name}</strong>
                        <span className="meta mono">{row.code}</span>
                      </span>
                      <span className="meta">
                        {row.organization}
                        {row.official ? ` · ${t("official_source")}` : ""}
                        {row.machine_readable ? "" : ` · ${t("map_layer_unavailable")}`}
                      </span>
                    </div>
                  ),
                },
                {
                  id: "status",
                  label: t("status"),
                  cell: (row: SourceHealth) => (
                    <div className="stack-sm">
                      {/* `SourceStatus` is a published enum (`shared/enums.py:131-136`); the screen
                          that printed `healthy` and `never_fetched` in mono was the one with no
                          vocabulary, not the server. `enumLabel` still echoes a value this list has
                          not caught up with, so a future state shows as a code rather than vanish. */}
                      <span className="chip provenance">{enumLabel(SOURCE_STATUS_KEYS, row.status)}</span>
                      <FreshnessChip value={row.freshness_state} label={row.updated_label} />
                    </div>
                  ),
                },
                {
                  id: "interval",
                  label: t("col_interval"),
                  // Zero is not "never": the worker's test is `elapsed >= 0`, true on every tick
                  // (`services/ingestion.py:283`), so "Every 0s" would be a number that means the
                  // opposite of what it says. The column header is already "Interval", so the
                  // duration alone is a complete answer and need not be printed in seconds.
                  cell: (row: SourceHealth) =>
                    row.refresh_interval_seconds === 0
                      ? t("interval_every_tick")
                      : (secondsText(row.refresh_interval_seconds) ?? "—"),
                },
                {
                  id: "fetch",
                  label: t("last_successful_fetch"),
                  cell: (row: SourceHealth) => (
                    <div className="stack-sm">
                      <span>{serverLabel(row.last_successful_fetch, null, bcp47) ?? "—"}</span>
                      <span className="meta">
                        {t("records_found")}: {row.last_fetch_count}
                      </span>
                    </div>
                  ),
                },
                {
                  id: "errors",
                  label: t("consecutive_failures"),
                  cell: (row: SourceHealth) => (
                    <div className="stack-sm">
                      <span className={row.consecutive_failures ? "breach" : "meta"}>
                        {row.consecutive_failures}
                      </span>
                      {row.last_error ? (
                        <span className="meta">{row.last_error}</span>
                      ) : null}
                      {row.last_error_at ? (
                        <span className="meta mono">{formatStamp(row.last_error_at, bcp47)}</span>
                      ) : null}
                    </div>
                  ),
                },
                {
                  id: "notes",
                  label: t("source_notes"),
                  cell: (row: SourceHealth) => (
                    <div className="stack-sm">
                      {row.notes ? <span className="meta">{row.notes}</span> : null}
                      {row.url ? (
                        <a className="meta" href={row.url} target="_blank" rel="noreferrer noopener">
                          {t("open_source")} ↗
                        </a>
                      ) : null}
                      {row.enabled ? null : <span className="meta">{t("offline_disabled")}</span>}
                    </div>
                  ),
                },
                {
                  id: "action",
                  label: t("col_action"),
                  cell: (row: SourceHealth) =>
                    canRun ? (
                      <button
                        type="button"
                        className="button small"
                        disabled={busy !== null}
                        onClick={() => void runOne(row.code)}
                      >
                        {busy === row.code ? t("sending") : t("run_source")}
                      </button>
                    ) : (
                      <span className="meta">—</span>
                    ),
                },
              ]}
              rows={data.items}
              keyOf={(row) => row.code}
            />
          </section>
        )}
      </Panel>

      <SubSection title={t("ingestion_runs")} count={runs.data?.items.length}>
        <Panel state={runs} isEmpty={(data) => data.items.length === 0} emptyTitle={t("bucket_empty")}>
          {(data) => (
            <>
              <MetaStrip generatedAt={sources.data?.generated_at} />
              <DataTable
                columns={[
                  {
                    id: "source",
                    label: t("source"),
                    cell: (row: IngestionRunRow) => <span className="mono">{row.source}</span>,
                  },
                  {
                    id: "status",
                    label: t("status"),
                    cell: (row: IngestionRunRow) => (
                      // A run's `ok`/`error` is not a `SourceStatus`: a healthy source has failing
                      // runs and a failing source has runs that succeeded. Two vocabularies, two
                      // maps - merging them is how "Ran" and "Healthy" come to mean the same cell.
                      <span className={`chip provenance${row.error ? " breach" : ""}`}>
                        {enumLabel(RUN_STATUS_KEYS, row.status)}
                      </span>
                    ),
                  },
                  { id: "found", label: t("records_found"), numeric: true, cell: (row: IngestionRunRow) => row.records_found },
                  { id: "new", label: t("records_new"), numeric: true, cell: (row: IngestionRunRow) => row.records_new },
                  {
                    id: "updated",
                    label: t("records_updated"),
                    numeric: true,
                    cell: (row: IngestionRunRow) => row.records_updated,
                  },
                  {
                    id: "started",
                    label: t("col_time"),
                    cell: (row: IngestionRunRow) => formatStamp(row.started_at, bcp47) ?? "—",
                  },
                  {
                    id: "error",
                    label: t("col_error"),
                    cell: (row: IngestionRunRow) => row.error ?? "—",
                  },
                ]}
                rows={data.items}
                keyOf={(row) => row.id}
              />
            </>
          )}
        </Panel>
      </SubSection>
    </Screen>
  );
}
