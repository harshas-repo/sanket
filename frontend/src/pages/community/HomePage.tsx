/**
 * The community home: four things a person can do, and what is happening where they are.
 *
 * §19 lists the main actions and §37 lists them again as the home screen, and this page is that
 * list - except for the fourth one. "CHECK LOCAL ALERTS" is not a button that leads somewhere
 * else, because the alerts are already on this page, in the reader's own language, fetched from
 * `/api/community/feed`. A button that scrolls to the section under it would be a way of making
 * someone tap twice for one thing.
 *
 * What the feed is allowed to contain is a server decision, not a rendering one: `local_feed()`
 * deliberately excludes other people's community reports from the alert list so an unverified
 * claim cannot read as an official warning, and every row here carries its evidence and freshness
 * state for the same reason. The incident rows are the officially-backed ones.
 *
 * Nothing on this screen is written by a model. The ASK SANKET button leads to the one surface
 * where a language model may choose words, and that screen says so.
 */

import { Link } from "react-router-dom";

import { api } from "../../api/client";
import type { Alert, FeedIncident, RiskSignal } from "../../api/types";
import { BigActions, ConnectionBanner } from "../../components/community/parts";
import {
  DemoChip,
  EvidenceChip,
  FreshnessChip,
  PrecisionChip,
  ProvenanceBadge,
} from "../../components/Chips";
import { Panel } from "../../components/StatePanel";
import { MetaStrip, Screen, SubSection } from "../../components/rc/parts";
import { useAuth } from "../../auth/AuthContext";
import { useAsync, usePolling } from "../../hooks/useAsync";
import { useI18n } from "../../i18n/I18nContext";
import { HAZARD_KEYS } from "../../i18n/strings";
import { serverLabel } from "../../utils/time";

/** An official bulletin, quoted. The source link is the point: a person can check us. */
function AlertCard({ alert }: { alert: Alert }) {
  const { t, bcp47 } = useI18n();
  return (
    <article className="item-card">
      <div className="row-between">
        <h3>{alert.title}</h3>
        <FreshnessChip value={alert.freshness_state} label={alert.published_label} />
      </div>
      <p className="item-body">{alert.body || alert.title}</p>
      <div className="row chip-row">
        {/* The agency's own name and link, never a paraphrase of it. */}
        {alert.source_url ? (
          <a className="meta" href={alert.source_url} target="_blank" rel="noreferrer noopener">
            {alert.source_name} ↗
          </a>
        ) : (
          <span className="meta">{alert.source_name}</span>
        )}
        {alert.district ? <span className="meta">{alert.district}</span> : null}
        {alert.is_pdf_bulletin ? <span className="meta">{t("alert_pdf")}</span> : null}
        {alert.demo ? <DemoChip /> : null}
        <ProvenanceBadge value={alert.provenance} />
      </div>
      {/* The server's own age sentence when it has one. An undated bulletin gets that stated:
          `published_label` would otherwise print the English sentinel "no published time". */}
      <p className="meta">
        {alert.published_at
          ? (serverLabel(alert.published_at, alert.published_label, bcp47) ?? "—")
          : t("alert_undated")}
      </p>
    </article>
  );
}

