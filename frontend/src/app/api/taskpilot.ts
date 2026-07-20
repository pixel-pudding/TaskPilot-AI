export type SourceType = "jira" | "defect" | "email" | "transcript" | "injected" | "servicenow" | "github" | "slack";
export type Priority = "P0" | "P1" | "P2" | "P3";
export type TaskStatus = "open" | "in_progress" | "blocked" | "done" | "deferred";

export type Task = {
  id: string;
  title: string;
  description?: string;
  source: string;
  source_type: SourceType;
  priority?: Priority | null;
  deadline?: string | null;
  owner?: string | null;
  status?: TaskStatus;
  dependencies?: string[];
  blocks?: string[];
  raw_text?: string;
  merged_from?: string[];
  merged_sources?: string[];
  grounded?: boolean | null;
  grounding_confidence?: number | null;
  confidence?: number | null;
  source_sentence?: string | null;
  vp_escalation?: boolean;
  customer_facing?: boolean;
  dedup_group?: string | null;
  dedup_explanation?: string | null;
  dedup_confidence?: number | null;
  blocking_impact_score?: number | null;
  time_block?: string | null;
};

export type RankedTask = Task & {
  rank: number;
  score: number;
  score_breakdown?: Record<string, number>;
  rationale: string;
};

export type Alert = {
  severity: "info" | "warning" | "critical";
  message: string;
  task_id?: string | null;
};

export type DailyPlan = {
  generated_at: string;
  top_priorities: RankedTask[];
  do_next: RankedTask[];
  deferred: RankedTask[];
  blocked: RankedTask[];
  alerts: Alert[];
  ranked_tasks: RankedTask[];
  time_blocked_plan?: TimeBlock[] | null;
  highest_leverage_tasks?: LeverageTask[] | null;
  deferred_tasks_detected?: DeferredTask[] | null;
};

export type TimeBlock = {
  start: string;
  end: string;
  task_id: string;
  title: string;
  priority?: string | null;
  score: number;
  slot_type: string;
};

export type LeverageTask = {
  task_id: string;
  title: string;
  leverage_score: number;
  blocks_directly: number;
  blocks_transitively: number;
  blocked_by: string[];
};

export type DeferredTask = {
  task_id: string;
  title: string;
  priority?: string | null;
  source_type?: string;
  appeared_in_last_n_runs: number;
  reason: string;
};

export type CalendarEvent = {
  id: number;
  event_id: string;
  title: string;
  start_time: string;
  end_time: string;
  is_all_day: number;
  source: string;
};

export type ChatResponse = {
  answer: string;
  referenced_task_ids: string[];
};

export type ChatRequest = {
  message: string;
};

export type InjectRequest = {
  title: string;
  description?: string;
  source_type?: SourceType;
  priority?: Priority | null;
  deadline?: string | null;
  owner?: string | null;
};

export type Source = {
  name: string;
  color: string;
  status: string;
  last_sync?: string | null;
  error?: string | null;
};

export type SourcesResponse = {
  sources: Source[];
  total_tasks: number;
};

export type ConnectorStatus = {
  name: string;
  connected: boolean;
  last_sync: string | null;
  error: string | null;
};

export type MetricsSummary = {
  connectors: ConnectorStatus[];
  sync_latency: unknown[];
  ingestion_volume: { timestamp: string; count: number }[];
  llm_usage: unknown[];
  api_latency: { avg_latency_ms: number; total_calls: number };
  websocket_health: { total_connections: number; channels: Record<string, number> };
  task_count: number;
  has_plan: boolean;
};

export type ExtractionItem = {
  task_id: string;
  raw_text: string;
  title: string;
  source_type: SourceType;
  source: string;
  confidence?: number | null;
  priority?: Priority | null;
  deadline?: string | null;
  status?: string;
  source_sentence?: string | null;
  grounded?: boolean | null;
  grounding_confidence?: number | null;
};

export type DashboardResponse = {
  plan: DailyPlan;
  dependency_analysis: {
    critical_path: string[];
    blocking_impacts: Record<string, BlockingImpact>;
    highest_leverage_tasks: LeverageTask[];
    unblocking_recommendations: UnblockingRecommendation[];
  };
  time_blocked_plan?: { time_blocks: TimeBlock[]; unavailable_slots: { start: string; end: string; title: string }[] } | null;
  today_calendar_events: CalendarEvent[];
  deferred_tasks: DeferredTask[];
  team_velocity: { daily_counts: { day: string; completed: number; total: number }[] };
  completion_patterns: { peak_completion_patterns: { hour: number; day: number; count: number }[] };
  user_preferences: Record<string, string>;
};

