/**
 * One help request, from the side that has to act on it.
 *
 * This is the counterpart of the resident's screen, and the two deliberately show different
 * things. The console sees who the team is, the internal notes, the audit trail and the deadline
 * clock; the person who asked sees `victim_timeline` and a next step. Both views come from the
 * server already separated - this file only declines to render the fields a victim would be hurt
 * by, and says which subset the requester is shown.
 *
 * The SLA line is the reason this screen exists. A request that nobody acknowledged is the
 * failure mode of every disaster hotline, so the deadline is stated as a fact with the server's
 * own minutes on it, not as a colour an operator has to interpret.
 */

import { Link, useParams } from "react-router-dom";

import { api } from "../../api/client";
import type { AuditEvent, MatchedResource, RequestUpdate } from "../../api/types";
import { DemoChip, ProvenanceBadge, UrgencyTag } from "../../components/Chips";
import { Failed, Loading, Panel } from "../../components/StatePanel";
import { RequestActions } from "../../components/rc/Actions";
import {
  DataTable,
  Delta,
  FieldGrid,
  KeyValue,
  ReasonList,
  RefreshRow,
  Screen,
  SubSection,
} from "../../components/rc/parts";
import { useAsync, usePolling } from "../../hooks/useAsync";
import { useI18n } from "../../i18n/I18nContext";
import { ASSISTANCE_STATUS_KEYS } from "../../i18n/strings";
import { formatStamp, minutesText, serverLabel } from "../../utils/time";

