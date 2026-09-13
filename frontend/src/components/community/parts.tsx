/**
 * The pieces every community screen is built from.
 *
 * These are deliberately not the console's components. A control room reads tables; a person
 * standing in a street with a cracked phone screen taps one big thing at a time. So the shared
 * vocabulary here is: a target at least 48 px tall, one question per field group, plain-language
 * hints under the question, and a status line that never relies on colour alone (§16).
 *
 * The frame (`Screen`, `SubSection`, `MetaStrip`) *is* shared with `components/rc/parts.tsx`,
 * notwithstanding the folder name - a heading is a heading on either surface, and duplicating it
 * would mean two files drifting apart on how a timestamp is worded.
 *
 * Two rules hold across the whole file, because breaking either one makes this product dangerous:
 *
 * - **A field the server will not accept is refused here, with the server's own limit.** §56 puts
 *   validation on the server and this is not a replacement for it - but a person offline cannot
 *   get a server answer, so the limit (4,000 characters, 6 help types, 1-100,000 people) has to
 *   be visible where it costs nothing rather than after a queued item fails five times.
 * - **Nothing pretends to have succeeded.** If the phone cannot store a queue, the offline option
 *   is not offered. If dictation is unavailable, no microphone is drawn. If a location was
 *   refused, the field says so and asks for words instead.
 */

