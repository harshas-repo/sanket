/**
 * The language control.
 *
 * Each option is written in its own script, and neither is translated into the other. That
 * is the whole point: someone who cannot read the language currently on screen has to be
 * able to recognise their own. A button labelled "Nepali" in English is useless to the only
 * person who needs to press it.
 *
 * It is a pair of buttons rather than a `<select>` because the app has exactly two languages
 * and a 44px tap target each - the same reason the community tabs are big.
 */

import { LANGUAGES } from "../i18n/strings";
import { useI18n } from "../i18n/I18nContext";

export function LanguageSwitch() {
  const { language, setLanguage, t } = useI18n();

  return (
    <div className="row" role="group" aria-label={t("language")}>
      {LANGUAGES.map((option) => {
        const active = option.value === language;
        return (
          <button
            key={option.value}
            type="button"
            className={active ? "button small primary" : "button small ghost"}
            aria-pressed={active}
            lang={option.value}
            onClick={() => setLanguage(option.value)}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
