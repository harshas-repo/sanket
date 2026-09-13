/**
 * REPORT SOMETHING - one message in the person's own words, and whatever the phone knows.
 *
 * §20 sets the rule this screen obeys: the system may extract structure from the sentence, but
 * the LLM must not invent a location or a severity, and an ambiguous location must be asked
 * about. So the two things that could be guessed are the two things this form always asks
 * outright - where you are, and whether anyone needs help - and nothing here infers them from
 * the text. The classification that *is* inferred (which hazard, how urgent) is done by
 * deterministic code on the server, and this screen shows what it decided afterwards rather
 * than pretending the person decided it.
 *
 * The `needs_help` switch is §22's escalation path: a report flagged that way opens an
 * assistance request in the same call, and the answer names its reference code. Leaving it off
 * means the message is filed as information, which is why the line beside it says so plainly.
 *
 * Offline, "Submit" becomes "save it and send when signal returns" and the payload goes to the
 * outbox with this phone's clock on it (`client_timestamp`), so the record is stamped when it
 * was written and not when the coverage came back.
 */

import { useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../../api/client";
import type { ReportIn, ReportOutcome } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import {
  ChoiceGrid,
  FlagRow,
  LocationField,
  MESSAGE_MAX,
  MessageField,
  NO_LOCATION,
  NumberField,
  SendLine,
  ServerSaid,
  type SharedLocation,
} from "../../components/community/parts";
import { DemoChip, EvidenceChip } from "../../components/Chips";
import { MetaStrip, Screen, SubSection } from "../../components/rc/parts";
import { enqueue, type OutboxItem } from "../../offline/outbox";
import { useI18n } from "../../i18n/I18nContext";
import {
  ASSISTANCE_TYPE_KEYS,
  HAZARD_KEYS,
  LOCATION_CONFIDENCE_KEYS,
  REPORT_TYPE_KEYS,
  VERIFICATION_KEYS,
} from "../../i18n/strings";
import { useOnline } from "../../hooks/useOnline";

/** `report_type` and `incident_type` are `max_length=32`; these are the published enums. */
const REPORT_TYPES = Object.keys(REPORT_TYPE_KEYS);
const HAZARD_TYPES = Object.keys(HAZARD_KEYS);

export function ReportPage() {
  const { t, enumLabel, language } = useI18n();
  const { user } = useAuth();
  const online = useOnline();

  const [message, setMessage] = useState("");
  const [dictated, setDictated] = useState(false);
  const [reportType, setReportType] = useState("incident");
  const [incidentType, setIncidentType] = useState<string | null>(null);
  const [location, setLocation] = useState<SharedLocation>(NO_LOCATION);
  const [people, setPeople] = useState<number | null>(null);
  const [injuries, setInjuries] = useState<number | null>(null);
  const [medical, setMedical] = useState(false);
  const [danger, setDanger] = useState(false);
  const [needsHelp, setNeedsHelp] = useState(false);
  const [helpTypes, setHelpTypes] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<ReportOutcome | null>(null);
  const [saved, setSaved] = useState<OutboxItem | null>(null);

  const body = (): ReportIn => ({
    message: message.trim(),
    report_type: reportType,
    incident_type: incidentType,
    latitude: location.latitude,
    longitude: location.longitude,
    location_text: location.location_text,
    people_count: people,
    medical_need: medical,
    injuries: injuries ?? 0,
    language,
    // A photo can only be a link here: the API takes attachment URLs and there is no upload
    // endpoint, so §21's "optional photo" is not offered as if it worked.
    attachments: [],
    client_timestamp: new Date().toISOString(),
    submitted_offline: !online,
    needs_help: needsHelp,
    help_types: needsHelp ? helpTypes : [],
    immediate_danger: danger,
    voice_transcript: dictated,
  });

  const tooLong = message.length > MESSAGE_MAX;
  const canSend = message.trim().length >= 3 && !tooLong;

  const send = async () => {
    if (!canSend || busy) return;
    setBusy(true);
    setError(null);
    setOutcome(null);
    setSaved(null);

    if (!online) {
      const item = enqueue({ kind: "report", payload: body() as unknown as Record<string, unknown>, origin: "report" });
      setBusy(false);
      if (!item) {
        setError(t("offline_disabled"));
        return;
      }
      setSaved(item);
      reset();
      return;
    }

    try {
      const answer = await api.community.report(body());
      setOutcome(answer);
      reset();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  const reset = () => {
    setMessage("");
    setDictated(false);
    setPeople(null);
    setInjuries(null);
    setMedical(false);
    setDanger(false);
    setNeedsHelp(false);
    setHelpTypes([]);
  };

  return (
    <Screen title={t("nav_report")} intro={t("report_prompt")}>
      <form
        className="stack"
        onSubmit={(event) => {
          event.preventDefault();
          void send();
        }}
      >
        <MessageField
          id="report-message"
          label={t("description")}
          prompt={t("report_prompt")}
          value={message}
          onChange={setMessage}
          onVoice={() => setDictated(true)}
          error={message.trim().length > 0 || !busy ? null : error}
        />

        <LocationField value={location} onChange={setLocation} />

        <ChoiceGrid
          label={t("request_type")}
          note={t("optional")}
          options={REPORT_TYPES.map((value) => ({ value, label: enumLabel(REPORT_TYPE_KEYS, value) }))}
          selected={[reportType]}
          // Single choice: `report_type` is one value on the server, so a tap moves the answer and
          // there is never a report with no type on it.
          onChange={(next) => {
            if (next.length > 0) setReportType(next[next.length - 1]);
          }}
          max={1}
          min={1}
        />

        <ChoiceGrid
          label={t("filter_type")}
          note={t("hazard_inferred_note")}
          options={HAZARD_TYPES.map((value) => ({ value, label: enumLabel(HAZARD_KEYS, value) }))}
          selected={incidentType ? [incidentType] : []}
          onChange={(next) => setIncidentType(next[next.length - 1] ?? null)}
          max={1}
        />

        <div className="row-inline">
          <NumberField
            id="report-people"
            label={t("people_count")}
            value={people}
            onChange={setPeople}
            min={1}
            max={100_000}
            hint={t("optional")}
          />
          <NumberField
            id="report-injuries"
            label={t("injured")}
            value={injuries}
            onChange={setInjuries}
            min={0}
            max={100_000}
            hint={t("optional")}
          />
        </div>

        <div className="stack-sm">
          <FlagRow id="report-medical" label={t("medical_need")} checked={medical} onChange={setMedical} />
          <FlagRow id="report-danger" label={t("immediate_danger")} checked={danger} onChange={setDanger} />
        </div>

        <SubSection title={t("nav_help")} note={t("danger_note")}>
          <FlagRow
            id="report-needs-help"
            label={t("help_cta")}
            checked={needsHelp}
            onChange={setNeedsHelp}
            hint={t("help_switch_note")}
          />
          {needsHelp ? (
            <ChoiceGrid
              label={t("help_types")}
              options={Object.keys(ASSISTANCE_TYPE_KEYS).map((value) => ({
                value,
                label: enumLabel(ASSISTANCE_TYPE_KEYS, value),
              }))}
              selected={helpTypes}
              onChange={setHelpTypes}
            />
          ) : null}
        </SubSection>

        <SendLine
          busy={busy}
          disabled={!canSend}
          onSubmit={() => void send()}
          error={error ?? (tooLong ? t("too_long") : null)}
          okNote={saved ? `${t("queued_offline")} · ${t("pending_label")}` : null}
        />
      </form>

      {outcome ? (
        <SubSection title={t("sent")}>
          <div className="stack-sm">
            {/* The server's own sentence about what the message became, in the reporter's
                language. Left exactly as it arrived. */}
            <ServerSaid text={outcome.answer} />
            <div>
              <span className="stat-label">{t("what_happens_next")}</span>
              <ServerSaid text={outcome.what_happens_next} />
            </div>
            <div className="row chip-row">
              {outcome.incident ? <EvidenceChip value={outcome.incident.evidence_state} /> : null}
              <span className="chip provenance">
                {enumLabel(VERIFICATION_KEYS, outcome.report.verification_status)}
              </span>
              <span className="meta">{enumLabel(REPORT_TYPE_KEYS, outcome.report.report_type)}</span>
              <span className="meta">{outcome.report.district ?? "—"}</span>
              {/* Says how sure the platform is that this is the place, in words: a reporter whose
                  location was only guessed from their profile has to be able to see that. */}
              {outcome.report.location_confidence ? (
                <span className="chip provenance">
                  {enumLabel(LOCATION_CONFIDENCE_KEYS, outcome.report.location_confidence)}
                </span>
              ) : null}
              {outcome.report.demo || outcome.demo_mode ? <DemoChip /> : null}
            </div>
            <p className="meta">
              {t("filter_type")}: {enumLabel(HAZARD_KEYS, outcome.report.incident_type ?? outcome.incident?.incident_type ?? "")}
            </p>
            {outcome.incident ? (
              <p className="meta">
                <Link to={`/community/incidents/${encodeURIComponent(outcome.incident.id)}`}>
                  {outcome.incident.title}
                </Link>
              </p>
            ) : null}
            {outcome.assistance_request ? (
              <div className="item-card">
                <strong>{t("queue_kind_assistance_request")}</strong>
                <p className="meta">
                  <Link to={`/community/requests/${encodeURIComponent(outcome.assistance_request.ref_code)}`}>
                    {outcome.assistance_request.ref_code}
                  </Link>
                </p>
                <p className="field-hint">{t("ref_code_hint")}</p>
              </div>
            ) : null}
            <MetaStrip generatedAt={outcome.report.at} />
          </div>
        </SubSection>
      ) : null}

      {user?.home_district ? (
        <p className="meta">
          {t("home_district")}: {user.home_district}
        </p>
      ) : null}
    </Screen>
  );
}
