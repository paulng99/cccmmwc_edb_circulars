const LOOPBACK_HOSTS = new Set(["localhost", "127.0.0.1", "::1", "0.0.0.0"]);

/** Browser base for API calls. Empty means same-origin `/api` (proxied by the web server). */
export function resolveApiBase(configured?: string | null): string {
  const value = (configured ?? "").trim().replace(/\/$/, "");
  if (!value) return "";
  try {
    const host = new URL(value).hostname.replace(/^\[|\]$/g, "").toLowerCase();
    // Loopback is only reachable from the machine running the browser.
    // A public site must use the same-origin proxy instead.
    if (LOOPBACK_HOSTS.has(host)) return "";
  } catch {
    return value;
  }
  return value;
}

export function apiBase(): string {
  return resolveApiBase(process.env.NEXT_PUBLIC_API_URL);
}

export type KnowledgeSource = "local" | "local_and_dify" | "dify";

function authHeaders(token?: string | null): HeadersInit {
  const h: HeadersInit = { "Content-Type": "application/json" };
  if (token) h.Authorization = `Bearer ${token}`;
  return h;
}

export async function login(username: string, password: string) {
  let res: Response;
  try {
    res = await fetch(`${apiBase()}/api/auth/login`, {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({ username, password }),
    });
  } catch {
    throw new Error("api_unreachable");
  }
  if (res.status === 502) throw new Error("api_unreachable");
  if (!res.ok) throw new Error("login_failed");
  return res.json() as Promise<{ access_token: string }>;
}

