/**
 * Turning a timestamp into words, in one place.
 *
 * Two rules decide everything here.
 *
 * The client never computes an age. "3 hours ago" is a subtraction between two clocks, and in
 * this product the server's clock is often not the wall clock at all: a rehearsal runs on a
 * simulated clock, and `shared/timeutils.humanize_age()` measures against that one. A browser
 * doing its own arithmetic would print a confident, wrong age on a record that is pretending to
 * be from yesterday. So every relative label must come from the server - `updated_label`,
 * `age`, `published_label`, `status_label` - and when a payload has none, the screen shows the
 * absolute stamp and says nothing about how old it is.
 *
 * The formatting itself is locale-aware, because a Nepali reader gets Devanagari numerals from
 * `Intl` only if the tag is right, and `useI18n().bcp47` is the app's single source for that.
 */

/** `2026-09-12T14:57:24Z` -> `12 Sep 2026, 20:57` in the reader's locale. */
export function formatStamp(iso: string | null | undefined, bcp47: string): string | null {
  if (!iso) return null;
  const at = Date.parse(iso);
  if (Number.isNaN(at)) return iso; // an unparsable stamp is shown as it arrived, not hidden
  return new Intl.DateTimeFormat(bcp47, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(at));
}

/** For a row where the time is noise and the day is the fact. */
export function formatDay(iso: string | null | undefined, bcp47: string): string | null {
  if (!iso) return null;
  const at = Date.parse(iso);
  if (Number.isNaN(at)) return iso;
  return new Intl.DateTimeFormat(bcp47, { dateStyle: "medium" }).format(new Date(at));
}

/**
 * The server's own words if it sent any, otherwise the absolute stamp.
 *
 * `label` is the payload's `*_label` field - already the right sentence, already computed
 * against the clock the record belongs to. Falling back to the stamp rather than to a made-up
 * "recent" is the point: a screen that cannot say how old something is should look like it.
 */
export function serverLabel(
  iso: string | null | undefined,
  label: string | null | undefined,
  bcp47: string,
): string | null {
  const own = label?.trim();
  if (own) return own;
  return formatStamp(iso, bcp47);
}

/**
 * A duration the server already worked out, e.g. an SLA's minutes. Numbers only, no guessing.
 *
 * The unit is part of the returned string, so a template must not add its own "min" after it -
 * that produced "Overdue by 5 h 27 min min". The unit words are English abbreviations in both
 * languages, which is a known localisation gap rather than a choice.
 */
export function minutesText(minutes: number | null | undefined): string | null {
  if (minutes === null || minutes === undefined) return null;
  const rounded = Math.round(Math.abs(minutes));
  if (rounded < 60) return `${rounded} min`;
  const hours = Math.floor(rounded / 60);
  const rest = rounded % 60;
  return rest ? `${hours} h ${rest} min` : `${hours} h`;
}

/**
 * A duration or interval the server sent in seconds - a source's fetch interval, a rehearsal
 * step's offset, how long a fetch took.
 *
 * Under a minute it speaks seconds, because that is the unit the interval is written in. Above
 * it, `minutesText` does the saying, so "1 h 30 min" is not rounded into a confident "1 h" and
 * the rounding rule stays in exactly one place. A day and above is a day: no source is
 * configured to fetch "every 1500 min", and a console row that wide stops being scannable.
 */
export function secondsText(seconds: number | null | undefined): string | null {
  if (seconds === null || seconds === undefined) return null;
  const total = Math.round(Math.abs(seconds));
  if (total < 60) return `${total} s`;
  if (total < 86400) return minutesText(total / 60);
  return `${Math.round(total / 86400)} d`;
}
