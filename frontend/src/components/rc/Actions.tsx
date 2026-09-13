/**
 * The action panels. Both are driven by what the server said this caller may do, never by a
 * list of buttons written here.
 *
 * An incident detail publishes `{action, label, method, path, permission}` per action, so the
 * console can render it directly - including the *path*, which does not follow the action name
 * (`request_verification` posts to `request-verification`, `link_report` to `link/report`). A
 * request detail publishes only `{action, target}` with no label, path or permission at all, so
 * this file supplies those from the endpoint list and says plainly when it does not recognise
 * one. The two shapes are docs/known-issues.md item 29; until they are unified, the difference
 * is handled here rather than hidden.
 *
 * A form appears only for the fields the endpoint actually requires, and the button stays
 * disabled until they are filled - the server rejects them otherwise with a validation message
 * in English, and a person in a control room should not have to read that to know why nothing
 * happened.
 */

import { useState } from "react";

import { ApiError, request } from "../../api/client";
import type { ActionSpec, IncidentDetail, RequestAction, RequestDetail } from "../../api/types";
import { useI18n } from "../../i18n/I18nContext";
import type { StringKey } from "../../i18n/strings";
import { ASSISTANCE_STATUS_KEYS, INCIDENT_STATUS_KEYS } from "../../i18n/strings";
import { ReasonList } from "./parts";

interface FormField {
  key: string;
  labelKey: StringKey;
  hintKey?: StringKey;
  type: "text" | "textarea" | "checkbox";
  required?: boolean;
}

/** The body each incident endpoint demands, keyed by the last part of its published path. */
const INCIDENT_FIELDS: Record<string, FormField[]> = {
  verify: [{ key: "reason", labelKey: "action_reason_hint", type: "textarea", required: true }],
  "request-verification": [
    { key: "reason", labelKey: "action_reason_hint", type: "textarea", required: true },
  ],
  note: [{ key: "note", labelKey: "action_note_hint", type: "textarea", required: true }],
  review: [{ key: "reason", labelKey: "action_reason_hint", type: "textarea" }],
  status: [],
  "link/report": [
    { key: "report_id", labelKey: "action_target_hint", type: "text", required: true },
  ],
  "link/observation": [
    { key: "observation_id", labelKey: "action_target_hint", type: "text", required: true },
  ],
  merge: [
    { key: "duplicate_id", labelKey: "action_target_hint", type: "text", required: true },
    { key: "reason", labelKey: "action_reason_hint", type: "textarea" },
  ],
  split: [
    { key: "report_ids", labelKey: "action_target_hint", type: "text", required: true },
    { key: "reason", labelKey: "action_reason_hint", type: "textarea" },
  ],
};

/**
 * The published path minus the `/api/rc/incidents/{id}/` prefix it was built with.
 *
 * `marker` already ends in the slash, so the tail starts at `at + marker.length` - slicing one
 * further turns `status` into `tatus`, which reads as "no form for this action" and then sends an
 * empty body the server rejects. Found in the browser: every incident action button 422'd.
 */
function tailOf(path: string, id: string): string {
  const marker = `/${id}/`;
  const at = path.indexOf(marker);
  return at === -1 ? "" : path.slice(at + marker.length);
}

/** `spec.id` is a private addition so a row can work out its own path tail. */
type RowSpec = ActionSpec & { id: string };

