/**
 * The shared pieces of the console: a screen header, a number that means something, a table,
 * and the strip that says when the data was made.
 *
 * These exist so that the same claim is worded the same way on six screens. The important
 * convention is `MetaStrip`: every panel states its own `generated_at` in the server's own
 * words, because an operator who cannot tell when a number was computed cannot tell whether
 * to act on it - and a screen that looks live and is not is the failure this product cannot
 * afford.
 */

import { useId, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { useI18n } from "../../i18n/I18nContext";
import type { StringKey } from "../../i18n/strings";
import { formatStamp } from "../../utils/time";
import type { Urgency } from "../../api/types";

/* ------------------------------------------------------------------ page frame */

export function Screen({
  title,
  intro,
  actions,
  children,
}: {
  title: string;
  intro?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <>
      <div className="row-between screen-head">
        <h1>{title}</h1>
        {actions ? <div className="row">{actions}</div> : null}
      </div>
      {intro ? <p className="lede">{intro}</p> : null}
      <div className="stack">{children}</div>
    </>
  );
}

/** A section inside a screen: a heading, why it is there, and what it holds. */
export function SubSection({
  title,
  note,
  count,
  actions,
  children,
}: {
  title: string;
  note?: ReactNode;
  count?: number | null;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="card stack-sm">
      <div className="row-between">
        <h2>
          {title}
          {count !== null && count !== undefined ? <span className="count">{count}</span> : null}
        </h2>
        {actions}
      </div>
      {note ? <p className="meta">{note}</p> : null}
      {children}
    </section>
  );
}

/**
 * The condition of the data, in the reader's terms.
 *
 * `generatedAt` is the payload's own stamp. `stale` is passed when the panel is showing cached
 * rows after a failed refresh - the caller knows and this does not guess.
 */
export function MetaStrip({
  generatedAt,
  extra,
  stale,
}: {
  generatedAt?: string | null;
  extra?: ReactNode;
  stale?: boolean;
}) {
  const { t, bcp47 } = useI18n();
  const stamp = generatedAt ? formatStamp(generatedAt, bcp47) : null;
  if (!stamp && !extra) return null;
  return (
    <p className={`meta meta-strip${stale ? " stale" : ""}`} role="note">
      {stamp ? `${t("generated_at")}: ${stamp}` : null}
      {stamp && extra ? " · " : null}
      {extra}
    </p>
  );
}

/* ------------------------------------------------------------------ numbers */

/**
 * One figure, with the words that make it a fact rather than a number.
 *
 * `note` is where the second-order detail goes ("2 of them are past their deadline"), so the
 * headline stays a single claim. `urgency` tints the value only when the number *is* an urgency
 * count - a red five for "critical, unacknowledged" - and never for a neutral total.
 */
export function Stat({
  label,
  value,
  note,
  urgency,
}: {
  label: string;
  value: number | string;
  note?: ReactNode;
  urgency?: Urgency;
}) {
  return (
    <div className="stat">
      <span className={`stat-value${urgency ? ` stat-${urgency}` : ""}`}>{value}</span>
      <span className="stat-label">{label}</span>
      {note ? <span className="meta">{note}</span> : null}
    </div>
  );
}

export function KeyValue({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="kv">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

/** A definition list built from rows that exist, so a missing field shows nothing. */
export function FieldGrid({
  items,
}: {
  items: { label: string; value: ReactNode; when?: boolean }[];
}) {
  const shown = items.filter((item) => item.when !== false && item.value !== null && item.value !== undefined);
  if (!shown.length) return null;
  return (
    <dl className="kv-grid">
      {shown.map((item, index) => (
        <KeyValue key={`${item.label}-${index}`} label={item.label}>
          {item.value}
        </KeyValue>
      ))}
    </dl>
  );
}

/* ------------------------------------------------------------------ tables */

export interface Column<T> {
  id: string;
  label: ReactNode;
  cell: (row: T, index: number) => ReactNode;
  /** `numeric` right-aligns, which is how a column of counts stays readable. */
  numeric?: boolean;
}

export function DataTable<T>({
  columns,
  rows,
  keyOf,
  caption,
}: {
  columns: Column<T>[];
  rows: T[];
  /** Takes the row index too, because a timeline's `at`+`kind` pair is not always unique. */
  keyOf: (row: T, index: number) => string;
  caption?: string;
}) {
  return (
    <div className="table-wrap">
      <table className="table">
        {caption ? <caption className="sr-only">{caption}</caption> : null}
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.id} scope="col" className={column.numeric ? "num" : undefined}>
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={keyOf(row, index)}>
              {columns.map((column) => (
                <td key={column.id} className={column.numeric ? "num" : undefined}>
                  {column.cell(row, index)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ------------------------------------------------------------------ controls */

/**
 * A filter over one of the API's enums.
 *
 * The options come from the key map, never from a list written here: when the backend adds a
 * status, a filter that was told the old names silently hides the new records, which is worse
 * than a filter with no option for it. Values outside the map still arrive as raw strings from
 * the server and are matched by `enumLabel`'s own fallback.
 */
export function EnumSelect({
  label,
  keys,
  value,
  onChange,
  includeAll = true,
}: {
  label: string;
  keys: Record<string, StringKey>;
  value: string;
  onChange: (next: string) => void;
  includeAll?: boolean;
}) {
  const { t, enumLabel } = useI18n();
  // `useId`, not a slug of the label: the labels are translated, so a slug would change when the
  // interface language changed and would collide the moment two filters on one screen shared a
  // word. An unassociated `<label>` is not a label - a screen reader reads this control as "combo
  // box, blank", which is what the browser pass found on every console filter.
  const id = useId();
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <select
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        {includeAll ? <option value="">{t("filter_all")}</option> : null}
        {Object.keys(keys).map((option) => (
          <option key={option} value={option}>
            {enumLabel(keys, option)}
          </option>
        ))}
      </select>
    </div>
  );
}

/** A free-text filter that says plainly that it is a filter. */
export function TextFilter({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (next: string) => void;
  placeholder?: string;
}) {
  const id = useId();
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        type="text"
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
      />
    </div>
  );
}

/**
 * Refresh, the interval it runs on, and whether it has stopped.
 *
 * `paused` is shown rather than hidden because a polling screen that silently stopped is the
 * same failure as a dead feed - only harder to notice from across the room.
 *
 * `seconds` is optional because an interval is a claim: a screen that refreshes on request
 * instead of on a clock must not advertise one. Omit it and only the `paused` half of the line
 * can appear, which is a fact about the timer rather than a promise about one.
 */
export function RefreshRow({
  generatedAt,
  onRefresh,
  seconds,
  paused,
  busy,
  busyLabel,
  note,
}: {
  generatedAt?: string | null;
  onRefresh: () => void;
  seconds?: number | null;
  paused: boolean;
  /** True while the refresh action is still running, so the button says so instead of looking dead. */
  busy?: boolean;
  busyLabel?: string;
  /** One line about what is happening, or about what is on screen while it happens. */
  note?: ReactNode;
}) {
  const { t } = useI18n();
  return (
    <>
      <MetaStrip generatedAt={generatedAt} stale={paused} extra={note} />
      <div className="row">
        <button type="button" className="button small" onClick={onRefresh} disabled={busy}>
          {busy ? (busyLabel ?? t("sending")) : t("refresh")}
        </button>
        {seconds !== null && seconds !== undefined ? (
          <span className="meta">{t("auto_refresh", { seconds })}</span>
        ) : null}
        {paused ? <span className="meta">{t("paused")}</span> : null}
      </div>
    </>
  );
}

/* ------------------------------------------------------------------ small things */

/** `{"status": "in_progress"}` -> `status: In progress`. Unknown keys print their raw value. */
export function Delta({ value }: { value: Record<string, unknown> | null | undefined }) {
  if (!value) return <span className="meta">—</span>;
  const entries = Object.entries(value).filter(([, item]) => item !== null && item !== undefined);
  if (!entries.length) return <span className="meta">—</span>;
  return (
    <span className="mono">
      {entries.map(([key, item], index) => (
        <span key={key}>
          {index ? "; " : ""}
          {key}={typeof item === "object" ? JSON.stringify(item) : String(item)}
        </span>
      ))}
    </span>
  );
}

/** A list of sentences, used for `why` and `prioritization_reasons`. */
export function ReasonList({ items, className }: { items: ReactNode[]; className?: string }) {
  if (!items.length) return null;
  return (
    <ul className={`reason-list${className ? ` ${className}` : ""}`}>
      {items.map((item, index) => (
        <li key={index}>{item}</li>
      ))}
    </ul>
  );
}

/** A number, or nothing at all. Never a zero where the server sent a null. */
export function count(value: number | null | undefined): string | null {
  return value === null || value === undefined ? null : String(value);
}

/**
 * Where a record named in the log lives in this app, if it lives anywhere.
 *
 * The audit trail names seven kinds of record and only three of them have a page of their own:
 * a facility has a list but no record page, and a source, an account and the platform's own mode
 * rows have nothing to open. For those this prints the id and stops. A link that lands on a page
 * saying "not found" is worse than no link at all, because it reads as the platform having lost
 * the record rather than never having had a page for it.
 */
const ENTITY_ROUTES: Record<string, string> = {
  incident: "/response-center/incidents",
  report: "/response-center/reports",
  // `/requests/:refCode` accepts the internal id too - `api.rc.request()` takes either.
  assistance_request: "/response-center/requests",
};

export function EntityLink({ entityType, entityId }: { entityType: string; entityId: string }) {
  const base = ENTITY_ROUTES[entityType];
  if (!base || !entityId) return <span className="mono">{entityId || "—"}</span>;
  return (
    <Link className="mono" to={`${base}/${encodeURIComponent(entityId)}`}>
      {entityId}
    </Link>
  );
}
