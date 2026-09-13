/**
 * ACCOUNT - what the platform assumes about you, and the short list of things you can change.
 *
 * `PATCH /api/auth/me` accepts four fields and this screen offers two of them. A community account
 * is not asked for a name or a phone number when it reports (§55: minimise personal information),
 * so the account screen does not invite them either - a form field is a suggestion that the data
 * is wanted. What stays is the two things that change what the person is *shown*: the language
 * SANKET writes in, and the area their feed and their questions are about.
 *
 * The distinction between the two language controls is real and easy to lose. The switch in the
 * header changes this browser's interface. `preferred_language` changes the language the backend
 * writes its own sentences in - an alert body, an assistant reply, a case update - and it follows
 * the account rather than the device, so the same person on a relative's phone still gets Nepali
 * content. Changing it here also moves the interface, because a person who asks for Nepali should
 * not have to find a second switch to get it.
 *
 * There is no district picker, because there is no district list to pick from: `Boundaries
 * .district_names()` exists on the server and is published by no endpoint, so the field is free
 * text and the note under it says what a misspelling costs. Recorded in docs/known-issues.md.
 */

import { useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../../api/client";
import { ChoiceGrid, ConnectionBanner, Field } from "../../components/community/parts";
import { Screen, SubSection } from "../../components/rc/parts";
import { useAuth } from "../../auth/AuthContext";
import { useI18n } from "../../i18n/I18nContext";
import { LANGUAGES } from "../../i18n/strings";
import type { Language } from "../../i18n/strings";
import { useOutbox } from "../../offline/outbox";

/** `ProfilePatch.home_district` is `max_length=64`. */
const DISTRICT_MAX = 64;

export function AccountPage() {
  const { t, language, setLanguage } = useI18n();
  const { user, logout, refreshMe } = useAuth();
  const outbox = useOutbox();

  const [preferred, setPreferred] = useState<Language>(user?.preferred_language ?? language);
  const [district, setDistrict] = useState(user?.home_district ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const save = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      await api.auth.updateMe({
        preferred_language: preferred,
        // An empty box is a clearing, not an omission: `null` is what tells the server to forget
        // the area, and leaving the key out would keep the old one.
        home_district: district.trim() ? district.trim().slice(0, DISTRICT_MAX) : null,
      });
      await refreshMe();
      // The account preference is not an explicit device choice, so a later sign-in on a shared
      // phone can still be switched by whoever holds it.
      setLanguage(preferred, false);
      setSaved(true);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen title={t("nav_account")} intro={t("account_intro")}>
      <ConnectionBanner />

      <SubSection title={t("signed_in_as", { name: user?.display_name || user?.username || "—" })}>
        <div className="stack-sm">
          <Field label={t("username")}>
            <input className="big-input" type="text" value={user?.username ?? ""} readOnly />
          </Field>
          {/* What other people's screens could show, if this platform ever named a reporter. It
              does not: an alias is the only handle a community account has. */}
          <p className="meta">
            {t("col_actor")}: {user?.alias ?? "—"}
          </p>
          <p className="meta">{t("privacy_note")}</p>
        </div>
      </SubSection>

      <SubSection title={t("language")}>
        <div className="stack-sm">
          <ChoiceGrid
            label={t("language")}
            note={t("pref_language_note")}
            options={LANGUAGES.map((entry) => ({ value: entry.value, label: entry.label }))}
            selected={[preferred]}
            // One language, always. An empty selection is not a state this screen can hold, so
            // `next.length` is checked rather than a `?? "en"` fallback standing ready to fire.
            onChange={(next) => {
              if (next.length > 0) setPreferred(next[next.length - 1] as Language);
            }}
            max={1}
            min={1}
          />

          <Field label={t("home_district")} htmlFor="account-district" hint={t("district_note")}>
            <input
              id="account-district"
              className="big-input"
              type="text"
              value={district}
              maxLength={DISTRICT_MAX}
              onChange={(event) => setDistrict(event.target.value)}
            />
          </Field>

          <div className="stack-sm send-line">
            <button type="button" className="button large primary" disabled={busy} onClick={() => void save()}>
              {busy ? t("sending") : t("save")}
            </button>
            {error ? (
              <p className="field-hint breach" role="alert">
                {error}
              </p>
            ) : null}
            {saved ? (
              <p className="field-hint" role="status">
                {t("profile_saved")}
              </p>
            ) : null}
          </div>
        </div>
      </SubSection>

      <SubSection title={t("pending_label")}>
        <div className="stack-sm">
          {outbox.stored ? null : <p className="field-hint">{t("offline_disabled")}</p>}
          {outbox.stored && !outbox.count ? <p className="meta">{t("outbox_none")}</p> : null}
          {outbox.count ? (
            <>
              <p className="meta">{t("queued_count", { count: outbox.count })}</p>
              <div className="row">
                <button
                  type="button"
                  className="button small"
                  onClick={() => void outbox.flush()}
                  disabled={outbox.flushing}
                >
                  {outbox.flushing ? t("sending") : t("flush_now")}
                </button>
              </div>
              <p className="meta">
                <Link to="/community/mine">{t("nav_mine")}</Link>
              </p>
              {outbox.flushError ? <p className="field-hint breach">{outbox.flushError}</p> : null}
            </>
          ) : null}
        </div>
      </SubSection>

      <button type="button" className="button" onClick={logout}>
        {t("sign_out")}
      </button>
    </Screen>
  );
}
