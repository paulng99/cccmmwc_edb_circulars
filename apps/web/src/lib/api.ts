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
  params: { q?: string; page?: number; page_size?: number } = {},
) {
  const sp = new URLSearchParams();
  if (params.q) sp.set("q", params.q);
  sp.set("page", String(params.page || 1));
  sp.set("page_size", String(params.page_size || 20));
  sp.set("grouped", "true");
  const res = await fetch(`${API_URL}/api/documents?${sp}`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error("list_failed");
  return res.json() as Promise<{
    total: number;
    page: number;
    page_size: number;
    grouped?: boolean;
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
  },
) {
  const res = await fetch(`${API_URL}/api/chat`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error("chat_failed");
  return res.json();
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
