/**
 * The API contract, copied from live responses rather than written from memory.
 *
 * Regenerate the shapes with `python probe/api_shapes.py`, which prints every route's keys
 * and one example value. A type here that the server does not actually send is worse than
 * `any`, because it makes a wrong guess look checked.
 */

export type Surface = "response_center" | "community";
export type Role = "response_center" | "community";
export type Rank = "operator" | "coordinator" | "analyst" | "community_member";

export type Urgency = "critical" | "urgent" | "attention" | "information";
export type EvidenceState =
  | "officially_confirmed"
  | "officially_reported"
  | "corroborated"
  | "community_reported"
  | "conflicting"
  | "unverified";
export type FreshnessState = "fresh" | "recent" | "aging" | "stale" | "unknown";
export type IncidentStatus = "active" | "monitoring" | "contained" | "resolved" | "archived";
export type AssistanceStatus =
  | "received"
  | "reviewing"
  | "response_team_notified"
  | "assigned"
  | "in_progress"
  | "resolved"
  | "cancelled";
export type LocationPrecision =
  | "source_coordinate"
  | "named_place"
  | "local_level"
  | "district_centroid"
  | "user_shared"
  | "unlocated";

/** Where a fact came from, shown to the reader wherever the fact appears. */
export type Provenance = "official" | "community" | "derived" | "operator" | "demo" | string;

export interface User {
  id: string;
  username: string;
  display_name: string;
  alias: string | null;
  role: Role;
  /** null for a community account: a rank only exists inside the Response Center. */
  rank: Rank | null;
  is_response_center: boolean;
  permissions: string[];
  home_district: string | null;
  preferred_language: "en" | "ne";
  phone: string | null;
  created_at: string | null;
  last_login_at: string | null;
}

export interface SystemMode {
  mode: "live" | "demo";
  scenario_id: string | null;
  sim_clock: string | null;
}

export interface LoginResponse {
  token: string;
  user: User;
  surface: Surface;
  mode: SystemMode;
}

export interface DemoAccount {
  username: string;
  display_name: string;
  role: string;
  rank: string;
  surface: string;
}

/* ------------------------------------------------------------------ incidents */

export interface ImpactBlock {
  deaths?: number;
  injured?: number;
  missing?: number;
  affected_people?: number;
  affected_families?: number;
  houses_damaged?: number;
  displaced_persons?: number;
  report_count?: number;
  official_source_count?: number;
  cross_validated?: boolean;
  freshness_state?: FreshnessState;
  location_precision?: LocationPrecision;
}

export interface Incident {
  id: string;
  ref_code: string;
  title: string;
  incident_type: string;
  status: IncidentStatus;
  severity: string | null;
  urgency: Urgency;
  district: string | null;
  province: string | null;
  local_municipality: string | null;
  location_name: string | null;
  location_precision: LocationPrecision;
  latitude: number | null;
  longitude: number | null;
  within_nepal: boolean;
  magnitude: number | null;
  depth_km: number | null;
  event_time: string | null;
  event_time_label: string | null;
  first_detected_at: string | null;
  last_updated_at: string | null;
  updated_label: string | null;
  freshness_state: FreshnessState;
  evidence_state: EvidenceState;
  impact_score: number;
  score_band: string;
  prioritization_reasons: string[];
  community_report_count: number;
  assistance_request_count?: number;
  open_assistance_count: number;
  supporting_signal_count: number;
  conflicting_signal_count: number;
  duplicate_count: number;
  cluster_id: string | null;
  needs_review: boolean;
  review_reason: string | null;
  provenance: Provenance;
  /** True for a rehearsal row. Never render one of these without saying what it is. */
  demo: boolean;
  impact: ImpactBlock;
}

export interface EvidenceRecord {
  observation_id: string;
  role: string;
  kind: string;
  title: string | null;
  summary: string | null;
  source: string;
  source_name: string;
  source_organization: string | null;
  source_url: string | null;
  official: boolean;
  authority: number;
  provenance: Provenance;
  demo: boolean;
  district: string | null;
  location_name: string | null;
  latitude: number | null;
  longitude: number | null;
  at: string | null;
  age: string | null;
  freshness_state: FreshnessState;
  deaths: number | null;
  injured: number | null;
  missing: number | null;
  affected_people: number | null;
  magnitude: number | null;
  severity: string | null;
  incident_type: string | null;
  unit: string | null;
  value: number | string | null;
  linked_at: string | null;
  linked_by: string | null;
}

