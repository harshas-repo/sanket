/**
 * REPORTS - what people sent, and whether an operator has checked it.
 *
 * `GET /api/rc/reports` filters by district, by incident, and by whether duplicates are wanted.
 * It does not filter by verification state, so "show me everything still unverified" is the
 * dashboard's number and not a view of this list - the operator reads the state in a column
 * instead. Recorded in docs/known-issues.md rather than papered over with a client-side filter,
 * because a filter that only narrows the hundred rows already loaded looks like it searched the
 * whole table.
 *
 * Nothing here is computed by this screen. The verification state, the urgency and the corroboration
 * count all arrive from the server, which is what keeps this list and the incident it feeds from
 * disagreeing about the same message.
 */

import { useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../../api/client";
import type { CommunityReport } from "../../api/types";
import { DemoChip, ProvenanceBadge, UrgencyTag } from "../../components/Chips";
import { Panel } from "../../components/StatePanel";
import { DataTable, MetaStrip, RefreshRow, Screen, TextFilter } from "../../components/rc/parts";
import { useAsync, usePolling } from "../../hooks/useAsync";
import { useI18n } from "../../i18n/I18nContext";
import {
  HAZARD_KEYS,
  LOCATION_CONFIDENCE_KEYS_STAFF,
  REPORT_TYPE_KEYS,
  VERIFICATION_KEYS,
} from "../../i18n/strings";
import { serverLabel } from "../../utils/time";

export function ReportsPage() {
  const { t, enumLabel, bcp47 } = useI18n();
  const [district, setDistrict] = useState("");
  const [includeDuplicates, setIncludeDuplicates] = useState(false);

  const state = useAsync(
    (signal) =>
      api.rc.reports(
        {
          district: district.trim() || undefined,
          include_duplicates: includeDuplicates || undefined,
          limit: 100,
        },
        signal,
      ),
    [district, includeDuplicates],
  );
  const paused = usePolling(state.reload, 60_000);

  return (
    <Screen title={t("nav_reports")} intro={t("reports_intro")}>
      <RefreshRow onRefresh={state.reload} seconds={60} paused={paused} />

      <section className="card">
        <div className="filter-grid">
          <TextFilter label={t("filter_district")} value={district} onChange={setDistrict} />
        </div>
        <label className="checkbox-row">
          <input
            type="checkbox"
            checked={includeDuplicates}
            onChange={(event) => setIncludeDuplicates(event.target.checked)}
          />
          {/* Off by default because a duplicate is the same event twice, and counting it as a
              second report would make one landslide look like two. */}
          <span>{t("include_duplicates")}</span>
        </label>
      </section>

      <Panel state={state} isEmpty={(data) => data.items.length === 0} emptyTitle={t("bucket_empty")}>
        {(data) => (
          <section className="card">
            <MetaStrip
              generatedAt={null}
              extra={t("showing_of", { shown: data.items.length, total: data.count })}
            />
            <DataTable
              columns={[
                {
                  id: "message",
                  label: t("description"),
                  cell: (row: CommunityReport) => (
                    <div className="stack-sm">
                      <span className="row">
                        {row.demo ? <DemoChip /> : null}
                        <Link to={`/response-center/reports/${encodeURIComponent(row.id)}`}>
                          {row.message.slice(0, 90)}
                          {row.message.length > 90 ? "…" : ""}
                        </Link>
                      </span>
                      <span className="meta">
                        {enumLabel(REPORT_TYPE_KEYS, row.report_type)}
                        {row.corroborating_count > 1
                          ? ` · ${t("corroboration")}: ${row.corroborating_count}`
                          : ""}
                      </span>
                    </div>
                  ),
                },
                {
                  id: "hazard",
                  label: t("filter_type"),
                  cell: (row: CommunityReport) =>
                    row.incident_type ? enumLabel(HAZARD_KEYS, row.incident_type) : "—",
                },
                {
                  id: "where",
                  label: t("location"),
                  cell: (row: CommunityReport) => (
                    <div className="stack-sm">
                      <span>{row.district ?? "—"}</span>
                      {/* How sure we are this is the place, in words: a message geocoded from a
                          profile is not the same evidence as one with a coordinate. The staff map,
                          because one of these values tells the reader about their own profile. */}
                      <span className="meta">
                        {enumLabel(LOCATION_CONFIDENCE_KEYS_STAFF, row.location_confidence)}
                      </span>
                    </div>
                  ),
                },
                {
                  id: "verification",
                  label: t("status"),
                  cell: (row: CommunityReport) => (
                    <span className="row">
                      <span className="chip provenance">
                        {enumLabel(VERIFICATION_KEYS, row.verification_status)}
                      </span>
                      {row.duplicate_status === "duplicate" ? (
                        <span className="chip provenance">
                          {enumLabel(VERIFICATION_KEYS, "duplicate")}
                        </span>
                      ) : null}
                    </span>
                  ),
                },
                {
                  id: "urgency",
                  label: t("col_urgency"),
                  cell: (row: CommunityReport) => <UrgencyTag value={row.urgency} />,
                },
                {
                  id: "when",
                  label: t("col_time"),
                  cell: (row: CommunityReport) => serverLabel(row.at, row.age, bcp47) ?? "—",
                },
                {
                  id: "provenance",
                  label: t("source"),
                  cell: (row: CommunityReport) => <ProvenanceBadge value={row.provenance} />,
                },
                {
                  id: "open",
                  label: t("col_action"),
                  cell: (row: CommunityReport) => (
                    <Link
                      className="button small"
                      to={`/response-center/reports/${encodeURIComponent(row.id)}`}
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
