"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "@/i18n/routing";
import AssistantMarkdown from "@/components/AssistantMarkdown";
import ChatDocPanel from "@/components/ChatDocPanel";
import GroupedSources from "@/components/GroupedSources";
import WebSourceNotice from "@/components/WebSourceNotice";
import { useAuth } from "@/lib/auth";
import { Icon } from "@/components/Icon";
import { CHAT_MAX_FILES, type Citation, useChat } from "@/lib/chat-store";
import { citationsUseWeb } from "@/lib/group-citations";
import { PROGRAMME_OPTIONS, TOPIC_OPTIONS } from "@/lib/taxonomy";

type Preview = {
  ref: string;
  title: string;
  documentId?: string;
  sourceUrl?: string;
  circularNo?: string | null;
  issuedAt?: string | null;
  web?: boolean;
};

const KNOWLEDGE_OPTIONS: { value: "local" | "local_and_dify" | "dify"; key: string }[] = [
  { value: "local", key: "local" },
  { value: "local_and_dify", key: "localAndDify" },
  { value: "dify", key: "dify" },
];

const SUGGESTED_PROMPT_KEYS = ["prompt1", "prompt2", "prompt3", "prompt4"] as const;

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

const CONTINUE_TAIL_CHARS = 300;

export default function ChatPage() {
  const t = useTranslations("chat");
  const { token, ready } = useAuth();
  const router = useRouter();
  const {
    question,
    setQuestion,
    knowledge,
    setKnowledge,
    programme,
    setProgramme,
    topic,
    setTopic,
    sessionId,
    sessions,
    sessionsError,
    msgs,
    loading,
    loadingPromptOnly,
    restoring,
    pending,
    setPending,
    extracting,
    attachError,
    ask,
    onNewChat,
    openSession,
    deleteSession,
    onStop,
    onPickFiles,
  } = useChat();
  const [historyOpen, setHistoryOpen] = useState(false);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [preview, setPreview] = useState<Preview | null>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

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

  function openCitation(c: Citation) {
    setPreview({
      ref: c.ref,
      title: c.title || c.ref,
      documentId: c.document_id,
      sourceUrl: c.source_url,
      circularNo: c.circular_no,
      issuedAt: c.issued_at,
      web: c.backend === "web",
    });
    setHistoryOpen(false);
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void ask(question);
  }

  function onContinue(content: string) {
    if (loading) return;
    const tail = content.slice(-CONTINUE_TAIL_CHARS).trim();
    const prompt = tail ? t("continuePromptWithTail", { tail }) : t("continuePrompt");
    void ask(prompt);
  }

  function handleNewChat() {
    onNewChat();
    setPreview(null);
    setHistoryOpen(false);
    setConfirmDeleteId(null);
    textareaRef.current?.focus();
  }

  function handleOpenSession(id: string) {
    setHistoryOpen(false);
    setConfirmDeleteId(null);
    if (id === sessionId) return;
    setPreview(null);
    void openSession(id);
  }

  async function onDelete(id: string) {
    if (confirmDeleteId !== id) {
      setConfirmDeleteId(id);
      return;
    }
    setConfirmDeleteId(null);
    if (sessionId === id) setPreview(null);
    await deleteSession(id);
  }

  function onChooseFiles(list: File[]) {
    void onPickFiles(list);
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
          <button type="button" className="btn secondary sm" onClick={handleNewChat} disabled={msgs.length === 0 && !loading && !sessionId && !question.trim() && pending.length === 0}>
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
                <button type="button" className="chat-history-open" onClick={() => handleOpenSession(s.id)}>
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
            {restoring ? (
              <div className="chat-empty">
                <span className="spinner lg" />
                <p>{t("restoring")}</p>
              </div>
            ) : null}

            {msgs.length === 0 && !loading && !restoring ? (
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
                  {m.role === "assistant" && !m.error && citationsUseWeb(m.citations) ? <WebSourceNotice /> : null}
                  {m.content ? (
                    <div className={`msg-bubble${m.error ? " error" : ""}${m.role === "assistant" && !m.error ? " md" : ""}`}>
                      {m.role === "assistant" && !m.error ? (
                        <AssistantMarkdown
                          content={m.content}
                          citations={m.citations}
                          activeRef={preview?.ref}
                          onOpen={openCitation}
                        />
                      ) : (
                        m.content
                      )}
                    </div>
                  ) : null}

                  {m.role === "assistant" && m.truncated && !m.error ? (
                    <div className="msg-truncated">
                      <p className="msg-note">
                        <Icon name="info" />
                        <span>{t("truncatedNotice")}</span>
                      </p>
                      <button
                        type="button"
                        className="btn secondary sm"
                        disabled={loading}
                        onClick={() => onContinue(m.content)}
                      >
                        {t("continue")}
                      </button>
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
                    <GroupedSources
                      citations={m.citations}
                      answerContent={m.content}
                      activeRef={preview?.ref}
                      onOpen={openCitation}
                      onClose={() => setPreview(null)}
                    />
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
                onChange={(e) => {
                  const list = Array.from(e.target.files || []);
                  e.target.value = "";
                  onChooseFiles(list);
                }}
              />
              <button
                className="btn ghost icon-only"
                type="button"
                aria-label={t("attach")}
                title={t("attach")}
                disabled={loading || extracting || pending.length >= CHAT_MAX_FILES}
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
            webSource={preview.web}
            onClose={() => setPreview(null)}
          />
        ) : null}
      </div>
    </div>
  );
}
