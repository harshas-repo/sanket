/**
 * ACTIVITY - what the platform did, in the order it did it.
 *
 * This is the audit trail read as a feed: `/api/rc/activity` and `/api/rc/audit` answer from the
 * same table, and the feed adds one field the log does not - `summary`, the server's own sentence
 * for what changed. That sentence is printed as it arrived rather than reassembled here, because
 * a summary composed on the client would be a second account of the same event, and two accounts
 * that disagree is exactly what an audit trail exists to prevent.
 *
 * Ages are shown next to a formatted timestamp, not instead of one. "3 minutes ago" on a screen
 * that was opened an hour ago is a claim about the moment the page was painted; the stamp is a
 * claim about the event.
 */

import { useState } from "react";

import { api } from "../../api/client";
import type { ActivityEvent } from "../../api/types";
import { Panel } from "../../components/StatePanel";
import {
  DataTable,
  EntityLink,
  MetaStrip,
  RefreshRow,
  Screen,
  SubSection,
} from "../../components/rc/parts";
import { useAsync, usePolling } from "../../hooks/useAsync";
import { useI18n } from "../../i18n/I18nContext";
import { ACTION_KEYS, ACTOR_KIND_KEYS, ENTITY_KEYS } from "../../i18n/strings";
import { formatStamp } from "../../utils/time";

/** `GET /api/rc/activity` caps `limit` at 200. */
const LIMITS = [25, 50, 100, 200];

export function ActivityPage() {
  const { t, enumLabel, bcp47 } = useI18n();
  const [limit, setLimit] = useState(50);

  const state = useAsync(() => api.rc.activity(limit), [limit]);
  const paused = usePolling(state.reload, 30_000);

  return (
    <Screen title={t("nav_activity")} intro={t("activity_intro")}>
      <RefreshRow onRefresh={state.reload} seconds={30} paused={paused} />

      <section className="card">
        <div className="row">
          <div className="field">
            <label htmlFor="activity-limit">{t("col_count")}</label>
            <select
              id="activity-limit"
              value={String(limit)}
              onChange={(event) => setLimit(Number(event.target.value))}
            >
              {LIMITS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </div>
          {/* Stated rather than left to be discovered: an operator who works out on their own
              that this tab and the audit log are the same rows stops trusting one of them. */}
          <p className="meta">{t("activity_is_audit")}</p>
        </div>
      </section>

      <Panel state={state} isEmpty={(data) => data.items.length === 0} emptyTitle={t("bucket_empty")}>
        {(data) => (
          <SubSection title={t("nav_activity")} count={data.items.length}>
            <MetaStrip extra={t("showing_of", { shown: data.items.length, total: data.items.length })} />
            <DataTable
              columns={[
                {
                  id: "at",
                  label: t("col_time"),
                  cell: (row: ActivityEvent) => (
                    <div className="stack-sm">
                      <span>{formatStamp(row.at, bcp47) ?? "—"}</span>
                      {/* The server's own age. It is English in both languages - a localisation
                          gap recorded in docs/known-issues.md, not a choice made here. */}
                      {row.age ? <span className="meta">{row.age}</span> : null}
                    </div>
                  ),
                },
                {
                  id: "action",
                  label: t("col_action"),
                  cell: (row: ActivityEvent) => enumLabel(ACTION_KEYS, row.action),
                },
                {
                  id: "actor",
                  label: t("col_actor"),
                  cell: (row: ActivityEvent) => (
                    <div className="stack-sm">
                      <span>{row.actor ?? "—"}</span>
                      <span className="meta">{enumLabel(ACTOR_KIND_KEYS, row.actor_kind)}</span>
                    </div>
                  ),
                },
                {
                  id: "entity",
                  label: t("col_record"),
                  cell: (row: ActivityEvent) => (
                    <div className="stack-sm">
                      <span className="meta">{enumLabel(ENTITY_KEYS, row.entity_type)}</span>
                      <EntityLink entityType={row.entity_type} entityId={row.entity_id} />
                    </div>
                  ),
                },
                { id: "summary", label: t("col_summary"), cell: (row: ActivityEvent) => row.summary },
                {
                  id: "reason",
                  label: t("reason"),
                  cell: (row: ActivityEvent) =>
                    row.reason ? <span className="meta">{row.reason}</span> : <span className="meta">—</span>,
                },
              ]}
              rows={data.items}
              // `at` alone repeats when a batch of steps lands in the same second, and `action`
              // alone repeats every time one operator does the same thing twice.
              keyOf={(row, index) => `${row.at ?? "?"}-${row.entity_id}-${row.action}-${index}`}
            />
          </SubSection>
        )}
      </Panel>
    </Screen>
  );
}