/** One action, its form, and whatever the server said when it refused. */
function ActionRow({
  spec,
  onDone,
}: {
  spec: RowSpec;
  onDone: () => void;
}) {
  const { t, enumLabel } = useI18n();
  const tail = tailOf(spec.path, spec.id);
  const fields = INCIDENT_FIELDS[tail];
  // A status move is the one action whose label this screen can rebuild in the reader's language
  // from its `target`; every other one arrives as the server's English prose. Known gap.
  const label =
    spec.action === "set_status" && spec.target
      ? t("ra_status_to", { status: enumLabel(INCIDENT_STATUS_KEYS, spec.target) })
      : spec.label;
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  // `split` wants a list; the form takes it comma-separated rather than building a report
  // picker that would need its own endpoint to search.
  const body = (): Record<string, unknown> => {
    const out: Record<string, unknown> = {};
    for (const field of fields ?? []) {
      const raw = (values[field.key] ?? "").trim();
      out[field.key] = field.key.endsWith("_ids")
        ? raw.split(",").map((part) => part.trim()).filter(Boolean)
        : raw;
    }
    if (tail === "status" && spec.target) out.status = spec.target;
    if (tail === "review") out.needs_review = values.needs_review === "on";
    return out;
  };

  const missing = (fields ?? []).filter(
    (field) => field.required && !(values[field.key] ?? "").trim(),
  );

  const submit = async () => {
    setBusy(true);
    setError(null);
    setDone(false);
    try {
      await request<unknown>(spec.method || "POST", spec.path, { body: body() });
      setValues({});
      setDone(true);
      onDone();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : String(cause));
    } finally {
      setBusy(false);
    }
  };

  return (
    <li className="action-row">
      <div className="row-between">
        <strong>{label}</strong>
        <button
          type="button"
          className="button small primary"
          disabled={busy || missing.length > 0}
          onClick={submit}
        >
          {busy ? t("sending") : t("run_action")}
        </button>
      </div>

      {fields && fields.length ? (
        <div className="action-form">
          {fields.map((field) => (
            <div className="field" key={field.key}>
              <label htmlFor={`${spec.action}-${field.key}`}>
                {t(field.labelKey)}
                {field.required ? " *" : ""}
              </label>
              {field.type === "textarea" ? (
                <textarea
                  id={`${spec.action}-${field.key}`}
                  value={values[field.key] ?? ""}
                  onChange={(event) =>
                    setValues((prev) => ({ ...prev, [field.key]: event.target.value }))
                  }
                />
              ) : (
                <input
                  id={`${spec.action}-${field.key}`}
                  type="text"
                  value={values[field.key] ?? ""}
                  onChange={(event) =>
                    setValues((prev) => ({ ...prev, [field.key]: event.target.value }))
                  }
                />
              )}
              {field.hintKey ? <p className="field-hint">{t(field.hintKey)}</p> : null}
            </div>
          ))}
        </div>
      ) : null}

      {fields === undefined ? <p className="meta">{t("action_no_form")}</p> : null}
      {missing.length ? <p className="field-hint">{t("action_required")}</p> : null}
      {done ? (
        <p className="meta" role="status">
          {t("action_done")}
        </p>
      ) : null}
      {error ? (
        <p className="meta" role="alert">
          {t("action_failed")} {error}
        </p>
      ) : null}
    </li>
  );
}

export function IncidentActions({
  incidentId,
  detail,
  onChanged,
}: {
  incidentId: string;
  detail: IncidentDetail;
  onChanged: () => void;
}) {
  const { t } = useI18n();
  const actions = detail.available_actions ?? [];

  return (
    <section className="card stack-sm">
      <h2>{t("actions_title")}</h2>
      <p className="meta">{t("actions_hint")}</p>
      {actions.length ? (
        <ul className="action-list">
          {actions.map((spec, index) => (
            <ActionRow
              key={`${spec.action}-${spec.target ?? index}`}
              spec={{ ...spec, id: incidentId }}
              onDone={onChanged}
            />
          ))}
        </ul>
      ) : (
        <p className="meta">{t("no_actions_for_role")}</p>
      )}
    </section>
  );
}

/* ------------------------------------------------------------------ requests */

const REQUEST_FIELDS: Record<string, FormField[]> = {
  acknowledge: [],
  escalate: [{ key: "reason", labelKey: "action_reason_hint", type: "textarea", required: true }],
  note: [{ key: "note", labelKey: "action_note_hint", type: "textarea", required: true }],
  message: [
    {
      key: "message",
      labelKey: "action_message_hint",
      hintKey: "victim_view",
      type: "textarea",
      required: true,
    },
  ],
  assign: [
    { key: "team", labelKey: "team_name", hintKey: "plan_generated_by", type: "text", required: true },
    { key: "note", labelKey: "action_note_hint", type: "textarea" },
  ],
  status: [],
  cancel: [{ key: "reason", labelKey: "action_reason_hint", type: "textarea" }],
};

const REQUEST_LABELS: Record<string, StringKey> = {
  acknowledge: "ra_acknowledge",
  assign: "ra_assign",
  escalate: "ra_escalate",
  note: "ra_note",
  message: "ra_message",
  cancel: "ra_cancel",
};

/**
 * The request action list, translated into the paths the client already knows.
 *
 * `available_actions` on a request says only `acknowledge` or `status:reviewing`, so the path is
 * rebuilt from the request id here. That is the same coupling the backend is asked to remove
 * (known issues 27 and 29); until then, an action name this file does not recognise is *listed
 * as not offered* rather than guessed at, because a wrong button on a live rescue request is
 * worse than a missing one.
 */
function toSpec(requestId: string, action: RequestAction): (RowSpec & { known: boolean }) | null {
  const base = `/api/rc/requests/${encodeURIComponent(requestId)}`;
  if (action.action.startsWith("status:")) {
    const target = action.action.slice("status:".length);
    return {
      action: "status",
      label: target,
      method: "POST",
      path: `${base}/status`,
      permission: "assistance:update",
      target,
      id: requestId,
      known: true,
    };
  }
  const known = action.action in REQUEST_FIELDS;
  return {
    action: action.action,
    label: action.action,
    method: "POST",
    path: `${base}/${action.action}`,
    permission: "assistance:update",
    target: action.target ?? null,
    id: requestId,
    known,
  };
}