export interface EvidenceBlock {
  state: EvidenceState;
  label: string;
  meaning: string;
  official_confirmation: boolean;
  confirmed_by_source: string | null;
  verified_by_operator: boolean;
  source_count: number;
  conflicting_count: number;
  records: EvidenceRecord[];
}

/** One entry of an incident's timeline (`/incidents/{id}/timeline` and the detail). */
export interface TimelineEvent {
  at: string | null;
  kind: string;
  label: string | null;
  detail: string | null;
  entity_id: string | null;
  received_at: string | null;
  source: string | null;
  provenance: Provenance;
}

export interface TimelineResponse {
  incident_id: string;
  events: TimelineEvent[];
}

/**
 * One entry of a *request's* timeline. Different from an incident timeline: these are the
 * status changes and messages on one request, including the ones a victim is allowed to see.
 */
export interface RequestUpdate {
  id: string;
  at: string | null;
  kind: string;
  actor: string | null;
  actor_type: string | null;
  message: string | null;
  from_status: string | null;
  to_status: string | null;
}

/**
 * An action the server says this caller may take on this record, with the endpoint that
 * performs it. The console renders buttons from this list instead of deciding for itself
 * what is allowed, so a permission change cannot leave a dead button on screen.
 */
export interface ActionSpec {
  action: string;
  label: string;
  method: string;
  path: string;
  permission: string;
  /**
   * Present on the repeated actions: `set_status` appears once per allowed status, all of them
   * on the same path, distinguished only by this. The label is prose ("Set status to
   * Monitoring"), so a screen cannot recover the value from it. Verified live on
   * `probe/action_surface.py`.
   */
  target?: string | null;
}

/**
 * A request detail answers with a *different* action shape than an incident detail: a bare
 * `{action, target}` with no label, method, path or permission. The console cannot render
 * request buttons from `ActionSpec`, so it renders them from this and supplies its own
 * wording. Recorded in docs/known-issues.md as something the two endpoints should unify.
 */
export interface RequestAction {
  action: string;
  target: string | null;
}

export interface ScoreComponent {
  raw: number;
  weight: number;
  contribution: number;
}

export interface WhyPrioritized {
  headline: string;
  reasons: string[];
  score: number;
  score_band: string;
  components: Record<string, ScoreComponent>;
  weights: Record<string, number>;
  formula: string;
  explanation: string;
  freshness_multiplier: number;
}

export interface IncidentDetail {
  incident: Incident;
  evidence: EvidenceBlock;
  why_prioritized: WhyPrioritized;
  timeline: TimelineEvent[];
  reports: CommunityReport[];
  requests: AssistanceRequest[];
  signals: RiskSignal[];
  alerts: Alert[];
  duplicates: Incident[];
  related_incidents: Incident[];
  audit: AuditEvent[];
  available_actions: ActionSpec[];
}

/* ------------------------------------------------------------------ community
 *
 * These are what the server actually answered, copied from `logs/api_shapes.log`. Where a
 * community call returns fewer fields than the console's, the field is optional here - not
 * because it might be missing, but because for *this* caller it is, on purpose.
 */

export interface CommunityReport {
  id: string;
  message: string;
  report_type: string;
  incident_type: string | null;
  severity: string | null;
  urgency: Urgency;
  /** `pending` until an operator verifies it; never a guess made by the frontend. */
  verification_status: string;
  duplicate_status: string;
  corroborating_count: number;
  district: string | null;
  location_text: string | null;
  location_confidence: string | null;
  latitude: number | null;
  longitude: number | null;
  /** Set when the report was linked to an incident; null means it is still standing alone. */
  incident: { id: string; ref_code: string; title: string } | null;
  distance_to_incident_km: number | null;
  /** Ref code of the request that carried this report forward, if any. */
  carried_on_request: string | null;
  language: string;
  submitted_offline: boolean;
  at: string | null;
  age: string | null;
  provenance: Provenance;
  demo: boolean;
}