export function RequestDetailPage() {
  const { refCode = "" } = useParams();
  const { t, enumLabel, bcp47 } = useI18n();
  const state = useAsync((signal) => api.rc.request(refCode, signal), [refCode]);
  const paused = usePolling(state.reload, 45_000);

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
        const request = data.request;
        const sla = data.sla ?? request.sla ?? {};
        const plan = request.response_plan;
        const structured = request.structured;
        const remaining = sla.minutes_remaining;

        return (
          <Screen
            title={`${t("nav_requests")} ${request.ref_code}`}
            actions={
              <Link className="button small" to="/response-center/queue">
                {t("queue_title")}
              </Link>
            }
          >
            <RefreshRow generatedAt={null} onRefresh={state.reload} seconds={45} paused={paused} />

            <section className="card stack-sm">
              <div className="row">
                <span className="mono">{request.ref_code}</span>
                <UrgencyTag value={request.urgency} />
                {/* The reader's own status word; `status_label` follows the requester's language. */}
                <span className="chip">{enumLabel(ASSISTANCE_STATUS_KEYS, request.status)}</span>
                <ProvenanceBadge value={request.provenance} />
                {request.demo ? <DemoChip /> : null}
                {request.submitted_offline ? (
                  <span className="chip provenance">{t("queued_offline")}</span>
                ) : null}
              </div>

              <p className="request-message">{request.description}</p>

              <ReasonList items={request.urgency_reasons ?? []} />

              <div className="sla-line">
                {sla.due_at ? (
                  <>
                    <span className="meta">
                      {t("sla_due")}: {formatStamp(sla.due_at, bcp47)}
                    </span>
                    {remaining !== null && remaining !== undefined ? (
                      <span className={`notice${sla.breached ? " error" : ""}`}>
                        {sla.breached
                          ? t("sla_overdue", { minutes: minutesText(remaining) ?? "" })
                          : t("sla_remaining", { minutes: minutesText(remaining) ?? "" })}
                      </span>
                    ) : null}
                    {!sla.acknowledged ? <span className="notice warn">{t("unacknowledged_critical")}</span> : null}
                  </>
                ) : (
                  <span className="meta">{t("sla_no_deadline")}</span>
                )}
              </div>

              <FieldGrid
                items={[
                  { label: t("request_type"), value: request.request_type },
                  { label: t("help_types"), value: (request.assistance_types ?? []).join(", ") || null },
                  { label: t("district"), value: request.district ?? request.province },
                  { label: t("location"), value: request.location_text },
                  { label: t("people_count"), value: request.people_count },
                  { label: t("requester_language"), value: request.language.toUpperCase() },
                  {
                    label: t("immediate_danger"),
                    value: request.immediate_danger ? t("yes") : null,
                  },
                  { label: t("medical_need"), value: request.medical_need ? t("yes") : null },
                  {
                    label: t("context_flags"),
                    value: structured ? (
                      <span className="row">
                        {structured.trapped ? <span className="chip urgency-critical">{t("trapped")}</span> : null}
                        {structured.minors_involved ? (
                          <span className="chip urgency-urgent">{t("minors_involved")}</span>
                        ) : null}
                        {structured.elderly_or_disabled_involved ? (
                          <span className="chip urgency-attention">{t("elderly_or_disabled")}</span>
                        ) : null}
                      </span>
                    ) : null,
                  },
                  {
                    label: t("assigned_to"),
                    value: request.assigned_team ?? request.assigned_to,
                  },
                  {
                    label: t("col_time"),
                    value: serverLabel(request.created_at, request.age, bcp47),
                  },
                  {
                    label: t("acknowledged"),
                    value: formatStamp(request.acknowledged_at, bcp47),
                    when: Boolean(request.acknowledged_at),
                  },
                  {
                    label: t("nav_incidents"),
                    value: request.incident ? (
                      <Link to={`/response-center/incidents/${encodeURIComponent(request.incident.id)}`}>
                        {request.incident.title}
                      </Link>
                    ) : null,
                  },
                ]}
              />
            </section>

            {plan ? (
              <SubSection title={t("planned_response")} note={plan.victim_visibility}>
                <div className="stack-sm">
                  <ol className="step-list">
                    {plan.steps.map((step) => (
                      <li key={step.step}>{step.text}</li>
                    ))}
                  </ol>
                  {plan.unknowns.length ? (
                    <>
                      <h3>{t("plan_unknowns")}</h3>
                      <ReasonList items={plan.unknowns} />
                    </>
                  ) : null}
                  <KeyValue label={t("plan_generated_by")}>{plan.generated_by}</KeyValue>
                  <KeyValue label={t("sla_due")}>{plan.sla_minutes} min</KeyValue>
                </div>
              </SubSection>
            ) : null}

            {(data.matched_resources ?? request.matched_resources ?? []).length ? (
              <SubSection
                title={t("matched_facilities")}
                count={(data.matched_resources ?? request.matched_resources ?? []).length}
              >
                <DataTable
                  columns={[
                    {
                      id: "name",
                      label: t("col_incident"),
                      cell: (row: MatchedResource) => (
                        <div className="stack-sm">
                          <span>
                            <strong>{row.name}</strong>
                            <span className="meta"> · {row.resource_type}</span>
                          </span>
                          <span className="meta">{row.district ?? "—"}</span>
                        </div>
                      ),
                    },
                    { id: "availability", label: t("availability"), cell: (row: MatchedResource) => row.availability },
                    {
                      id: "contact",
                      label: t("contact"),
                      cell: (row: MatchedResource) => (
                        <span className="row">
                          <span className="mono">{row.contact ?? "—"}</span>
                          {row.contact_verified ? (
                            <span className="chip evidence-officially_confirmed">{t("contact_verified")}</span>
                          ) : null}
                        </span>
                      ),
                    },
                    {
                      id: "distance",
                      label: t("distance"),
                      numeric: true,
                      cell: (row: MatchedResource) =>
                        row.distance_km === null ? "—" : `${row.distance_km.toFixed(1)} km`,
                    },
                    {
                      id: "provenance",
                      label: t("source"),
                      cell: (row: MatchedResource) => (
                        <span className="row">
                          <ProvenanceBadge value={row.provenance} />
                          <span className="meta">{formatStamp(row.verified_at, bcp47) ?? "—"}</span>
                        </span>
                      ),
                    },
                  ]}
                  rows={data.matched_resources ?? request.matched_resources ?? []}
                  keyOf={(row) => row.id}
                />
              </SubSection>
            ) : null}

            <RequestActions data={data} onDone={state.reload} />

            <SubSection title={t("timeline_title")} count={data.timeline.length}>
              {data.timeline.length ? (
                <DataTable
                  columns={[
                    {
                      id: "when",
                      label: t("col_time"),
                      cell: (row: RequestUpdate) => (
                        <span className="mono">{formatStamp(row.at, bcp47) ?? "—"}</span>
                      ),
                    },
                    { id: "kind", label: t("col_type"), cell: (row: RequestUpdate) => row.kind },
                    { id: "actor", label: t("col_actor"), cell: (row: RequestUpdate) => row.actor ?? "—" },
                    {
                      id: "what",
                      label: t("details"),
                      cell: (row: RequestUpdate) => (
                        <div className="stack-sm">
                          <span>{row.message}</span>
                          {row.from_status || row.to_status ? (
                            <span className="mono">
                              {row.from_status ?? "—"} → {row.to_status ?? "—"}
                            </span>
                          ) : null}
                        </div>
                      ),
                    },
                  ]}
                  rows={data.timeline}
                  keyOf={(row, index) => `${row.id}-${index}`}
                />
              ) : (
                <p className="meta">{t("no_timeline")}</p>
              )}
              {data.victim_timeline ? (
                <p className="meta">
                  {t("victim_view")}: {data.victim_timeline.length} / {data.timeline.length}
                </p>
              ) : null}
            </SubSection>

            {data.audit?.length ? (
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
                    { id: "before", label: t("before"), cell: (row: AuditEvent) => <Delta value={row.previous} /> },
                    { id: "after", label: t("after"), cell: (row: AuditEvent) => <Delta value={row.new} /> },
                    { id: "reason", label: t("reason"), cell: (row: AuditEvent) => row.reason ?? "—" },
                  ]}
                  rows={data.audit}
                  keyOf={(row) => row.id}
                />
              </SubSection>
            ) : null}
          </Screen>
        );
      }}
    </Panel>
  );
}
