export type RiskLevel = "safe" | "moderate" | "sensitive";

interface BaseEvent {
  id: string;
  ts: string;
  thread: string;
  updated_ts?: string;
  /** "user" for things you said; "goal" / "background" for work your Muse did on its own. */
  source?: string;
  /** For background events: the short label of the work being done. */
  about?: string;
}

export interface UserEvent extends BaseEvent {
  type: "user";
  text: string;
}

export interface AssistantEvent extends BaseEvent {
  type: "assistant";
  text: string;
  reasoning?: string;
  /** A background pass that found nothing worth interrupting you for. */
  quiet?: boolean;
}

export interface ToolEvent extends BaseEvent {
  type: "tool";
  tool: string;
  summary: string;
  args: Record<string, unknown>;
  status: "running" | "ok" | "error" | "blocked";
  output?: string;
}

export interface ApprovalEvent extends BaseEvent {
  type: "approval";
  tool: string;
  summary: string;
  risk: RiskLevel;
  reasons: string[];
  warnings: string[];
  egress_target?: string | null;
  /** What the user asked for — why this action is happening. */
  purpose?: string;
  /** What a standing permission would be bound to (host, recipient, program). */
  target?: string | null;
  grant_key?: string;
  /** Scopes the Sentinel offers for this call, in display order. */
  grant_options?: GrantScope[];
  args: Record<string, unknown>;
  status: "pending" | "approved" | "denied" | "expired";
  scope?: string | null;
}

export type GrantScope = "once" | "task" | "session" | "24h" | "always";

export interface Grant {
  key: string;
  tool: string;
  target: string | null;
  scope: GrantScope;
  granted_at: string;
  expires_at: string | null;
  task_id?: string | null;
}

export interface QuestionEvent extends BaseEvent {
  type: "question";
  text: string;
  status: "pending" | "answered" | "expired";
  answer?: string;
}

export interface NoticeEvent extends BaseEvent {
  type: "notice";
  level: "info" | "warn" | "error";
  text: string;
  source?: string;
}

export interface ArtifactEvent extends BaseEvent {
  type: "artifact";
  path: string;
  name: string;
  action: string;
}

/** The browser as the agent sees it: one card per run, updated frame after frame. */
export interface BrowserEvent extends BaseEvent {
  type: "browser";
  url: string;
  title: string;
  /** caption of the last action: "Opened example.com", "Clicked 'Sign in'", "You typed" */
  action: string;
  /** id of the latest frame; fetch with frameUrl() — frames live in memory on the server */
  frame: string;
  frames: number;
  status: "live" | "done";
  by_user?: boolean;
  updated_ts?: string;
}

export type TimelineEvent =
  | UserEvent
  | AssistantEvent
  | ToolEvent
  | ApprovalEvent
  | QuestionEvent
  | NoticeEvent
  | ArtifactEvent
  | BrowserEvent;

export interface ThreadMeta {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  busy: boolean;
  queued: number;
  events: number;
}

export interface Status {
  state: "idle" | "working" | "waiting";
  detail: string;
  thread: string;
  ts?: string;
}

export interface Profile {
  name: string;
  emoji: string;
  color: string;
  style: string;
  /** What you want to be called. */
  user_name: string;
  /** How eagerly background work runs and reaches out. */
  proactivity: Proactivity;
  /** `proactivity !== "off"`, kept for older clients. */
  proactive: boolean;
  goal_interval_minutes: number;
  /** "22:00-08:00" in the server's local time, or "" for none. */
  quiet_hours: string;
}

export type Proactivity = "off" | "low" | "default" | "high";

export interface GoalStep {
  idx: number;
  title: string;
  status: "pending" | "in_progress" | "done" | "blocked" | "skipped";
  note: string;
  updated_at: string;
}

export type GoalCategory =
  | ""
  | "health"
  | "finance"
  | "career"
  | "learning"
  | "relationships"
  | "family"
  | "home"
  | "travel"
  | "creative"
  | "other";

/** A plan change the agent suggested; the user accepts or dismisses it. */
export interface GoalProposal {
  reason: string;
  steps: string[];
  created_at: string;
}

export interface Goal {
  id: string;
  title: string;
  description: string;
  status: "active" | "paused" | "done" | "cancelled";
  notes: string;
  category: GoalCategory;
  /** Target date, YYYY-MM-DD, or "". */
  due: string;
  overdue: boolean;
  /** Reminder cadence such as "daily 08:00" or "weekly mon 09:00", or "". */
  check_in: string;
  next_check_in: string | null;
  proposal: GoalProposal | null;
  created_at: string;
  updated_at: string;
  progress: { done: number; total: number };
  next_step: string | null;
  steps: GoalStep[];
}

export interface MemoryItem {
  id: string;
  content: string;
  category: string;
  created_at: string;
  source: string;
  /** set when the line was rewritten or is the result of a merge */
  updated_at?: string;
}