import { useCallback, useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { useOnline } from "../../hooks/useOnline";
import { useSpeechInput } from "../../hooks/useSpeechInput";
import { useI18n } from "../../i18n/I18nContext";
import type { StringKey } from "../../i18n/strings";
import { useOutbox } from "../../offline/outbox";

/** `ReportIn.message` and `AssistanceRequestIn.description` are both capped at 4,000. */
export const MESSAGE_MAX = 4000;
/** `help_types` and `assistance_types` are `max_length=6` on the server. */
export const CHOICE_MAX = 6;

/* ------------------------------------------------------------------ the four home buttons */

export interface BigAction {
  to: string;
  titleKey: StringKey;
  hintKey: StringKey;
  /** `danger` is reserved for the one action that must never look like the others. */
  tone?: "danger" | "primary";
  when?: boolean;
}

/**
 * §19's four main actions, at thumb size.
 *
 * These are links, not buttons: each one goes to a screen with more questions on it, and a
 * person should be able to leave and come back without losing the route they are on.
 */
export function BigActions({ items }: { items: BigAction[] }) {
  const { t } = useI18n();
  const shown = items.filter((item) => item.when !== false);
  if (!shown.length) return null;
  return (
    <nav className="big-actions" aria-label={t("home_prompt")}>
      {shown.map((item) => (
        <Link
          key={item.to}
          className={`big-action${item.tone ? ` big-action-${item.tone}` : ""}`}
          to={item.to}
        >
          <span className="big-action-title">{t(item.titleKey)}</span>
          <span className="big-action-hint">{t(item.hintKey)}</span>
        </Link>
      ))}
    </nav>
  );
}

/* ------------------------------------------------------------------ connectivity */

/**
 * The connection line, and the queue it explains.
 *
 * Says three different things that are easy to conflate: the device has no network, the server
 * is unreachable, or there is something still sitting on the phone. Only the third one has a
 * button.
 */
export function ConnectionBanner() {
  const { t } = useI18n();
  const online = useOnline();
  const outbox = useOutbox();

  if (!online) {
    return (
      <p className="banner banner-offline" role="status">
        {t("offline_banner")}
        {outbox.count ? <span className="banner-count">{t("queued_count", { count: outbox.count })}</span> : null}
      </p>
    );
  }

  if (outbox.count) {
    return (
      <div className="banner banner-queued" role="status">
        <span>
          {t("queued_count", { count: outbox.count })} · {t("queued_offline")}
        </span>
        <button type="button" className="button small" onClick={outbox.flush} disabled={outbox.flushing}>
          {outbox.flushing ? t("sending") : t("flush_now")}
        </button>
        {outbox.lastOutcome?.accepted ? (
          <span className="meta">{t("flush_sent", { count: outbox.lastOutcome.accepted })}</span>
        ) : null}
        {outbox.flushError ? <span className="meta breach">{outbox.flushError}</span> : null}
      </div>
    );
  }

  return null;
}

/* ------------------------------------------------------------------ fields */

export function Field({
  label,
  hint,
  htmlFor,
  children,
}: {
  label: string;
  hint?: ReactNode;
  htmlFor?: string;
  children: ReactNode;
}) {
  return (
    <div className="field">
      {htmlFor ? <label htmlFor={htmlFor}>{label}</label> : <span className="field-label">{label}</span>}
      {children}
      {hint ? <p className="field-hint">{hint}</p> : null}
    </div>
  );
}

/**
 * The message box, with dictation attached.
 *
 * `onVoice` is called the first time a transcript lands, which is what sets
 * `voice_transcript` on the payload: an operator should know the sentence was spoken, because a
 * recognised phrase and a typed one fail differently (names, place names, numbers).
 *
 * `max` is the server's own ceiling for that field. The reporter's message and the rescue
 * description take 4,000 characters, `ChatIn.message` takes 2,000, so the counter has to be told
 * which one it is counting against.
 */
export function MessageField({
  id,
  label,
  prompt,
  value,
  onChange,
  onVoice,
  error,
  rows = 4,
  max = MESSAGE_MAX,
}: {
  id: string;
  label: string;
  prompt?: string;
  value: string;
  onChange: (next: string) => void;
  onVoice?: () => void;
  error?: string | null;
  rows?: number;
  max?: number;
}) {
  const { t, bcp47, language } = useI18n();
  const [voiced, setVoiced] = useState(false);

  const append = useCallback(
    (text: string) => {
      onChange(value ? `${value} ${text}` : text);
      setVoiced(true);
      onVoice?.();
    },
    [onChange, onVoice, value],
  );

  const speech = useSpeechInput({ lang: bcp47, onTranscript: append });
  const over = value.length > max;

  const speechMessage = (): string | null => {
    if (!speech.error) return null;
    if (speech.error === "network") return t("voice_network");
    if (speech.error === "no-speech") return t("voice_hint");
    return t("voice_denied");
  };

  return (
    <Field
      label={label}
      htmlFor={id}
      hint={
        <>
          {prompt ? <span>{prompt}</span> : null}
          {prompt ? <br /> : null}
          {/* Once anything has been dictated, the line says so: it is the difference between
              "I wrote that" and "the phone heard something like that", and the person should
              know which one they are submitting. */}
          {voiced ? (
            <span>
              {t("voice_input")} · {t("voice_hint")}
            </span>
          ) : speech.supported ? (
            <span>{t("voice_hint")}</span>
          ) : (
            <span>{t("voice_unsupported")}</span>
          )}
        </>
      }
    >
      <textarea
        id={id}
        className="big-input"
        rows={rows}
        value={value}
        lang={language}
        onChange={(event) => onChange(event.target.value)}
        placeholder={prompt ?? undefined}
      />
      <div className="row-between field-tools">
        <span className={`meta${over ? " breach" : ""}`}>
          {t("char_count", { n: value.length, max })}
        </span>
        {speech.supported ? (
          <button
            type="button"
            className={`button small${speech.listening ? " danger" : ""}`}
            aria-pressed={speech.listening}
            onClick={speech.toggle}
          >
            {speech.listening ? t("voice_stop") : t("voice_input")}
          </button>
        ) : (
          <span className="meta">{t("voice_unsupported")}</span>
        )}
      </div>
      {speechMessage() ? <p className="field-hint">{speechMessage()}</p> : null}
      {over ? <p className="field-hint breach">{t("too_long")}</p> : null}
      {error ? <p className="field-hint breach">{error}</p> : null}
    </Field>
  );
}

/**
 * A set of options a person taps, not a dropdown: §37 is a thumb-first interface.
 *
 * `max={1}` means *choose one*, so a second tap has to move the selection rather than be refused.
 * Treating it as a ceiling alone turns every required single-choice control into a trap: the
 * preselected value fills the only slot, every alternative renders disabled, and the person is left
 * unable to change their answer. `min` is the other half - the floor below which a tap does not
 * clear, because a language or a report type that silently becomes empty falls back to a default
 * the person never picked.
 */
export function ChoiceGrid({
  label,
  note,
  options,
  selected,
  onChange,
  max = CHOICE_MAX,
  min = 0,
}: {
  label: string;
  note?: ReactNode;
  /** The raw enum value and its label, so the payload carries the value. */
  options: { value: string; label: string }[];
  selected: string[];
  onChange: (next: string[]) => void;
  max?: number;
  min?: number;
}) {
  const { t } = useI18n();
  const single = max === 1;
  const toggle = (value: string) => {
    if (selected.includes(value)) {
      // Tapping the only permitted answer off the screen would leave the field empty, and the
      // caller's fallback would quietly fill it with something else.
      if (selected.length <= min) return;
      onChange(selected.filter((item) => item !== value));
      return;
    }
    // Past the server's ceiling the extra pick would be dropped on the floor at flush time, so it
    // is refused here. A single choice is not refused, it is replaced.
    if (selected.length >= max) {
      onChange(single ? [value] : selected);
      return;
    }
    onChange([...selected, value]);
  };

  return (
    <Field label={label} hint={note ?? t("help_types_note", { max })}>
      <div className="choice-grid" role="group" aria-label={label}>
        {options.map((option) => {
          const on = selected.includes(option.value);
          // Only a multi-select with its slots full is unable to take another tap.
          const full = !on && !single && selected.length >= max;
          return (
            <button
              key={option.value}
              type="button"
              className={`choice${on ? " choice-on" : ""}`}
              aria-pressed={on}
              disabled={full}
              onClick={() => toggle(option.value)}
            >
              {on ? <span aria-hidden="true">✓ </span> : null}
              {option.label}
            </button>
          );
        })}
      </div>
    </Field>
  );
}

/** One yes/no question, as a row tall enough to hit while the ground is moving. */
export function FlagRow({
  id,
  label,
  checked,
  onChange,
  hint,
}: {
  id: string;
  label: string;
  checked: boolean;
  onChange: (next: boolean) => void;
  hint?: ReactNode;
}) {
  const { t } = useI18n();
  return (
    <div className="flag-row">
      <label className="flag-label" htmlFor={id}>
        {label}
      </label>
      <div className="row">
        <button
          type="button"
          id={id}
          className={`button small${checked ? " danger" : ""}`}
          aria-pressed={checked}
          onClick={() => onChange(!checked)}
        >
          {checked ? t("yes") : t("no")}
        </button>
      </div>
      {hint ? <p className="field-hint">{hint}</p> : null}
    </div>
  );
}

/** A whole-number field that refuses what the server would refuse anyway. */
export function NumberField({
  id,
  label,
  value,
  onChange,
  min,
  max,
  hint,
}: {
  id: string;
  label: string;
  value: number | null;
  onChange: (next: number | null) => void;
  min: number;
  max: number;
  hint?: ReactNode;
}) {
  const { t } = useI18n();
  const [text, setText] = useState(value === null ? "" : String(value));
  const bad = text !== "" && (Number.isNaN(Number(text)) || Number(text) < min || Number(text) > max);

  return (
    <Field
      label={label}
      htmlFor={id}
      hint={
        bad ? (
          <span className="breach">
            {t("required")} · {min}–{max}
          </span>
        ) : (
          hint
        )
      }
    >
      <input
        id={id}
        className="big-input"
        type="number"
        inputMode="numeric"
        value={text}
        min={min}
        max={max}
        onChange={(event) => {
          setText(event.target.value);
          const parsed = Number(event.target.value);
          if (event.target.value === "") onChange(null);
          else if (!Number.isNaN(parsed) && parsed >= min && parsed <= max) onChange(Math.trunc(parsed));
        }}
      />
    </Field>
  );
}

/* ------------------------------------------------------------------ location */

export interface SharedLocation {
  latitude: number | null;
  longitude: number | null;
  location_text: string | null;
  /** The device's own error radius, shown to the person and never sent. */
  accuracy: number | null;
}

export const NO_LOCATION: SharedLocation = {
  latitude: null,
  longitude: null,
  location_text: null,
  accuracy: null,
};

type GeoState = "idle" | "locating" | "ok" | "denied" | "unavailable" | "timeout";

/**
 * Coordinates if the phone will give them, words if it will not.
 *
 * The browser only offers geolocation on a secure origin, so over a plain-http LAN address this
 * reports `unavailable` - which is why the text field beside it is never disabled and never
 * marked optional-by-default: a tole and a ward is a location the platform can work with, and it
 * is the one a person can always provide.
 */
export function LocationField({
  value,
  onChange,
}: {
  value: SharedLocation;
  onChange: (next: SharedLocation) => void;
}) {
  const { t } = useI18n();
  const [state, setState] = useState<GeoState>("idle");

  const ask = () => {
    if (typeof navigator === "undefined" || !navigator.geolocation) {
      setState("unavailable");
      return;
    }
    setState("locating");
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setState("ok");
        onChange({
          ...value,
          latitude: Number(position.coords.latitude.toFixed(5)),
          longitude: Number(position.coords.longitude.toFixed(5)),
          accuracy: Math.round(position.coords.accuracy),
        });
      },
      (error) => {
        // 1 denied by the person, 2 unavailable here, 3 too slow to be worth waiting for.
        setState(error.code === 1 ? "denied" : error.code === 3 ? "timeout" : "unavailable");
      },
      { enableHighAccuracy: true, timeout: 12_000, maximumAge: 60_000 },
    );
  };

  const stateLine = (): string | null => {
    if (state === "locating") return t("loc_locating");
    if (state === "denied") return t("loc_denied");
    if (state === "unavailable") return t("loc_unavailable");
    if (state === "timeout") return t("loc_unavailable");
    return null;
  };

  const hasCoords = value.latitude !== null && value.longitude !== null;

  return (
    <Field
      label={t("loc_prompt")}
      hint={
        hasCoords ? (
          <span>
            <span className="mono">
              {value.latitude?.toFixed(3)}, {value.longitude?.toFixed(3)}
            </span>
            {value.accuracy ? ` · ${t("loc_accuracy", { metres: value.accuracy })}` : null}
          </span>
        ) : (
          <span>{stateLine() ?? t("loc_none_note")}</span>
        )
      }
    >
      <div className="row loc-row">
        <input
          className="big-input loc-text"
          type="text"
          aria-label={t("location")}
          value={value.location_text ?? ""}
          placeholder={t("loc_text_placeholder")}
          maxLength={300}
          onChange={(event) => onChange({ ...value, location_text: event.target.value || null })}
        />
        <button
          type="button"
          className="button small"
          onClick={ask}
          disabled={state === "locating"}
          aria-busy={state === "locating"}
        >
          {hasCoords ? t("share_location") : t("loc_use")}
        </button>
        {hasCoords ? (
          <button
            type="button"
            className="button small"
            onClick={() =>
              onChange({ ...value, latitude: null, longitude: null, accuracy: null })
            }
          >
            {t("remove_item")}
          </button>
        ) : null}
      </div>
    </Field>
  );
}

