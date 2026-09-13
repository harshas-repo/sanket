/**
 * One incident, everything the console is allowed to know about it, and the reasoning next to
 * the number it explains.
 *
 * This is the screen the map's "open full record" link lands on. Three rules shape it:
 *
 * The score never appears alone. `why_prioritized` carries the components, the weights and the
 * formula string the server used, so an operator who disagrees with a ranking can see which term
 * they disagree with and say so in a review note.
 *
 * Every claim names its record. The evidence block lists the observations behind the incident with
 * their source, authority and own timestamp; a statement with no record behind it is shown as
 * having none rather than being smoothed over.
 *
 * Nothing here is generated language. The assistant is a separate screen with its own provenance;
 * mixing its prose into the record would make a guess indistinguishable from an entry.
 */

import { Link, useParams } from "react-router-dom";

import { api } from "../../api/client";
import type {
  AssistanceRequest,
  AuditEvent,
  CommunityReport,
  EvidenceRecord,
  Incident,
  ScoreComponent,
  TimelineEvent,
} from "../../api/types";
import {
  DemoChip,
  EvidenceChip,
  FreshnessChip,
  PrecisionChip,
  ProvenanceBadge,
  Score,
  UrgencyTag,
} from "../../components/Chips";
import { Failed, Loading, Panel } from "../../components/StatePanel";
import { IncidentActions } from "../../components/rc/Actions";
import {
  DataTable,
  Delta,
  FieldGrid,
  MetaStrip,
  ReasonList,
  RefreshRow,
  Screen,
  SubSection,
} from "../../components/rc/parts";
import { useAsync, usePolling } from "../../hooks/useAsync";
import { useI18n } from "../../i18n/I18nContext";
import { ASSISTANCE_STATUS_KEYS, HAZARD_KEYS, INCIDENT_STATUS_KEYS } from "../../i18n/strings";
import { formatStamp, serverLabel } from "../../utils/time";

