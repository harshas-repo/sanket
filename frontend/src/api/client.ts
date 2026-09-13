/**
 * The only file in the frontend that talks HTTP.
 *
 * Paths come from `logs/routes.txt`, accepted parameters from `logs/api_bodies.log` and
 * response fields from `logs/api_shapes.log` - all three printed by the probes in `probe/`.
 * Nothing here is written from memory, because an invented path answers 404 in a way that
 * looks exactly like an empty database, and an invented query parameter is silently ignored
 * and looks exactly like "no matches".
 *
 * Three jobs this file takes on so no page has to:
 *  1. Attach the token, and say plainly when the server has rejected it.
 *  2. Turn every failure - HTTP, network, unparseable - into one `ApiError` shape with a
 *     sentence a user can act on. A spinner that never ends is not a failure state.
 *  3. Keep the two provenance headers the server puts on every response, so "am I looking
 *     at a rehearsal?" is a single value the whole app agrees on rather than a guess made
 *     per screen.
 */

import type {
  ActivityResponse,
  AgentClassifyIn,
  AgentInvestigateIn,
  AgentRespondIn,
  AgentRun,
  AgentRunsResponse,
  AgentStatusResponse,
  AgentToolsResponse,
  AlertsResponse,
  AssignIn,
  AssistanceRequestIn,
  AuditListResponse,
  ChatIn,
  CommunityActivity,
  CommunityFeed,
  CommunityRequestDetail,
  Dashboard,
  DemoAccountsResponse,
  HealthResponse,
  HelpRequestOutcome,
  IncidentDetail,
  IncidentListResponse,
  LinkIn,
  LoginIn,
  LoginResponse,
  NoteIn,
  NotificationsResponse,
  OfflineFlushIn,
  ProfilePatch,
  PublicIncident,
  QueueResponse,
  ReasonIn,
  RegisterIn,
  ReportDetailResponse,
  ReportIn,
  ReportListResponse,
  ReportOutcome,
  RequestDetail,
  RequestListResponse,
  ResourceAvailabilityIn,
  ResourceCreateIn,
  ResourceListResponse,
  SignalsResponse,
  SourceRunsResponse,
  SourcesResponse,
  SourcePollAck,
  StatusIn,
  SystemStatus,
  TimelineResponse,
  UserResponse,
} from "./types";

/* ------------------------------------------------------------------ configuration */

/**
 * Empty by design. In development Vite proxies `/api` and `/geo` to the backend (see
 * `vite.config.ts`), and in production the two are served from one origin. Setting this
 * explicitly would introduce a CORS conversation in development that production never has.
 */
const API_ROOT = (import.meta.env.VITE_API_URL ?? "").replace(/\/+$/, "");

/** Where the geojson boundary files are mounted (see `backend/app/main.py`). */
export const GEO_ROOT = API_ROOT;

/* ------------------------------------------------------------------ token */

const TOKEN_KEY = "sanket.token";

function readStoredToken(): string | null {
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    // Private-mode Safari throws on any storage access. A session that cannot persist a
    // token is still usable until reload.
    return null;
  }
}

let token: string | null = readStoredToken();

export function getToken(): string | null {
  return token;
}

export function setToken(value: string | null): void {
  token = value;
  try {
    if (value) window.localStorage.setItem(TOKEN_KEY, value);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* ignored for the same reason as above */
  }
}

/**
 * The token lives in localStorage, which any script on this page can read. Acceptable while
 * there is nothing behind it but demo credentials and the app has no third-party scripts;
 * listed in docs/known-issues.md as a pre-production item (an httpOnly cookie plus CSRF
 * token is the replacement).
 */

let unauthorizedHandler: ((reason: ApiError) => void) | null = null;

/** Registered by the auth context so a revoked session can end in one place. */
export function onUnauthorized(handler: ((reason: ApiError) => void) | null): void {
  unauthorizedHandler = handler;
}

/* ------------------------------------------------------------------ provenance meta */

export interface ApiMeta {
  mode: "live" | "demo";
  /** When the server produced the last response, from `X-Sanket-Generated-At`. */
  generatedAt: string | null;
}

let meta: ApiMeta = { mode: "live", generatedAt: null };
const metaListeners = new Set<(next: ApiMeta) => void>();

export function getMeta(): ApiMeta {
  return meta;
}

export function onMetaChange(listener: (next: ApiMeta) => void): () => void {
  metaListeners.add(listener);
  return () => metaListeners.delete(listener);
}

