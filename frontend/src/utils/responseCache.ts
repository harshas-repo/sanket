/**
 * The last answer a screen received, kept on the device so the next visit is not blank.
 *
 * This is not an offline mode and must not be read as one. It stores the payload of a screen that
 * already loaded, and the screen shows it *while saying that it is doing so*, then replaces it with
 * the server's newest answer the moment that arrives. The payload carries its own `generated_at`,
 * so what is on screen states when it was made, and a panel that fell back to it gets a stale note
 * from the same machinery that handles a failed refresh.
 *
 * Only aggregate, non-personal payloads belong here - the Response Center's counts, never somebody's
 * reports or their own account. Storage itself cannot be trusted: private mode and a full quota both
 * throw, and neither is a reason to break a screen.
 */

const PREFIX = "sanket.cache.";

/** Past this the figures describe an earlier shift rather than this one, so they are not shown. */
const MAX_AGE_MS = 2 * 60 * 60 * 1000;

interface Entry<T> {
  saved_at: number;
  payload: T;
}

export interface Cached<T> {
  payload: T;
  saved_at: number;
}

function store(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    // Private mode and disabled storage both throw on *access*, not on use.
    return null;
  }
}

export function readCached<T>(key: string): Cached<T> | null {
  const box = store();
  if (!box) return null;
  let raw: string | null = null;
  try {
    raw = box.getItem(PREFIX + key);
  } catch {
    return null;
  }
  if (!raw) return null;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null || !("payload" in parsed)) {
      throw new Error("not a cache entry");
    }
    const entry = parsed as Entry<T>;
    const savedAt = Number(entry.saved_at);
    // The device's own clock against the device's own stamp: both halves are local, so a wrong
    // clock ages the entry, which is the safe direction.
    if (!Number.isFinite(savedAt) || Date.now() - savedAt > MAX_AGE_MS) throw new Error("too old to show");
    return { payload: entry.payload, saved_at: savedAt };
  } catch {
    // A payload written by a build that no longer exists, or a hand-edited entry. Dropping it is
    // the whole recovery - the screen fetches again like any first visit.
    try {
      box.removeItem(PREFIX + key);
    } catch {
      /* nothing left to try */
    }
    return null;
  }
}

export function writeCached(key: string, payload: unknown): void {
  const box = store();
  if (!box) return;
  try {
    const entry: Entry<unknown> = { saved_at: Date.now(), payload };
    box.setItem(PREFIX + key, JSON.stringify(entry));
  } catch {
    // A full quota costs the next visit its instant first paint, and nothing else.
  }
}
