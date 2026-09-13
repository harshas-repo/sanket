/**
 * MY REQUESTS - this account's own trail, and nothing belonging to anyone else.
 *
 * Two endpoints, because they answer two different questions. `/api/community/requests` is the
 * cases (with the server's own "what happens next" sentence for each), `/api/community/activity`
 * is the reports that never became a case. Neither takes a parameter that could widen the scope:
 * the filter is the authenticated user id, so this screen cannot be pointed at another person's
 * rescue request by editing a URL.
 *
 * The third block is the phone's own queue. It belongs here because a person comes to this screen
 * to ask "did they get it", and an item still sitting on the device is the one answer that has to
 * be given before anything else - it is also why a request listed below may have no reference
 * code yet.
 */

import { Link } from "react-router-dom";

import { api } from "../../api/client";
import type { AssistanceRequest, CommunityReport } from "../../api/types";
import { ConnectionBanner } from "../../components/community/parts";
import { DemoChip, UrgencyTag } from "../../components/Chips";
import { Panel } from "../../components/StatePanel";
import { MetaStrip, Screen, SubSection } from "../../components/rc/parts";
import { useOutbox } from "../../offline/outbox";
import { useAsync } from "../../hooks/useAsync";
import { useI18n } from "../../i18n/I18nContext";
import { ASSISTANCE_STATUS_KEYS, VERIFICATION_KEYS } from "../../i18n/strings";
import { minutesText, serverLabel } from "../../utils/time";

/** The one state a queued item can legitimately be in from here: not sent, or refused. */
function PendingList() {
  const { t, bcp47 } = useI18n();
  const outbox = useOutbox();
  if (!outbox.count) return null;

  return (
    <SubSection title={t("pending_label")} count={outbox.count}>
      <ul className="item-list">
        {outbox.items.map((item) => (
          <li key={item.client_ref} className="item-card">
            <div className="row-between">
              <strong>{t(item.kind === "report" ? "nav_report" : "nav_help")}</strong>
              <span className="meta">{serverLabel(item.queued_at, null, bcp47)}</span>
            </div>
            <p className="item-body">
              {String(
                (item.payload.message ?? item.payload.description ?? "") as string,
              ).slice(0, 120)}
            </p>
            {typeof item.payload.server_ref_code === "string" ? (
              <p className="meta">
                <Link to={`/community/requests/${encodeURIComponent(item.payload.server_ref_code)}`}>
                  {item.payload.server_ref_code}
                </Link>
              </p>
            ) : null}
            {item.last_error ? <p className="field-hint breach">{item.last_error}</p> : null}
            <div className="row">
              <button
                type="button"
                className="button small"
                onClick={outbox.flush}
                disabled={outbox.flushing}
              >
                {outbox.flushing ? t("sending") : t("flush_now")}
              </button>
              <button type="button" className="button small" onClick={() => outbox.removeItem(item.client_ref)}>
                {t("remove_item")}
              </button>
            </div>
          </li>
        ))}
      </ul>
    </SubSection>
  );
}

function RequestCard({ row }: { row: AssistanceRequest }) {
  const { t, enumLabel, bcp47 } = useI18n();
  const minutes = row.sla?.minutes_remaining;
  return (
    <li className="item-card" key={row.id}>
      <div className="row-between">
        <strong>
          <Link to={`/community/requests/${encodeURIComponent(row.ref_code)}`}>{row.ref_code}</Link>
        </strong>
        <span className="meta">{serverLabel(row.created_at, row.age, bcp47) ?? "—"}</span>
      </div>
      <p className="item-body">{row.description}</p>
      <div className="row chip-row">
        <UrgencyTag value={row.urgency} title={row.urgency_reasons.join(" · ")} />
        {/* Built from the enum, never from `status_label`: that field follows the language the
            request was filed in, which is not necessarily the language being read now. */}
        <span className="chip provenance">{enumLabel(ASSISTANCE_STATUS_KEYS, row.status)}</span>
        {row.submitted_offline ? <span className="chip provenance">{t("pending_label")}</span> : null}
        {row.demo ? <DemoChip /> : null}
      </div>
      {minutes !== null && minutes !== undefined ? (
        <p className={`meta${row.sla?.breached ? " breach" : ""}`}>
          {t("sla_due")}:{" "}
          {row.sla?.breached
            ? t("sla_overdue", { minutes: minutesText(minutes) ?? "" })
            : t("sla_remaining", { minutes: minutesText(minutes) ?? "" })}
        </p>
      ) : null}
      {/* The server's own sentence about what happens to this case, in the language the case was
          filed in. */}
      {row.what_happens_next ? <p className="server-said">{row.what_happens_next}</p> : null}
    </li>
  );
}

