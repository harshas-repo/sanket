/**
 * ASK SANKET - the one community screen where a model may choose words, and it says so.
 *
 * `POST /api/agent/chat` answers from `local_feed` - the exact same records this account's home
 * screen reads - so the answer and the picture on the page in front of them cannot disagree. With
 * no model configured the workflow composes the reply from those records itself and reports
 * `mode: "deterministic"`; the line under the answer is the API's own claim about how the sentence
 * was made, and this screen shows `mode` rather than deciding for itself whether to trust it.
 *
 * What is *not* here matters as much: no suggested questions, no "is there anything else I can
 * help you with", no conversation. `ChatIn.history` exists on the schema and `answer_question()`
 * never reads it, so a second question here is answered from the records, not from the first
 * answer. Building a chat log on top of that would be theatre, so it is in docs/known-issues.md
 * instead.
 *
 * The reply follows the language of the question, not the language of this interface (§the
 * workflow's own rule). A reader with the Nepali chrome who types in English gets English back, so
 * the answer is labelled with the language it arrived in rather than left to confuse.
 */

import { useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../../api/client";
import type { AgentRun } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import {
  Field,
  MessageField,
  ServerSaid,
} from "../../components/community/parts";
import { DemoChip, ProvenanceBadge } from "../../components/Chips";
import { Failed } from "../../components/StatePanel";
import { Screen, SubSection } from "../../components/rc/parts";
import { useI18n } from "../../i18n/I18nContext";
import { useOnline } from "../../hooks/useOnline";

/** `ChatIn.message` is 1..2000 and `district` is `max_length=64`. */
const ASK_MAX = 2000;
const DISTRICT_MAX = 64;

/** `based_on` is a loose dict on the wire; a count that is not a number renders as nothing. */
function countOf(value: unknown): number | null {
  return typeof value === "number" ? value : null;
}

export function AskPage() {
  const { t, language } = useI18n();
  const { user, can } = useAuth();
  const online = useOnline();

  const [question, setQuestion] = useState("");
  const [area, setArea] = useState(user?.home_district ?? "");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);
  const [run, setRun] = useState<AgentRun | null>(null);

  const tooLong = question.length > ASK_MAX;
  const canAsk = question.trim().length > 0 && !tooLong && online;

  const ask = async () => {
    if (!canAsk || busy) return;
    setBusy(true);
    setFailure(null);
    setRun(null);
    try {
      setRun(
        await api.agent.chat(
          {
            message: question.trim(),
            language,
            // An area typed here beats the saved home district: the workflow says so explicitly,
            // because someone asking about their village while away wants the village.
            district: area.trim() ? area.trim().slice(0, DISTRICT_MAX) : null,
          },
        ),
      );
    } catch (cause) {
      setFailure(cause);
    } finally {
      setBusy(false);
    }
  };

  const based = run?.based_on;
  const parts = based
    ? [
        countOf(based.alerts) !== null ? `${t("local_alerts")}: ${countOf(based.alerts)}` : null,
        countOf(based.signals) !== null ? `${t("layer_signals")}: ${countOf(based.signals)}` : null,
        countOf(based.incidents) !== null
          ? `${t("nav_incidents")}: ${countOf(based.incidents)}`
          : null,
        typeof based.district === "string" && based.district
          ? `${t("district")}: ${based.district}`
          : null,
      ].filter((line): line is string => line !== null)
    : [];

  return (
    <Screen title={t("ask_sanket")} intro={t("ask_intro")}>
      <form
        className="stack"
        onSubmit={(event) => {
          event.preventDefault();
          void ask();
        }}
      >
        <MessageField
          id="ask-question"
          label={t("ask_sanket")}
          prompt={t("ask_placeholder")}
          value={question}
          onChange={setQuestion}
          max={ASK_MAX}
          rows={3}
        />

        <Field label={t("filter_district")} htmlFor="ask-district" hint={t("optional")}>
          <input
            id="ask-district"
            className="big-input"
            type="text"
            value={area}
            maxLength={DISTRICT_MAX}
            placeholder={user?.home_district ?? undefined}
            onChange={(event) => setArea(event.target.value)}
          />
        </Field>

        <div className="stack-sm send-line">
          <button type="submit" className="button large primary" disabled={!canAsk || busy}>
            {busy ? t("sending") : t("ask_sanket")}
          </button>
          {/* An ask cannot be queued: the offline outbox carries reports and help requests only,
              because those are the things that must reach the Response Center. */}
          {online ? null : <p className="field-hint">{t("ask_offline")}</p>}
          {tooLong ? (
            <p className="field-hint breach" role="alert">
              {t("too_long")}
            </p>
          ) : null}
        </div>
      </form>

      {failure ? (
        <SubSection title={t("error_title")}>
          {/* `Failed` is the console's panel and it is right here too: an unreachable server and
              a refused question are different failures and must not read the same. */}
          <Failed error={failure} />
        </SubSection>
      ) : null}

      {run ? (
        <SubSection title={t("ask_sanket")}>
          <div className="stack-sm">
            <ServerSaid text={run.response_text} />
            {/* The claim about how the sentence was written, from the response itself. */}
            <p className="meta">{run.mode === "strands" ? t("answer_model") : t("answer_rules")}</p>
            {run.note ? <p className="meta">{run.note}</p> : null}
            {parts.length ? (
              <p className="meta">
                <span className="stat-label">{t("based_on")}</span> {parts.join(" · ")}
              </p>
            ) : null}
            <div className="row chip-row">
              {/* The reply is in the language the *question* was written in, which is not
                  necessarily the language of this interface. */}
              {run.language ? (
                <span className="meta">
                  {t("requester_language")}: {run.language}
                </span>
              ) : null}
              <ProvenanceBadge value={run.provenance} />
              {run.provenance === "demo" ? <DemoChip /> : null}
            </div>
            {run.error ? <p className="field-hint breach">{run.error}</p> : null}
          </div>
        </SubSection>
      ) : null}

      {/* The answer is information; these are the two things that change anything. §19's actions
          stay one tap away on the screen whose whole job is answering. */}
      {run ? (
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
        </div>
      ) : null}
    </Screen>
  );
}
