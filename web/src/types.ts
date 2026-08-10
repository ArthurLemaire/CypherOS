export type RiskLevel = "safe" | "moderate" | "sensitive";

interface BaseEvent {
  id: string;
  ts: string;
  thread: string;
  updated_ts?: string;
}

export interface UserEvent extends BaseEvent {
  type: "user";
  text: string;
}

export interface AssistantEvent extends BaseEvent {
  type: "assistant";
  text: string;
  reasoning?: string;
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

export type TimelineEvent =
  | UserEvent
  | AssistantEvent
  | ToolEvent
  | ApprovalEvent
  | QuestionEvent
  | NoticeEvent
  | ArtifactEvent;

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
  proactive: boolean;
  goal_interval_minutes: number;
}

export interface GoalStep {
  idx: number;
  title: string;
  status: "pending" | "in_progress" | "done" | "blocked" | "skipped";
  note: string;
  updated_at: string;
}

export interface Goal {
  id: string;
  title: string;
  description: string;
  status: "active" | "paused" | "done" | "cancelled";
  notes: string;
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
  llm: { provider: string; model: string; stream: boolean };
  agent: { language: string; max_steps: number; show_thinking: boolean; workspace: string };
  connectors: { email: boolean; browser: boolean; mcp: string[] };
  tools: ToolInfo[];
  memory_enabled: boolean;
  data_dir: string;
  started_at: string;
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

export type WsMessage =
  | { kind: "hello"; state: StateSnapshot }
  | { kind: "event"; event: TimelineEvent }
  | { kind: "update"; event: TimelineEvent }
  | { kind: "stream_start"; thread: string; id: string; ts: string }
  | { kind: "delta"; thread: string; id: string; text: string }
  | { kind: "stream_end"; thread: string; id: string }
  | { kind: "status"; status: Status }
  | { kind: "thread"; thread: ThreadMeta }
  | { kind: "thread_deleted"; thread: string }
  | { kind: "thread_cleared"; thread: string }
  | { kind: "goals" }
  | { kind: "memory" }
  | { kind: "ideas"; ideas: IdeasData }
  | { kind: "profile"; profile: Profile }
  | { kind: "settings"; settings: SettingsView }
  | { kind: "approvals_reset" }
  | { kind: "error"; error: string }
  | { kind: "pong"; status: Status };