function ReportCard({ row }: { row: CommunityReport }) {
  const { t, enumLabel, bcp47 } = useI18n();
  return (
    <li className="item-card" key={row.id}>
      <div className="row-between">
        <strong>{row.location_text ?? row.district ?? t("nav_report")}</strong>
        <span className="meta">{serverLabel(row.at, row.age, bcp47) ?? "—"}</span>
      </div>
      <p className="item-body">{row.message}</p>
      <div className="row chip-row">
        <span className="chip provenance">{enumLabel(VERIFICATION_KEYS, row.verification_status)}</span>
        {row.incident ? (
          <Link className="meta" to={`/community/incidents/${encodeURIComponent(row.incident.id)}`}>
            {row.incident.title}
          </Link>
        ) : null}
        {row.carried_on_request ? (
          <Link className="meta" to={`/community/requests/${encodeURIComponent(row.carried_on_request)}`}>
            {row.carried_on_request}
          </Link>
        ) : null}
        {row.duplicate_status === "duplicate" ? (
          <span className="chip provenance">{enumLabel(VERIFICATION_KEYS, "duplicate")}</span>
        ) : null}
        {row.submitted_offline ? <span className="chip provenance">{t("pending_label")}</span> : null}
        {row.demo ? <DemoChip /> : null}
      </div>
    </li>
  );
}

export function MinePage() {
  const { t } = useI18n();
  const cases = useAsync((signal) => api.community.requests(signal), []);
  const trail = useAsync((signal) => api.community.activity(signal), []);

  return (
    <Screen title={t("nav_mine")} intro={t("ref_code_hint")}>
      <ConnectionBanner />
      <PendingList />

      {/* The list below is every request this account filed, closed ones included - `/community
         /requests` takes no status filter. So the heading counts what is shown and the server's own
         open tally is stated separately, rather than labelling a cancelled case "open". */}
      <SubSection title={t("nav_mine")} count={cases.data?.count}>
        <MetaStrip generatedAt={cases.data?.generated_at} stale={Boolean(cases.error)} />
        {trail.data && cases.data?.items.length ? (
          <p className="meta">
            {t("open_requests")}: {trail.data.open_count}
          </p>
        ) : null}
        <Panel
          state={cases}
          isEmpty={(value) => value.items.length === 0}
          emptyTitle={t("nothing_yet")}
        >
          {(value) => (
            <ul className="item-list">
              {value.items.map((row) => (
                <RequestCard key={row.id} row={row} />
              ))}
            </ul>
          )}
        </Panel>
      </SubSection>

      <SubSection title={t("my_reports")}>
        <Panel
          state={trail}
          isEmpty={(value) => value.reports.length === 0}
          emptyTitle={t("nothing_yet")}
        >
          {(value) => (
            <ul className="item-list">
              {value.reports.map((row) => (
                <ReportCard key={row.id} row={row} />
              ))}
            </ul>
          )}
        </Panel>
      </SubSection>

      {/* A resident is entitled to know that other people's cases are not listed here, and why. */}
      <p className="meta">{t("privacy_note")}</p>
    </Screen>
  );
}