export interface AssistanceRequest {
  id: string;
  ref_code: string;
  request_type: string;
  status: AssistanceStatus;
  status_label: string;
  urgency: Urgency;
  urgency_reasons: string[];
  description: string | null;
  district: string | null;
  province: string | null;
  location_text: string | null;
  location_confidence: string | null;
  latitude: number | null;
  longitude: number | null;
  people_count: number | null;
  immediate_danger: boolean;
  medical_need: boolean;
  assistance_types: string[];
  language: string;
  created_at: string | null;
  acknowledged_at: string | null;
  resolved_at: string | null;
  age: string | null;
  provenance: Provenance;
  demo: boolean;
  submitted_offline?: boolean;
  incident: { id: string; ref_code: string; title: string; incident_type: string } | null;
  report_id?: string | null;
  /** Console only - a victim is never shown who is coming. */
  assigned_to?: string | null;
  assigned_team?: string | null;
  response_plan?: ResponsePlan;
  structured?: RequestStructured;
  /** Trimmed to `{acknowledged}` on the community view; the full block sits on the detail. */
  sla?: SlaBlock;
  matched_resources?: MatchedResource[];
  timeline?: RequestUpdate[];
  /** Community-facing wording only. The console has its own fields. */
  next_step?: string;
  what_happens_next?: string;
}

/** `sla_minutes` target, when it is due, and whether that deadline has passed. */
export interface SlaBlock {
  sla_minutes?: number | null;
  due_at?: string | null;
  minutes_remaining?: number | null;
  acknowledged?: boolean;
  breached?: boolean;
}

export interface MatchedResource {
  id: string;
  name: string;
  resource_type: string;
  district: string | null;
  availability: string;
  contact: string | null;
  contact_verified: boolean;
  distance_km: number | null;
  source: string | null;
  verified_at: string | null;
  provenance: Provenance;
}

/** The steps the deterministic planner produced for one request. */
export interface ResponsePlan {
  urgency: string;
  urgency_reasons: string[];
  sla_minutes: number;
  steps: { step: string; text: string }[];
  unknowns: string[];
  generated_by: string;
  /** States plainly what the requester is shown and what stays internal. */
  victim_visibility: string;
}

export interface RequestStructured {
  trapped: boolean;
  minors_involved: boolean;
  elderly_or_disabled_involved: boolean;
  submitted_offline: boolean;
  from_report: string | null;
}

export interface RequestDetail {
  request: AssistanceRequest;
  /** The full block is at the top level; `request.sla` is trimmed for victims. */
  sla: SlaBlock;
  matched_resources?: MatchedResource[];
  timeline: RequestUpdate[];
  /** The subset of the timeline this person is allowed to see. */
  victim_timeline?: RequestUpdate[];
  audit?: AuditEvent[];
  available_actions: RequestAction[];
}

/** `GET /community/requests/{ref_code}` - a victim's own view, keyed by ref code. */
export interface CommunityRequestDetail {
  request: AssistanceRequest;
  sla: SlaBlock;
  timeline: RequestUpdate[];
}

/**
 * What `POST /community/reports` says back.
 *
 * The three sentences are the whole design of the response: `answer` tells the person what their
 * message *became* (logged, attached, duplicated, or turned into a help case), and
 * `what_happens_next` tells them what will happen to it. Both are written by the server in the
 * *reporter's* language, which is why they are rendered verbatim and never re-worded here.
 */
export interface ReportOutcome {
  report: CommunityReport;
  /** The incident the report joined, in the same public projection as `/community/incidents/{id}`. */
  incident: PublicIncident["incident"] | null;
  assistance_request: AssistanceRequest | null;
  answer: string;
  what_happens_next: string;
  demo_mode: boolean;
}

/** What `POST /community/requests` says back: the case, its receipt and its first steps. */
export interface HelpRequestOutcome {
  request: AssistanceRequest;
  timeline: RequestUpdate[];
  /** A bilingual sentence meant to be read aloud or forwarded. */
  receipt: string;
  what_happens_next: string;
  sla: SlaBlock;
}

