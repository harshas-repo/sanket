/**
 * MY REQUEST - one case, seen from the side that is waiting for it.
 *
 * `GET /api/community/requests/{ref_code}` is not the console's endpoint with fields hidden by
 * this screen: the server builds a different projection (`victim_view=True`), which drops who has
 * been assigned, the internal notes and the response plan, and keeps the status. The status is
 * never withheld from the person who asked - only the operational detail around it. So there is
 * nothing here to filter: this page renders what came and cannot be talked into showing more by a
 * URL, because `_own_request()` answers 404 for a ref code that is not yours.
 *
 * Two wording rules on this screen:
 *
 * - The status chip is rebuilt from the enum in the reader's current language, not taken from
 *   `status_label`, which is written in the language the *case* was filed in. The two differ the
 *   moment someone checks an English request from a Nepali phone.
 * - `next_step` is the server's own sentence and is rendered as it arrived. Nobody at a keyboard
 *   in Kathmandu should be improving what happens next for a person in Sindhupalchok.
 *
 * Cancellation is offered because the lifecycle allows it from every open state (§the transition
 * table: only resolved and cancelled are terminal), and it asks for a reason because a team
 * already on the road cannot be turned back by an empty tap.
 */

import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../../api/client";
import type { CommunityRequestDetail, RequestUpdate } from "../../api/types";
import { Field, RefCode, ServerSaid } from "../../components/community/parts";
import { DemoChip, ProvenanceBadge, UrgencyTag } from "../../components/Chips";
import { Panel } from "../../components/StatePanel";
import { MetaStrip, Screen, SubSection } from "../../components/rc/parts";
import { useAuth } from "../../auth/AuthContext";
import { useAsync } from "../../hooks/useAsync";
import { useI18n } from "../../i18n/I18nContext";
import {
  ASSISTANCE_STATUS_KEYS,
  ASSISTANCE_TYPE_KEYS,
  LOCATION_CONFIDENCE_KEYS,
} from "../../i18n/strings";
import { formatStamp, minutesText, serverLabel } from "../../utils/time";

/** `CancelIn.reason` is `max_length=500`. */
const REASON_MAX = 500;

/** The lifecycle has exactly two terminal states, and the server refuses a move from either. */
const CLOSED = new Set(["resolved", "cancelled"]);

function TimelineRow({
  row,
  bcp47,
  enumLabel,
}: {
  row: RequestUpdate;
  bcp47: string;
  enumLabel: ReturnType<typeof useI18n>["enumLabel"];
}) {
  return (
    <li className="item-card">
      <div className="row-between">
        <span className="meta mono">{formatStamp(row.at, bcp47) ?? "—"}</span>
        {/* `kind` is an internal code (`status_change`, `message`) with no published label list,
            so it is printed small and monospaced rather than translated into words this app
            would be inventing. Recorded in docs/known-issues.md. */}
        <span className="meta mono">{row.kind}</span>
      </div>
      {row.message ? <p className="item-body">{row.message}</p> : null}
      {row.to_status ? (
        <p className="meta">
          {row.actor ? `${row.actor} · ` : ""}
          {/* The states are the case lifecycle this screen already labels, so the arrow reads in
              the language being looked at rather than as raw enum codes. */}
          {row.from_status
            ? `${enumLabel(ASSISTANCE_STATUS_KEYS, row.from_status)} → `
            : ""}
          {enumLabel(ASSISTANCE_STATUS_KEYS, row.to_status)}
        </p>
      ) : (
        <p className="meta">{row.actor ?? "—"}</p>
      )}
    </li>
  );
}