function RequestActionRow({
  spec,
  onDone,
}: {
  spec: RowSpec & { known: boolean };
  onDone: () => void;
}) {
  const { t, enumLabel } = useI18n();
  const label =
    spec.action === "status"
      ? t("ra_status_to", { status: enumLabel(ASSISTANCE_STATUS_KEYS, spec.target ?? "") })
      : REQUEST_LABELS[spec.action]
        ? t(REQUEST_LABELS[spec.action])
        : spec.label;

  if (!spec.known && spec.action !== "status") {
    return (
      <li className="action-row">
        <div className="row-between">
          <strong>{label}</strong>
          <button type="button" className="button small" disabled>
            {t("run_action")}
          </button>
        </div>
        <p className="meta">{t("action_no_form")}</p>
      </li>
    );
  }

  const fields = REQUEST_FIELDS[spec.action] ?? [];
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const missing = fields.filter((field) => field.required && !(values[field.key] ?? "").trim());

  const submit = async () => {
    setBusy(true);
    setError(null);
    setDone(false);
    const body: Record<string, unknown> = {};
    for (const field of fields) body[field.key] = (values[field.key] ?? "").trim();
    if (spec.action === "status") {
      body.status = spec.target;
      // The endpoint's field is `note`, not the `reason` the incident routes use. Same
      // sentence, two names - the schemas are not unified yet.
      if (body.reason) {
        body.note = body.reason;
        delete body.reason;
      }
    }
    try {
      await request<unknown>(spec.method, spec.path, { body });
      setValues({});
      setDone(true);
      onDone();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : String(cause));
    } finally {
      setBusy(false);
    }
  };

  return (
    <li className="action-row">
      <div className="row-between">
        <strong>{label}</strong>
        <button
          type="button"
          className={`button small${spec.action === "cancel" ? " danger" : " primary"}`}
          disabled={busy || missing.length > 0}
          onClick={submit}
        >
          {busy ? t("sending") : t("run_action")}
        </button>
      </div>
      {fields.length ? (
        <div className="action-form">
          {fields.map((field) => (
            <div className="field" key={field.key}>
              <label htmlFor={`req-${spec.action}-${field.key}`}>
                {t(field.labelKey)}
                {field.required ? " *" : ""}
              </label>
              {field.type === "textarea" ? (
                <textarea
                  id={`req-${spec.action}-${field.key}`}
                  value={values[field.key] ?? ""}
                  onChange={(event) =>
                    setValues((prev) => ({ ...prev, [field.key]: event.target.value }))
                  }
                />
              ) : (
                <input
                  id={`req-${spec.action}-${field.key}`}
                  type="text"
                  value={values[field.key] ?? ""}
                  onChange={(event) =>
                    setValues((prev) => ({ ...prev, [field.key]: event.target.value }))
                  }
                />
              )}
              {field.hintKey ? <p className="field-hint">{t(field.hintKey)}</p> : null}
            </div>
          ))}
        </div>
      ) : null}
      {missing.length ? <p className="field-hint">{t("action_required")}</p> : null}
      {done ? (
        <p className="meta" role="status">
          {t("action_done")}
        </p>
      ) : null}
      {error ? (
        <p className="meta" role="alert">
          {t("action_failed")} {error}
        </p>
      ) : null}
    </li>
  );
}

export function RequestActions({
  data,
  onDone,
}: {
  data: RequestDetail;
  onDone: () => void;
}) {
  const { t } = useI18n();
  const specs = (data.available_actions ?? [])
    .map((action) => toSpec(data.request.id, action))
    .filter((spec): spec is RowSpec & { known: boolean } => spec !== null);

  return (
    <section className="card stack-sm">
      <h2>{t("actions_title")}</h2>
      <p className="meta">{t("actions_hint")}</p>
      {specs.length ? (
        <>
          <ul className="action-list">
            {specs.map((spec) => (
              <RequestActionRow key={spec.action + (spec.target ?? "")} spec={spec} onDone={onDone} />
            ))}
          </ul>
          {data.request.urgency_reasons?.length ? (
            <>
              <h3>{t("urgency_reasons")}</h3>
              <ReasonList items={data.request.urgency_reasons} />
            </>
          ) : null}
        </>
      ) : (
        <p className="meta">{t("no_actions_for_role")}</p>
      )}
    </section>
  );
}