/** One district's risk level, with what pushed it up. §11 keeps predictions labelled. */
function SignalCard({ signal }: { signal: RiskSignal }) {
  const { t, enumLabel, bcp47 } = useI18n();
  return (
    <article className="item-card">
      <div className="row-between">
        <h3>
          {signal.label || enumLabel(HAZARD_KEYS, signal.hazard)}
          {signal.district ? <span className="meta"> · {signal.district}</span> : null}
        </h3>
        <FreshnessChip value={signal.freshness_state} label={serverLabel(signal.observed_at, null, bcp47)} />
      </div>
      <p className="item-body">{signal.statement}</p>
      <div className="row chip-row">
        <span className="meta">{enumLabel(HAZARD_KEYS, signal.hazard)}</span>
        <span className="meta">{t(signal.is_prediction ? "signal_prediction" : "signal_observed")}</span>
        {signal.provenance ? <ProvenanceBadge value={signal.provenance} /> : null}
      </div>
      {signal.contributing_factors.length ? (
        <ul className="reason-list compact">
          {signal.contributing_factors.map((factor, index) => (
            <li key={`${factor.kind}-${index}`}>
              {factor.statement}
              <span className="meta"> · {factor.source}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </article>
  );
}

export function HomePage() {
  const { t, bcp47 } = useI18n();
  const { user, can } = useAuth();

  const feed = useAsync(
    (signal) =>
      api.community.feed(
        { district: user?.home_district ?? undefined, language: bcp47.slice(0, 2) },
        signal,
      ),
    [user?.home_district, bcp47],
  );
  const inbox = useAsync((signal) => api.notifications.list(signal), []);
  usePolling(feed.reload, 60_000);

  const data = feed.data;

  return (
    <Screen title={t("home_prompt")} intro={t("surface_community")}>
      <ConnectionBanner />

      <BigActions
        items={[
          { to: "/community/ask", titleKey: "ask_sanket", hintKey: "ask_hint", when: can("agent:chat") },
          { to: "/community/report", titleKey: "nav_report", hintKey: "report_hint", when: can("community:report") },
          {
            to: "/community/help",
            titleKey: "nav_help",
            hintKey: "help_hint",
            tone: "danger",
            when: can("community:request"),
          },
          { to: "/community/mine", titleKey: "nav_mine", hintKey: "ref_code_hint", when: can("community:read_own") },
        ]}
      />

      <SubSection title={t("local_alerts")} note={t("alerts_hint")} count={data?.counts.alerts}>
        <MetaStrip generatedAt={data?.generated_at} stale={Boolean(feed.error)} />
        {/* The server's own sentence for the nothing-at-all case, which already names the area it
            looked at (`_no_alerts_line`). It goes in the empty state itself, because repeating it
            under a second empty message reads like two findings rather than one. */}
        <Panel state={feed} isEmpty={(value) => value.alerts.length === 0} emptyTitle={data?.empty_message ?? t("empty_title")}>
          {(value) => (
            <div className="stack-sm">
              {value.alerts.map((alert) => (
                <AlertCard key={alert.id} alert={alert} />
              ))}
            </div>
          )}
        </Panel>
      </SubSection>

      <SubSection title={t("layer_signals")} count={data?.counts.signals}>
        <Panel
          state={feed}
          isEmpty={(value) => value.signals.length === 0}
          emptyTitle={t("bucket_empty")}
        >
          {(value) => (
            <div className="stack-sm">
              {value.signals.map((signal) => (
                <SignalCard key={`${signal.code}-${signal.district}`} signal={signal} />
              ))}
            </div>
          )}
        </Panel>
      </SubSection>

      <SubSection title={t("feed_title")} note={t("public_official_note")} count={data?.counts.incidents}>
        <Panel
          state={feed}
          isEmpty={(value) => value.incidents.length === 0}
          emptyTitle={t("empty_title")}
        >
          {(value) => (
            <div className="stack-sm">
              {value.incidents.map((incident: FeedIncident) => (
                <article className="item-card" key={incident.id}>
                  <div className="row-between">
                    <h3>
                      <Link to={`/community/incidents/${encodeURIComponent(incident.id)}`}>
                        {incident.title}
                      </Link>
                    </h3>
                    <EvidenceChip value={incident.evidence_state} />
                  </div>
                  <div className="row chip-row">
                    <span className="meta">
                      {t("col_district")}: {incident.district ?? "—"}
                    </span>
                    <span className="meta">{t("event_time")}: {serverLabel(incident.event_time, incident.updated_label, bcp47) ?? "—"}</span>
                    <FreshnessChip value={incident.freshness_state} label={incident.updated_label} />
                    <PrecisionChip value={incident.location_precision} />
                    <ProvenanceBadge value={incident.provenance} />
                  </div>
                </article>
              ))}
            </div>
          )}
        </Panel>
      </SubSection>

      {can("community:read_own") ? (
        <SubSection title={t("messages_for_you")} count={inbox.data?.unread}>
          <Panel
            state={inbox}
            isEmpty={(value) => value.items.length === 0}
            emptyTitle={t("nothing_yet")}
          >
            {(value) => (
              <ul className="item-list">
                {value.items.slice(0, 8).map((row) => (
                  <li key={row.id} className={`item-card${row.read ? "" : " item-unread"}`}>
                    <div className="row-between">
                      <strong>{row.title}</strong>
                      <span className="meta">{serverLabel(row.at, row.age, bcp47) ?? "—"}</span>
                    </div>
                    <p className="item-body">{row.body}</p>
                    <div className="row">
                      {row.link ? (
                        <Link className="button small" to={row.link}>
                          {t("open_record")}
                        </Link>
                      ) : null}
                      {row.read ? null : (
                        <button
                          type="button"
                          className="button small"
                          onClick={() => {
                            // Marking read is not worth failing the page over: the answer
                            // re-reads the inbox either way.
                            void api.notifications.read(row.id).then(inbox.reload).catch(() => null);
                          }}
                        >
                          {t("mark_read")}
                        </button>
                      )}
                      {row.district ? <span className="meta">{row.district}</span> : null}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </SubSection>
      ) : null}
    </Screen>
  );
}