export interface CommunityFeed {
  district: string | null;
  language: string;
  generated_at: string;
  counts: { alerts: number; signals: number; incidents: number };
  /** A server-written sentence for the case where there is nothing to show. */
  empty_message: string | null;
  alerts: Alert[];
  signals: RiskSignal[];
  incidents: FeedIncident[];
}

export interface CommunityActivity {
  open_count: number;
  reports: CommunityReport[];
  requests: AssistanceRequest[];
  user: { alias: string | null; home_district: string | null };
}

/** What a community account is told about an incident: the official record and nothing else. */
export interface PublicIncident {
  incident: {
    id: string;
    ref_code: string;
    title: string;
    incident_type: string;
    district: string | null;
    evidence_state: EvidenceState;
    official: boolean;
    last_updated_at: string | null;
    /** The record's own endpoint, which answers with this same public projection. */
    api_url: string;
  };
  official_only: boolean;
  reports: CommunityReport[];
}

/** The feed's incident projection is smaller than the console's list. */
export interface FeedIncident {
  id: string;
  ref_code: string;
  title: string;
  district: string | null;
  incident_type: string;
  severity: string | null;
  event_time: string | null;
  updated_label: string | null;
  freshness_state: FreshnessState;
  evidence_state: EvidenceState;
  location_name: string | null;
  location_precision: LocationPrecision;
  latitude: number | null;
  longitude: number | null;
  within_nepal: boolean;
  provenance: Provenance;
}

/* ------------------------------------------------------------------ operations */

/**
 * One row of the action queue.
 *
 * The two kinds the queue mixes are *not* the same shape and the server does not pretend they
 * are: an `assistance_request` row carries the deadline and the caller's own numbers, an
 * `incident_review` row carries the evidence state and the impact score. Reading
 * `row.impact_score` off a request row is `undefined`, which is how a `NaN` got onto the screen.
 * Every field below that is only true for one kind is optional, per `action_queue()` in
 * `backend/app/services/response_center.py`.
 */
export interface QueueItem {
  id: string;
  ref_code: string;
  /** One of `assistance_request` or `incident_review` - which record to open, see `kind`. */
  kind: string;
  title: string;
  urgency: Urgency;
  status: string;
  district: string | null;
  at: string | null;
  age: string | null;
  why: string[];
  demo: boolean;
  /** `incident_review` only - a help request has no evidence state or score of its own. */
  evidence_state?: EvidenceState;
  impact_score?: number | null;
  /** `assistance_request` only. */
  acknowledged?: boolean;
  sla?: SlaBlock;
  incident_id?: string | null;
  medical_need?: boolean;
  immediate_danger?: boolean;
  people_count?: number | null;
}

export interface QueueResponse {
  buckets: Record<Urgency, QueueItem[]>;
  counts: Record<Urgency, number>;
  total_open_requests: number;
  unacknowledged_critical: number;
  sla_breaches: number;
  generated_at: string;
}

export interface Dashboard {
  generated_at: string;
  last_change: string | null;
  last_change_label: string | null;
  incidents: {
    total_active: number;
    new_last_24h: number;
    needs_review: number;
    cross_validated: number;
    by_type: Record<string, number>;
  };
  assistance: { open: number; critical: number; by_urgency: Partial<Record<Urgency, number>> };
  community: { reports_last_24h: number; unverified_pending: number };
}

export interface ResourceRow {
  id: string;
  name: string;
  resource_type: string;
  district: string | null;
  province: string | null;
  address: string | null;
  latitude: number | null;
  longitude: number | null;
  has_location: boolean;
  in_nepal: boolean;
  availability: string;
  availability_age: string | null;
  availability_verified_at: string | null;
  capacity: number | null;
  contact: string | null;
  contact_verified: boolean;
  description: string | null;
  source: string | null;
  source_url: string | null;
  /** The OpenStreetMap id this row was seeded from - a number, not a string. */
  osm_id: number | null;
  district_from: string | null;
  provenance: Provenance;
  demo: boolean;
  at: string | null;
  age: string | null;
}

