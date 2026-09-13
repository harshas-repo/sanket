/**
 * The outbox: what a phone holds when there is nothing to send to.
 *
 * Spec §54 is blunt about the requirement - a victim's report must not be lost because of
 * temporary connectivity - and the server side of it already exists: `POST
 * /api/community/offline/flush` takes a batch of `{kind, client_ref, payload}`, re-stamps each
 * one as `submitted_offline=true` so an update written yesterday is not presented as one written
 * now, and answers per item so one bad record cannot lose the rest.
 *
 * What lives here, then, is only the other half: keep the text, the numbers and the phone's own
 * clock reading until a send works. Three rules shape the file:
 *
 * 1. **Nothing is discarded on a failure to read.** A queue written by a previous version, or
 *    corrupt because the storage was full mid-write, is set aside under a separate key and the
 *    app starts clean. Silently emptying it would be the exact loss §54 forbids, so the old
 *    bytes stay on the device where a person can find them.
 * 2. **An item is removed only when the server accepted it.** A rejected item stays in the
 *    queue with `last_error` set and its attempt count raised, because "it failed once" and "the
 *    message is too long" are different problems, and the second one will never fix itself by
 *    retrying.
 * 3. **The queue belongs to the device, not to a session.** It survives sign-out, because the
 *    report was written before the connection was lost and the person may not be able to sign in
 *    again from there.
 */

import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";
import type { OfflineItemIn, OfflineFlushIn } from "../api/types";

export type OutboxKind = "report" | "request";

/** What was typed, plus everything needed to replay it as the endpoint that normally takes it. */
export interface OutboxItem {
  client_ref: string;
  kind: OutboxKind;
  payload: Record<string, unknown>;
  /** The phone's own clock, sent as `client_timestamp` so the record can be re-stamped honestly. */
  queued_at: string;
  attempts: number;
  last_error: string | null;
  /** Where it came from, for the line that says "queued from the report screen". */
  origin: string | null;
}

/** One server answer about one queued item. `null` while the queue has never been flushed. */
export interface FlushOutcome {
  accepted: number;
  rejected: number;
  errors: { client_ref: string | null; error: string }[];
}

const STORE_KEY = "sanket.outbox.v1";
/** Corrupt or newer-schema data is parked here rather than deleted. */
const QUARANTINE_KEY = "sanket.outbox.unreadable";

/** Stop after this many attempts: five failed sends means the item is wrong, not the signal. */
export const MAX_ATTEMPTS = 5;

function storage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    // Private mode and disabled storage both throw on *access*, not on use.
    return null;
  }
}

/**
 * A reference the phone makes up.
 *
 * `crypto.randomUUID` is missing on a non-secure origin - which is exactly how a LAN deployment
 * reaches this app - so it is a preference, not an assumption.
 */
