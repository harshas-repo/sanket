/**
 * One shape for "call the API and show what comes back".
 *
 * The rule that decides its design: a reloading screen must never fall back to blank. An
 * operator watching a queue who presses refresh and sees the rows vanish for 400ms learns to
 * stop pressing refresh. So `loading` is true only before the first successful answer, and a
 * later failure keeps the previous data on screen while saying loudly that it is stale.
 *
 * The optional `cacheKey` extends that same rule across a page load rather than only across a
 * refetch: the screen opens on what this device stored last time, already labelled as such, and
 * updates when the server answers. Without it nothing is stored, which is what every screen that
 * shows one person's own records wants.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "../api/client";
import { readCached, writeCached } from "../utils/responseCache";

export interface AsyncState<T> {
  data: T | null;
  error: ApiError | null;
  /** True only before the first answer arrives - the "show a spinner" flag. */
  loading: boolean;
  /** True while refetching with data already on screen - the "dim the panel" flag. */
  refreshing: boolean;
  /** True while what is on screen is the payload this device stored on an earlier visit rather
   *  than an answer from the server. Only set when the caller asked for a cache, and only the
   *  caller can say so honestly - which is why it is exposed rather than rendered from here. */
  cached: boolean;
  reload: () => void;
  /** Replaces the cached data after a local mutation, without a round trip. */
  setData: (next: T) => void;
}

export function useAsync<T>(
  load: (signal: AbortSignal) => Promise<T>,
  deps: readonly unknown[] = [],
  cacheKey?: string,
): AsyncState<T> {
  // Read once, before anything else decides whether this screen starts blank or starts with the
  // last answer it got. A lazy initialiser, because every later render must not touch storage.
  const [boot] = useState(() => (cacheKey ? readCached<T>(cacheKey) : null));
  const [data, setData] = useState<T | null>(boot?.payload ?? null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(boot === null);
  const [cached, setCached] = useState(boot !== null);
  const [refreshing, setRefreshing] = useState(false);
  const [nonce, setNonce] = useState(0);
  const hasData = useRef(boot !== null);

  // `load` is re-created every render by most callers, so it cannot be a dependency. The
  // array the caller passes is the dependency list, deliberately, and this ref keeps the
  // latest closure without forcing a re-fetch.
  const loadRef = useRef(load);
  loadRef.current = load;

  useEffect(() => {
    const controller = new AbortController();
    let active = true;

    if (hasData.current) setRefreshing(true);
    else setLoading(true);

    loadRef
      .current(controller.signal)
      .then((result) => {
        if (!active) return;
        hasData.current = true;
        setData(result);
        setError(null);
        // The server's answer supersedes the stored one: it is the only way this flag turns off.
        setCached(false);
        if (cacheKey) writeCached(cacheKey, result);
      })
      .catch((cause: unknown) => {
        if (!active || controller.signal.aborted) return;
        setError(
          cause instanceof ApiError
            ? cause
            : new ApiError({
                kind: "parse",
                path: "",
                detail: cause instanceof Error ? cause.message : "Something went wrong loading this.",
              }),
        );
      })
      .finally(() => {
        if (!active) return;
        setLoading(false);
        setRefreshing(false);
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [...deps, nonce]);

  const reload = useCallback(() => setNonce((value) => value + 1), []);

  // A caller's own update is as current as a server's answer, and is stored so the next visit does
  // not resurrect the payload from before the change someone just made.
  const replace = useCallback(
    (next: T) => {
      hasData.current = true;
      setCached(false);
      setLoading(false);
      setData(next);
      if (cacheKey) writeCached(cacheKey, next);
    },
    [cacheKey],
  );

  return { data, error, loading, refreshing, cached, reload, setData: replace };
}

/**
 * Repeats a fetch on an interval while the tab is visible.
 *
 * Auto-refresh is a judgement call in a product where a stale screen is dangerous and a
 * screen that moves under your hands is unusable: the interval only fires when the document
 * is visible, and a paused interval is reported to the caller so it can say "paused".
 */
export function usePolling(reload: () => void, intervalMs: number | null): boolean {
  const [paused, setPaused] = useState(false);
  const reloadRef = useRef(reload);
  reloadRef.current = reload;

  useEffect(() => {
    if (!intervalMs) return;
    const tick = () => {
      if (document.visibilityState === "hidden") {
        setPaused(true);
        return;
      }
      setPaused(false);
      reloadRef.current();
    };
    const id = window.setInterval(tick, intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);

  return paused;
}