export interface SourceHealth {
  code: string;
  name: string;
  organization: string;
  source_type: string;
  official: boolean;
  machine_readable: boolean;
  enabled: boolean;
  status: string;
  url: string | null;
  refresh_interval_seconds: number;
  last_checked_at: string | null;
  last_successful_fetch: string | null;
  last_error: string | null;
  last_error_at: string | null;
  last_data_timestamp: string | null;
  last_fetch_count: number;
  consecutive_failures: number;
  freshness_state: FreshnessState;
  data_age_seconds: number | null;
  fetch_age_seconds: number | null;
  updated_label: string | null;
  notes: string | null;
}

export interface Alert {
  id: string;
  title: string;
  body: string;
  kind: string;
  severity: string;
  /** The issuing agency's own wording, quoted. Never rewrite it - link to it. */
  source: string;
  source_name: string;
  source_url: string | null;
  district: string | null;
  province: string | null;
  latitude: number | null;
  longitude: number | null;
  published_at: string | null;
  /** Says where the date came from, because some bulletins are undated. */
  published_date_source: string | null;
  published_label: string | null;
  expiry_at: string | null;
  freshness_state: FreshnessState;
  is_pdf_bulletin: boolean;
  provenance: Provenance;
  demo: boolean;
}

/** One of the records that pushed a district's risk level up. */
export interface ContributingFactor {
  kind: string;
  statement: string;
  source: string;
  observed_at: string | null;
  freshness: FreshnessState;
  display_band: string;
  is_official_threshold: boolean;
  official_status: string;
}

/**
 * A risk signal is a statement about conditions in an area, computed from other records.
 * It is not a prediction of an event unless `is_prediction` says so, and it is never drawn
 * as a point without this being obvious in the UI.
 */
export interface RiskSignal {
  code: string;
  district: string | null;
  province: string | null;
  hazard: string;
  level: string;
  label: string;
  statement: string;
  is_prediction: boolean;
  contributing_factors: ContributingFactor[];
  observed_at: string | null;
  freshness_state: FreshnessState;
  latitude: number | null;
  longitude: number | null;
  location_precision: LocationPrecision;
  provenance: Provenance;
}

export interface ActivityEvent {
  at: string | null;
  age: string | null;
  action: string;
  actor: string | null;
  actor_kind: string | null;
  entity_type: string;
  entity_id: string;
  summary: string;
  reason: string | null;
}

export interface AuditEvent {
  id: string;
  at: string | null;
  action: string;
  actor: string | null;
  actor_kind: string | null;
  entity_type: string;
  entity_id: string;
  previous: Record<string, unknown> | null;
  new: Record<string, unknown> | null;
  reason: string | null;
}

export interface NotificationRow {
  id: string;
  kind: string;
  severity: string;
  title: string;
  body: string;
  audience: string;
  district: string | null;
  incident_id: string | null;
  request_id: string | null;
  link: string | null;
  at: string | null;
  age: string | null;
  read: boolean;
  provenance: Provenance;
}

/* ------------------------------------------------------------------ agent */

/**
 * One line of an agent run's activity: the name of a step or a tool, the status it ended
 * with, when it happened, and one line about what came back.
 *
 * There is no field here for the model's own text, which is the point. The server builds this
 * list from step names and tool-authored digests, so reasoning is not something this screen
 * could display even if it wanted to (`agent/trace.py`).
 */
export interface AgentActivityStep {
  at: string | null;
  /** Upper-case action code, e.g. `CHECKING_ROAD_STATUS` or a tool's own name. */
  action: string;
  /** `phase` is the workflow's fixed spine; `tool` is something the model chose to call. */
  kind: string;
  status: string;
  detail?: string | null;
  /** Only on stored runs: the scalars the agent passed. Not rendered as a matter of design. */
  asked?: Record<string, unknown>;
}