/* ------------------------------------------------------------------ submit */

/**
 * The send line.
 *
 * Offline, the button cannot say "Submit" - it says what will actually happen, that the message
 * stays on the phone. That sentence is the difference between a person waiting for a response and
 * a person assuming nobody got it.
 */
export function SendLine({
  busy,
  disabled,
  onSubmit,
  error,
  okNote,
}: {
  busy: boolean;
  disabled: boolean;
  onSubmit: () => void;
  error?: ReactNode;
  okNote?: ReactNode;
}) {
  const { t } = useI18n();
  const online = useOnline();
  return (
    <div className="stack-sm send-line">
      <button
        type="submit"
        className={`button large${online ? " primary" : ""}`}
        disabled={busy || disabled}
        onClick={(event) => {
          // The button is inside a <form>; this keeps the two paths (Enter key, tap) identical.
          event.preventDefault();
          onSubmit();
        }}
      >
        {busy ? t("sending") : online ? t("submit") : t("send_offline")}
      </button>
      {online ? null : <p className="field-hint">{t("queued_offline")}</p>}
      {error ? (
        <p className="field-hint breach" role="alert">
          {error}
        </p>
      ) : null}
      {okNote ? (
        <p className="field-hint" role="status">
          {okNote}
        </p>
      ) : null}
    </div>
  );
}

/** The server's own answer, kept visually apart from everything this app wrote. */
export function ServerSaid({ text }: { text: string | null | undefined }) {
  if (!text) return null;
  return <p className="server-said">{text}</p>;
}

/**
 * A reference code a person is told to keep.
 *
 * `select-all-on-focus` because the way it is actually kept is a photo or a text to a relative,
 * and no one re-types eleven characters in the dark.
 */
export function RefCode({ code }: { code: string }) {
  const { t } = useI18n();
  return (
    <div className="ref-code">
      <span className="stat-label">{t("receipt_title")}</span>
      <input
        className="mono"
        type="text"
        readOnly
        value={code}
        onFocus={(event) => event.target.select()}
        aria-label={t("ref_code")}
      />
      <p className="field-hint">{t("ref_code_hint")}</p>
    </div>
  );
}
