const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type KnowledgeSource = "local" | "local_and_dify" | "dify";

function authHeaders(token?: string | null): HeadersInit {
  const h: HeadersInit = { "Content-Type": "application/json" };
  if (token) h.Authorization = `Bearer ${token}`;
  return h;
}

export async function login(username: string, password: string) {
  const res = await fetch(`${API_URL}/api/auth/login`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) throw new Error("login_failed");
  return res.json() as Promise<{ access_token: string }>;
}

export async function me(token: string) {
  const res = await fetch(`${API_URL}/api/auth/me`, { headers: authHeaders(token) });
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
  } = {},
) {
  const sp = new URLSearchParams();
  if (params.q) sp.set("q", params.q);
  if (params.status) sp.set("status", params.status);
  if (params.programme && params.programme !== "all") sp.set("programme", params.programme);
  else if (params.category && params.category !== "all") sp.set("category", params.category);
  if (params.topic && params.topic !== "all") sp.set("topic", params.topic);
  sp.set("page", String(params.page || 1));
  sp.set("page_size", String(params.page_size || 20));
  sp.set("grouped", String(params.grouped ?? true));
  const res = await fetch(`${API_URL}/api/documents?${sp}`, { headers: authHeaders(token) });
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
  },
  opts?: { timeoutMs?: number },
) {
  const timeoutMs = opts?.timeoutMs ?? 90_000;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${API_URL}/api/chat`, {
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
    if (e instanceof DOMException && e.name === "AbortError") {
      throw new Error("chat_timeout");
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

export async function triggerClassify(token: string, force = false) {
  const sp = new URLSearchParams();
  if (force) sp.set("force", "true");
  const res = await fetch(`${API_URL}/api/ingest/classify?${sp}`, {
    method: "POST",
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error("classify_failed");
  return res.json() as Promise<{ ok: boolean; started?: boolean; task_id?: string }>;
}

export async function ingestStatus(token: string) {
  const res = await fetch(`${API_URL}/api/ingest/status`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error("status_failed");
  return res.json();
}

export async function triggerCrawl(token: string, sourceId?: string) {
  const url = sourceId
    ? `${API_URL}/api/ingest/crawl?source_id=${encodeURIComponent(sourceId)}`
    : `${API_URL}/api/ingest/crawl`;
  const res = await fetch(url, { method: "POST", headers: authHeaders(token) });
  if (!res.ok) throw new Error("crawl_failed");
  return res.json() as Promise<{
    ok: boolean;
    started: boolean;
    source_id?: string | null;
    reason?: string;
  }>;
}

export async function triggerReindex(token: string, scope: "all" | "failed" | "stored" = "all") {
  const sp = new URLSearchParams({ scope });
  const res = await fetch(`${API_URL}/api/ingest/reindex?${sp}`, {
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
    ? `${API_URL}/api/ingest/crawl/stop?run_id=${encodeURIComponent(runId)}`
    : `${API_URL}/api/ingest/crawl/stop`;
  const res = await fetch(url, { method: "POST", headers: authHeaders(token) });
  if (!res.ok) throw new Error("stop_failed");
  return res.json() as Promise<{ ok: boolean; stopped: number }>;
}

export function fileUrl(documentId: string) {
  return `${API_URL}/api/documents/${documentId}/file`;
}

export type SecretField = { configured: boolean; masked: string | null };
export type SettingsResponse = {
  editable: Record<string, unknown>;
  readonly: Record<string, unknown>;
  meta: { updated_at: string | null; updated_by: string | null };
  warnings: string[];
};

export async function getSettings(token: string) {
  const res = await fetch(`${API_URL}/api/settings`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error("settings_get_failed");
  return res.json() as Promise<SettingsResponse>;
}

export async function updateSettings(token: string, body: Record<string, unknown>) {
  const res = await fetch(`${API_URL}/api/settings`, {
    method: "PUT",
    headers: authHeaders(token),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error("settings_update_failed");
  return res.json() as Promise<SettingsResponse>;
}

export { API_URL };
