/**
 * The four states every panel can be in, kept apart on purpose.
 *
 * A single "no data" component for all of them is the quietest way to make this product
 * dangerous: an operator cannot tell an empty district from a dead data feed, and a resident
 * cannot tell "no incidents near you" from "your report did not send". So each state has its
 * own component, its own words and, for the failure, its own way out.
 */

import type { ReactNode } from "react";

import { ApiError } from "../api/client";
import { useI18n } from "../i18n/I18nContext";

export function Loading({ label }: { label?: string }) {
  const { t } = useI18n();
  return (
    <div className="state" role="status" aria-live="polite">
      <div className="row">
        <span className="spinner" aria-hidden="true" />
        <h3>{label ?? t("loading")}</h3>
      </div>
    </div>
  );
}

export function Empty({
  title,
  detail,
  action,
}: {
  title?: string;
  detail?: ReactNode;
  action?: ReactNode;
}) {
  const { t } = useI18n();
  return (
    <div className="state empty">
      <h3>{title ?? t("empty_title")}</h3>
      {detail ? <p className="meta">{detail}</p> : null}
      {action}
    </div>
  );
}

/**
 * A failure, with the reason the server gave.
 *
 * `unreachable` is separated from an HTTP error because the two need different actions: one
 * is "check your phone's signal", the other is "this record or this permission is the
 * problem". Showing old data is allowed only when the caller passes `staleNote`, so a panel
 * that kept its previous rows must say that it did.
 */
export function Failed({
  error,
  onRetry,
  staleNote,
}: {
  error: unknown;
  onRetry?: () => void;
  staleNote?: ReactNode;
}) {
  const { t } = useI18n();
  const apiError = error instanceof ApiError ? error : null;
  const detail =
    apiError?.detail ?? (error instanceof Error ? error.message : String(error ?? "Unknown error"));

  return (
    <div className="state error" role="alert">
      <h3>{apiError?.unreachable ? t("unreachable") : t("error_title")}</h3>
      <p className="meta">{detail}</p>
      {apiError?.forbidden ? <p className="meta">{t("no_actions")}</p> : null}
      {staleNote ? <p className="meta">{staleNote}</p> : null}
      {onRetry ? (
        <button type="button" className="button" onClick={onRetry}>
          {t("retry")}
        </button>
      ) : null}
    </div>
  );
}

/**
 * Renders the loading / failed / loaded choice for one `useAsync` result and hands the data
 * to `children`. `isEmpty` is the caller's judgement, because only the caller knows whether
 * zero rows is a fact worth stating or a filter that matched nothing.
 */
export function Panel<T>({
  state,
  children,
  isEmpty,
  emptyTitle,
  emptyDetail,
}: {
  state: { data: T | null; error: ApiError | null; loading: boolean };
  children: (data: T) => ReactNode;
  isEmpty?: (data: T) => boolean;
  emptyTitle?: string;
  emptyDetail?: ReactNode;
}) {
  const { data, error, loading } = state;
  const { t } = useI18n();
  if (loading) return <Loading />;
  if (error && data === null) return <Failed error={error} />;
  if (data === null) return <Empty title={emptyTitle} detail={emptyDetail} />;
  if (isEmpty?.(data)) return <Empty title={emptyTitle} detail={emptyDetail} />;
  return (
    <>
      {error ? (
        <p className="meta" role="status">
          {t("stale_warning", { detail: error.detail })}
        </p>
      ) : null}
      {children(data)}
    </>
  );
}
