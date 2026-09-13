/**
 * A stand-in for screens that do not exist yet.
 *
 * It says it is not built, because a route that renders a blank panel is read as "no data" by
 * the next person to open this app - and "no data" is a claim about Nepal, not about this
 * codebase. Every use of this component is deleted as its real screen lands; none of them
 * should survive into a deployment.
 */

import { Empty } from "../components/StatePanel";
import { useI18n } from "../i18n/I18nContext";
import type { StringKey } from "../i18n/strings";

export function NotBuilt({ section }: { section?: StringKey }) {
  const { t } = useI18n();
  return (
    <Empty
      title={section ? t(section) : undefined}
      detail={t("not_built")}
    />
  );
}
