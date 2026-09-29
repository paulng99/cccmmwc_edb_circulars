"use client";

import { ChangeEvent, FormEvent, Fragment, useCallback, useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "@/i18n/routing";
import ChatDocPanel from "@/components/ChatDocPanel";
import {
  chatAsk,
  deleteChatSession,
  extractChatFile,
  getChatSession,
  KnowledgeSource,
  listChatSessions,
  type ChatAttachmentMeta,
  type ChatSessionSummary,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Icon } from "@/components/Icon";
import { PROGRAMME_OPTIONS, TOPIC_OPTIONS, type Programme, type Topic } from "@/lib/taxonomy";

type Citation = {
  ref: string;
  title?: string;
  circular_no?: string | null;
  issued_at?: string | null;
  source_url?: string;
  document_id?: string;
  backend?: string;
};

type PendingFile = { filename: string; text: string; charCount: number };

type Msg = {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  attachments?: ChatAttachmentMeta[];
  error?: boolean;
};

type Preview = {
  ref: string;
  title: string;
  documentId?: string;
  sourceUrl?: string;
  circularNo?: string | null;
  issuedAt?: string | null;
};

const KNOWLEDGE_OPTIONS: { value: KnowledgeSource; key: string }[] = [
  { value: "local", key: "local" },
  { value: "local_and_dify", key: "localAndDify" },
  { value: "dify", key: "dify" },
];

const SUGGESTED_PROMPT_KEYS = ["prompt1", "prompt2", "prompt3", "prompt4"] as const;
const SESSION_KEY = "edb_chat_session";

function storedSessionId() {
  if (typeof window === "undefined") return null;
  const fromUrl = new URLSearchParams(window.location.search).get("session");
  if (fromUrl) return fromUrl;
  return sessionStorage.getItem(SESSION_KEY);
}

function rememberSession(id: string | null) {
  if (typeof window === "undefined") return;
  if (id) sessionStorage.setItem(SESSION_KEY, id);
  else sessionStorage.removeItem(SESSION_KEY);
  const url = new URL(window.location.href);
  if (id) url.searchParams.set("session", id);
  else url.searchParams.delete("session");
  const next = `${url.pathname}${url.search}${url.hash}`;
  const current = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  if (next !== current) window.history.replaceState(window.history.state, "", next);
}

const MAX_FILES = 3;
const MAX_FILE_BYTES = 8 * 1024 * 1024;

function newId() {
  return crypto.randomUUID();
}

function formatStamp(iso: string | null | undefined) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${y}-${m}-${day} ${hh}:${mm}`;
}

function renderWithCitations(
  content: string,
  citations: Citation[] | undefined,
  activeRef: string | undefined,
  onOpen: (c: Citation) => void,
) {
  if (!citations || citations.length === 0) return content;
  const byRef = new Map(citations.map((c) => [String(c.ref), c]));
  const parts = content.split(/(\[(?:L|D)?\d+\])/g);
  return parts.map((part, i) => {
    const m = /^\[((?:L|D)?\d+)\]$/.exec(part);
    if (!m) return <Fragment key={i}>{part}</Fragment>;
    const c = byRef.get(m[1]);
    if (!c) return <Fragment key={i}>{part}</Fragment>;
    return (
      <button
        key={i}
        type="button"
        className={`cite-ref${activeRef === c.ref ? " active" : ""}`}
        title={c.title || m[1]}
        onClick={() => onOpen(c)}
      >
        {m[1]}
      </button>
    );
  });
}

export default function ChatPage() {
  const t = useTranslations("chat");
  const locale = useLocale();
  const { token, ready } = useAuth();
  const router = useRouter();
  const [question, setQuestion] = useState("");
  const [knowledge, setKnowledge] = useState<KnowledgeSource>("local");
  const [programme, setProgramme] = useState<Programme>("all");
  const [topic, setTopic] = useState<Topic>("all");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<ChatSessionSummary[]>([]);
  const [sessionsError, setSessionsError] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadingPromptOnly, setLoadingPromptOnly] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [pending, setPending] = useState<PendingFile[]>([]);
  const [extracting, setExtracting] = useState(false);
  const [attachError, setAttachError] = useState<string | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const viewGen = useRef(0);

  useEffect(() => {
    if (ready && !token) router.replace("/login");
  }, [ready, token, router]);

  useEffect(() => {
    const el = logRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [msgs, loading]);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 176)}px`;
  }, [question]);

  const refreshSessions = useCallback(async () => {
    if (!token) return;
    try {
      const data = await listChatSessions(token);
      setSessions(data.items || []);
      setSessionsError(false);
    } catch {
      setSessionsError(true);
    }
  }, [token]);

  useEffect(() => {
    void refreshSessions();
  }, [refreshSessions]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key !== "Escape") return;
      setPreview(null);
      setHistoryOpen(false);
      setConfirmDeleteId(null);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const openCitation = useCallback((c: Citation) => {
    setPreview({
      ref: c.ref,
      title: c.title || c.ref,
      documentId: c.document_id,
      sourceUrl: c.source_url,
      circularNo: c.circular_no,
      issuedAt: c.issued_at,
    });
    setHistoryOpen(false);
  }, []);

  const ask = useCallback(
    async (raw: string, files: PendingFile[] = pending) => {
      if (!token || loading) return;
      const gen = viewGen.current;
      const q = raw.trim();
      const promptOnly = !q && files.length === 0;
      const sentFiles = files;
      setQuestion("");
      if (sentFiles.length) {
        setPending((current) => current.filter((f) => !sentFiles.includes(f)));
      }
      setAttachError(null);
      setMsgs((m) => [
        ...m,
        {
          id: newId(),
          role: "user",
          content: promptOnly ? t("promptOnlyLabel") : q,
          attachments: sentFiles.map((f) => ({ filename: f.filename, char_count: f.charCount })),
        },
      ]);
      setLoadingPromptOnly(promptOnly);
      setLoading(true);
      const controller = new AbortController();
      abortRef.current = controller;
      try {
        const res = await chatAsk(
          token,
          {
            question: q,
            session_id: sessionId,
            knowledge_source: knowledge,
            locale,
            programme: programme === "all" ? null : programme,
            topic: topic === "all" ? null : topic,
            attachments: sentFiles.map((f) => ({ filename: f.filename, text: f.text })),
          },
          { signal: controller.signal },
        );
        if (gen !== viewGen.current) return;
        setActiveSession(res.session_id);
        setMsgs((m) => [
          ...m,
          { id: newId(), role: "assistant", content: res.answer, citations: res.citations || [] },
        ]);
        void refreshSessions();
      } catch (err) {
        if (gen !== viewGen.current) return;
        if (sentFiles.length) {
          setPending((current) => [...sentFiles.filter((f) => !current.includes(f)), ...current]);
        }
        const code = err instanceof Error ? err.message : "";
        if (code === "chat_cancelled") {
          setMsgs((m) => [...m, { id: newId(), role: "assistant", content: t("cancelled"), error: true }]);
        } else {
          const msg = code === "chat_timeout" ? t("timeout") : t("error");
          setMsgs((m) => [...m, { id: newId(), role: "assistant", content: msg, error: true }]);
        }
      } finally {
        abortRef.current = null;
        if (gen === viewGen.current) {
          setLoading(false);
          setLoadingPromptOnly(false);
        }
      }
    },
    [token, loading, pending, sessionId, knowledge, locale, programme, topic, t, refreshSessions],
  );

  function setActiveSession(id: string | null) {
    rememberSession(id);
    setSessionId(id);
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void ask(question);
  }

  function onStop() {
    abortRef.current?.abort();
  }

  function onNewChat() {
    viewGen.current += 1;
    if (loading) abortRef.current?.abort();
    setLoading(false);
    setLoadingPromptOnly(false);
    setMsgs([]);
    setActiveSession(null);
    setQuestion("");
    setPending([]);
    setAttachError(null);
    setPreview(null);
    setHistoryOpen(false);
    textareaRef.current?.focus();
  }

  async function openSession(id: string) {
    if (!token || id === sessionId) {
      setHistoryOpen(false);
      return;
    }
    viewGen.current += 1;
    const gen = viewGen.current;
    if (loading) abortRef.current?.abort();
    setLoading(false);
    setLoadingPromptOnly(false);
    setActiveSession(id);
    setMsgs([]);
    setQuestion("");
    setPending([]);
    setPreview(null);
    setHistoryOpen(false);
    setConfirmDeleteId(null);
    try {
      const data = await getChatSession(token, id);
      if (gen !== viewGen.current) return;
      if (data.knowledge_source === "local" || data.knowledge_source === "dify" || data.knowledge_source === "local_and_dify") {
        setKnowledge(data.knowledge_source);
      }
      setMsgs(
        (data.messages || []).map((m) => ({
          id: m.id,
          role: m.role,
          content: m.content === "（僅系統提示）" ? t("promptOnlyLabel") : m.content,
          citations: (m.citations || []) as Citation[],
          attachments: m.attachments || [],
        })),
      );
    } catch {
      if (gen !== viewGen.current) return;
      setMsgs([{ id: newId(), role: "assistant", content: t("historyLoadError"), error: true }]);
    }
  }

  const restoredRef = useRef(false);
  useEffect(() => {
    if (!token || restoredRef.current) return;
    restoredRef.current = true;
    const id = storedSessionId();
    if (id) void openSession(id);
  }, [token]);

  async function onDelete(id: string) {
    if (!token) return;
    if (confirmDeleteId !== id) {
      setConfirmDeleteId(id);
      return;
    }
    setConfirmDeleteId(null);
    try {
      await deleteChatSession(token, id);
      setSessions((items) => items.filter((s) => s.id !== id));
      if (sessionId === id) onNewChat();
    } catch {
      setSessionsError(true);
    }
  }

  async function onPickFiles(e: ChangeEvent<HTMLInputElement>) {
    const list = Array.from(e.target.files || []);
    e.target.value = "";
    if (!token || list.length === 0) return;
    const room = MAX_FILES - pending.length;
    if (room <= 0) {
      setAttachError(t("attachTooMany"));
      return;
    }
    const batch = list.slice(0, room);
    if (list.length > room) setAttachError(t("attachTooMany"));
    else setAttachError(null);
    setExtracting(true);
    try {
      for (const file of batch) {
        if (file.size > MAX_FILE_BYTES) {
          setAttachError(t("attachTooLarge"));
          continue;
        }
        try {
          const res = await extractChatFile(token, file);
          setPending((p) => {
            if (p.length >= MAX_FILES) return p;
            return [...p, { filename: res.filename, text: res.text, charCount: res.char_count }];
          });
        } catch (err) {
          const code = err instanceof Error ? err.message : "";
          if (code === "no_text") setAttachError(t("attachEmpty"));
          else if (code === "file_too_large") setAttachError(t("attachTooLarge"));
          else if (code === "unsupported_type") setAttachError(t("attachType"));
          else setAttachError(t("attachFailed"));
        }
      }
    } finally {
      setExtracting(false);
    }
  }

  if (!token) return null;

  const knowledgeKey = KNOWLEDGE_OPTIONS.find((o) => o.value === knowledge)?.key || "local";
  const programmeKey = PROGRAMME_OPTIONS.find((o) => o.value === programme)?.key || "programmeAll";
  const topicKey = TOPIC_OPTIONS.find((o) => o.value === topic)?.key || "topicAll";
  const scopeIsDefault = knowledge === "local" && programme === "all" && topic === "all";

  return (
    <div className="page chat-page">
      <header className="page-head">
        <div>
          <h1>{t("title")}</h1>
          <p className="page-subtitle">{t("subtitle")}</p>
        </div>
        <div className="page-actions">
          <button
            type="button"
            className="btn secondary sm chat-history-toggle"
            onClick={() => setHistoryOpen((v) => !v)}
            aria-expanded={historyOpen}
          >
            <Icon name="clock" />
            <span>{t("history")}</span>
          </button>
          <button type="button" className="btn secondary sm" onClick={onNewChat} disabled={msgs.length === 0 && !loading && !sessionId}>
            <Icon name="plus" />
            <span>{t("newChat")}</span>
          </button>
        </div>
      </header>

      <div className={`chat-workspace${preview ? " has-preview" : ""}`}>
        {historyOpen ? (
          <button type="button" className="chat-scrim" aria-label={t("historyClose")} onClick={() => setHistoryOpen(false)} />
        ) : null}
        <aside className={`chat-history${historyOpen ? " open" : ""}`} aria-label={t("history")}>
          <div className="chat-history-head">
            <span className="lead">
              <Icon name="clock" />
              {t("history")}
            </span>
            <button type="button" className="btn ghost icon-only sm chat-history-close" onClick={() => setHistoryOpen(false)} aria-label={t("historyClose")}>
              <Icon name="x" />
            </button>
          </div>
          <div className="chat-history-list">
            {sessionsError ? <p className="chat-history-empty">{t("historyFailed")}</p> : null}
            {!sessionsError && sessions.length === 0 ? <p className="chat-history-empty">{t("historyEmpty")}</p> : null}
            {sessions.map((s) => (
              <div key={s.id} className={`chat-history-item${s.id === sessionId ? " active" : ""}`}>
                <button type="button" className="chat-history-open" onClick={() => void openSession(s.id)}>
                  <span className="chat-history-title">{s.title}</span>
                  <time className="chat-history-time" dateTime={s.updated_at || undefined}>
                    {formatStamp(s.updated_at || s.created_at)}
                  </time>
                </button>
                {confirmDeleteId === s.id ? (
                  <button type="button" className="btn danger sm" onClick={() => void onDelete(s.id)}>
                    {t("deleteConfirm")}
                  </button>
                ) : (
                  <button
                    type="button"
                    className="btn ghost icon-only sm"
                    aria-label={t("deleteChat")}
                    title={t("deleteChat")}
                    onClick={() => onDelete(s.id)}
                  >
                    <Icon name="trash-2" />
                  </button>
                )}
              </div>
            ))}
          </div>
        </aside>

        <section className="card chat">
          <div className="chat-scope">
            <button
              type="button"
              className="chat-scope-toggle"
              aria-expanded={filtersOpen}
              aria-controls="chat-scope-body"
              onClick={() => setFiltersOpen((v) => !v)}
            >
              <span className="lead">
                <Icon name="sliders-horizontal" />
                <span>{t("filters")}</span>
                <span className="chat-scope-summary">
                  <span className={`badge ${knowledge === "local" ? "" : "blue"}`}>{t(knowledgeKey)}</span>
                  <span className={`badge ${programme === "all" ? "" : "violet"}`}>{t(programmeKey)}</span>
                  <span className={`badge ${topic === "all" ? "" : "teal"}`}>{t(topicKey)}</span>
                  {scopeIsDefault ? null : (
                    <span className="muted" style={{ fontSize: "0.76rem" }}>
                      · {t("scopeCustom")}
                    </span>
                  )}
                </span>
              </span>
              <Icon name={filtersOpen ? "chevron-up" : "chevron-down"} />
            </button>

            {filtersOpen ? (
              <div className="chat-scope-body" id="chat-scope-body">
                <div className="filter-row">
                  <span className="label" id="ks-label">
                    {t("knowledge")}
                  </span>
                  <div className="segmented" role="group" aria-labelledby="ks-label">
                    {KNOWLEDGE_OPTIONS.map(({ value, key }) => (
                      <button
                        key={value}
                        type="button"
                        aria-pressed={knowledge === value}
                        onClick={() => setKnowledge(value)}
                      >
                        {t(key)}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="filter-row">
                  <span className="label" id="chat-prog-label">
                    {t("programmeFilter")}
                  </span>
                  <div className="chips" role="group" aria-labelledby="chat-prog-label">
                    {PROGRAMME_OPTIONS.map(({ value, key }) => (
                      <button
                        key={value}
                        type="button"
                        className="chip sm"
                        aria-pressed={programme === value}
                        onClick={() => setProgramme(value)}
                      >
                        {t(key)}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="filter-row">
                  <span className="label" id="chat-topic-label">
                    {t("topicFilter")}
                  </span>
                  <div className="chips" role="group" aria-labelledby="chat-topic-label">
                    {TOPIC_OPTIONS.map(({ value, key }) => (
                      <button
                        key={value}
                        type="button"
                        className="chip sm"
                        aria-pressed={topic === value}
                        onClick={() => setTopic(value)}
                      >
                        {t(key)}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            ) : null}
          </div>

          <div className="chat-log" ref={logRef} aria-live="polite">
            {msgs.length === 0 && !loading ? (
              <div className="chat-empty">
                <div className="chat-empty-mark">
                  <Icon name="sparkles" />
                </div>
                <h2>{t("emptyTitle")}</h2>
                <p>{t("emptyLead")}</p>
                <div className="prompt-grid">
                  {SUGGESTED_PROMPT_KEYS.map((key) => (
                    <button key={key} type="button" className="prompt-card" onClick={() => void ask(t(key), [])}>
                      <Icon name="message-square" />
                      <span>{t(key)}</span>
                    </button>
                  ))}
                </div>
                <p className="msg-note" style={{ marginTop: "1rem" }}>
                  <Icon name="shield-check" />
                  <span>{t("groundingNote")}</span>
                </p>
              </div>
            ) : null}

            {msgs.map((m) => (
              <div key={m.id} className={`msg ${m.role}`}>
                <div className="msg-avatar" aria-hidden>
                  {m.role === "assistant" ? <Icon name="sparkles" /> : <Icon name="user" />}
                </div>
                <div className="msg-body">
                  {m.content ? (
                    <div className={`msg-bubble${m.error ? " error" : ""}`}>
                      {m.role === "assistant" ? renderWithCitations(m.content, m.citations, preview?.ref, openCitation) : m.content}
                    </div>
                  ) : null}

                  {m.attachments && m.attachments.length > 0 ? (
                    <div className="msg-files" aria-label={t("attached")}>
                      {m.attachments.map((f) => (
                        <span key={f.filename} className="attach-chip static">
                          <Icon name="file-text" />
                          <span>{f.filename}</span>
                        </span>
                      ))}
                    </div>
                  ) : null}

                  {m.role === "assistant" && m.citations && m.citations.length > 0 ? (
                    <div className="sources">
                      <span className="sources-head">
                        <Icon name="quote" />
                        {t("sourcesCount", { count: m.citations.length })}
                      </span>
                      <div className="source-grid">
                        {m.citations.map((c, j) => (
                          <button
                            key={`${c.ref}-${j}`}
                            type="button"
                            className={`source-card${preview?.ref === c.ref ? " active" : ""}`}
                            onClick={() => openCitation(c)}
                          >
                            <span className="source-num">{c.ref}</span>
                            <span className="source-body">
                              <span className="source-title">{c.title || "—"}</span>
                              <span className="source-meta">
                                {c.circular_no ? (
                                  <span>
                                    <Icon name="hash" /> {c.circular_no}
                                  </span>
                                ) : null}
                                {c.issued_at ? (
                                  <span>
                                    <Icon name="calendar" /> {c.issued_at}
                                  </span>
                                ) : null}
                                {c.backend && c.backend !== "local" ? <span className="badge sky">{c.backend}</span> : null}
                              </span>
                            </span>
                          </button>
                        ))}
                      </div>
                    </div>
                  ) : m.role === "assistant" && !m.error ? (
                    <p className="msg-note">
                      <Icon name="info" />
                      <span>{t("noCitations")}</span>
                    </p>
                  ) : null}
                </div>
              </div>
            ))}

            {loading ? (
              <div className="msg assistant">
                <div className="msg-avatar" aria-hidden>
                  <Icon name="sparkles" />
                </div>
                <div className="msg-body">
                  <div className="msg-bubble">
                    <span className="typing">
                      <span className="typing-dots" aria-hidden>
                        <i />
                        <i />
                        <i />
                      </span>
                      {loadingPromptOnly ? t("thinkingPromptOnly") : t("thinking")}
                    </span>
                  </div>
                </div>
              </div>
            ) : null}
          </div>

          <form className="composer" onSubmit={onSubmit}>
            {pending.length > 0 ? (
              <div className="composer-files">
                {pending.map((f) => (
                  <span key={f.filename} className="attach-chip">
                    <Icon name="file-text" />
                    <span>{f.filename}</span>
                    <button
                      type="button"
                      className="attach-remove"
                      aria-label={t("removeFile")}
                      onClick={() => setPending((p) => p.filter((item) => item.filename !== f.filename))}
                    >
                      <Icon name="x" />
                    </button>
                  </span>
                ))}
              </div>
            ) : null}
            {attachError ? <p className="composer-error">{attachError}</p> : null}
            <label className="sr-only" htmlFor="q">
              {t("placeholder")}
            </label>
            <div className="composer-box">
              <input
                ref={fileRef}
                type="file"
                accept=".pdf,.txt,.md,.csv,text/plain,application/pdf"
                multiple
                hidden
                onChange={(e) => void onPickFiles(e)}
              />
              <button
                className="btn ghost icon-only"
                type="button"
                aria-label={t("attach")}
                title={t("attach")}
                disabled={loading || extracting || pending.length >= MAX_FILES}
                onClick={() => fileRef.current?.click()}
              >
                <Icon name="paperclip" />
              </button>
              <textarea
                id="q"
                ref={textareaRef}
                rows={1}
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder={t("placeholder")}
                disabled={loading}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    (e.currentTarget.form as HTMLFormElement | null)?.requestSubmit();
                  }
                }}
              />
              {loading ? (
                <button className="btn danger icon-only" type="button" onClick={onStop} aria-label={t("stop")} title={t("stop")}>
                  <Icon name="square" />
                </button>
              ) : (
                <button className="btn icon-only" type="submit" aria-label={t("send")} title={t("send")} disabled={extracting}>
                  <Icon name="send" />
                </button>
              )}
            </div>
            <div className="composer-hint">
              <span>
                {extracting ? (
                  t("extracting")
                ) : (
                  <>
                    <kbd>Enter</kbd> {t("hintSend")} · <kbd>Shift</kbd> + <kbd>Enter</kbd> {t("hintNewline")}
                    {" · "}
                    {t("attachHint")}
                  </>
                )}
              </span>
              {sessionId ? <span>{t("sessionActive")}</span> : null}
            </div>
          </form>
        </section>

        {preview ? (
          <ChatDocPanel
            token={token}
            title={preview.title}
            documentId={preview.documentId}
            sourceUrl={preview.sourceUrl}
            circularNo={preview.circularNo}
            issuedAt={preview.issuedAt}
            onClose={() => setPreview(null)}
          />
        ) : null}
      </div>
    </div>
  );
}