function publishMode(mode: string | null, generatedAt: string | null): void {
  const next: ApiMeta = {
    mode: mode === "demo" ? "demo" : "live",
    generatedAt: generatedAt ?? meta.generatedAt,
  };
  if (next.mode === meta.mode && next.generatedAt === meta.generatedAt) return;
  meta = next;
  for (const listener of metaListeners) listener(next);
}

/* ------------------------------------------------------------------ errors */

export type ApiErrorKind = "http" | "network" | "timeout" | "parse";

/** One error shape for everything that can go wrong, with a sentence for the screen. */
export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number;
  readonly path: string;
  /** The server's own explanation, when it sent one. */
  readonly detail: string;
  /** Field-level messages from a 422, keyed by field name. */
  readonly fields: Record<string, string>;

  constructor(init: {
    kind?: ApiErrorKind;
    status?: number;
    path: string;
    detail: string;
    fields?: Record<string, string>;
    cause?: unknown;
  }) {
    super(init.detail);
    this.name = "ApiError";
    this.kind = init.kind ?? "http";
    this.status = init.status ?? 0;
    this.path = init.path;
    this.detail = init.detail;
    this.fields = init.fields ?? {};
    if (init.cause) this.cause = init.cause;
  }

  get unauthorized(): boolean {
    return this.status === 401;
  }

  get forbidden(): boolean {
    return this.status === 403;
  }

  get notFound(): boolean {
    return this.status === 404;
  }

  /** True when the request never reached the server: show "offline", never "no results". */
  get unreachable(): boolean {
    return this.kind === "network" || this.kind === "timeout";
  }
}

/**
 * FastAPI sends `detail` as a string for its own refusals and as an array of validation
 * errors for a 422. Both arrive here, and both are flattened into something a form can
 * display under the field it belongs to.
 */
function interpret(status: number, body: unknown, path: string): ApiError {
  const record = (body ?? {}) as Record<string, unknown>;
  const raw = record.detail;

  if (typeof raw === "string" && raw.trim()) {
    return new ApiError({ status, path, detail: raw });
  }
  if (Array.isArray(raw)) {
    const fields: Record<string, string> = {};
    const messages: string[] = [];
    for (const item of raw) {
      const entry = (item ?? {}) as Record<string, unknown>;
      const loc = Array.isArray(entry.loc) ? (entry.loc as unknown[]) : [];
      const field = loc.filter((part) => part !== "body").pop();
      const message = typeof entry.msg === "string" ? entry.msg : "Invalid value";
      if (typeof field === "string") {
        fields[field] = message;
        messages.push(`${field}: ${message}`);
      } else {
        messages.push(message);
      }
    }
    return new ApiError({
      status,
      path,
      detail: messages.join("; ") || "The server refused this request.",
      fields,
    });
  }
  if (status === 401) {
    return new ApiError({ status, path, detail: "Your session has ended. Sign in again." });
  }
  if (status === 403) {
    return new ApiError({
      status,
      path,
      detail: "Your role cannot do this on this record.",
    });
  }
  if (status === 404) {
    return new ApiError({ status, path, detail: "No such record." });
  }
  return new ApiError({
    status,
    path,
    detail: `The server answered ${status} for ${path}.`,
  });
}

/* ------------------------------------------------------------------ transport */

export type QueryValue = string | number | boolean | null | undefined | string[];
export type Query = Record<string, QueryValue>;

/**
 * `undefined` and `null` are skipped rather than sent as text, because `?district=` would
 * reach the server as an empty string and filter every row out - which looks like an empty
 * country, not like a bug.
 */
export function withQuery(path: string, query?: Query): string {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) {
      for (const item of value) params.append(key, String(item));
      continue;
    }
    params.set(key, String(value));
  }
  const text = params.toString();
  return text ? `${path}?${text}` : path;
}

function timeoutSignal(ms: number): { signal: AbortSignal; cancel: () => void } {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(new DOMException("timeout", "TimeoutError")), ms);
  return { signal: controller.signal, cancel: () => window.clearTimeout(timer) };
}

export interface RequestOptions {
  query?: Query;
  body?: unknown;
  /** False to skip the Authorization header (login, health, demo account list). */
  auth?: boolean;
  signal?: AbortSignal;
  timeoutMs?: number;
}