export type BlockingImpact = {
  task_id: string;
  title: string;
  blocks_directly: number;
  blocks_transitively: number;
  total_impact_score: number;
  blocked_by_ids: string[];
  blocked_by_names: string[];
  blocking_ids: string[];
  blocking_names: string[];
};

export type UnblockingRecommendation = {
  blocked_task_id: string;
  blocked_task_title: string;
  blocking_task_id: string;
  blocking_task_title: string;
  blocking_task_status: string;
  suggestion: string;
};

export type DedupGroup = {
  id?: string;
  merged_count: number;
  match_confidence: number;
  reasoning: string;
  tasks: { id: string; title: string; source: string; snippet?: string; priority?: Priority | null; status?: string; deadline?: string | null; owner?: string | null }[];
};

export type WebSocketEvent = {
  event: string;
  data: unknown;
};

// Same-origin by default (frontend + backend served together, e.g. behind
// the nginx proxy in docker-compose — relative "/api/..." paths just work).
// Set VITE_API_BASE_URL when frontend and backend are on different origins
// (e.g. a Vercel-hosted frontend calling a Railway/Render-hosted backend).
const API_BASE = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") || "";

const TOKEN_STORAGE_KEY = "taskpilot_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_STORAGE_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_STORAGE_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_STORAGE_KEY);
}