export interface AgentRun {
  id: string;
  trigger: string;
  subject_type: string | null;
  subject_id: string | null;
  mode: "strands" | "deterministic";
  status: string;
  model: string | null;
  response_text: string;
  findings: Record<string, unknown>;
  /**
   * The activity timeline: every step and every tool call of the run, in the order they
   * happened. The key is `tool_calls` because that is the column the run is stored under, and it
   * holds more than tool calls - the fixed spine steps a run performs itself are in the same list,
   * which is what makes the order readable as the explanation. A response run fills it, and so
   * does an investigation run now that its tools report back to the trace; on that route the tool
   * rows carry no `detail`, because the watcher writing them is not the tool and cannot know
   * which of the numbers in a result matter (`agent/trace.py` refuses to guess).
   */
  tool_calls: AgentActivityStep[];
  error: string | null;
  duration_ms: number | null;
  provenance: Provenance;
  created_at: string | null;
  ref_code?: string;
  known?: string[];
  unknown?: string[];
  note?: string | null;
  rejected_numbers?: string[];
  language?: string;
  based_on?: Record<string, unknown>;
  /* The responder's own fields. They are optional because an investigation run has no cause
     to fill them: it reads, it does not file. */
  /** How many turns the model actually took - the 1-2 call target, measured not claimed. */
  model_calls?: number | null;
  /** Ref codes of the help requests this run created, if any. */
  created_requests?: string[];
  report_id?: string | null;
  /** What the fixed keyword rules read off the report. The rules, never the model, set this. */
  reading?: {
    risk_flags?: Record<string, boolean>;
    help_types?: string[];
    words?: number;
    method?: string | null;
  };
  location?: {
    latitude?: number | null;
    longitude?: number | null;
    district?: string | null;
    province?: string | null;
    location_text?: string | null;
    location_confidence?: string | null;
    method?: string | null;
  };
}

export interface AgentTool {
  name: string;
  description: string;
  arguments: string[];
  /** Which set the tool belongs to: reading records, or answering a victim report. */
  set?: string;
  /** True for the four tools that change something. The list is published, not assumed. */
  writes?: boolean;
}

export interface AgentStatusResponse {
  available: boolean;
  provider: string | null;
  model: string | null;
  credentials_present: boolean;
  reason: string | null;
  /** Only present when a model is *not* available: it says what runs instead. */
  fallback: string | null;
  runs: { total: number; by_mode: Record<string, number>; by_status: Record<string, number> };
  generated_at: string;
}

/* ------------------------------------------------------------------ response envelopes
 *
 * Named because the client returns them and every page destructures them. Each one is the
 * envelope the endpoint actually sends - several lists have a `count`, several do not, and
 * that difference is real rather than an oversight. */

export interface HealthResponse {
  app: string;
  status: string;
  environment: string;
  time: string;
  mode: SystemMode;
}

export interface UserResponse {
  user: User;
}

export interface DemoAccountsResponse {
  accounts: DemoAccount[];
  created_now: number;
  password: string;
}

export interface IncidentListResponse {
  items: Incident[];
  count: number;
  generated_at: string;
}

export interface ReportListResponse {
  items: CommunityReport[];
  count: number;
}

/** `GET /api/rc/reports/{id}` - the landing page for the link the backend puts in a notification. */
export interface ReportDetailResponse {
  report: CommunityReport;
}

export interface RequestListResponse {
  items: AssistanceRequest[];
  count: number;
  generated_at?: string;
}

export interface ActivityResponse {
  items: ActivityEvent[];
}

export interface AuditListResponse {
  items: AuditEvent[];
  count: number;
}

export interface NotificationsResponse {
  items: NotificationRow[];
  unread: number;
}

export interface CatalogueCounts {
  total: number;
  empty: boolean;
  by_type: Record<string, number>;
  by_availability: Record<string, number>;
  last_change: string | null;
  last_change_age: string | null;
}

export interface SeedStatus {
  state: string;
  state_label: string;
  started_at: string | null;
  finished_at: string | null;
  result: Record<string, unknown> | null;
}

export interface ResourceListResponse {
  items: ResourceRow[];
  count: number;
  /** Says why an empty filter is empty - "no facilities seeded" is not the same as none matched. */
  empty_reason: string | null;
  catalogue: CatalogueCounts;
  seed: SeedStatus;
}