export async function request<T>(
  method: string,
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const { query, body, auth = true, signal, timeoutMs = 30_000 } = options;
  const url = `${API_ROOT}${withQuery(path, query)}`;
  const headers: Record<string, string> = { Accept: "application/json" };
  if (auth && token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";

  const timer = timeoutSignal(timeoutMs);
  const combined = signal ?? timer.signal;

  let response: Response;
  try {
    response = await fetch(url, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: combined,
    });
  } catch (cause) {
    const aborted = cause instanceof DOMException && cause.name === "AbortError";
    if (signal?.aborted) throw cause; // the caller navigated away; not a user-facing error
    if (aborted || (cause instanceof Error && cause.name === "TimeoutError")) {
      throw new ApiError({
        kind: "timeout",
        path,
        detail: "The server did not answer in time. The data on screen may be older than it looks.",
        cause,
      });
    }
    throw new ApiError({
      kind: "network",
      path,
      detail: `Cannot reach the server at ${API_ROOT || "this origin"}. Is the backend running?`,
      cause,
    });
  } finally {
    timer.cancel();
  }

  publishMode(
    response.headers.get("x-sanket-mode"),
    response.headers.get("x-sanket-generated-at"),
  );

  const text = await response.text();
  let parsed: unknown = null;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch (cause) {
      // A proxy or an HTML error page, not the API. Saying so beats showing "[object Object]".
      throw new ApiError({
        kind: "parse",
        status: response.status,
        path,
        detail: `${path} answered something that is not JSON (${text.slice(0, 80) || "empty body"}).`,
        cause,
      });
    }
  }

  if (!response.ok) {
    const error = interpret(response.status, parsed, path);
    if (response.status === 401 && auth && token) {
      setToken(null);
      unauthorizedHandler?.(error);
    }
    throw error;
  }

  if (response.status === 204 || text === "") return undefined as T;
  return parsed as T;
}

export const get = <T,>(path: string, query?: Query, options: RequestOptions = {}) =>
  request<T>("GET", path, { query, ...options });

export const post = <T,>(path: string, body?: unknown, options: RequestOptions = {}) =>
  request<T>("POST", path, { body, ...options });

export const patch = <T,>(path: string, body?: unknown, options: RequestOptions = {}) =>
  request<T>("PATCH", path, { body, ...options });

/* ------------------------------------------------------------------ endpoints */

export interface IncidentFilters extends Query {
  incident_type?: string;
  district?: string;
  urgency?: string;
  evidence_state?: string;
  q?: string;
  only_within_nepal?: boolean;
  include_archived?: boolean;
  limit?: number;
}

export interface RequestFilters extends Query {
  status?: string;
  urgency?: string;
  district?: string;
  unassigned_only?: boolean;
  limit?: number;
}

export interface ResourceFilters extends Query {
  resource_type?: string;
  district?: string;
  availability?: string;
  include_inactive?: boolean;
  limit?: number;
}

/**
 * How long to wait on an agent run that goes to a real model.
 *
 * The default 30s is right for a dashboard read. An agent loop is not a dashboard read: it
 * sends the report to the model, waits, calls the tools the model chose, waits again, and
 * answers - so two provider round-trips plus the tool time can pass half a minute while every
 * step it completed is already committed. Cutting that off at 30s would show an operator a
 * timeout over a request that was genuinely filed, which is worse than waiting. Stored runs and
 * the activity timeline are how the finished run is checked, not by re-issuing the call.
 *
 * The resident's chat gets it too: that route asks the same model the same question in a
 * resident's words, and a reply that takes a minute is still a reply the screen should show.
 */
const AGENT_RUN_TIMEOUT_MS = 180_000;

