/**
 * ONE REPORT - the message exactly as a person sent it, and the one thing an operator can do to it.
 *
 * This is where the console link the platform writes into its own notification lands
 * (`/response-center/reports/{id}`, from `services/community.py`), so it has to work from a cold
 * open: an operator arrives with a report id and nothing else.
 *
 * The message is rendered as it arrived, in the language it was written in. It is not translated
 * and not summarised: the words a frightened person chose are evidence, and a paraphrase of them
 * is not. What this screen adds is only the standing the platform has given the report so far.
 *
 * Verification is the single action available here, and it needs a reason of at least five
 * characters because it is written to the audit trail - "verified" with nothing behind it is an
 * assertion, not a record. The `state` is sent explicitly rather than left to the schema's
 * default, which names an *evidence* state (`officially_confirmed`) while the column being
 * written is `verification_status`; the two vocabularies are not the same list.
 */

import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../../api/client";
import { DemoChip, ProvenanceBadge, UrgencyTag } from "../../components/Chips";
import { Panel } from "../../components/StatePanel";
import { EnumSelect, FieldGrid, MetaStrip, Screen, SubSection } from "../../components/rc/parts";
import { useAuth } from "../../auth/AuthContext";
import { useAsync } from "../../hooks/useAsync";
import { useI18n } from "../../i18n/I18nContext";
import {
  HAZARD_KEYS,
  LANGUAGE_NAME_KEYS,
  LOCATION_CONFIDENCE_KEYS_STAFF,
  REPORT_TYPE_KEYS,
  SEVERITY_KEYS,
  VERIFICATION_KEYS,
} from "../../i18n/strings";
import type { StringKey } from "../../i18n/strings";
import { serverLabel } from "../../utils/time";

/** `VerifyIn.reason` is `min_length=5`, so a shorter one is refused by the server anyway. */
const REASON_MIN = 5;
const REASON_MAX = 500;

/** The states an operator may move a report *to*. `pending` is left out on purpose: returning a
 *  report to unverified is an un-decision, and it is not offered as a one-tap option. */
const VERIFY_STATES: Record<string, StringKey> = {
  verified: VERIFICATION_KEYS.verified,
  rejected: VERIFICATION_KEYS.rejected,
  duplicate: VERIFICATION_KEYS.duplicate,
  conflicting: VERIFICATION_KEYS.conflicting,
};