/** The ingestion worker's own account of itself. `running` is three-state on purpose: a process
 *  with no worker at all (ingestion switched off before the thread was made, a test client that
 *  never ran the lifespan) cannot say a thread stopped, so `null` means "nobody here to ask". */
export interface IngestionWorkerStatus {
  running: boolean | null;
  reason: string | null;
  tick_seconds: number | null;
  cycles: number;
  last_cycle_at: string | null;
  /** The server's phrase, already carrying "ago" - `"just now"`, `"4 min ago"`. */
  last_cycle_label: string | null;
  paused: string | null;
}

export interface SourcesResponse {
  items: SourceHealth[];
  worker: IngestionWorkerStatus;
  generated_at: string;
}

/** What `POST /api/sources/run-due?now=true` queued. The pass it asked for has not happened yet
 *  when this arrives - that is the point of the call. `refresh.cycles` is the worker's own counter
 *  *before* it, so a later `worker.cycles` greater than that number is the completion signal, and
 *  no browser clock has to be trusted to read one. */
export interface SourcePollAck {
  ran: Record<string, unknown>;
  due_now: string[];
  refresh: {
    triggered: boolean;
    forced: boolean;
    reason: string | null;
    cycles: number;
    floor_seconds: number | null;
  };
  worker: IngestionWorkerStatus;
}

export interface IngestionRunRow {
  id: string;
  source: string;
  started_at: string | null;
  finished_at: string | null;
  status: string;
  records_found: number;
  records_new: number;
  records_updated: number;
  error: string | null;
}

export interface SourceRunsResponse {
  items: IngestionRunRow[];
}

export interface AlertsResponse {
  items: Alert[];
  generated_at: string;
}

export interface SignalsResponse {
  items: RiskSignal[];
}

export interface AgentToolsResponse {
  count: number;
  /** False once the responder's set is included: some of those tools write. */
  read_only: boolean;
  tools: AgentTool[];
  sets?: Record<string, { count: number; read_only: boolean }>;
  write_tools?: string[];
  note?: string | null;
}

export interface AgentRunsResponse {
  count: number;
  items: AgentRun[];
  note?: string;
}

/* ------------------------------------------------------------------ system */

export interface SystemStatus {
  time: string;
  mode: SystemMode;
  ingestion_enabled: boolean;
  ingestion_worker: IngestionWorkerStatus;
  sources_total: number;
  sources_healthy: number;
  sources_failing: { code: string; status: string; last_error: string | null }[];
  recent_failures: SourceHealth[];
  llm: { configured: boolean; provider: string | null; model: string | null; note: string | null };
}

/** Every list endpoint in this API answers with this envelope. */
export interface ListResponse<T> {
  items: T[];
  count?: number;
  total?: number;
  generated_at?: string;
  note?: string;
}

/* ------------------------------------------------------------------ request bodies
 *
 * Verified with `python probe/api_bodies.py`, which prints the OpenAPI model behind each
 * write and the query parameters of each read. That check matters more here than in a
 * normal project: the backend schemas are `extra="ignore"`, so a misspelled field is not
 * a 422 - it is quietly dropped and the value never reaches the database. Nothing on
 * screen would look wrong; the report would just be missing its location.
 *
 * Optional fields that have a server-side default are optional here too, and `null` is
 * allowed only where the schema says `str | None`.
 */

export interface AttachmentIn {
  kind?: string;
  url?: string;
  name?: string;
  label?: string;
}

export interface LoginIn {
  username: string;
  password: string;
}

export interface RegisterIn {
  username: string;
  password: string;
  display_name?: string;
  preferred_language?: "en" | "ne";
  home_district?: string | null;
  phone?: string | null;
  /** Honoured only when the server allows demo accounts; a community signup cannot
   *  self-issue Response Center access. */
  role?: "community" | "response_center";
  rank?: "operator" | "coordinator" | "analyst" | null;
}

export interface ProfilePatch {
  display_name?: string | null;
  preferred_language?: "en" | "ne" | null;
  home_district?: string | null;
  phone?: string | null;
}