/** One entry of the memory log: a tidy-up merge or drop, or an update the agent made. Undoable. */
export interface MemoryChange {
  id: string;
  at: string;
  action: "merge" | "rewrite" | "drop";
  before: MemoryItem[];
  after: MemoryItem | null;
  reason: string;
  restored: boolean;
}

export interface TidyReport {
  considered: number;
  changed: number;
  merged: MemoryChange[];
  dropped: MemoryChange[];
  skipped: string[];
  planned: { op: string; before: string[]; content?: string; reason?: string }[];
  lines: string[];
}

export interface Idea {
  title: string;
  detail: string;
  prompt: string;
}

export interface IdeasData {
  generated_at: string | null;
  source: string;
  ideas: Idea[];
  error?: string;
}

export interface ToolInfo {
  name: string;
  risk: RiskLevel;
  description: string;
}

export interface SettingsView {
  version: string;
  profile: Profile;
  sentinel: {
    mode: "ask" | "strict" | "auto";
    always_ask_tools: string[];
    always_allow_tools: string[];
    deny_tools: string[];
    taint_tracking: boolean;
    egress_allowlist: string[];
  };
  /** Each shell / python call in its own bubblewrap namespace (Linux); status says why not. */
  sandbox: { mode: "auto" | "bwrap" | "off"; active: boolean; status: string };
  llm: { provider: string; model: string; stream: boolean };
  agent: { language: string; max_steps: number; show_thinking: boolean; workspace: string };
  connectors: { email: boolean; calendar: boolean; contacts: boolean; browser: boolean; mcp: string[] };
  tools: ToolInfo[];
  memory_enabled: boolean;
  data_dir: string;
  started_at: string;
  /** First-run setup finished (or skipped) in the app. */
  onboarded: boolean;
  /** A model is configured with a key (or a local endpoint that needs none). */
  llm_ready: boolean;
}

// ----------------------------------------------------------------------------- connections
export interface ProviderPreset {
  label: string;
  provider: string;
  base_url: string;
  models?: string[];
  no_key?: boolean;
}

export interface ConnectionsData {
  llm: {
    provider: string;
    model: string;
    base_url: string;
    tool_mode: string;
    stream: boolean;
    /** vault = key entered in the app; config = from config.toml / env; missing = referenced but not set. */
    key_source: "vault" | "config" | "missing" | "none";
    from_app: boolean;
  };
  providers: Record<string, ProviderPreset>;
  email: {
    enabled: boolean;
    configured: boolean;
    address: string;
    imap_host: string;
    imap_port: number;
    smtp_host: string;
    smtp_port: number;
    smtp_starttls: boolean;
    password_set: boolean;
  };
  browser: { enabled: boolean; available: boolean };
  calendar: {
    enabled: boolean;
    configured: boolean;
    refresh_minutes: number;
    /** Working hours, "HH:MM", for "when am I free". */
    day_start: string;
    day_end: string;
    feeds: CalendarFeed[];
  };
  contacts: {
    enabled: boolean;
    /** Anyone to look up: a source, or people the agent was told about. */
    configured: boolean;
    count: number;
    /** People in the agent's own book ("My contacts"). */
    own: number;
    sources: ContactSource[];
  };
  mcp: Array<{
    name: string;
    command: string | null;
    args: string[];
    url: string | null;
    risk: string;
    tools: number;
    connected: boolean;
    from_app: boolean;
  }>;
  vault: string[];
  onboarded: boolean;
}

/** One connected calendar: a private .ics link (kept in the vault) or a file. */
export interface CalendarFeed {
  name: string;
  from_app: boolean;
  events: number;
  fetched_at: string | null;
  error: string;
}

/** One connected address book: a .vcf file (uploaded or on disk) or a link kept in the vault. */
export interface ContactSource {
  name: string;
  from_app: boolean;
  file: boolean;
  contacts: number;
  fetched_at: string | null;
  error: string;
}

/** One person, as GET /api/contacts returns them. */
export interface Contact {
  id: string;
  name: string;
  first: string;
  last: string;
  nickname: string;
  /** "alice@example.com" or "alice@example.com (work)". */
  emails: string[];
  phones: string[];
  org: string;
  title: string;
  birthday: string;
  addresses: string[];
  urls: string[];
  note: string;
  source: string;
}

export interface CalendarEvent {
  uid: string;
  summary: string;
  start: string;
  end: string;
  all_day: boolean;
  location: string;
  description: string;
  calendar: string;
}

/** GET /api/calendar: today's and tomorrow's events with the feeds' status. */
export interface CalendarData {
  enabled: boolean;
  configured: boolean;
  today: string;
  events: CalendarEvent[];
  feeds: Array<{ name: string; events: number; fetched_at: string | null; error: string }>;
  fetched_at: string | null;
  stale: boolean;
}

export interface TestResult {
  ok: boolean;
  error?: string;
  reply?: string;
  ms?: number;
  inbox?: number | null;
  /** calendar test: events across the feeds */
  events?: number;
  feeds?: number;
  /** contacts test: people across the sources */
  contacts?: number;
  sources?: number;
}

