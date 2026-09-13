/**
 * The chips that carry a record's status, and the only place their colours are decided.
 *
 * Three axes stay visibly separate, because collapsing them is how a screen stops being
 * truthful:
 *   urgency   how fast someone must act        (red scale)
 *   evidence  how sure we are that it happened (a ramp, strongest at the top)
 *   freshness how old the information is       (a fading scale)
 * A hazard icon or hue identifies the *kind* of event and never its severity, and the demo
 * chip uses a colour no status uses anywhere else.
 */

import type { ReactNode } from "react";

import {
  EVIDENCE_KEYS,
  FRESHNESS_KEYS,
  PRECISION_KEYS,
  PROVENANCE_KEYS,
  URGENCY_KEYS,
} from "../i18n/strings";
import { useI18n } from "../i18n/I18nContext";
import type {
  EvidenceState,
  FreshnessState,
  LocationPrecision,
  Provenance,
  Urgency,
} from "../api/types";

/** `title` is the server's own explanation of the label, shown on hover. */
function Chip({
  className,
  children,
  title,
}: {
  className: string;
  children: ReactNode;
  title?: string | null;
}) {
  return (
    <span className={`chip ${className}`} title={title ?? undefined}>
      {children}
    </span>
  );
}

export function UrgencyTag({ value, title }: { value: Urgency | string; title?: string | null }) {
  const { enumLabel } = useI18n();
  return (
    <Chip className={`urgency-${value}`} title={title}>
      {enumLabel(URGENCY_KEYS, value)}
    </Chip>
  );
}

export function EvidenceChip({
  value,
  title,
}: {
  value: EvidenceState | string;
  title?: string | null;
}) {
  const { enumLabel } = useI18n();
  return (
    <Chip className={`evidence-${value}`} title={title}>
      {enumLabel(EVIDENCE_KEYS, value)}
    </Chip>
  );
}

export function FreshnessChip({
  value,
  /** Usually the server's own `updated_label`, so the age shown is the age computed. */
  label,
  title,
}: {
  value: FreshnessState | string;
  label?: string | null;
  title?: string | null;
}) {
  const { enumLabel } = useI18n();
  const name = enumLabel(FRESHNESS_KEYS, value);
  return (
    <Chip className={`fresh-${value}`} title={title}>
      {label ? `${name} · ${label}` : name}
    </Chip>
  );
}

/**
 * Location precision is drawn as text, not as colour, and a coarse one says so: the risk on
 * a map is reading a district centroid as a place somebody stood.
 */
export function PrecisionChip({ value }: { value: LocationPrecision | string }) {
  const { enumLabel, t } = useI18n();
  const coarse = value === "district_centroid" || value === "unlocated";
  return (
    <Chip
      className="provenance"
      title={coarse ? t("precision_district_centroid") : null}
    >
      <span className="sr-only">{t("location")}: </span>
      {enumLabel(PRECISION_KEYS, value)}
    </Chip>
  );
}

export function ProvenanceBadge({ value }: { value: Provenance | null | undefined }) {
  const { enumLabel } = useI18n();
  if (!value) return null;
  return <Chip className="provenance">{enumLabel(PROVENANCE_KEYS, value)}</Chip>;
}

/** The rehearsal marker. Anything that renders a demo row must render this with it. */
export function DemoChip() {
  const { t } = useI18n();
  return <Chip className="demo">{t("provenance_demo")}</Chip>;
}

/** A row's full set of chips, in the order a reader should meet them. */
export function StatusChips({
  urgency,
  evidence,
  freshness,
  updatedLabel,
  demo,
  provenance,
  why,
}: {
  urgency?: Urgency | string | null;
  evidence?: EvidenceState | string | null;
  freshness?: FreshnessState | string | null;
  updatedLabel?: string | null;
  demo?: boolean;
  provenance?: Provenance | null;
  why?: string | null;
}) {
  return (
    <div className="row">
      {demo ? <DemoChip /> : null}
      {urgency ? <UrgencyTag value={urgency} title={why} /> : null}
      {evidence ? <EvidenceChip value={evidence} title={why} /> : null}
      {freshness ? <FreshnessChip value={freshness} label={updatedLabel} /> : null}
      {provenance ? <ProvenanceBadge value={provenance} /> : null}
    </div>
  );
}

/** A number that came from the server, formatted without inventing precision. */
export function Score({ value, band }: { value: number; band?: string }) {
  const { t } = useI18n();
  return (
    <span className="mono" title={`${t("impact_score")}: ${band ?? ""}`.trim()}>
      {Math.round(value)}
      <span className="sr-only"> {t("impact_score")}</span>
    </span>
  );
}