export function ReportDetailPage() {
  const { reportId = "" } = useParams();
  const { t, enumLabel, bcp47 } = useI18n();
  const { can } = useAuth();

  const state = useAsync((signal) => api.rc.report(reportId, signal), [reportId]);

  const [verifyState, setVerifyState] = useState("verified");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const submit = async () => {
    if (busy || reason.trim().length < REASON_MIN) return;
    setBusy(true);
    setError(null);
    setDone(false);
    try {
      const answer = await api.rc.verifyReport(reportId, {
        reason: reason.trim().slice(0, REASON_MAX),
        state: verifyState,
      });
      // The endpoint answers with the report it just changed, so the screen re-reads it rather
      // than trusting a local copy of what it asked for.
      state.setData({ report: answer.report });
      setReason("");
      setDone(true);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen
      title={t("nav_reports")}
      intro={t("reports_intro")}
      actions={
        <Link className="button small" to="/response-center/reports">
          {t("back")}
        </Link>
      }
    >
      <Panel state={state}>
        {(value) => {
          const report = value.report;
          return (
            <div className="stack">
              <SubSection title={t("description")}>
                <div className="stack-sm">
                  <div className="row chip-row">
                    {report.demo ? <DemoChip /> : null}
                    <UrgencyTag value={report.urgency} />
                    <span className="chip provenance">
                      {enumLabel(VERIFICATION_KEYS, report.verification_status)}
                    </span>
                    {report.duplicate_status === "duplicate" ? (
                      <span className="chip provenance">
                        {enumLabel(VERIFICATION_KEYS, "duplicate")}
                      </span>
                    ) : null}
                    <ProvenanceBadge value={report.provenance} />
                  </div>
                  {/* The reporter's own words. `item-body` keeps the line length readable and
                      `pre-line` is not used: a message with hard line breaks is still prose. */}
                  <p className="request-message">{report.message}</p>
                  <MetaStrip
                    generatedAt={report.at}
                    extra={serverLabel(report.at, report.age, bcp47)}
                  />
                </div>
              </SubSection>

              <SubSection title={t("details")}>
                <FieldGrid
                  items={[
                    { label: t("request_type"), value: enumLabel(REPORT_TYPE_KEYS, report.report_type) },
                    {
                      label: t("filter_type"),
                      value: report.incident_type
                        ? enumLabel(HAZARD_KEYS, report.incident_type)
                        : t("hazard_inferred_note"),
                    },
                    /* It is a severity, and the row above it already owns the word "status" - two
                       fields on one record answering to one heading. `Severity` is a published enum
                       (`low`...`severe`), so it is named like one instead of shown as code. */
                    {
                      label: t("severity"),
                      value: enumLabel(SEVERITY_KEYS, report.severity),
                      when: Boolean(report.severity),
                    },
                    { label: t("col_district"), value: report.district },
                    { label: t("location"), value: report.location_text },
                    {
                      label: t("location_confidence"),
                      // The staff map: "Inferred from your home district" addresses the resident,
                      // and nobody on this side of the screen is that person.
                      value: enumLabel(LOCATION_CONFIDENCE_KEYS_STAFF, report.location_confidence),
                    },
                    {
                      label: t("requester_language"),
                      value: enumLabel(LANGUAGE_NAME_KEYS, report.language),
                    },
                    {
                      label: t("corroboration"),
                      value: String(report.corroborating_count),
                      when: report.corroborating_count > 0,
                    },
                    {
                      label: t("distance"),
                      value:
                        report.distance_to_incident_km === null
                          ? null
                          : `${report.distance_to_incident_km} km`,
                      when: report.distance_to_incident_km !== null,
                    },
                    {
                      label: t("pending_label"),
                      value: report.submitted_offline ? t("yes") : null,
                      when: report.submitted_offline,
                    },
                  ]}
                />
                {report.latitude !== null && report.longitude !== null ? (
                  <p className="meta mono">
                    {report.latitude.toFixed(5)}, {report.longitude.toFixed(5)}
                  </p>
                ) : (
                  <p className="meta">{t("map_unplaced")}</p>
                )}
              </SubSection>

              {report.incident ? (
                <SubSection title={t("linked_incident")}>
                  <p className="meta">
                    <Link
                      to={`/response-center/incidents/${encodeURIComponent(report.incident.id)}`}
                    >
                      {report.incident.ref_code} · {report.incident.title}
                    </Link>
                  </p>
                </SubSection>
              ) : (
                <SubSection title={t("linked_incident")}>
                  <p className="meta">{t("attached_none")}</p>
                </SubSection>
              )}

              {report.carried_on_request ? (
                <SubSection title={t("carried_on_request")}>
                  <p className="meta">
                    <Link
                      to={`/response-center/requests/${encodeURIComponent(report.carried_on_request)}`}
                    >
                      {report.carried_on_request}
                    </Link>
                  </p>
                </SubSection>
              ) : null}

              {can("reports:verify") ? (
                <SubSection title={t("verify_action")} note={t("verify_reason_hint")}>
                  <div className="action-form">
                    <EnumSelect
                      label={t("status")}
                      keys={VERIFY_STATES}
                      value={verifyState}
                      onChange={setVerifyState}
                      includeAll={false}
                    />
                    <div className="field">
                      <label htmlFor="verify-reason">{t("reason")}</label>
                      <textarea
                        id="verify-reason"
                        rows={3}
                        value={reason}
                        maxLength={REASON_MAX}
                        placeholder={t("verify_reason_hint")}
                        onChange={(event) => setReason(event.target.value)}
                      />
                      {reason.trim().length < REASON_MIN ? (
                        <span className="field-hint">{t("action_required")}</span>
                      ) : null}
                    </div>
                    <div className="row">
                      <button
                        type="button"
                        className="button primary"
                        disabled={busy || reason.trim().length < REASON_MIN}
                        onClick={() => void submit()}
                      >
                        {busy ? t("sending") : t("submit")}
                      </button>
                    </div>
                    {error ? (
                      <p className="field-hint breach" role="alert">
                        {error}
                      </p>
                    ) : null}
                    {done ? (
                      <p className="field-hint" role="status">
                        {t("verify_done")}
                      </p>
                    ) : null}
                  </div>
                </SubSection>
              ) : (
                <p className="meta">{t("no_actions_for_role")}</p>
              )}
            </div>
          );
        }}
      </Panel>
    </Screen>
  );
}
