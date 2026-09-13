/**
 * ASSISTANT - the language layer, shown as the instrument it is.
 *
 * Four things on this screen exist because §7 says an assistant nobody can inspect is not
 * allowed to be part of a disaster response:
 *
 * - Whether a model is configured at all. When none is, the deterministic path still answers, and
 *   the screen says so instead of looking broken.
 * - The tool inventory, published by the server rather than asserted here, so "what it may look
 *   at" is answerable by reading the product - including which of those tools write.
 * - The activity timeline of a run over a victim's report: every step and tool call, in order,
 *   with what each one returned. It is the record of a decision to file a case, and the reason
 *   it shows actions rather than the model's working is that an action can be checked against
 *   evidence and a guess cannot.
 * - Every stored run, including the ones whose wording was thrown away because it stated numbers
 *   no record contains. A rejection that is not shown is a trust model that only reports success.
 *
 * Staff accounts have `agent:run` and no `agent:chat`: a resident's question is answered on the
 * community surface. So this page investigates named incidents and answers a report someone
 * else filed; it does not offer a chat box that would answer 403.
 */

import { useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../../api/client";
import type { AgentActivityStep, AgentRun, AgentTool } from "../../api/types";
import { DemoChip, ProvenanceBadge } from "../../components/Chips";
import { Panel } from "../../components/StatePanel";
import {
  DataTable,
  FieldGrid,
  MetaStrip,
  ReasonList,
  RefreshRow,
  Screen,
  Stat,
  SubSection,
} from "../../components/rc/parts";
import { useAsync, usePolling } from "../../hooks/useAsync";
import { useI18n } from "../../i18n/I18nContext";
import {
  AGENT_ACTIVITY_KEYS,
  AGENT_STATUS_KEYS,
  AGENT_STEP_STATUS_KEYS,
  ASSISTANCE_TYPE_KEYS,
  LOCATION_CONFIDENCE_KEYS_STAFF,
  type StringKey,
} from "../../i18n/strings";
import { formatStamp } from "../../utils/time";

/**
 * The risk words the keyword table reads off a report, under the labels the community help form
 * and the request detail page already give them. One concept, one word for it, in three places.
 */
const READING_FLAG_KEYS: Record<string, StringKey> = {
  medical_need: "medical_need",
  trapped: "trapped",
  immediate_danger: "immediate_danger",
  minors_involved: "minors_involved",
  elderly_or_disabled_involved: "elderly_or_disabled",
};

/**
 * `AgentInvestigateIn` takes either an internal id (`inc_…`) or a reference code
 * (`INC-20260912-0001-ab12`), and the endpoint will not guess which it was sent. The two
 * never look alike, so the shape of the string decides the field it goes into.
 */
function asTarget(value: string): { incident_id?: string; ref_code?: string } {
  return /^[A-Z]{3}-/.test(value) ? { ref_code: value } : { incident_id: value };
}

/**
 * The activity timeline: what ran, in what order, how each step ended, and the one line the
 * tool itself wrote about what came back.
 *
 * There is no field in here for the model's reasoning, and that is structural rather than a
 * gap on this screen - `agent/trace.py` only accepts action names, statuses, timestamps and a
 * digest a tool built out of its own result. So an operator can see that the road check ran and
 * came back empty, and that priority was set by the fixed rules; what they cannot see is a
 * chain of intermediate guesses, because a guess is not something to act on in a response.
 *
 * The workflow's own steps are labelled in the reader's language. A tool's name is printed as
 * the server spells it: it is the same string the inventory below publishes, and renaming it
 * here would give one thing two names.
 */
function ActivityTimeline({ steps }: { steps: AgentActivityStep[] }) {
  const { t, enumLabel, bcp47 } = useI18n();

  if (!steps.length) return <p className="meta">{t("activity_none")}</p>;

  return (
    <ul className="item-list">
      {steps.map((step, index) => (
        <li key={`${step.at}-${step.action}-${index}`} className="item-card">
          <div className="row-between">
            <span className="mono">{enumLabel(AGENT_ACTIVITY_KEYS, step.action)}</span>
            {/* Always stated, including when it is simply "ok": the note above promises a status
                per step, and a row with no status is indistinguishable from a step whose status
                was never recorded. Only a step that did not end cleanly is coloured for it. */}
            <span className={step.status === "ok" ? "chip provenance" : "chip provenance breach"}>
              {enumLabel(AGENT_STEP_STATUS_KEYS, step.status)}
            </span>
          </div>
          {step.detail ? <p className="item-body">{step.detail}</p> : null}
          <p className="meta">
            <span className="mono">{formatStamp(step.at, bcp47) ?? "—"}</span>
            {" · "}
            {step.kind === "tool" ? t("activity_kind_tool") : t("activity_kind_phase")}
          </p>
        </li>
      ))}
    </ul>
  );
}

export function AssistantPage() {
  const { t, enumLabel, bcp47 } = useI18n();

  const status = useAsync(() => api.agent.status(), []);
  const tools = useAsync(() => api.agent.tools(), []);
  const paused = usePolling(status.reload, 60_000);

  const [target, setTarget] = useState("");
  const [answer, setAnswer] = useState<AgentRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /* The responder, on its own state. An investigation reads and a response files a case, so
     letting both write into one `answer` would put a lookup and a piece of paperwork in the
     same box - and the box below has to be able to say which of the two it is showing. */
  const [report, setReport] = useState("");
  const [reportId, setReportId] = useState("");
  const [filed, setFiled] = useState<AgentRun | null>(null);
  const [responding, setResponding] = useState(false);
  const [respondError, setRespondError] = useState<string | null>(null);

  // The runs for whatever was last investigated. The endpoint needs an incident id, and the
  // answer carries the one it ran against, so the list cannot drift onto a different incident.
  const history = useAsync(
    () =>
      answer?.subject_id
        ? api.agent.investigations(answer.subject_id, 10)
        : Promise.resolve({ count: 0, items: [] as AgentRun[] }),
    [answer?.subject_id],
  );

  const run = async () => {
    const value = target.trim();
    if (!value || busy) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.agent.investigate(asTarget(value));
      setAnswer(result);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  const respond = async () => {
    const text = report.trim();
    if (!text || responding) return;
    setResponding(true);
    setRespondError(null);
    try {
      // `text` is sent exactly as typed. Nothing here tidies the caller's words, expands an
      // abbreviation or adds a district the report did not name: those are the model's and the
      // gazetteer's jobs on the server, and each one says whose guess the result is.
      const result = await api.agent.respond({ text, report_id: reportId.trim() || null });
      setFiled(result);
      // This run changed how many runs exist and may have changed what the model can do, so
      // the availability panel above is refreshed rather than left showing a stale "no".
      void status.reload();
    } catch (cause) {
      setRespondError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setResponding(false);
    }
  };

  const model = status.data;

  /* What the keyword rules read out of the report, spelled out with the labels this app already
     uses for the same flags. Derived here rather than in the JSX because a run that filed
     nothing still has these, and the empty case has to render as nothing rather than as "0". */
  const filedFlags = Object.entries(filed?.reading?.risk_flags ?? {})
    .filter(([, on]) => on)
    .map(([name]) => {
      // A flag this map has not caught up with prints as its code instead of vanishing - the
      // same rule `enumLabel` follows for an enum this file does not know yet.
      const key = READING_FLAG_KEYS[name];
      return key ? t(key) : name;
    });
  const filedTypes = (filed?.reading?.help_types ?? []).map((kind) =>
    enumLabel(ASSISTANCE_TYPE_KEYS, kind),
  );
  const filedLocation = filed?.location;

  return (
    <Screen title={t("nav_assistant")} intro={t("assistant_intro")}>
      <RefreshRow generatedAt={model?.generated_at} onRefresh={status.reload} seconds={60} paused={paused} />

      <SubSection title={t("answer_title")} note={t("agent_runs_note")}>
        <div className="stat-grid">
          <Stat
            label={t("agent_available")}
            value={model ? (model.available ? t("yes") : t("no")) : "—"}
            note={model?.available ? model.model : t("agent_unavailable")}
          />
          <Stat label={t("agent_runs_total")} value={model?.runs.total ?? 0} />
          <Stat label={t("agent_tools_title")} value={tools.data?.count ?? 0} />
        </div>
        <FieldGrid
          items={[
            { label: t("agent_provider"), value: model?.provider ?? null },
            { label: t("agent_model"), value: model?.model ?? null },
            {
              label: t("agent_credentials"),
              value: model ? (model.credentials_present ? t("yes") : t("no")) : null,
            },
            { label: t("agent_fallback_reason"), value: model?.reason ?? null },
            { label: t("based_on"), value: model?.fallback ?? null },
          ]}
        />
      </SubSection>

      <SubSection title={t("investigate_incident")} note={t("investigate_hint")}>
        <div className="action-form">
          <div className="field">
            <label htmlFor="agent-target">{t("col_incident")}</label>
            <input
              id="agent-target"
              type="text"
              className="mono"
              maxLength={36}
              placeholder={t("investigate_placeholder")}
              value={target}
              onChange={(event) => setTarget(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") void run();
              }}
            />
          </div>
          <div className="row">
            <button
              type="button"
              className="button primary"
              disabled={busy || !target.trim()}
              onClick={() => void run()}
            >
              {busy ? t("sending") : t("investigate_run")}
            </button>
            {answer ? (
              <button type="button" className="button ghost" onClick={() => setAnswer(null)}>
                {t("close")}
              </button>
            ) : null}
          </div>
          {error ? (
            <p className="field-hint breach" role="alert">
              {error}
            </p>
          ) : null}
        </div>
      </SubSection>

      {answer ? (
        <SubSection
          title={answer.ref_code ? `${t("col_incident")}: ${answer.ref_code}` : t("answer_title")}
          actions={
            <span className="row">
              {answer.provenance === "demo" ? <DemoChip /> : null}
              <ProvenanceBadge value={answer.provenance} />
            </span>
          }
        >
          <FieldGrid
            items={[
              {
                label: t("answer_how"),
                value: answer.mode === "strands" ? t("answer_model") : t("answer_rules"),
              },
              { label: t("col_status"), value: enumLabel(AGENT_STATUS_KEYS, answer.status) },
              {
                label: t("col_time"),
                value: formatStamp(answer.created_at, bcp47),
              },
              {
                label: t("agent_model"),
                value: answer.model,
              },
              {
                label: t("duration"),
                value:
                  answer.duration_ms === null ? null : t("agent_duration", { ms: answer.duration_ms }),
              },
            ]}
          />

          {/* The answer itself, in the block reserved for text this app did not write. It is
              never re-flowed, translated or summarised on the way to the screen. */}
          <p className="server-said">{answer.response_text || "—"}</p>

          {answer.error ? (
            <p className="field-hint breach" role="alert">
              {answer.error}
            </p>
          ) : null}
          {answer.note ? <p className="meta">{answer.note}</p> : null}

          <div className="filter-grid">
            <div>
              <h4>{t("known_facts")}</h4>
              <ReasonList items={answer.known ?? []} className="compact" />
            </div>
            <div>
              <h4>{t("not_known")}</h4>
              <ReasonList items={answer.unknown ?? []} className="compact" />
            </div>
            {answer.rejected_numbers?.length ? (
              <div>
                {/* The most important list on the page: numbers a model said that no record says. */}
                <h4 className="breach">{t("rejected_numbers")}</h4>
                <ReasonList items={answer.rejected_numbers} className="compact" />
              </div>
            ) : null}
          </div>
        </SubSection>
      ) : null}

      {/* ------------------------------------------------------------ the responder */}
      <SubSection title={t("respond_title")} note={t("respond_hint")}>
        <div className="action-form">
          <div className="field">
            <label htmlFor="victim-report">{t("respond_title")}</label>
            <textarea
              id="victim-report"
              rows={3}
              maxLength={4000}
              placeholder={t("respond_placeholder")}
              value={report}
              onChange={(event) => setReport(event.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="victim-report-id">{t("respond_report_id")}</label>
            <input
              id="victim-report-id"
              type="text"
              className="mono"
              maxLength={36}
              value={reportId}
              onChange={(event) => setReportId(event.target.value)}
            />
            <p className="field-hint">{t("respond_report_hint")}</p>
          </div>
          <div className="row">
            <button
              type="button"
              className="button primary"
              disabled={responding || !report.trim()}
              onClick={() => void respond()}
            >
              {responding ? t("sending") : t("respond_run")}
            </button>
            {filed ? (
              <button type="button" className="button ghost" onClick={() => setFiled(null)}>
                {t("close")}
              </button>
            ) : null}
          </div>
          {respondError ? (
            <p className="field-hint breach" role="alert">
              {respondError}
            </p>
          ) : null}
        </div>
      </SubSection>

      {filed ? (
        <SubSection
          title={t("respond_title")}
          actions={
            <span className="row">
              {filed.provenance === "demo" ? <DemoChip /> : null}
              <ProvenanceBadge value={filed.provenance} />
            </span>
          }
        >
          <FieldGrid
            items={[
              {
                label: t("answer_how"),
                value: filed.mode === "strands" ? t("answer_model") : t("answer_rules"),
              },
              { label: t("col_status"), value: enumLabel(AGENT_STATUS_KEYS, filed.status) },
              {
                label: t("respond_filed"),
                // The case, linked where it is worked on. A ref code is the request detail
                // page's own route parameter, so this link cannot point at the wrong case.
                value: filed.created_requests?.length ? (
                  <span className="row">
                    {(filed.created_requests ?? []).map((ref) => (
                      <Link
                        key={ref}
                        className="mono"
                        to={`/response-center/requests/${encodeURIComponent(ref)}`}
                      >
                        {ref}
                      </Link>
                    ))}
                  </span>
                ) : (
                  t("respond_none")
                ),
              },
              {
                label: t("respond_model_calls"),
                value: filed.model_calls === null || filed.model_calls === undefined ? null : String(filed.model_calls),
              },
              { label: t("col_time"), value: formatStamp(filed.created_at, bcp47) },
              {
                label: t("duration"),
                value:
                  filed.duration_ms === null ? null : t("agent_duration", { ms: filed.duration_ms }),
              },
            ]}
          />

          <p className="server-said">{filed.response_text || "—"}</p>

          {filed.error ? (
            <p className="field-hint breach" role="alert">
              {filed.error}
            </p>
          ) : null}
          {filed.note ? <p className="meta">{filed.note}</p> : null}

          <div className="filter-grid">
            <div>
              <h4>{t("respond_reading")}</h4>
              <ReasonList items={filedFlags} className="compact" />
              <h4>{t("respond_help_types")}</h4>
              <ReasonList items={filedTypes} className="compact" />
              <p className="field-hint">{t("respond_reading_note")}</p>
            </div>
            <div>
              <h4>{t("respond_location")}</h4>
              <FieldGrid
                items={[
                  { label: t("location"), value: filedLocation?.location_text ?? null },
                  { label: t("district"), value: filedLocation?.district ?? null },
                  { label: t("province"), value: filedLocation?.province ?? null },
                  {
                    label: t("respond_coordinate"),
                    value:
                      filedLocation?.latitude === null || filedLocation?.latitude === undefined
                        ? null
                        : `${filedLocation.latitude},${filedLocation.longitude ?? ""}`,
                  },
                  {
                    label: t("location_confidence"),
                    value: enumLabel(
                      LOCATION_CONFIDENCE_KEYS_STAFF,
                      filedLocation?.location_confidence,
                    ),
                  },
                ]}
              />
            </div>
            {filed.rejected_numbers?.length ? (
              <div>
                <h4 className="breach">{t("rejected_numbers")}</h4>
                <ReasonList items={filed.rejected_numbers} className="compact" />
              </div>
            ) : null}
          </div>

          {/* The timeline, last: everything above is what the caller said and what the system
              decided, and this is the working out of that decision - in actions, not prose. */}
          <div>
            <h4>{t("activity_title")}</h4>
            <p className="field-hint">{t("activity_note")}</p>
            <ActivityTimeline steps={filed.tool_calls} />
          </div>
        </SubSection>
      ) : null}

      <Panel state={tools} isEmpty={(data) => data.tools.length === 0} emptyTitle={t("bucket_empty")}>
        {(data) => (
          <SubSection title={t("agent_tools_title")} count={data.count} note={t("agent_tools_readonly")}>
            <DataTable
              columns={[
                {
                  id: "name",
                  label: t("agent_tools_title"),
                  cell: (row: AgentTool) => <span className="mono">{row.name}</span>,
                },
                { id: "description", label: t("col_summary"), cell: (row: AgentTool) => row.description },
                {
                  /* Which of the two sets the tool is in, and whether it changes anything. The
                     server publishes this instead of the screen asserting it, because "the agent
                     can only read" was true of one set and false of the other. */
                  id: "set",
                  label: t("agent_tool_set"),
                  cell: (row: AgentTool) => (
                    <span className="row">
                      <span className="meta mono">{row.set ?? "—"}</span>
                      {row.writes ? <span className="chip provenance breach">{t("agent_tool_writes")}</span> : null}
                    </span>
                  ),
                },
                {
                  id: "arguments",
                  label: t("agent_tool_args"),
                  cell: (row: AgentTool) =>
                    row.arguments.length ? (
                      <span className="meta mono">{row.arguments.join(", ")}</span>
                    ) : (
                      <span className="meta">—</span>
                    ),
                },
              ]}
              rows={data.tools}
              keyOf={(row) => row.name}
            />
          </SubSection>
        )}
      </Panel>

      {answer?.subject_id ? (
        <SubSection title={t("agent_history")} count={history.data?.count} note={t("agent_history_note")}>
          <MetaStrip generatedAt={answer.created_at} />
          {(history.data?.items.length ?? 0) === 0 ? (
            <p className="meta">{t("assistant_no_runs")}</p>
          ) : (
            <div className="stack-sm">
              {(history.data?.items ?? []).map((row, index) => (
                <div key={row.id ?? index} className="card card-tight">
                  <div className="row-between">
                    <span className="meta">
                      {formatStamp(row.created_at, bcp47) ?? "—"} ·{" "}
                      {row.mode === "strands" ? t("answer_model") : t("answer_rules")}
                    </span>
                    <span className={`chip provenance${row.status === "completed" ? "" : " breach"}`}>
                      {enumLabel(AGENT_STATUS_KEYS, row.status)}
                    </span>
                  </div>
                  <p className="server-said">{row.response_text || "—"}</p>
                  {/* Counted as the tool rows only, not the length of the timeline: the list also
                      holds the fixed spine steps, and "Tools it called: 7" over a run that chose
                      one tool would be a number the record does not support. A run with no tool
                      rows shows nothing rather than a zero it cannot stand behind. Both routes
                      fill this now; an investigation used to store an empty list however many
                      tools the model called (docs/known-issues.md, issue 68). */}
                  {row.tool_calls.some((step) => step.kind === "tool") ? (
                    <p className="meta mono">
                      {t("agent_tool_calls")}:{" "}
                      {row.tool_calls.filter((step) => step.kind === "tool").length}
                    </p>
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </SubSection>
      ) : null}
    </Screen>
  );
}