export async function me(token: string) {
  const res = await fetch(`${apiBase()}/api/auth/me`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error("unauthorized");
  return res.json();
}

export async function listDocuments(
  token: string,
  params: {
    q?: string;
    page?: number;
    page_size?: number;
    status?: string;
    grouped?: boolean;
    category?: "all" | "circular" | "document";
    programme?: "all" | "circular" | "sister_school" | "lwlssg" | "other";
    topic?: "all" | string;
    sort_by?: "issued_at" | "revised_at" | "downloaded_at";
    sort_dir?: "asc" | "desc";
  } = {},
) {
  const sp = new URLSearchParams();
  if (params.q) sp.set("q", params.q);
  if (params.status) sp.set("status", params.status);
  if (params.programme && params.programme !== "all") sp.set("programme", params.programme);
  else if (params.category && params.category !== "all") sp.set("category", params.category);
  if (params.topic && params.topic !== "all") sp.set("topic", params.topic);
  if (params.sort_by) sp.set("sort_by", params.sort_by);
  if (params.sort_dir) sp.set("sort_dir", params.sort_dir);
  sp.set("page", String(params.page || 1));
  sp.set("page_size", String(params.page_size || 20));
  sp.set("grouped", String(params.grouped ?? true));
  const res = await fetch(`${apiBase()}/api/documents?${sp}`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error("list_failed");
  return res.json() as Promise<{
    total: number;
    page: number;
    page_size: number;
    grouped?: boolean;
    category?: string;
    programme?: string;
    topic?: string;
    file_count?: number;
    items: unknown[];
  }>;
}

export async function chatAsk(
  token: string,
  body: {
    question: string;
    session_id?: string | null;
    knowledge_source?: KnowledgeSource;
    locale?: string;
    programme?: string | null;
    topic?: string | null;
    focus_document_id?: string | null;
    attachments?: { filename: string; text: string }[];
  },
  opts?: { timeoutMs?: number; signal?: AbortSignal },
) {
  // Backend OpenRouter timeout is 120s; keep client slightly above that.
  const timeoutMs = opts?.timeoutMs ?? 150_000;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort("timeout"), timeoutMs);
  const onExternalAbort = () => controller.abort("user");
  opts?.signal?.addEventListener("abort", onExternalAbort, { once: true });
  try {
    const res = await fetch(`${apiBase()}/api/chat`, {
      method: "POST",
      headers: authHeaders(token),
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    if (!res.ok) {
      const detail = await res.text().catch(() => "");
      throw new Error(detail || `chat_failed_${res.status}`);
    }
    return res.json();
  } catch (e) {
    if (controller.signal.aborted) {
      throw new Error(controller.signal.reason === "user" ? "chat_cancelled" : "chat_timeout");
    }
    throw e;
  } finally {
    clearTimeout(timer);
    opts?.signal?.removeEventListener("abort", onExternalAbort);
  }
}

export type ChatSessionSummary = {
  id: string;
  title: string;
  knowledge_source: KnowledgeSource;
  focus_document_id?: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export type ChatAttachmentMeta = { filename: string; char_count: number };

export type ChatHistoryMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: unknown[];
  attachments?: ChatAttachmentMeta[];
  truncated?: boolean;
  created_at: string | null;
};

async function errorCode(res: Response, fallback: string) {
  try {
    const data = await res.json();
    if (typeof data?.detail === "string") return data.detail;
  } catch {
    /* ignore */
  }
  return fallback;
}

export async function listChatSessions(token: string) {
  const res = await fetch(`${apiBase()}/api/chat/sessions`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error(await errorCode(res, "history_failed"));
  return res.json() as Promise<{ items: ChatSessionSummary[] }>;
}

export async function getChatSession(token: string, sessionId: string) {
  const res = await fetch(`${apiBase()}/api/chat/sessions/${sessionId}`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error(await errorCode(res, "history_failed"));
  return res.json() as Promise<ChatSessionSummary & { messages: ChatHistoryMessage[] }>;
}

export async function deleteChatSession(token: string, sessionId: string) {
  const res = await fetch(`${apiBase()}/api/chat/sessions/${sessionId}`, {
    method: "DELETE",
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error(await errorCode(res, "history_failed"));
}

export async function extractChatFile(token: string, file: File) {
  const body = new FormData();
  body.append("file", file);
  const res = await fetch(`${apiBase()}/api/chat/extract`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body,
  });
  if (!res.ok) throw new Error(await errorCode(res, "attach_failed"));
  return res.json() as Promise<{ filename: string; text: string; char_count: number }>;
}

export async function triggerClassify(token: string, force = false) {
  const sp = new URLSearchParams();
  if (force) sp.set("force", "true");
  const res = await fetch(`${apiBase()}/api/ingest/classify?${sp}`, {
    method: "POST",
    headers: authHeaders(token),
  });
  if (!res.ok) {
    if (res.status === 409) throw new Error("busy");
    throw new Error("classify_failed");
  }
  return res.json() as Promise<{ ok: boolean; started?: boolean; task_id?: string }>;
}

export async function ingestStatus(token: string) {
  const res = await fetch(`${apiBase()}/api/ingest/status`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error("status_failed");
  return res.json();
}

export async function triggerCrawl(token: string, sourceId?: string) {
  const url = sourceId
    ? `${apiBase()}/api/ingest/crawl?source_id=${encodeURIComponent(sourceId)}`
    : `${apiBase()}/api/ingest/crawl`;
  const res = await fetch(url, { method: "POST", headers: authHeaders(token) });
  if (!res.ok) {
    if (res.status === 409) throw new Error("busy");
    throw new Error("crawl_failed");
  }
  return res.json() as Promise<{
    ok: boolean;
    started: boolean;
    source_id?: string | null;
    reason?: string;
  }>;
}

export async function triggerReindex(token: string, scope: "all" | "failed" | "stored" = "all") {
  const sp = new URLSearchParams({ scope });
  const res = await fetch(`${apiBase()}/api/ingest/reindex?${sp}`, {
    method: "POST",
    headers: authHeaders(token),
  });
  if (!res.ok) {
    if (res.status === 409) throw new Error("busy");
    throw new Error("reindex_failed");
  }
  return res.json() as Promise<{ ok: boolean; started: boolean; scope: string; task_id: string }>;
}

export async function stopCrawl(token: string, runId?: string) {
  const url = runId
    ? `${apiBase()}/api/ingest/crawl/stop?run_id=${encodeURIComponent(runId)}`
    : `${apiBase()}/api/ingest/crawl/stop`;
  const res = await fetch(url, { method: "POST", headers: authHeaders(token) });
  if (!res.ok) throw new Error("stop_failed");
  return res.json() as Promise<{ ok: boolean; stopped: number }>;
}

export function fileUrl(documentId: string) {
  return `${apiBase()}/api/documents/${documentId}/file`;
}

export type SecretField = { configured: boolean; masked: string | null };
export type SettingsResponse = {
  editable: Record<string, unknown>;
  readonly: Record<string, unknown>;
  meta: { updated_at: string | null; updated_by: string | null };
  warnings: string[];
  defaults?: { system_prompt?: string };
};

export type DocumentActivity = {
  name?: string | null;
  starts_at?: string | null;
  deadline_at?: string | null;
  summary?: string | null;
  location?: string | null;
};

export type ReanalyzeResult = {
  document_id: string;
  ok: boolean;
  school_action?: string | null;
  activities?: DocumentActivity[];
  error?: string | null;
  message?: string | null;
};

export async function reanalyzeDocuments(token: string, documentIds: string[]) {
  if (documentIds.length === 0) {
    throw new Error("reanalyze_empty");
  }
  const res = await fetch(`${apiBase()}/api/documents/reanalyze`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ document_ids: documentIds }),
  });
  if (!res.ok) {
    if (res.status === 422) throw new Error("reanalyze_empty");
    throw new Error("reanalyze_failed");
  }
  return res.json() as Promise<{ results: ReanalyzeResult[] }>;
}

export type DatesProgress = {
  done: number;
  total: number;
  current?: string | null;
};

export type CalendarEvent = {
  date: string;
  kind: "start" | "deadline";
  activity_name?: string | null;
  summary?: string | null;
  location?: string | null;
  document_id: string;
  document_title: string;
  circular_no?: string | null;
};

export async function getUpcomingDeadlines(token: string, days = 7) {
  const res = await fetch(
    `${apiBase()}/api/documents/calendar/upcoming-deadlines?days=${days}`,
    { headers: authHeaders(token) },
  );
  if (!res.ok) throw new Error("calendar_failed");
  return res.json() as Promise<{
    from: string;
    to: string;
    dates_updating?: boolean;
    dates_progress?: DatesProgress | null;
    items: CalendarEvent[];
  }>;
}

export async function getCalendarEvents(token: string) {
  const res = await fetch(`${apiBase()}/api/documents/calendar/events`, {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error("calendar_failed");
  return res.json() as Promise<{
    dates_updating?: boolean;
    dates_progress?: DatesProgress | null;
    days: Array<{ date: string; events: CalendarEvent[] }>;
  }>;
}

export async function getSettings(token: string) {
  const res = await fetch(`${apiBase()}/api/settings`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error("settings_get_failed");
  return res.json() as Promise<SettingsResponse>;
}

export async function updateSettings(token: string, body: Record<string, unknown>) {
  const res = await fetch(`${apiBase()}/api/settings`, {
    method: "PUT",
    headers: authHeaders(token),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error("settings_update_failed");
  return res.json() as Promise<SettingsResponse>;
}

export async function improveSystemPrompt(token: string, prompt: string) {
  const res = await fetch(`${apiBase()}/api/settings/improve-system-prompt`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ prompt }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json() as Promise<{ prompt: string }>;
}

export type CrawlSource = {
  id: string;
  name: { en: string; "zh-HK": string };
  enabled: boolean;
  auto_ai_analyze?: boolean;
  priority: number;
  type: "site_attachments" | "circular_aspnet";
  base_url: string;
  rate_limit_seconds: number;
  schedule: string;
  allow_hosts?: string[];
  file_extensions?: string[];
  seed_urls?: string[];
  path_prefixes?: string[];
  max_pages?: number;
  langs?: number[];
  year_from?: number;
  year_to?: number;
};

export async function getSourceConfig(token: string) {
  const res = await fetch(`${apiBase()}/api/sources/config`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error(await res.text());
  return res.json() as Promise<{ sources: CrawlSource[] }>;
}

export async function saveSourceConfig(token: string, sources: CrawlSource[]) {
  const res = await fetch(`${apiBase()}/api/sources/config`, {
    method: "PUT",
    headers: authHeaders(token),
    body: JSON.stringify({ sources }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json() as Promise<{ sources: CrawlSource[] }>;
}

export async function suggestSources(
  token: string,
  body: { mode: "topic" | "url"; query: string },
) {
  const res = await fetch(`${apiBase()}/api/sources/suggest`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json() as Promise<{ suggestions: CrawlSource[]; dropped: number }>;
}

export type UsageBucket = {
  calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cost_usd: number;
};

export type UsageReport = {
  from: string;
  to: string;
  timezone: string;
  currency: string;
  jina_usd_per_million: number;
  totals: UsageBucket & { estimated_cost_usd: number; provider_cost_usd: number };
  by_feature: Array<UsageBucket & { feature: string }>;
  by_user: Array<
    UsageBucket & {
      user_id: string | null;
      username: string | null;
      by_feature: Array<UsageBucket & { feature: string }>;
    }
  >;
  by_provider: Array<UsageBucket & { provider: string }>;
  by_model: Array<UsageBucket & { provider: string; model: string }>;
  by_day: Array<UsageBucket & { date: string }>;
  recent: Array<{
    created_at: string | null;
    user_id: string | null;
    username: string | null;
    provider: string;
    feature: string;
    model: string;
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
    cost_usd: number;
    cost_source: string;
  }>;
};

export async function getUsage(token: string, days: number) {
  const res = await fetch(`${apiBase()}/api/usage?days=${days}`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error("usage_get_failed");
  return res.json() as Promise<UsageReport>;
}