function makeRef(): string {
  const cryptoApi = typeof crypto === "undefined" ? undefined : crypto;
  if (cryptoApi && typeof cryptoApi.randomUUID === "function") return cryptoApi.randomUUID();
  return `q-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

function isItem(value: unknown): value is OutboxItem {
  if (typeof value !== "object" || value === null) return false;
  const row = value as Record<string, unknown>;
  return (
    typeof row.client_ref === "string" &&
    (row.kind === "report" || row.kind === "request") &&
    typeof row.payload === "object" &&
    row.payload !== null &&
    typeof row.queued_at === "string"
  );
}

function park(raw: string | null): void {
  const store = storage();
  if (!store || raw === null) return;
  try {
    store.setItem(QUARANTINE_KEY, raw);
    store.removeItem(STORE_KEY);
  } catch {
    /* if even the quarantine write fails, the next read returns nothing and starts over */
  }
}

export function readOutbox(): OutboxItem[] {
  const store = storage();
  if (!store) return [];
  let raw: string | null = null;
  try {
    raw = store.getItem(STORE_KEY);
  } catch {
    return [];
  }
  if (!raw) return [];
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) throw new Error("not a list");
    // Anything in the list that is not recognisably an item is dropped *with* its bytes
    // preserved in the quarantine, so a partial corruption does not silently eat a report.
    const items = parsed.filter(isItem).map((item) => ({
      ...item,
      attempts: typeof item.attempts === "number" ? item.attempts : 0,
      last_error: typeof item.last_error === "string" ? item.last_error : null,
      origin: typeof item.origin === "string" ? item.origin : null,
    }));
    if (items.length !== parsed.length) park(raw);
    return items;
  } catch {
    park(raw);
    return [];
  }
}

function write(items: OutboxItem[]): boolean {
  const store = storage();
  if (!store) return false;
  try {
    store.setItem(STORE_KEY, JSON.stringify(items));
    return true;
  } catch {
    // A full quota is the one failure the person can act on, and it is why `enqueue`
    // returns a boolean instead of assuming it worked.
    return false;
  }
}

/* ------------------------------------------------------------------ notifications */

const listeners = new Set<() => void>();

function emit(): void {
  for (const listener of [...listeners]) listener();
}

/** Lets a component outside the hook (a banner, the account screen) react to a queue change. */
export function subscribeToOutbox(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/* ------------------------------------------------------------------ operations */

export function enqueue(input: {
  kind: OutboxKind;
  payload: Record<string, unknown>;
  origin?: string | null;
}): OutboxItem | null {
  const item: OutboxItem = {
    client_ref: makeRef(),
    kind: input.kind,
    payload: input.payload,
    queued_at: new Date().toISOString(),
    attempts: 0,
    last_error: null,
    origin: input.origin ?? null,
  };
  const next = [...readOutbox(), item];
  return write(next) ? (emit(), item) : null;
}

export function remove(clientRef: string): void {
  const remaining = readOutbox().filter((item) => item.client_ref !== clientRef);
  if (remaining.length !== readOutbox().length) {
    write(remaining);
    emit();
  }
}

export function clearOutbox(): void {
  write([]);
  emit();
}

function toOfflineItem(item: OutboxItem): OfflineItemIn {
  // The queued copy carries the phone's clock, never the console's: the server compares them
  // and says plainly when they disagree.
  return {
    kind: item.kind,
    client_ref: item.client_ref,
    payload: { ...item.payload, client_timestamp: item.queued_at, submitted_offline: true },
  };
}

/**
 * Sends the whole queue and reports per item.
 *
 * Items past `MAX_ATTEMPTS` are not sent again by this function - they stay listed with their
 * error so a person can delete them, which is the only honest action left for a message the
 * server has refused five times.
 */
export async function flushOutbox(): Promise<FlushOutcome | null> {
  const sendable = readOutbox().filter((item) => item.attempts < MAX_ATTEMPTS);
  if (!sendable.length) return null;

  const body: OfflineFlushIn = { items: sendable.map(toOfflineItem) };
  let response: Record<string, unknown>;
  try {
    response = await api.community.flush(body);
  } catch (cause) {
    // The network failed again: nothing was accepted, so nothing is dropped and the attempt
    // count does not move. A queue that gave up after one lost signal is useless.
    return {
      accepted: 0,
      rejected: 0,
      errors: [
        {
          client_ref: null,
          error: cause instanceof Error ? cause.message : "Could not reach the server",
        },
      ],
    };
  }

  const results = Array.isArray(response.results) ? (response.results as Record<string, unknown>[]) : [];
  const byRef = new Map<string, Record<string, unknown>>();
  for (const row of results) {
    if (typeof row.client_ref === "string") byRef.set(row.client_ref, row);
  }

  const accepted: string[] = [];
  const errors: { client_ref: string | null; error: string }[] = [];
  const updated = readOutbox().map((item) => {
    const result = byRef.get(item.client_ref);
    if (!result) {
      // No answer for this item means it was not in the batch the server processed (a capped
      // request, or a queue that changed mid-flight). Leave it and try again.
      return item;
    }
    if (result.ok) {
      accepted.push(item.client_ref);
      const ref = typeof result.ref_code === "string" ? result.ref_code : null;
      if (item.kind === "request" && ref) {
        // The reference code is the one thing a victim has to keep. It only exists after
        // the server accepted the item, so it is written back here rather than invented. The
        // server's schema is `extra="ignore"`, so the field is dropped on the way in - it is
        // stored for this phone's own "waiting items" list, not for the API.
        item.payload.server_ref_code = ref;
      }
      return { ...item, last_error: null };
    }
    const message = typeof result.error === "string" ? result.error : "The server refused it";
    errors.push({ client_ref: item.client_ref, error: message });
    return { ...item, attempts: item.attempts + 1, last_error: message };
  });

  write(updated.filter((item) => !accepted.includes(item.client_ref)));
  emit();
  return {
    accepted: accepted.length,
    rejected: errors.length,
    errors,
  };
}

/* ------------------------------------------------------------------ hook */

/**
 * The queue as React state.
 *
 * Every mount re-reads storage, so two open tabs of the same phone do not disagree about what is
 * still waiting to go.
 */
export function useOutbox(): {
  items: OutboxItem[];
  count: number;
  stale: OutboxItem[];
  flushing: boolean;
  flushError: string | null;
  lastOutcome: FlushOutcome | null;
  flush: () => Promise<void>;
  removeItem: (clientRef: string) => void;
  stored: boolean;
} {
  const [items, setItems] = useState<OutboxItem[]>(() => readOutbox());
  const [flushing, setFlushing] = useState(false);
  const [flushError, setFlushError] = useState<string | null>(null);
  const [lastOutcome, setLastOutcome] = useState<FlushOutcome | null>(null);

  useEffect(() => {
    const refresh = () => setItems(readOutbox());
    const off = subscribeToOutbox(refresh);
    window.addEventListener("online", refresh);
    refresh();
    return () => {
      off();
      window.removeEventListener("online", refresh);
    };
  }, []);

  const flush = useCallback(async () => {
    setFlushing(true);
    setFlushError(null);
    try {
      const outcome = await flushOutbox();
      setLastOutcome(outcome);
      if (outcome && outcome.errors.length) {
        setFlushError(outcome.errors[0].error);
      }
    } catch (cause) {
      setFlushError(cause instanceof Error ? cause.message : "Could not send the saved items");
    } finally {
      setItems(readOutbox());
      setFlushing(false);
    }
  }, []);

  const removeItem = useCallback((clientRef: string) => {
    remove(clientRef);
    setItems(readOutbox());
  }, []);

  return {
    items,
    count: items.length,
    stale: items.filter((item) => item.attempts >= MAX_ATTEMPTS),
    flushing,
    flushError,
    lastOutcome,
    flush,
    removeItem,
    // False means storage is unavailable: the queue would be lost on the next screen, and a
    // person offered "saved on this phone" while that is a lie is worse off than with no option.
    stored: storage() !== null,
  };
}
