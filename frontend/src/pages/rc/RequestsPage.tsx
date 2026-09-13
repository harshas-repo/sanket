/**
 * Every open help request, filterable by the three things a coordinator actually splits work by:
 * status, urgency, and whether anyone has taken it.
 *
 * The queue is the prioritised version of this list; this is the version you use when you are
 * allocating people ("show me everything unassigned in Sindhupalchok"). Both call the same
 * endpoint with different parameters, so they cannot disagree about what is open.
 */

import { useState } from "react";

import { Link } from "react-router-dom";

import { api } from "../../api/client";
import type { AssistanceRequest } from "../../api/types";
import { DemoChip, UrgencyTag } from "../../components/Chips";
import { Panel } from "../../components/StatePanel";
import { DataTable, EnumSelect, MetaStrip, RefreshRow, Screen, TextFilter } from "../../components/rc/parts";
import { useAsync, usePolling } from "../../hooks/useAsync";
import { useI18n } from "../../i18n/I18nContext";
import { ASSISTANCE_STATUS_KEYS, URGENCY_KEYS } from "../../i18n/strings";
import { serverLabel } from "../../utils/time";

export function RequestsPage() {
  const { t, enumLabel, bcp47 } = useI18n();
  const [status, setStatus] = useState("");
  const [urgency, setUrgency] = useState("");
  const [district, setDistrict] = useState("");
  const [unassignedOnly, setUnassignedOnly] = useState(false);

  const state = useAsync(
    (signal) =>
      api.rc.requests(
        {
          status: status || undefined,
          urgency: urgency || undefined,
          district: district.trim() || undefined,
          unassigned_only: unassignedOnly || undefined,
          limit: 200,
        },
        signal,
      ),
    [status, urgency, district, unassignedOnly],
  );
  const paused = usePolling(state.reload, 45_000);

  return (
    <Screen title={t("nav_requests")}>
      <RefreshRow generatedAt={state.data?.generated_at} onRefresh={state.reload} seconds={45} paused={paused} />

      <section className="card">
        <div className="filter-grid">
          <EnumSelect label={t("status")} keys={ASSISTANCE_STATUS_KEYS} value={status} onChange={setStatus} />
          <EnumSelect label={t("filter_urgency")} keys={URGENCY_KEYS} value={urgency} onChange={setUrgency} />
          <TextFilter label={t("filter_district")} value={district} onChange={setDistrict} />
        </div>
        <label className="checkbox-row">
          <input
            type="checkbox"
            checked={unassignedOnly}
            onChange={(event) => setUnassignedOnly(event.target.checked)}
          />
          <span>{t("unassigned_only")}</span>
        </label>
      </section>

      <Panel state={state} isEmpty={(data) => data.items.length === 0} emptyTitle={t("queue_is_empty")}>
        {(data) => (
          <section className="card">
            <MetaStrip generatedAt={null} extra={t("showing_of", { shown: data.items.length, total: data.count })} />
            <DataTable
              columns={[
                {
                  id: "request",
                  label: t("description"),
                  cell: (row: AssistanceRequest) => (
                    <div className="stack-sm">
                      <span className="row">
                        {row.demo ? <DemoChip /> : null}
                        <Link to={`/response-center/requests/${encodeURIComponent(row.ref_code)}`}>
                          {row.ref_code}
                        </Link>
                        <UrgencyTag value={row.urgency} />
                      </span>
                      <span className="meta">{row.description}</span>
                    </div>
                  ),
                },
                { id: "type", label: t("request_type"), cell: (row: AssistanceRequest) => row.request_type },
                {
                  // The reader's words, not the server's `status_label`: that one follows the
                  // language the *requester* wrote in, which is right on their phone and wrong
                  // in a control room reading a mix of both languages. See known issue 38.
                  id: "status",
                  label: t("status"),
                  cell: (row: AssistanceRequest) => enumLabel(ASSISTANCE_STATUS_KEYS, row.status),
                },
                { id: "district", label: t("col_district"), cell: (row: AssistanceRequest) => row.district ?? "—" },
                {
                  id: "assigned",
                  label: t("assigned_to"),
                  cell: (row: AssistanceRequest) => row.assigned_team ?? row.assigned_to ?? "—",
                },
                {
                  id: "when",
                  label: t("col_time"),
                  cell: (row: AssistanceRequest) => serverLabel(row.created_at, row.age, bcp47) ?? "—",
                },
                {
                  id: "open",
                  label: t("col_action"),
                  cell: (row: AssistanceRequest) => (
                    <Link
                      className="button small"
                      to={`/response-center/requests/${encodeURIComponent(row.ref_code)}`}
                    >
                      {t("open_record")}
                    </Link>
                  ),
                },
              ]}
              rows={data.items}
              keyOf={(row) => row.id}
            />
          </section>
        )}
      </Panel>
    </Screen>
  );
}
