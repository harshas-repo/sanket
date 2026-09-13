/**
 * Who is signed in, what they may do, and which of the two products they are looking at.
 *
 * The token comes from `POST /api/auth/login` and is held by `api/client.ts`. This context
 * holds the *user*, because the two surfaces are decided by the account, not by the URL: an
 * operator who types a community address must land on the console, and a resident who types
 * a console address must not be shown a queue they cannot read.
 *
 * `permissions` is copied from the server's own answer. Nothing in the frontend recomputes
 * what an operator may do - it asks `can()`, which asks that list, and the server enforces
 * the same list again on every call. A UI that hid a button the API would accept is a bug
 * the operator works around; this design makes the API the only authority.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";

import { ApiError, api, getToken, onUnauthorized, setToken } from "../api/client";
import type { Surface, SystemMode, User } from "../api/types";
import { useI18n } from "../i18n/I18nContext";

export type AuthStatus = "booting" | "signed_out" | "signed_in";

export interface AuthValue {
  status: AuthStatus;
  user: User | null;
  /** Which product this account belongs to, straight from the login response. */
  surface: Surface | null;
  mode: SystemMode;
  error: string | null;
  busy: boolean;
  login: (username: string, password: string) => Promise<LoginOutcome>;
  logout: () => void;
  /** Re-reads the account; used after a profile edit. */
  refreshMe: () => Promise<void>;
  can: (permission: string | undefined | null) => boolean;
  /** True for operator/coordinator/analyst - the staff side of the app. */
  isStaff: boolean;
}

/** `unknown` so the caller can only branch on the two real outcomes. */
export type LoginOutcome = { ok: true; surface: Surface } | { ok: false; message: string };

const LIVE_MODE: SystemMode = { mode: "live", scenario_id: null, sim_clock: null };

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const { adoptPreference } = useI18n();
  const [status, setStatus] = useState<AuthStatus>(() => (getToken() ? "booting" : "signed_out"));
  const [user, setUser] = useState<User | null>(null);
  const [surface, setSurface] = useState<Surface | null>(null);
  const [mode, setMode] = useState<SystemMode>(LIVE_MODE);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const clearSession = useCallback(() => {
    setToken(null);
    setUser(null);
    setSurface(null);
    setStatus("signed_out");
  }, []);

  // A revoked or expired token can surface on any call. Ending the session here means one
  // place decides what "you are signed out" looks like, instead of twelve screens each
  // inventing their own half-message.
  useEffect(
    () =>
      onUnauthorized((reason) => {
        clearSession();
        setError(reason.detail);
      }),
    [clearSession],
  );

  /** Boot: a stored token is not proof it still works, so ask before trusting it. */
  useEffect(() => {
    if (!getToken()) return;
    let cancelled = false;
    api
      .auth.me()
      .then((response) => {
        if (cancelled) return;
        setUser(response.user);
        setSurface(response.user.is_response_center ? "response_center" : "community");
        setStatus("signed_in");
        adoptPreference(response.user.preferred_language);
      })
      .catch((cause: unknown) => {
        if (cancelled) return;
        const detail = cause instanceof ApiError ? cause.detail : "Could not restore your session.";
        if (cause instanceof ApiError && cause.unauthorized) {
          clearSession();
          setError(detail);
          return;
        }
        // Unreachable or a server fault: say so and show the login screen, but keep the
        // token. A phone that lost signal should come back to the same session on retry,
        // not be asked for a password it already has.
        setStatus("signed_out");
        setError(detail);
      });
    return () => {
      cancelled = true;
    };
  }, [adoptPreference, clearSession]);

  const login = useCallback(
    async (username: string, password: string): Promise<LoginOutcome> => {
      setBusy(true);
      setError(null);
      try {
        const response = await api.auth.login({ username, password });
        setToken(response.token);
        setUser(response.user);
        setSurface(response.surface);
        setMode(response.mode);
        setStatus("signed_in");
        adoptPreference(response.user.preferred_language);
        return { ok: true, surface: response.surface };
      } catch (cause) {
        const message =
          cause instanceof ApiError
            ? cause.detail
            : cause instanceof Error
              ? cause.message
              : "Could not sign in.";
        setError(message);
        return { ok: false, message };
      } finally {
        if (mounted.current) setBusy(false);
      }
    },
    [adoptPreference],
  );

  const logout = useCallback(() => {
    clearSession();
    setError(null);
    setMode(LIVE_MODE);
  }, [clearSession]);

  const refreshMe = useCallback(async () => {
    if (!getToken()) return;
    const response = await api.auth.me();
    setUser(response.user);
  }, []);

  const can = useCallback(
    (permission: string | undefined | null) => {
      if (!permission) return true; // an action with no permission listed is allowed
      return user?.permissions.includes(permission) ?? false;
    },
    [user],
  );

  const value = useMemo<AuthValue>(
    () => ({
      status,
      user,
      surface,
      mode,
      error,
      busy,
      login,
      logout,
      refreshMe,
      can,
      isStaff: user?.is_response_center ?? false,
    }),
    [status, user, surface, mode, error, busy, login, logout, refreshMe, can],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside <AuthProvider>");
  return value;
}

/** Which page a signed-in user should land on, derived from the account, never from a guess. */
export function homeFor(surface: Surface | null): string {
  return surface === "response_center" ? "/response-center" : "/community";
}