export function IncidentDetailPage() {
  const { incidentId = "" } = useParams();
  const { t, enumLabel, bcp47 } = useI18n();
  const state = useAsync((signal) => api.rc.incident(incidentId, signal), [incidentId]);
  const paused = usePolling(state.reload, 60_000);

  if (state.loading) return <Loading />;
  if (state.error && !state.data) {
    return state.error.notFound || state.error.forbidden ? (
      <Failed error={new Error(t("record_not_found"))} onRetry={state.reload} />
    ) : (
      <Failed error={state.error} onRetry={state.reload} />
    );
  }

  return (
    <Panel state={state}>
      {(data) => {
        const incident = data.incident;
        const evidence = data.evidence;
        const why = data.why_prioritized;
        const impact = incident.impact;

        return (
          <Screen
            title={incident.title}
            actions={
              <Link className="button small" to="/response-center/incidents">
                {t("back_to_incidents")}
              </Link>
            }
          >
            <RefreshRow generatedAt={null} onRefresh={state.reload} seconds={60} paused={paused} />

            <section className="card stack-sm">
              <div className="row">
                <span className="mono">{incident.ref_code}</span>
                <span className="meta">{enumLabel(HAZARD_KEYS, incident.incident_type)}</span>
                {incident.demo ? <DemoChip /> : null}
              </div>
              <div className="row">
                <UrgencyTag value={incident.urgency} />
                <EvidenceChip value={incident.evidence_state} title={evidence.meaning} />
                <FreshnessChip
                  value={incident.freshness_state}
                  label={incident.updated_label}
                  title={serverLabel(incident.last_updated_at, incident.updated_label, bcp47) ?? undefined}
                />
                <PrecisionChip value={incident.location_precision} />
                <ProvenanceBadge value={incident.provenance} />
                <span className="chip">{enumLabel(INCIDENT_STATUS_KEYS, incident.status)}</span>
                <Score value={incident.impact_score} band={incident.score_band} />
              </div>

              {incident.needs_review ? (
                <p className="notice warn">
                  {t("review_flag", { reason: incident.review_reason ?? t("needs_review") })}
                </p>
              ) : null}

              <FieldGrid
                items={[
                  { label: t("district"), value: incident.district },
                  { label: t("province"), value: incident.province, when: Boolean(incident.province) },
                  {
                    label: t("location"),
                    value: incident.location_name ?? incident.local_municipality,
                  },
                  {
                    label: t("event_time"),
                    value: serverLabel(incident.event_time, incident.event_time_label, bcp47),
                  },
                  {
                    label: t("magnitude"),
                    value: incident.magnitude,
                    when: incident.magnitude !== null,
                  },
                  { label: t("deaths"), value: impact.deaths, when: Boolean(impact.deaths) },
                  { label: t("injured"), value: impact.injured, when: Boolean(impact.injured) },
                  { label: t("missing"), value: impact.missing, when: Boolean(impact.missing) },
                  { label: t("affected"), value: impact.affected_people, when: Boolean(impact.affected_people) },
                  { label: t("houses_damaged"), value: impact.houses_damaged, when: Boolean(impact.houses_damaged) },
                  { label: t("displaced_persons"), value: impact.displaced_persons, when: Boolean(impact.displaced_persons) },
                  { label: t("col_reports"), value: incident.community_report_count },
                  { label: t("col_requests"), value: incident.open_assistance_count },
                  {
                    label: t("conflicting_records"),
                    value: incident.conflicting_signal_count,
                    when: incident.conflicting_signal_count > 0,
                  },
                  {
                    label: t("duplicates_merged"),
                    value: incident.duplicate_count,
                    when: incident.duplicate_count > 0,
                  },
                ]}
              />
            </section>

            <SubSection title={t("why_prioritized")}>
              <p>{why.headline}</p>
              <ReasonList items={why.reasons} />
              <p className="meta">{why.explanation}</p>
              <div className="row">
                <span className="mono">
                  {t("impact_score")}: {Math.round(why.score)} ({why.score_band})
                </span>
                <span className="mono">
                  {t("freshness_multiplier")}: {why.freshness_multiplier}
                </span>
              </div>
              <p className="mono formula">{why.formula}</p>
              <DataTable
                columns={[
                  { id: "name", label: t("col_type"), cell: (row: [string, ScoreComponent]) => row[0] },
                  { id: "raw", label: t("col_raw"), numeric: true, cell: (row: [string, ScoreComponent]) => row[1].raw },
                  { id: "weight", label: t("col_weight"), numeric: true, cell: (row: [string, ScoreComponent]) => row[1].weight },
                  {
                    id: "contribution",
                    label: t("col_contribution"),
                    numeric: true,
                    cell: (row: [string, ScoreComponent]) => row[1].contribution,
                  },
                ]}
                rows={Object.entries(why.components)}
                keyOf={(row) => row[0]}
              />
            </SubSection>

            <SubSection
              title={t("evidence_behind")}
              note={`${evidence.label} - ${evidence.meaning}`}
              count={evidence.source_count}
            >
              <div className="row">
                {evidence.official_confirmation ? (
                  <span className="notice">{t("confirmed_by")}: {evidence.confirmed_by_source ?? "—"}</span>
                ) : null}
                {evidence.verified_by_operator ? <span className="notice">{t("verified_by_operator")}</span> : null}
                {evidence.conflicting_count ? (
                  <span className="notice warn">
                    {t("conflicting_records")}: {evidence.conflicting_count}
                  </span>
                ) : null}
              </div>
              {evidence.records.length ? (
                <DataTable
                  columns={[
                    {
                      id: "record",
                      label: t("details"),
                      cell: (row: EvidenceRecord) => (
                        <div className="stack-sm">
                          <span className="row">
                            <strong>{row.title ?? row.summary ?? row.kind}</strong>
                            <span className="meta">{enumLabel(HAZARD_KEYS, row.incident_type ?? "")}</span>
                          </span>
                          <span className="meta">{row.summary}</span>
                          <span className="row">
                            <span>{row.source_name}</span>
                            {row.source_organization ? (
                              <span className="meta">{row.source_organization}</span>
                            ) : null}
                            {row.source_url ? (
                              <a href={row.source_url} target="_blank" rel="noreferrer">
                                {t("open_source")}
                              </a>
                            ) : null}
                          </span>
                        </div>
                      ),
                    },
                    { id: "role", label: t("col_role"), cell: (row: EvidenceRecord) => row.role },
                    { id: "authority", label: t("col_authority"), numeric: true, cell: (row: EvidenceRecord) => row.authority },
                    {
                      id: "when",
                      label: t("col_time"),
                      cell: (row: EvidenceRecord) => serverLabel(row.at, row.age, bcp47) ?? "—",
                    },
                    {
                      id: "numbers",
                      label: t("col_score"),
                      cell: (row: EvidenceRecord) => (
                        <span className="meta">
                          {[
                            row.deaths ? `${t("deaths")} ${row.deaths}` : null,
                            row.injured ? `${t("injured")} ${row.injured}` : null,
                            row.affected_people ? `${t("affected")} ${row.affected_people}` : null,
                          ]
                            .filter(Boolean)
                            .join(" · ") || "—"}
                        </span>
                      ),
                    },
                    {
                      id: "provenance",
                      label: t("source"),
                      cell: (row: EvidenceRecord) => (
                        <span className="row">
                          {row.demo ? <DemoChip /> : null}
                          <ProvenanceBadge value={row.provenance} />
                        </span>
                      ),
                    },
                  ]}
                  rows={evidence.records}
                  keyOf={(row) => `${row.observation_id}-${row.role}`}
                />
              ) : (
                <p className="notice warn">{t("no_source_records")}</p>
              )}
            </SubSection>

            <IncidentActions incidentId={incident.id} detail={data} onChanged={state.reload} />

            <SubSection title={t("attached_reports")} count={data.reports.length}>
              {data.reports.length ? (
                <DataTable
                  columns={[
                    {
                      id: "message",
                      label: t("description"),
                      cell: (row: CommunityReport) => (
                        <div className="stack-sm">
                          <span>{row.message}</span>
                          <span className="row">
                            <span className="mono">{row.id.slice(0, 8)}</span>
                            <span className="meta">{row.district ?? row.location_text ?? "—"}</span>
                            <span className="meta">{row.verification_status}</span>
                            {row.submitted_offline ? <span className="chip provenance">{t("queued_offline")}</span> : null}
                          </span>
                        </div>
                      ),
                    },
                    {
                      id: "when",
                      label: t("col_time"),
                      cell: (row: CommunityReport) => serverLabel(row.at, row.age, bcp47) ?? "—",
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
                  rows={data.reports}
                  keyOf={(row) => row.id}
                />
              ) : (
                <p className="meta">{t("attached_none")}</p>
              )}
            </SubSection>

            <SubSection title={t("attached_requests")} count={data.requests.length}>
              {data.requests.length ? (
                <DataTable
                  columns={[
                    {
                      id: "request",
                      label: t("description"),
                      cell: (row: AssistanceRequest) => (
                        <div className="stack-sm">
                          <span className="row">
                            <span className="mono">{row.ref_code}</span>
                            <UrgencyTag value={row.urgency} />
                            {row.demo ? <DemoChip /> : null}
                          </span>
                          <span>{row.description}</span>
                        </div>
                      ),
                    },
                    {
                      id: "status",
                      label: t("status"),
                      cell: (row: AssistanceRequest) => enumLabel(ASSISTANCE_STATUS_KEYS, row.status),
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
                  rows={data.requests}
                  keyOf={(row) => row.id}
                />
              ) : (
                <p className="meta">{t("attached_none")}</p>
              )}
            </SubSection>

            {data.signals.length ? (
              <SubSection title={t("attached_signals")} count={data.signals.length}>
                <ul className="reason-list">
                  {data.signals.map((signal) => (
                    <li key={`${signal.code}-${signal.district}`}>
                      <strong>{signal.label}</strong> · {signal.statement}
                      <span className="row">
                        <FreshnessChip value={signal.freshness_state} />
                        <ProvenanceBadge value={signal.provenance} />
                      </span>
                    </li>
                  ))}
                </ul>
              </SubSection>
            ) : null}

            {data.alerts.length ? (
              <SubSection title={t("attached_alerts")} count={data.alerts.length}>
                <ul className="reason-list">
                  {data.alerts.map((alert) => (
                    <li key={alert.id}>
                      <strong>{alert.title}</strong>
                      {alert.source_url ? (
                        <>
                          {" "}
                          <a href={alert.source_url} target="_blank" rel="noreferrer">
                            {t("open_source")}
                          </a>
                        </>
                      ) : null}
                      <span className="meta">
                        {alert.source_name} · {serverLabel(alert.published_at, alert.published_label, bcp47) ?? "—"}
                      </span>
                      {alert.demo ? <DemoChip /> : null}
                      <p>{alert.body}</p>
                    </li>
                  ))}
                </ul>
              </SubSection>
            ) : null}

            <SubSection title={t("timeline_title")} count={data.timeline.length}>
              {data.timeline.length ? (
                <DataTable
                  columns={[
                    {
                      id: "when",
                      label: t("col_time"),
                      cell: (row: TimelineEvent) => (
                        <span className="mono">{formatStamp(row.at, bcp47) ?? "—"}</span>
                      ),
                    },
                    { id: "kind", label: t("col_type"), cell: (row: TimelineEvent) => row.kind },
                    {
                      id: "what",
                      label: t("details"),
                      cell: (row: TimelineEvent) => (
                        <div className="stack-sm">
                          <span>{row.label}</span>
                          {row.detail ? <span className="meta">{row.detail}</span> : null}
                        </div>
                      ),
                    },
                    {
                      id: "provenance",
                      label: t("source"),
                      cell: (row: TimelineEvent) => <ProvenanceBadge value={row.provenance} />,
                    },
                  ]}
                  rows={data.timeline}
                  keyOf={(row, index) => `${row.at}-${row.kind}-${index}`}
                />
              ) : (
                <p className="meta">{t("no_timeline")}</p>
              )}
            </SubSection>

            {data.duplicates.length ? (
              <SubSection title={t("duplicates_merged")} count={data.duplicates.length}>
                <IncidentMiniList rows={data.duplicates} />
              </SubSection>
            ) : null}

            {data.related_incidents.length ? (
              <SubSection title={t("related_incidents")} count={data.related_incidents.length}>
                <IncidentMiniList rows={data.related_incidents} />
              </SubSection>
            ) : null}

            {data.audit.length ? (
              <SubSection title={t("changes_to_record")} count={data.audit.length}>
                <DataTable
                  columns={[
                    {
                      id: "when",
                      label: t("col_time"),
                      cell: (row: AuditEvent) => (
                        <span className="mono">{formatStamp(row.at, bcp47) ?? "—"}</span>
                      ),
                    },
                    { id: "action", label: t("col_action"), cell: (row: AuditEvent) => row.action },
                    { id: "actor", label: t("col_actor"), cell: (row: AuditEvent) => row.actor ?? "—" },
                    {
                      id: "before",
                      label: t("before"),
                      cell: (row: AuditEvent) => <Delta value={row.previous} />,
                    },
                    {
                      id: "after",
                      label: t("after"),
                      cell: (row: AuditEvent) => <Delta value={row.new} />,
                    },
                    { id: "reason", label: t("reason"), cell: (row: AuditEvent) => row.reason ?? "—" },
                  ]}
                  rows={data.audit}
                  keyOf={(row) => row.id}
                />
                <MetaStrip generatedAt={null} extra={t("demo_warning")} />
              </SubSection>
            ) : null}
          </Screen>
        );
      }}
    </Panel>
  );
}

/** Duplicates and related records are the same shape as a row of the register, so they render as one. */
function IncidentMiniList({ rows }: { rows: Incident[] }) {
  const { t, enumLabel, bcp47 } = useI18n();
  return (
    <DataTable
      columns={[
        {
          id: "incident",
          label: t("col_incident"),
          cell: (row: Incident) => (
            <span className="row">
              {row.demo ? <DemoChip /> : null}
              <Link to={`/response-center/incidents/${encodeURIComponent(row.id)}`}>{row.title}</Link>
            </span>
          ),
        },
        { id: "district", label: t("col_district"), cell: (row: Incident) => row.district ?? "—" },
        {
          id: "state",
          label: t("col_urgency"),
          cell: (row: Incident) => (
            <span className="row">
              <UrgencyTag value={row.urgency} />
              <EvidenceChip value={row.evidence_state} />
            </span>
          ),
        },
        {
          id: "status",
          label: t("col_status"),
          cell: (row: Incident) => enumLabel(INCIDENT_STATUS_KEYS, row.status),
        },
        {
          id: "updated",
          label: t("updated"),
          cell: (row: Incident) => serverLabel(row.last_updated_at, row.updated_label, bcp47) ?? "—",
        },
      ]}
      rows={rows}
      keyOf={(row) => row.id}
    />
  );
}
