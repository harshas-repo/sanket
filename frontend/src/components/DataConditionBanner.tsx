/**
 * The two things that must never be hidden: no network, and how old the last answer was.
 *
 * They are different failures, so they are not merged into one grey status line. Offline is amber
 * and it is about the device - the queue is holding what the person typed, and the screen may be
 * showing a cached picture. "Generated at" is plain text because nothing is wrong; the reader just
 * needs to know when the server produced what they are looking at.
 *
 * The age comes from the `X-Sanket-Generated-At` header on every response, not from a screen that
 * asked for it, so a page that loaded quietly still says when its numbers were made.
 */

import { useEffect, useState } from "react";

import { getMeta, onMetaChange } from "../api/client";
import type { ApiMeta } from "../api/client";
import { useOnline } from "../hooks/useOnline";
import { useI18n } from "../i18n/I18nContext";

/** `X-Sanket-Generated-At` is an ISO timestamp; only the clock time is useful on screen. */
function useGeneratedLabel(value: string | null): string | null {
  const { bcp47 } = useI18n();
  if (!value) return null;
  const stamp = Date.parse(value);
  if (Number.isNaN(stamp)) return value;
  return new Date(stamp).toLocaleTimeString(bcp47, { hour: "2-digit", minute: "2-digit" });
}

export function DataConditionBanner() {
  const { t } = useI18n();
  const online = useOnline();
  const [meta, setMeta] = useState<ApiMeta>(getMeta);

  useEffect(() => {
    const unsubscribe = onMetaChange(setMeta);
    return () => {
      unsubscribe();
    };
  }, []);

  const generated = useGeneratedLabel(meta.generatedAt);

  if (!online) {
    return (
      <div className="notice warn" role="status">
        <strong>{t("offline_banner")}</strong>
      </div>
    );
  }

  return generated ? (
    <p className="meta" title={meta.generatedAt ?? undefined}>
      {t("generated_at")} <span className="mono">{generated}</span>
    </p>
  ) : null;
}
