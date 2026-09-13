/**
 * ONE SITUATION, as a resident is allowed to see it.
 *
 * `GET /api/community/incidents/{id}` is a narrower projection than the console's incident: the
 * official record's own words, and the community reports attached to it, with nothing computed
 * from them. There is no impact score here, no `why_prioritized`, no evidence breakdown, no audit
 * trail and no help requests - the last of those because §55 forbids showing one person's case to
 * another. This screen cannot add what the endpoint did not send, which is the point of routing a
 * resident to that endpoint rather than to the console's.
 *
 * The distinction the whole page exists to keep is the one in `public_official_note`: the heading
 * block is an official record, and the list under it is what people said. Both are true statements
 * about different things, so they are in visibly separate sections and a report row carries its
 * own verification state rather than borrowing the incident's.
 *
 * `last_updated_at` has no age label on this projection. Following the rule in `utils/time.ts`,
 * the absolute stamp is shown and nothing is claimed about how old it is - the client does not do
 * clock arithmetic against a server whose clock may be a rehearsal's.
 */

import { Link, useParams } from "react-router-dom";

import { api } from "../../api/client";
import type { CommunityReport } from "../../api/types";
import { ConnectionBanner } from "../../components/community/parts";
import {
  DemoChip,
  EvidenceChip,
  ProvenanceBadge,
  UrgencyTag,
} from "../../components/Chips";
import { Panel } from "../../components/StatePanel";
import { FieldGrid, Screen, SubSection } from "../../components/rc/parts";
import { useAuth } from "../../auth/AuthContext";
import { useAsync } from "../../hooks/useAsync";
import { useI18n } from "../../i18n/I18nContext";
import { HAZARD_KEYS, VERIFICATION_KEYS } from "../../i18n/strings";
import { formatStamp, serverLabel } from "../../utils/time";

function ReportRow({ row, bcp47 }: { row: CommunityReport; bcp47: string }) {
  const { t, enumLabel } = useI18n();
  return (
    <li className="item-card">
      <p className="item-body">{row.message}</p>
      <div className="row chip-row">
        {/* The report's own standing with an operator - not the incident's, which is a different
            claim and sits in the section above. */}
        <span className="chip provenance">{enumLabel(VERIFICATION_KEYS, row.verification_status)}</span>
        <UrgencyTag value={row.urgency} />
        {row.duplicate_status === "duplicate" ? (
          <span className="chip provenance">{enumLabel(VERIFICATION_KEYS, "duplicate")}</span>
        ) : null}
        {row.corroborating_count > 1 ? (
          <span className="meta">
            {t("col_reports")}: {row.corroborating_count}
          </span>
        ) : null}
        {row.district ? <span className="meta">{row.district}</span> : null}
        <span className="meta">{serverLabel(row.at, row.age, bcp47) ?? "—"}</span>
        {row.demo ? <DemoChip /> : null}
      </div>
    </li>
  );
}

export function IncidentPage() {
  const { incidentId = "" } = useParams();
  const { t, enumLabel, bcp47 } = useI18n();
  const { can } = useAuth();
  const record = useAsync((signal) => api.community.incident(incidentId, signal), [incidentId]);

  return (
    <Screen
      title={t("details")}
      intro={t("public_official_note")}
      actions={
        <Link className="button small" to="/community">
          {t("back")}
        </Link>
      }
    >
      <ConnectionBanner />
      <Panel state={record}>
        {(value) => {
          const incident = value.incident;
          return (
            <div className="stack">
              <SubSection title={incident.title}>
                <div className="stack-sm">
                  <div className="row chip-row">
                    <EvidenceChip value={incident.evidence_state} />
                    {/* `official` is the endpoint's own claim about the record's provenance, and
                        it is always true on this route - which is worth stating out loud rather
                        than leaving as a green tick the reader assumes could have been red. */}
                    <ProvenanceBadge value={incident.official ? "official" : "community"} />
                    {incident.ref_code ? (
                      <span className="meta mono">
                        {t("ref_code")}: {incident.ref_code}
                      </span>
                    ) : null}
                  </div>
                  <FieldGrid
                    items={[
                      { label: t("filter_type"), value: enumLabel(HAZARD_KEYS, incident.incident_type) },
                      { label: t("col_district"), value: incident.district, when: Boolean(incident.district) },
                      {
                        label: t("updated"),
                        value: formatStamp(incident.last_updated_at, bcp47),
                        when: Boolean(incident.last_updated_at),
                      },
                    ]}
                  />
                  {/* `api_url` is deliberately not linked here. It is this platform's own endpoint
                      ("/api/incidents/{id}"), not the agency that recorded the event, so opening it
                      shows a resident a wall of JSON about a page they are already reading. The
                      external source is a separate field the public projection does not carry - see
                      docs/known-issues.md. */}
                </div>
              </SubSection>

              <SubSection title={t("attached_reports")} count={value.reports.length}>
                <Panel
                  state={{ data: value.reports, error: null, loading: false }}
                  isEmpty={(rows) => rows.length === 0}
                  emptyTitle={t("empty_title")}
                  emptyDetail={t("attached_none")}
                >
                  {(rows) => (
                    <ul className="item-list">
                      {rows.map((row) => (
                        <ReportRow key={row.id} row={row} bcp47={bcp47} />
                      ))}
                    </ul>
                  )}
                </Panel>
              </SubSection>

              {/* What a reader can do with a situation, next to the situation. */}
              <div className="row">
                {can("community:report") ? (
                  <Link className="button" to="/community/report">
                    {t("nav_report")}
                  </Link>
                ) : null}
                {can("community:request") ? (
                  <Link className="button danger" to="/community/help">
                    {t("nav_help")}
                  </Link>
                ) : null}
                {can("agent:chat") ? (
                  <Link className="button ghost" to="/community/ask">
                    {t("ask_sanket")}
                  </Link>
                ) : null}
              </div>
            </div>
          );
        }}
      </Panel>
    </Screen>
  );
}