export interface StateSnapshot {
  version: string;
  profile: Profile;
  status: Status;
  threads: ThreadMeta[];
  pending_approvals: ApprovalEvent[];
  goals: Goal[];
  settings: SettingsView;
}

export interface AuditEntry {
  ts: string;
  event: string;
  session?: string;
  tool?: string;
  summary?: string;
  risk?: string;
  decision?: string;
  approved?: boolean | null;
  approval_scope?: string | null;
  reasons?: string[];
  ok?: boolean;
  error?: string | null;
  duration_ms?: number;
  content?: string;
  tool_calls?: string[];
  [key: string]: unknown;
}

export interface ActivityData {
  audit: AuditEntry[];
  grants: Grant[];
  tainted: boolean;
}

/** One entry of the Feed: something that happened without you asking. */
export interface FeedItem {
  id: string;
  ts: string;
  kind: "background" | "artifact" | "approval" | "question";
  title: string;
  text: string;
  thread: string;
  thread_title: string;
  path?: string | null;
  quiet?: boolean;
}

export interface UpcomingData {
  proactive: boolean;
  proactivity: Proactivity;
  interval_minutes: number;
  /** The interval after the level's stretch/shrink. */
  effective_interval_minutes: number;
  quiet_hours: string;
  /** End of the current quiet window, if we are in one. */
  quiet_until: string | null;
  next_pass_at: string | null;
  queue: Array<{
    goal_id: string;
    title: string;
    category: GoalCategory;
    due: string | null;
    overdue: boolean;
    next_step: string | null;
    progress: { done: number; total: number };
  }>;
  /** Goal check-ins, soonest first. */
  check_ins: Array<{ goal_id: string; title: string; at: string; cadence: string }>;
  /** Reminders and routines: active ones soonest first, then recently finished. */
  reminders: Reminder[];
  /** Triggers: work that starts when something happens. */
  triggers: TriggersData;
  busy: boolean;
}

export type TriggerKind = "mail" | "event" | "hook";
export type TriggerStatus = "active" | "cancelled";

export interface Trigger {
  id: string;
  kind: TriggerKind;
  /** Words that must all appear in the sender/subject (mail) or title/place (event); a hook's name. */
  match: string;
  /** What to do when it fires. */
  text: string;
  thread: string;
  status: TriggerStatus;
  /** event: how long before the start. */
  lead_minutes: number;
  /** hook: the key in the URL ("" for other kinds). */
  secret: string;
  /** hook: the full URL to call ("" once cancelled). */
  url?: string;
  created_at: string;
  last_fired_at: string | null;
  fired: number;
}

export interface TriggersData {
  items: Trigger[];
  /** Which kinds have their connector: mail needs the mailbox, event the calendar. */
  available: Record<TriggerKind, boolean>;
  /** When the inbox was last looked at for mail triggers (ISO), and the last error if any. */
  mail_checked_at: string | null;
  mail_error: string;
  mail_poll_minutes: number;
}

export type ReminderKind = "remind" | "task";
export type ReminderStatus = "active" | "done" | "cancelled";

export interface Reminder {
  id: string;
  text: string;
  kind: ReminderKind;
  thread: string;
  status: ReminderStatus;
  /** Next time it fires (ISO); null once a one-off has fired. */
  next_at: string | null;
  /** "" for a one-off, else a cadence such as "daily 08:00". */
  repeat: string;
  created_at: string;
  last_fired_at: string | null;
  fired: number;
}

export interface PushInfo {
  /** pywebpush is installed on the server. */
  available: boolean;
  /** VAPID public key (base64url) the browser subscribes with. */
  public_key: string;
  subscriptions: number;
  devices: Array<{ endpoint: string; created_at: string | null; ua: string }>;
}

export interface FileInfo {
  path: string;
  name: string;
  size: number;
  modified: string;
}

export type WsMessage =
  | { kind: "hello"; state: StateSnapshot }
  | { kind: "event"; event: TimelineEvent }
  | { kind: "update"; event: TimelineEvent }
  | { kind: "stream_start"; thread: string; id: string; ts: string }
  | { kind: "delta"; thread: string; id: string; text: string }
  | { kind: "stream_end"; thread: string; id: string; discard?: boolean }
  | { kind: "status"; status: Status }
  | { kind: "thread"; thread: ThreadMeta }
  | { kind: "thread_deleted"; thread: string }
  | { kind: "thread_cleared"; thread: string }
  | { kind: "goals" }
  | { kind: "memory" }
  | { kind: "reminders" }
  | { kind: "triggers" }
  | { kind: "calendar"; calendar: CalendarData }
  | { kind: "ideas"; ideas: IdeasData }
  | { kind: "profile"; profile: Profile }
  | { kind: "settings"; settings: SettingsView }
  | { kind: "connections"; connections: ConnectionsData }
  | { kind: "approvals_reset" }
  | { kind: "error"; error: string }
  | { kind: "pong"; status: Status };