/** message 3..4000 chars, latitude -90..90, people_count 1..100000, max 6 attachments. */
export interface ReportIn {
  message: string;
  report_type?: string;
  incident_type?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  location_text?: string | null;
  people_count?: number | null;
  medical_need?: boolean;
  injuries?: number;
  language?: "en" | "ne";
  attachments?: AttachmentIn[];
  client_timestamp?: string | null;
  submitted_offline?: boolean;
  needs_help?: boolean;
  help_types?: string[];
  incident_id?: string | null;
  immediate_danger?: boolean;
  voice_transcript?: boolean;
}

export interface AssistanceRequestIn {
  description: string;
  request_type?: string;
  assistance_types?: string[];
  latitude?: number | null;
  longitude?: number | null;
  location_text?: string | null;
  people_count?: number;
  medical_need?: boolean;
  immediate_danger?: boolean;
  trapped?: boolean;
  minors_involved?: boolean;
  elderly_or_disabled_involved?: boolean;
  language?: "en" | "ne";
  attachments?: AttachmentIn[];
  incident_id?: string | null;
  report_id?: string | null;
  submitted_offline?: boolean;
  client_timestamp?: string | null;
}

export interface CancelIn {
  reason?: string;
}

export interface OfflineItemIn {
  kind: "report" | "request";
  client_ref?: string;
  payload: Record<string, unknown>;
}

export interface OfflineFlushIn {
  items: OfflineItemIn[];
}

/* ------------------------------------------------------------------ agent */

export interface ChatIn {
  message: string;
  language?: "en" | "ne";
  district?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  incident_id?: string | null;
  history?: Record<string, unknown>[];
}

export interface AgentClassifyIn {
  text: string;
  use_model?: boolean;
}

/**
 * One victim report handed to the responder. `text` is the caller's own words, verbatim.
 *
 * `report_id` is the only way a run gets attached to a person - the server reads the reporter
 * off that row, and there is no field for naming a victim directly, because that would let
 * anyone file for anyone.
 */
export interface AgentRespondIn {
  text: string;
  report_id?: string | null;
  incident_id?: string | null;
}

/** Exactly one of the two: the schema accepts either the id or the human ref code. */
export interface AgentInvestigateIn {
  incident_id?: string;
  ref_code?: string;
}

/* ------------------------------------------------------------------ console actions
 * These are the bodies behind `available_actions`; the buttons carry the path and the
 * endpoint, this file carries the fields.
 */

export type ResourceType =
  | "hospital"
  | "health_post"
  | "ambulance"
  | "shelter"
  | "police"
  | "army"
  | "fire"
  | "water_supply"
  | "food_distribution"
  | "helipad"
  | "emergency_contact";

export type Availability = "unknown" | "available" | "limited" | "closed";

export interface NoteIn {
  note: string;
  visible_to_requester?: boolean;
}

export interface IncidentStatusIn {
  status: string;
  reason?: string;
}

export interface VerifyIn {
  reason: string;
  state?: EvidenceState | string;
}

export interface ReviewIn {
  needs_review: boolean;
  reason?: string;
}

export interface MergeIn {
  duplicate_id: string;
  reason?: string;
}

export interface SplitIn {
  report_ids: string[];
  reason?: string;
}

export interface LinkIn {
  report_id?: string;
  observation_id?: string;
}

export interface AcknowledgeIn {
  note?: string;
}

export interface AssignIn {
  team: string;
  assigned_to?: string | null;
  note?: string;
  share_note_with_requester?: boolean;
}

export interface StatusIn {
  status: string;
  note?: string;
}

export interface EscalateIn {
  reason: string;
}

export interface VictimMessageIn {
  message: string;
}

export interface ReasonIn {
  reason?: string;
}

export interface ResourceCreateIn {
  resource_type: ResourceType | string;
  name: string;
  description?: string;
  latitude?: number | null;
  longitude?: number | null;
  address?: string | null;
  district?: string | null;
  contact?: string | null;
  capacity?: number | null;
  availability?: Availability;
}

export interface ResourceAvailabilityIn {
  availability: Availability;
  capacity?: number | null;
  contact_verified?: boolean | null;
  reason?: string;
}
