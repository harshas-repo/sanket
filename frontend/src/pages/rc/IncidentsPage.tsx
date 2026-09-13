/**
 * The incident register: one row per event, filterable, with the score next to the row it came
 * from.
 *
 * Filters are sent to the server rather than applied to the page it returned. `/api/incidents`
 * answers with up to `limit` rows already ordered by the scoring formula, so filtering ten thousand
 * records client-side would show a filtered view of whichever hundred rows happened to arrive -
 * which looks identical to "no matches in the country" and is far more dangerous.
 *
 * The event-type filter lists the eight hazard types this build knows about. A record filed under
 * a type outside that list cannot be reached from this dropdown; it is still in the register under
 * "All", and that limitation is written in docs/known-issues.md rather than hidden here.
 */

import { useState } from "react";

import { Link } from "react-router-dom";

import { api } from "../../api/client";
import type { Incident } from "../../api/types";
import { DemoChip, EvidenceChip, Score, UrgencyTag } from "../../components/Chips";
import { Panel } from "../../components/StatePanel";
import { DataTable, EnumSelect, MetaStrip, RefreshRow, Screen, TextFilter } from "../../components/rc/parts";
import { useAsync, usePolling } from "../../hooks/useAsync";
import { useI18n } from "../../i18n/I18nContext";
import { EVIDENCE_KEYS, HAZARD_KEYS, INCIDENT_STATUS_KEYS, URGENCY_KEYS } from "../../i18n/strings";
import { serverLabel } from "../../utils/time";

export function IncidentsPage() {
  const { t, enumLabel, bcp47 } = useI18n();
  const [urgency, setUrgency] = useState("");
  const [evidence, setEvidence] = useState("");
  const [type, setType] = useState("");
  const [district, setDistrict] = useState("");
  const [query, setQuery] = useState("");
  const [includeArchived, setIncludeArchived] = useState(false);

  const state = useAsync(
    (signal) =>
      api.incidents.list(
        {
          urgency: urgency || undefined,
          evidence_state: evidence || undefined,
          incident_type: type || undefined,
          district: district.trim() || undefined,
          q: query.trim() || undefined,
          include_archived: includeArchived || undefined,
          limit: 100,
        },
        signal,
      ),
    [urgency, evidence, type, district, query, includeArchived],
  );
  const paused = usePolling(state.reload, 60_000);

  const filtered = Boolean(urgency || evidence || type || district || query);
  const clear = () => {
    setUrgency("");
    setEvidence("");
    setType("");
    setDistrict("");
    setQuery("");
  };

  return (
    <Screen title={t("nav_incidents")} intro={t("incidents_intro")}>
      <RefreshRow generatedAt={state.data?.generated_at} onRefresh={state.reload} seconds={60} paused={paused} />

      <section className="card">
        <div className="filter-grid">
          <TextFilter label={t("search")} value={query} onChange={setQuery} placeholder={t("search")} />
          <TextFilter label={t("filter_district")} value={district} onChange={setDistrict} />
          <EnumSelect label={t("filter_urgency")} keys={URGENCY_KEYS} value={urgency} onChange={setUrgency} />
          <EnumSelect label={t("filter_evidence")} keys={EVIDENCE_KEYS} value={evidence} onChange={setEvidence} />
          <EnumSelect label={t("filter_type")} keys={HAZARD_KEYS} value={type} onChange={setType} />
        </div>
        <div className="row-between">
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={includeArchived}
              onChange={(event) => setIncludeArchived(event.target.checked)}
            />
            <span>{t("show_archived")}</span>
          </label>
          <div className="row">
            {filtered ? (
              <button type="button" className="button small" onClick={clear}>
                {t("clear_filters")}
              </button>
            ) : null}
            {state.data ? (
              <span className="meta">
                {t("showing_of", { shown: state.data.items.length, total: state.data.count })}
              </span>
            ) : null}
          </div>
        </div>
      </section>

      <Panel
        state={state}
        isEmpty={(data) => data.items.length === 0}
        emptyTitle={t("no_incidents_match")}
      >
        {(data) => (
          <section className="card">
            <MetaStrip generatedAt={data.generated_at} stale={Boolean(state.error)} />
            <DataTable
              columns={[
                {
                  id: "incident",
                  label: t("col_incident"),
                  cell: (row: Incident) => (
                    <div className="stack-sm">
                      <span className="row">
                        {row.demo ? <DemoChip /> : null}
                        <Link to={`/response-center/incidents/${encodeURIComponent(row.id)}`}>
                          {row.title}
                        </Link>
                      </span>
                      <span className="row">
                        <span className="mono">{row.ref_code}</span>
                        <span className="meta">{enumLabel(HAZARD_KEYS, row.incident_type)}</span>
                        {row.location_name ? <span className="meta">{row.location_name}</span> : null}
                      </span>
                      {row.needs_review && row.review_reason ? (
                        <span className="notice warn">{t("review_flag", { reason: row.review_reason })}</span>
                      ) : null}
                    </div>
                  ),
                },
                {
                  id: "district",
                  label: t("col_district"),
                  cell: (row: Incident) => row.district ?? "—",
                },
                {
                  id: "state",
                  label: t("col_urgency"),
                  cell: (row: Incident) => (
                    <div className="row">
                      <UrgencyTag value={row.urgency} />
                      <EvidenceChip value={row.evidence_state} title={row.prioritization_reasons[0]} />
                    </div>
                  ),
                },
                {
                  id: "status",
                  label: t("col_status"),
                  cell: (row: Incident) => enumLabel(INCIDENT_STATUS_KEYS, row.status),
                },
                {
                  id: "score",
                  label: t("col_score"),
                  numeric: true,
                  cell: (row: Incident) => <Score value={row.impact_score} band={row.score_band} />,
                },
                {
                  id: "counts",
                  label: t("col_reports"),
                  numeric: true,
                  cell: (row: Incident) => (
                    <span className="meta">
                      {row.community_report_count} / {row.open_assistance_count}
                    </span>
                  ),
                },
                {
                  id: "updated",
                  label: t("updated"),
                  cell: (row: Incident) =>
                    serverLabel(row.last_updated_at, row.updated_label, bcp47) ?? "—",
                },
                {
                  id: "open",
                  label: t("col_action"),
                  cell: (row: Incident) => (
                    <Link
                      className="button small"
                      to={`/response-center/incidents/${encodeURIComponent(row.id)}`}
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