export const api = {
  health: () => get<HealthResponse>("/api/health", undefined, { auth: false }),
  systemStatus: () => get<SystemStatus>("/api/system/status"),

  auth: {
    login: (body: LoginIn) =>
      post<LoginResponse>("/api/auth/login", body, { auth: false }),
    register: (body: RegisterIn) =>
      post<LoginResponse | Record<string, unknown>>("/api/auth/register", body, { auth: false }),
    me: (signal?: AbortSignal) => get<UserResponse>("/api/auth/me", undefined, { signal }),
    updateMe: (body: ProfilePatch) => patch<UserResponse>("/api/auth/me", body),
    demoAccounts: () => get<DemoAccountsResponse>("/api/auth/demo-accounts", undefined, { auth: false }),
  },

  incidents: {
    list: (filters: IncidentFilters = {}, signal?: AbortSignal) =>
      get<IncidentListResponse>("/api/incidents", { limit: 100, ...filters }, { signal }),
    detail: (id: string, signal?: AbortSignal) =>
      get<IncidentDetail>(`/api/incidents/${encodeURIComponent(id)}`, undefined, { signal }),
    timeline: (id: string) =>
      get<TimelineResponse>(`/api/incidents/${encodeURIComponent(id)}/timeline`),
    reports: (id: string, includeDuplicates = false) =>
      get<ReportListResponse>(`/api/incidents/${encodeURIComponent(id)}/reports`, {
        include_duplicates: includeDuplicates || undefined,
      }),
  },

  /** The console's own incident view: same record, plus what only staff may see. */
  rc: {
    dashboard: (signal?: AbortSignal) => get<Dashboard>("/api/rc/dashboard", undefined, { signal }),
    queue: (options: Query = {}, signal?: AbortSignal) =>
      get<QueueResponse>("/api/rc/queue", options, { signal }),
    incident: (id: string, signal?: AbortSignal) =>
      get<IncidentDetail>(`/api/rc/incidents/${encodeURIComponent(id)}`, undefined, { signal }),
    reports: (query: Query = {}, signal?: AbortSignal) =>
      get<ReportListResponse>("/api/rc/reports", { limit: 100, ...query }, { signal }),
    /** The destination of the `/response-center/reports/{id}` link the backend sends operators. */
    report: (reportId: string, signal?: AbortSignal) =>
      get<ReportDetailResponse>(`/api/rc/reports/${encodeURIComponent(reportId)}`, undefined, {
        signal,
      }),
    verifyReport: (reportId: string, body: { reason: string; state?: string }) =>
      post<ReportDetailResponse>(`/api/rc/reports/${encodeURIComponent(reportId)}/verify`, body),
    requests: (filters: RequestFilters = {}, signal?: AbortSignal) =>
      get<RequestListResponse>("/api/rc/requests", { limit: 200, ...filters }, { signal }),
    /** Accepts the internal id or the human ref code - the endpoint takes either. */
    request: (idOrRef: string, signal?: AbortSignal) =>
      get<RequestDetail>(`/api/rc/requests/${encodeURIComponent(idOrRef)}`, undefined, { signal }),
    acknowledge: (id: string, body: { note?: string } = {}) =>
      post<RequestDetail>(`/api/rc/requests/${encodeURIComponent(id)}/acknowledge`, body),
    assign: (id: string, body: AssignIn) =>
      post<RequestDetail>(`/api/rc/requests/${encodeURIComponent(id)}/assign`, body),
    status: (id: string, body: StatusIn) =>
      post<RequestDetail>(`/api/rc/requests/${encodeURIComponent(id)}/status`, body),
    escalate: (id: string, body: { reason: string }) =>
      post<RequestDetail>(`/api/rc/requests/${encodeURIComponent(id)}/escalate`, body),
    note: (id: string, body: NoteIn) =>
      post<RequestDetail>(`/api/rc/requests/${encodeURIComponent(id)}/note`, body),
    message: (id: string, body: { message: string }) =>
      post<RequestDetail>(`/api/rc/requests/${encodeURIComponent(id)}/message`, body),
    incidentAction: (id: string, action: string, body: unknown) =>
      post<IncidentDetail>(`/api/rc/incidents/${encodeURIComponent(id)}/${action}`, body),
    linkReport: (id: string, body: LinkIn) =>
      post<IncidentDetail>(`/api/rc/incidents/${encodeURIComponent(id)}/link/report`, body),
    linkObservation: (id: string, body: LinkIn) =>
      post<IncidentDetail>(`/api/rc/incidents/${encodeURIComponent(id)}/link/observation`, body),
    resources: (filters: ResourceFilters = {}, signal?: AbortSignal) =>
      get<ResourceListResponse>("/api/rc/resources", { limit: 300, ...filters }, { signal }),
    addResource: (body: ResourceCreateIn) => post<Record<string, unknown>>("/api/rc/resources", body),
    resourceAvailability: (id: string, body: ResourceAvailabilityIn) =>
      post<Record<string, unknown>>(`/api/rc/resources/${encodeURIComponent(id)}/availability`, body),
    deactivateResource: (id: string, body: ReasonIn = {}) =>
      post<Record<string, unknown>>(`/api/rc/resources/${encodeURIComponent(id)}/deactivate`, body),
    seedResources: (body: Record<string, unknown> = {}) =>
      post<Record<string, unknown>>("/api/rc/resources/seed", body),
    activity: (limit = 40) => get<ActivityResponse>("/api/rc/activity", { limit }),
    audit: (query: Query = {}) => get<AuditListResponse>("/api/rc/audit", { limit: 50, ...query }),
    auditFor: (entityType: string, entityId: string) =>
      get<AuditListResponse>(`/api/rc/audit/${encodeURIComponent(entityType)}/${encodeURIComponent(entityId)}`),
  },

  alerts: (query: { district?: string; limit?: number; include_undated?: boolean } = {}) =>
    get<AlertsResponse>("/api/alerts", { limit: 30, ...query }),

  signals: (district?: string) =>
    get<SignalsResponse>("/api/signals", district ? { district } : undefined),

  rebuildSignals: () => post<Record<string, unknown>>("/api/signals/rebuild"),

  sources: {
    list: () => get<SourcesResponse>("/api/sources"),
    runs: (limit = 50) => get<SourceRunsResponse>("/api/sources/runs", { limit }),
    run: (code: string) => post<Record<string, unknown>>(`/api/sources/${encodeURIComponent(code)}/run`),
    runDue: () => post<Record<string, unknown>>("/api/sources/run-due"),
    /** Ask the server to poll the official feeds now. Answers before that pass happens, with
     *  what was queued - the Overview screen calls it on mount and on Refresh. */
    pollNow: () => post<SourcePollAck>("/api/sources/run-due", undefined, { query: { now: true } }),
  },

  notifications: {
    list: (signal?: AbortSignal) => get<NotificationsResponse>("/api/notifications", undefined, { signal }),
    read: (id: string) => post<Record<string, unknown>>(`/api/notifications/${encodeURIComponent(id)}/read`),
    readAll: () => post<Record<string, unknown>>("/api/notifications/read-all"),
  },

  agent: {
    status: (signal?: AbortSignal) => get<AgentStatusResponse>("/api/agent/status", undefined, { signal }),
    tools: () => get<AgentToolsResponse>("/api/agent/tools"),
    chat: (body: ChatIn, signal?: AbortSignal) =>
      post<AgentRun>("/api/agent/chat", body, { signal, timeoutMs: AGENT_RUN_TIMEOUT_MS }),
    classify: (body: AgentClassifyIn) => post<Record<string, unknown>>("/api/agent/classify", body),
    investigate: (body: AgentInvestigateIn) =>
      post<AgentRun>("/api/agent/investigate", body, { timeoutMs: AGENT_RUN_TIMEOUT_MS }),
    /**
     * Answer one victim report. The only agent call that writes: it can file a help request,
     * and it returns the activity timeline the run recorded while doing so.
     */
    respond: (body: AgentRespondIn) =>
      post<AgentRun>("/api/agent/respond", body, { timeoutMs: AGENT_RUN_TIMEOUT_MS }),
    /** `incident_id` is required by the endpoint; it filters the stored runs by subject. */
    investigations: (incidentId: string, limit = 10) =>
      get<AgentRunsResponse>("/api/agent/investigations", { incident_id: incidentId, limit }),
  },

  community: {
    feed: (
      query: { district?: string; latitude?: number; longitude?: number; language?: string } = {},
      signal?: AbortSignal,
    ) => get<CommunityFeed>("/api/community/feed", query, { signal }),
    activity: (signal?: AbortSignal) => get<CommunityActivity>("/api/community/activity", undefined, { signal }),
    requests: (signal?: AbortSignal) => get<RequestListResponse>("/api/community/requests", undefined, { signal }),
    request: (refCode: string, signal?: AbortSignal) =>
      get<CommunityRequestDetail>(`/api/community/requests/${encodeURIComponent(refCode)}`, undefined, {
        signal,
      }),
    // `POST .../cancel` answers with the case and its timeline only - the SLA block is not in
    // that response, even though it is in the GET. `Pick` states that instead of a type that
    // promises a field the endpoint never sends.
    cancel: (refCode: string, body: { reason?: string } = {}) =>
      post<Pick<CommunityRequestDetail, "request" | "timeline">>(
        `/api/community/requests/${encodeURIComponent(refCode)}/cancel`,
        body,
      ),
    incident: (id: string, signal?: AbortSignal) =>
      get<PublicIncident>(`/api/community/incidents/${encodeURIComponent(id)}`, undefined, {
        signal,
      }),
    report: (body: ReportIn) => post<ReportOutcome>("/api/community/reports", body),
    requestHelp: (body: AssistanceRequestIn) =>
      post<HelpRequestOutcome>("/api/community/requests", body),
    flush: (body: OfflineFlushIn) =>
      post<Record<string, unknown>>("/api/community/offline/flush", body),
  },
};

export type Api = typeof api;
