/**
 * I NEED HELP - §21's questions, in §21's order, and nothing else.
 *
 * The form asks for a location, the problem, how many people, whether anyone needs treatment,
 * whether there is immediate danger, and what kind of help is wanted. It does not ask for a name,
 * a phone number or a relation to anyone: §55 says the platform must minimise personal
 * information, and a rescue request is not a registration form.
 *
 * Two things on this screen exist because of what happens *after* the tap. The `danger_note` line
 * says out loud that a form is not a phone call to the emergency services, because a person who
 * believes the queue is faster than 102 will sit and wait - and the "what happens next" block
 * after sending is the server's own sentence, not a reassurance written here, because an invented
 * one would be worse than none.
 *
 * The urgency is not chosen by the person. `assistance.create()` derives it from these answers
 * and returns the reasons, which are shown afterwards - so nobody can be talked out of a red
 * flag by a form, and nobody can win one by tapping hardest.
 */

import { useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../../api/client";
import type { AssistanceRequestIn, HelpRequestOutcome } from "../../api/types";
import {
  ChoiceGrid,
  FlagRow,
  LocationField,
  MESSAGE_MAX,
  MessageField,
  NO_LOCATION,
  NumberField,
  RefCode,
  SendLine,
  ServerSaid,
  type SharedLocation,
} from "../../components/community/parts";
import { DemoChip, UrgencyTag } from "../../components/Chips";
import { Screen, SubSection } from "../../components/rc/parts";
import { enqueue, type OutboxItem } from "../../offline/outbox";
import { useI18n } from "../../i18n/I18nContext";
import { ASSISTANCE_STATUS_KEYS, ASSISTANCE_TYPE_KEYS } from "../../i18n/strings";
import { useOnline } from "../../hooks/useOnline";
import { minutesText } from "../../utils/time";

const ASSISTANCE_TYPES = Object.keys(ASSISTANCE_TYPE_KEYS);

export function HelpPage() {
  const { t, enumLabel, language } = useI18n();
  const online = useOnline();

  const [description, setDescription] = useState("");
  const [location, setLocation] = useState<SharedLocation>(NO_LOCATION);
  const [people, setPeople] = useState<number | null>(1);
  const [medical, setMedical] = useState(false);
  const [danger, setDanger] = useState(false);
  const [trapped, setTrapped] = useState(false);
  const [minors, setMinors] = useState(false);
  const [elderly, setElderly] = useState(false);
  const [wanted, setWanted] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<OutboxItem | null>(null);
  const [outcome, setOutcome] = useState<HelpRequestOutcome | null>(null);

  const body = (): AssistanceRequestIn => ({
    description: description.trim(),
    // `request_type` is one word for the register; the detailed ask is `assistance_types`.
    request_type: wanted[0] ?? "other",
    assistance_types: wanted,
    latitude: location.latitude,
    longitude: location.longitude,
    location_text: location.location_text,
    people_count: people ?? 1,
    medical_need: medical,
    immediate_danger: danger,
    trapped,
    minors_involved: minors,
    elderly_or_disabled_involved: elderly,
    language,
    attachments: [],
    client_timestamp: new Date().toISOString(),
    submitted_offline: !online,
  });

  const tooLong = description.length > MESSAGE_MAX;
  const canSend = description.trim().length >= 3 && !tooLong;

  const send = async () => {
    if (!canSend || busy) return;
    setBusy(true);
    setError(null);
    setOutcome(null);
    setSaved(null);

    if (!online) {
      const item = enqueue({
        kind: "request",
        payload: body() as unknown as Record<string, unknown>,
        origin: "help",
      });
      setBusy(false);
      if (!item) {
        setError(t("offline_disabled"));
        return;
      }
      setSaved(item);
      setDescription("");
      setWanted([]);
      return;
    }

    try {
      setOutcome(await api.community.requestHelp(body()));
      setDescription("");
      setWanted([]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  const request = outcome?.request;
  const slaMinutes = outcome?.sla?.minutes_remaining;

  return (
    <Screen title={t("nav_help")} intro={t("help_prompt")}>
      {/* Said before asking, not after: a form that reads like the fastest route is the one
          thing this screen must not be. */}
      <p className="banner banner-danger" role="note">
        {t("danger_note")}
      </p>

      <form
        className="stack"
        onSubmit={(event) => {
          event.preventDefault();
          void send();
        }}
      >
        {/* Dictation is available here and the text arrives in the same box, but
            `AssistanceRequestIn` has no `voice_transcript` field - only `ReportIn` does - so an
            operator cannot tell a dictated plea from a typed one. Recorded in
            docs/known-issues.md rather than worked around on screen. */}
        <MessageField
          id="help-description"
          label={t("description")}
          prompt={t("help_prompt")}
          value={description}
          onChange={setDescription}
        />

        <LocationField value={location} onChange={setLocation} />

        <NumberField
          id="help-people"
          label={t("people_count")}
          value={people}
          onChange={setPeople}
          min={1}
          max={100_000}
        />

        <ChoiceGrid
          label={t("help_types")}
          options={ASSISTANCE_TYPES.map((value) => ({ value, label: enumLabel(ASSISTANCE_TYPE_KEYS, value) }))}
          selected={wanted}
          onChange={setWanted}
        />

        <div className="stack-sm">
          <FlagRow id="help-medical" label={t("medical_need")} checked={medical} onChange={setMedical} />
          <FlagRow id="help-danger" label={t("immediate_danger")} checked={danger} onChange={setDanger} />
          <FlagRow id="help-trapped" label={t("trapped")} checked={trapped} onChange={setTrapped} />
          <FlagRow id="help-minors" label={t("minors_involved")} checked={minors} onChange={setMinors} />
          <FlagRow
            id="help-elderly"
            label={t("elderly_or_disabled")}
            checked={elderly}
            onChange={setElderly}
          />
        </div>

        <SendLine
          busy={busy}
          disabled={!canSend}
          onSubmit={() => void send()}
          error={error ?? (tooLong ? t("too_long") : null)}
          okNote={saved ? `${t("queued_offline")} · ${t("pending_label")}` : null}
        />
      </form>

      {request && outcome ? (
        <SubSection title={t("sent")}>
          <div className="stack-sm">
            <RefCode code={request.ref_code} />
            {/* The receipt is the message written to be forwarded or read aloud, so it is
                rendered as it came and never re-worded. */}
            <ServerSaid text={outcome.receipt} />
            <div className="row chip-row">
              <UrgencyTag value={request.urgency} title={request.urgency_reasons.join(" · ")} />
              <span className="chip provenance">{enumLabel(ASSISTANCE_STATUS_KEYS, request.status)}</span>
              {request.demo ? <DemoChip /> : null}
            </div>
            {request.urgency_reasons.length ? (
              <ul className="reason-list">
                <li className="meta">{t("urgency_reasons")}</li>
                {request.urgency_reasons.map((reason, index) => (
                  <li key={`${reason}-${index}`}>{reason}</li>
                ))}
              </ul>
            ) : null}
            {slaMinutes !== null && slaMinutes !== undefined ? (
              <p className={`meta${slaMinutes < 0 ? " breach" : ""}`}>
                {t("sla_due")}:{" "}
                {slaMinutes < 0
                  ? t("sla_overdue", { minutes: minutesText(slaMinutes) ?? "" })
                  : t("sla_remaining", { minutes: minutesText(slaMinutes) ?? "" })}
              </p>
            ) : (
              <p className="meta">{t("sla_no_deadline")}</p>
            )}
            <div>
              <span className="stat-label">{t("what_happens_next")}</span>
              <ServerSaid text={outcome.what_happens_next} />
            </div>
            <Link className="button small" to={`/community/requests/${encodeURIComponent(request.ref_code)}`}>
              {t("open_record")}
            </Link>
          </div>
        </SubSection>
      ) : null}
    </Screen>
  );
}
