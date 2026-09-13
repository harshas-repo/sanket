/**
 * AUDIT - who changed what, when, and what the record said before they did.
 *
 * §55 makes this screen a promise rather than a feature: a person's help request is only held
 * here because the platform can account for every hand that touched it. So `previous` and `new`
 * are both printed, on every row, including the ones where nothing interesting changed. A log
 * that shows the new value alone is a record of outcomes, and an outcome nobody can trace back
 * to the value it replaced cannot be argued with.
 *
 * `entity_id` is offered as a filter with its own caveat printed beside it: the backend only
 * applies it alongside `entity_type`, so an id typed on its own silently returns everything.
 * A filter that looks applied and is not would be the worst thing on this page.
 */

import { useState } from "react";

import { api } from "../../api/client";
import type { AuditEvent } from "../../api/types";
import { Panel } from "../../components/StatePanel";
import {
  DataTable,
  Delta,
  EntityLink,
  EnumSelect,
  MetaStrip,
  RefreshRow,
  Screen,
  SubSection,
  TextFilter,
} from "../../components/rc/parts";
import { useAsync, usePolling } from "../../hooks/useAsync";
import { useI18n } from "../../i18n/I18nContext";
import { ACTION_KEYS, ACTOR_KIND_KEYS, ENTITY_KEYS } from "../../i18n/strings";
import { formatStamp } from "../../utils/time";

/** `GET /api/rc/audit` caps `limit` at 500. */
const LIMITS = [50, 100, 250, 500];

export function AuditPage() {
  const { t, enumLabel, bcp47 } = useI18n();

  const [entityType, setEntityType] = useState("");
  const [actorKind, setActorKind] = useState("");
  const [entityId, setEntityId] = useState("");
  const [limit, setLimit] = useState(100);

  const state = useAsync(
    () =>
      api.rc.audit({
        entity_type: entityType || undefined,
        actor_kind: actorKind || undefined,
        entity_id: entityId.trim() || undefined,
        limit,
      }),
    [entityType, actorKind, entityId, limit],
  );
  // Slower than the activity feed on purpose: this page is read after the fact, and a
  // half-thousand-row refresh every thirty seconds is noise for nobody's benefit.
  const paused = usePolling(state.reload, 120_000);

  const idWithoutType = Boolean(entityId.trim()) && !entityType;

  return (
    <Screen title={t("nav_audit")} intro={t("audit_intro")}>
      <RefreshRow onRefresh={state.reload} seconds={120} paused={paused} />

      <section className="card">
        <div className="filter-grid">
          <EnumSelect
            label={t("filter_entity")}
            keys={ENTITY_KEYS}
            value={entityType}
            onChange={setEntityType}
          />
          <EnumSelect
            label={t("col_actor")}
            keys={ACTOR_KIND_KEYS}
            value={actorKind}
            onChange={setActorKind}
          />
          <TextFilter label={t("col_record")} value={entityId} onChange={setEntityId} />
          <div className="field">
            <label htmlFor="audit-limit">{t("col_count")}</label>
            <select
              id="audit-limit"
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
        </div>
        {idWithoutType ? (
          <p className="field-hint breach" role="note">
            {t("audit_entity_id_hint")}
          </p>
        ) : null}
      </section>

      <Panel state={state} isEmpty={(data) => data.items.length === 0} emptyTitle={t("bucket_empty")}>
        {(data) => (
          <SubSection title={t("nav_audit")} count={data.count}>
            <MetaStrip extra={t("showing_of", { shown: data.items.length, total: data.count })} />
            <DataTable
              columns={[
                {
                  id: "at",
                  label: t("col_time"),
                  cell: (row: AuditEvent) => formatStamp(row.at, bcp47) ?? "—",
                },
                {
                  id: "action",
                  label: t("col_action"),
                  cell: (row: AuditEvent) => enumLabel(ACTION_KEYS, row.action),
                },
                {
                  id: "actor",
                  label: t("col_actor"),
                  cell: (row: AuditEvent) => (
                    <div className="stack-sm">
                      <span>{row.actor ?? "—"}</span>
                      <span className="meta">{enumLabel(ACTOR_KIND_KEYS, row.actor_kind)}</span>
                    </div>
                  ),
                },
                {
                  id: "entity",
                  label: t("col_record"),
                  cell: (row: AuditEvent) => (
                    <div className="stack-sm">
                      <span className="meta">{enumLabel(ENTITY_KEYS, row.entity_type)}</span>
                      <EntityLink entityType={row.entity_type} entityId={row.entity_id} />
                    </div>
                  ),
                },
                {
                  id: "change",
                  label: t("changes_to_record"),
                  cell: (row: AuditEvent) => (
                    <div className="stack-sm">
                      <span className="meta">
                        {t("before")}: <Delta value={row.previous} />
                      </span>
                      <span className="meta">
                        {t("after")}: <Delta value={row.new} />
                      </span>
                    </div>
                  ),
                },
                {
                  id: "reason",
                  label: t("reason"),
                  cell: (row: AuditEvent) =>
                    row.reason ? <span className="meta">{row.reason}</span> : <span className="meta">—</span>,
                },
              ]}
              rows={data.items}
              keyOf={(row) => row.id}
            />
          </SubSection>
        )}
      </Panel>
    </Screen>
  );
}