export function MyRequestPage() {
  const { refCode = "" } = useParams();
  const { t, enumLabel, bcp47 } = useI18n();
  const { can } = useAuth();
  const detail = useAsync((signal) => api.community.request(refCode, signal), [refCode]);

  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);

  const cancel = async () => {
    if (busy) return;
    setBusy(true);
    setCancelError(null);
    try {
      const answer = await api.community.cancel(refCode, { reason: reason.trim().slice(0, REASON_MAX) });
      // Cancel answers with the case and its timeline but not the SLA block, so the loaded
      // deadline is kept rather than dropped to nothing by a successful action.
      if (detail.data) {
        detail.setData({ ...detail.data, ...answer, sla: detail.data.sla });
      }
      setReason("");
    } catch (cause) {
      setCancelError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen
      title={t("nav_mine")}
      intro={t("victim_view")}
      actions={
        <Link className="button small" to="/community/mine">
          {t("back")}
        </Link>
      }
    >
      <Panel state={detail}>
        {(value: CommunityRequestDetail) => {
          const request = value.request;
          const sla = value.sla;
          const minutes = sla.minutes_remaining;
          const closed = CLOSED.has(request.status);
          return (
            <div className="stack">
              <SubSection title={t("receipt_title")}>
                <div className="stack-sm">
                  <RefCode code={request.ref_code} />
                  <div className="row chip-row">
                    <span className="chip provenance">
                      {enumLabel(ASSISTANCE_STATUS_KEYS, request.status)}
                    </span>
                    <UrgencyTag value={request.urgency} title={request.urgency_reasons.join(" · ")} />
                    {request.submitted_offline ? (
                      <span className="chip provenance">{t("pending_label")}</span>
                    ) : null}
                    {request.demo ? <DemoChip /> : null}
                    <ProvenanceBadge value={request.provenance} />
                  </div>
                  <MetaStrip generatedAt={request.created_at} extra={request.age ?? undefined} />
                  {/* The server's own "what happens next" for this status, in the language the
                      case was filed in. */}
                  <ServerSaid text={request.next_step} />
                  {closed ? <p className="meta">{t("case_closed_note")}</p> : null}
                </div>
              </SubSection>

              {/* A closed case has no deadline left to meet. Showing the last one it had reads as
                  "this is still overdue" to a person who stopped the request themselves. */}
              {closed ? null : (
                <SubSection title={t("sla_due")}>
                  <p className={`meta${sla.breached ? " breach" : ""}`}>
                    {minutes === null || minutes === undefined
                      ? sla.acknowledged
                        ? t("acknowledged")
                        : t("sla_no_deadline")
                      : minutes < 0
                        ? t("sla_overdue", { minutes: minutesText(minutes) ?? "" })
                        : t("sla_remaining", { minutes: minutesText(minutes) ?? "" })}
                  </p>
                  {request.urgency_reasons.length ? (
                    <ul className="reason-list compact">
                      <li className="meta">{t("urgency_reasons")}</li>
                      {request.urgency_reasons.map((reasonText, index) => (
                        <li key={`${reasonText}-${index}`}>{reasonText}</li>
                      ))}
                    </ul>
                  ) : null}
                </SubSection>
              )}

              <SubSection title={t("details")}>
                <div className="stack-sm">
                  {request.description ? <p className="item-body">{request.description}</p> : null}
                  <div className="row chip-row">
                    <span className="meta">
                      {t("people_count")}: {request.people_count ?? "—"}
                    </span>
                    {request.medical_need ? (
                      <span className="chip provenance">{t("medical_need")}</span>
                    ) : null}
                    {request.immediate_danger ? (
                      <span className="chip provenance">{t("immediate_danger")}</span>
                    ) : null}
                  </div>
                  {request.assistance_types.length ? (
                    <p className="meta">
                      {t("help_types")}:{" "}
                      {request.assistance_types
                        .map((type) => enumLabel(ASSISTANCE_TYPE_KEYS, type))
                        .join(", ")}
                    </p>
                  ) : null}
                  <div className="row chip-row">
                    <span className="meta">{request.location_text ?? "—"}</span>
                    {request.district ? <span className="meta">{request.district}</span> : null}
                    {/* How sure we are that this is the place, which is a separate claim from how
                        precisely it is drawn: `resolve_location()` reports confidence, not the
                        map's precision scale, so it gets its own words. */}
                    {request.location_confidence ? (
                      <span className="chip provenance">
                        {enumLabel(LOCATION_CONFIDENCE_KEYS, request.location_confidence)}
                      </span>
                    ) : null}
                  </div>
                  <p className="meta">
                    {t("requester_language")}: {request.language} ·{" "}
                    {serverLabel(request.created_at, request.age, bcp47) ?? "—"}
                  </p>
                  {request.incident ? (
                    <p className="meta">
                      <Link to={`/community/incidents/${encodeURIComponent(request.incident.id)}`}>
                        {request.incident.title}
                      </Link>
                    </p>
                  ) : null}
                </div>
              </SubSection>

              <SubSection title={t("timeline_title")} count={value.timeline.length}>
                {value.timeline.length ? (
                  <ul className="item-list">
                    {value.timeline.map((row, index) => (
                      <TimelineRow key={`${row.id}-${index}`} row={row} bcp47={bcp47} enumLabel={enumLabel} />
                    ))}
                  </ul>
                ) : (
                  <p className="meta">{t("no_timeline")}</p>
                )}
                {/* Says plainly what is *not* in this list: the console's view carries the team
                    name and the internal notes, and this projection never does. */}
                <p className="field-hint">{t("privacy_note")}</p>
              </SubSection>

              {closed || !can("community:request") ? null : (
                <SubSection title={t("cancel_request")} note={t("cancel_help")}>
                  <div className="stack-sm">
                    <Field label={t("reason")} htmlFor="cancel-reason">
                      <textarea
                        id="cancel-reason"
                        className="big-input"
                        rows={2}
                        value={reason}
                        maxLength={REASON_MAX}
                        placeholder={t("cancel_help")}
                        onChange={(event) => setReason(event.target.value)}
                      />
                    </Field>
                    <button
                      type="button"
                      className="button danger"
                      disabled={busy}
                      onClick={() => void cancel()}
                    >
                      {busy ? t("sending") : t("cancel_request")}
                    </button>
                    {cancelError ? (
                      <p className="field-hint breach" role="alert">
                        {cancelError}
                      </p>
                    ) : null}
                  </div>
                </SubSection>
              )}
            </div>
          );
        }}
      </Panel>
    </Screen>
  );
}