async function jsonFetch<T>(input: RequestInfo | URL, init?: RequestInit): Promise<T> {
  const token = getToken();
  const res = await fetch(input, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers ?? {}),
    },
  });
  if (res.status === 401) {
    clearToken();
    window.dispatchEvent(new CustomEvent("taskpilot:unauthorized"));
  }
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Request failed: ${res.status} ${res.statusText} ${text}`.trim());
  }
  return (await res.json()) as T;
}

export async function refreshPlan(): Promise<DailyPlan> {
  return jsonFetch<DailyPlan>(`${API_BASE}/api/refresh`, { method: "POST" });
}

export async function getPlan(): Promise<DailyPlan> {
  return jsonFetch<DailyPlan>(`${API_BASE}/api/plan`);
}

export async function getTasks(params?: { source_type?: string; priority?: string; status?: string; limit?: number; offset?: number }): Promise<{ tasks: Task[]; total: number }> {
  const url = new URL(`${API_BASE}/api/tasks`, window.location.origin);
  if (params?.source_type) url.searchParams.set("source_type", params.source_type);
  if (params?.priority) url.searchParams.set("priority", params.priority);
  if (params?.status) url.searchParams.set("status", params.status);
  if (params?.limit) url.searchParams.set("limit", String(params.limit));
  if (params?.offset) url.searchParams.set("offset", String(params.offset));
  return jsonFetch<{ tasks: Task[]; total: number }>(url.toString());
}

export async function getDashboard(): Promise<DashboardResponse> {
  return jsonFetch<DashboardResponse>(`${API_BASE}/api/dashboard`);
}

export async function chat(message: string): Promise<ChatResponse> {
  return jsonFetch<ChatResponse>(`${API_BASE}/api/chat`, {
    method: "POST",
    body: JSON.stringify({ message } satisfies ChatRequest),
  });
}

export async function injectTask(req: InjectRequest): Promise<DailyPlan> {
  return jsonFetch<DailyPlan>(`${API_BASE}/api/inject`, {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export async function getWeeklySummary(): Promise<{ summary: string; generated_at: string | null }> {
  return jsonFetch<{ summary: string; generated_at: string | null }>(`${API_BASE}/api/weekly-summary`);
}

export async function getSources(): Promise<SourcesResponse> {
  return jsonFetch<SourcesResponse>(`${API_BASE}/api/sources`);
}

export async function getMetrics(): Promise<MetricsSummary> {
  return jsonFetch<MetricsSummary>(`${API_BASE}/api/metrics`);
}

export async function getRecentExtractions(): Promise<{ extractions: ExtractionItem[]; total: number }> {
  return jsonFetch(`${API_BASE}/api/extractions/recent`);
}

export async function syncNow(sourceType?: string): Promise<void> {
  const url = sourceType
    ? `${API_BASE}/api/sync/now?source_type=${sourceType}`
    : `${API_BASE}/api/sync/now`;
  await jsonFetch<{ status: string }>(url, { method: "POST" });
}

export async function getCalendarToday(): Promise<{ events: CalendarEvent[]; unavailable_slots: any[] }> {
  return jsonFetch(`${API_BASE}/api/calendar/today`);
}

export async function getDependencyAnalysis(): Promise<any> {
  return jsonFetch(`${API_BASE}/api/dependency-analysis`);
}

export async function getDedupGroups(): Promise<{ groups: DedupGroup[] }> {
  return jsonFetch(`${API_BASE}/api/dedup-groups`);
}

export async function convertHiddenTask(req: { task_id: string; title?: string; priority?: Priority | null; deadline?: string | null }): Promise<{ status: string; task_id: string; title: string }> {
  return jsonFetch(`${API_BASE}/api/hidden-tasks/convert`, {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export async function getMemoryPreferences(): Promise<{ preferences: Record<string, string> }> {
  return jsonFetch(`${API_BASE}/api/memory/preferences`);
}

export async function getTeamMetrics(): Promise<{ teams: Record<string, any> }> {
  return jsonFetch(`${API_BASE}/api/team-metrics`);
}

export async function updateTask(taskId: string, req: Partial<{ title: string; description: string; priority: Priority | null; status: TaskStatus; deadline: string | null; owner: string | null; assignee: string | null; team: string | null }>): Promise<{ status: string; task: Task }> {
  return jsonFetch(`${API_BASE}/api/tasks/${taskId}`, {
    method: "PUT",
    body: JSON.stringify(req),
  });
}

export async function createTask(req: { title: string; description?: string; source_type?: SourceType; priority?: Priority | null; status?: TaskStatus; deadline?: string | null; owner?: string | null; assignee?: string | null; team?: string | null }): Promise<{ status: string; task: Task }> {
  return jsonFetch(`${API_BASE}/api/tasks`, {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export async function deleteTask(taskId: string): Promise<{ status: string; task_id: string; title: string }> {
  return jsonFetch(`${API_BASE}/api/tasks/${taskId}`, {
    method: "DELETE",
  });
}

export async function getA2aStatus(): Promise<{ status: string; agent_id: string; agents_connected: number; agents: any[] }> {
  return jsonFetch(`${API_BASE}/api/a2a/status`);
}

export async function reorderTasks(taskIds: string[]): Promise<{ status: string; count: number }> {
  return jsonFetch(`${API_BASE}/api/tasks/reorder`, {
    method: "PUT",
    body: JSON.stringify({ task_ids: taskIds }),
  });
}

export async function getHealth(): Promise<{
  status: string;
  version: string;
  jira_connected: boolean;
  github_connected: boolean;
  grok_connected: boolean;
  redis_connected: boolean;
  database_connected: boolean;
  task_count: number;
  last_sync: string | null;
  connectors: ConnectorStatus[];
}> {
  return jsonFetch(`${API_BASE}/api/health`);
}

type WsCallback = (event: WebSocketEvent) => void;

let _sharedWs: WebSocket | null = null;
let _wsCallbacks = new Set<WsCallback>();
let _wsReconnectTimer: ReturnType<typeof setTimeout> | null = null;

function _startWs(): void {
  if (_sharedWs && (_sharedWs.readyState === WebSocket.OPEN || _sharedWs.readyState === WebSocket.CONNECTING)) {
    return;
  }
  const token = getToken();
  // Same-origin default: derive ws(s):// from the page's own host. Once
  // API_BASE points at a different origin (split Vercel/Railway deploy),
  // the socket has to follow it there instead — window.location.host would
  // silently point the WS connection at the frontend's own host, which
  // isn't listening for WebSocket upgrades at all.
  let wsOrigin = `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}`;
  if (API_BASE) {
    const apiUrl = new URL(API_BASE);
    wsOrigin = `${apiUrl.protocol === "https:" ? "wss:" : "ws:"}//${apiUrl.host}`;
  }
  const wsUrl = `${wsOrigin}/ws${token ? `?token=${encodeURIComponent(token)}` : ""}`;
  const ws = new WebSocket(wsUrl);
  _sharedWs = ws;

  ws.onopen = () => {
    console.log("[WS] Connected to TaskPilot");
  };

  ws.onmessage = (msg) => {
    try {
      const event = JSON.parse(msg.data) as WebSocketEvent;
      _wsCallbacks.forEach((cb) => cb(event));
    } catch {
      console.warn("[WS] Failed to parse message:", msg.data);
    }
  };

  ws.onclose = () => {
    console.log("[WS] Disconnected from TaskPilot");
    if (_sharedWs === ws) {
      _sharedWs = null;
    }
    if (_wsCallbacks.size > 0) {
      _wsReconnectTimer = setTimeout(() => {
        if (_wsCallbacks.size > 0) {
          _startWs();
        }
      }, 3000);
    }
  };

  ws.onerror = () => {};
}

