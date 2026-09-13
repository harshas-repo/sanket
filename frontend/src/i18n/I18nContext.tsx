/**
 * Language state for the whole app.
 *
 * Order of precedence, because getting this wrong is how a Nepali speaker ends up staring at
 * English after signing in:
 *   1. an explicit choice made in this browser (the switch in the header),
 *   2. the signed-in account's `preferred_language`,
 *   3. the browser's own language, if it is Nepali,
 *   4. English.
 *
 * `t()` is only for chrome. Content that the server already writes in the reader's language
 * must be rendered as it arrives - re-translating it here would produce a second, worse
 * sentence and hide the fact that the platform speaks Nepali at all.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { lookup } from "./strings";
import type { Language, StringKey } from "./strings";

const LANGUAGE_KEY = "sanket.language";
const EXPLICIT_KEY = "sanket.language.explicit";

type Vars = Record<string, string | number | null | undefined>;

export interface I18nValue {
  language: Language;
  /** True when the reader chose this in the switch, as opposed to it being inherited. */
  chosenExplicitly: boolean;
  t: (key: StringKey, vars?: Vars) => string;
  /** Label for one of the API's enum values, falling back to the raw value. */
  enumLabel: (keys: Record<string, StringKey>, value: string | null | undefined) => string;
  setLanguage: (language: Language, explicit?: boolean) => void;
  /** Called with the account preference on sign-in; a manual choice always wins. */
  adoptPreference: (language: Language | null | undefined) => void;
  bcp47: string;
}

const I18nContext = createContext<I18nValue | null>(null);

function readStored(): Language | null {
  try {
    const stored = window.localStorage.getItem(LANGUAGE_KEY);
    return stored === "en" || stored === "ne" ? stored : null;
  } catch {
    return null;
  }
}

function readExplicit(): boolean {
  try {
    return window.localStorage.getItem(EXPLICIT_KEY) === "1";
  } catch {
    return false;
  }
}

function browserLanguage(): Language {
  return (window.navigator.language || "en").toLowerCase().startsWith("ne") ? "ne" : "en";
}

function persist(language: Language, explicit: boolean): void {
  try {
    window.localStorage.setItem(LANGUAGE_KEY, language);
    window.localStorage.setItem(EXPLICIT_KEY, explicit ? "1" : "0");
  } catch {
    /* storage may be unavailable; the language still applies for this session */
  }
}

/** `ne` in Nepali script needs Devanagari-capable fonts and a `lang` attribute for shaping. */
export const HTML_LANG: Record<Language, string> = { en: "en", ne: "ne" };

export function I18nProvider({ children }: { children: ReactNode }) {
  const [language, setLanguageState] = useState<Language>(() => readStored() ?? browserLanguage());
  const [chosenExplicitly, setChosenExplicitly] = useState<boolean>(readExplicit);

  useEffect(() => {
    document.documentElement.lang = HTML_LANG[language];
  }, [language]);

  const setLanguage = useCallback((next: Language, explicit = true) => {
    setLanguageState(next);
    setChosenExplicitly(explicit);
    persist(next, explicit);
  }, []);

  const adoptPreference = useCallback(
    (preferred: Language | null | undefined) => {
      if (!preferred) return;
      // A choice made on this device outranks the account setting: someone who switched to
      // read a shared screen should not be switched back by the next API call.
      if (readExplicit()) return;
      if (preferred !== language) setLanguage(preferred, false);
    },
    [language, setLanguage],
  );

  const t = useCallback(
    (key: StringKey, vars?: Vars) => {
      let text = lookup(key, language);
      if (vars) {
        for (const [name, value] of Object.entries(vars)) {
          text = text.split(`{${name}}`).join(value === null || value === undefined ? "" : String(value));
        }
      }
      return text;
    },
    [language],
  );

  const enumLabel = useCallback(
    (keys: Record<string, StringKey>, value: string | null | undefined) => {
      if (!value) return "—";
      const key = keys[value];
      // An enum the backend added before this file knew about shows up as its raw value,
      // which is readable, instead of disappearing.
      return key ? lookup(key, language) : value;
    },
    [language],
  );

  const value = useMemo<I18nValue>(
    () => ({
      language,
      chosenExplicitly,
      t,
      enumLabel,
      setLanguage,
      adoptPreference,
      // The speech recogniser needs a region tag, not the two-letter code the UI uses.
      bcp47: language === "ne" ? "ne-NP" : "en-US",
    }),
    [language, chosenExplicitly, t, enumLabel, setLanguage, adoptPreference],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nValue {
  const value = useContext(I18nContext);
  if (!value) throw new Error("useI18n must be used inside <I18nProvider>");
  return value;
}