function _stopWs(): void {
  if (_wsReconnectTimer) {
    clearTimeout(_wsReconnectTimer);
    _wsReconnectTimer = null;
  }
  if (_sharedWs) {
    _sharedWs.onclose = null;
    _sharedWs.close();
    _sharedWs = null;
  }
}

export function subscribeWs(cb: WsCallback): () => void {
  _wsCallbacks.add(cb);
  _startWs();
  return () => {
    _wsCallbacks.delete(cb);
    if (_wsCallbacks.size === 0) {
      _stopWs();
    }
  };
}

// ── Auth ─────────────────────────────────────────────────────────────────

export type AuthUser = { id: string; email: string; name: string };
export type AuthResponse = { access_token: string; token_type: string; user: AuthUser };

export async function signup(email: string, password: string, name: string): Promise<AuthResponse> {
  const res = await jsonFetch<AuthResponse>(`${API_BASE}/api/auth/signup`, {
    method: "POST",
    body: JSON.stringify({ email, password, name }),
  });
  setToken(res.access_token);
  return res;
}

export async function login(email: string, password: string): Promise<AuthResponse> {
  const res = await jsonFetch<AuthResponse>(`${API_BASE}/api/auth/login`, {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  setToken(res.access_token);
  return res;
}

// Landing page "Watch Demo" — drops the visitor into the pre-seeded demo
// dashboard with no signup. Shared account: this is showcase data, not a
// private workspace.
export async function demoLogin(): Promise<AuthResponse> {
  const res = await jsonFetch<AuthResponse>(`${API_BASE}/api/auth/demo`, {
    method: "POST",
  });
  setToken(res.access_token);
  return res;
}

export function logout(): void {
  clearToken();
}

export async function getMe(): Promise<AuthUser> {
  return jsonFetch<AuthUser>(`${API_BASE}/api/auth/me`);
}

// ── Connections (per-user integrations) ─────────────────────────────────────

export type ConnectionProvider = "jira" | "servicenow" | "outlook" | "github" | "slack";

export type Connection = {
  provider: ConnectionProvider;
  auth_type: "oauth" | "token";
  account_label: string;
  status: string;
  connected_at: string;
  last_sync: string | null;
  error: string | null;
};

export type ConnectionsResponse = {
  connections: Connection[];
  providers: { provider: ConnectionProvider; connected: boolean }[];
};

export async function getConnections(): Promise<ConnectionsResponse> {
  return jsonFetch<ConnectionsResponse>(`${API_BASE}/api/connections`);
}

export async function disconnectProvider(provider: ConnectionProvider): Promise<{ status: string; removed: boolean }> {
  return jsonFetch(`${API_BASE}/api/connections/${provider}`, { method: "DELETE" });
}

export async function connectJira(url: string, email: string, apiToken: string): Promise<{ status: string }> {
  return jsonFetch(`${API_BASE}/api/connections/jira`, {
    method: "POST",
    body: JSON.stringify({ url, email, api_token: apiToken }),
  });
}

export async function connectServiceNow(url: string, username: string, password: string): Promise<{ status: string }> {
  return jsonFetch(`${API_BASE}/api/connections/servicenow`, {
    method: "POST",
    body: JSON.stringify({ url, username, password }),
  });
}

export async function connectOutlook(clientId: string, clientSecret: string, tenantId: string): Promise<{ status: string }> {
  return jsonFetch(`${API_BASE}/api/connections/outlook`, {
    method: "POST",
    body: JSON.stringify({ client_id: clientId, client_secret: clientSecret, tenant_id: tenantId }),
  });
}

// GitHub/Slack use real OAuth: this is a full-page redirect (not a fetch),
// so the JWT travels as a query param since redirects can't carry headers.
export function startOAuthConnect(provider: "github" | "slack"): void {
  const token = getToken();
  const params = new URLSearchParams({
    token: token ?? "",
    origin: window.location.origin,
  });
  window.location.href = `${API_BASE}/api/connections/${provider}/authorize?${params.toString()}`;
}
