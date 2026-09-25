"use client";

import { FormEvent, Fragment, useCallback, useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Link, useRouter } from "@/i18n/routing";
import { chatAsk, KnowledgeSource } from "@/lib/api";
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

type Msg = {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  error?: boolean;
};

const KNOWLEDGE_OPTIONS: { value: KnowledgeSource; key: string }[] = [
  { value: "local", key: "local" },
  { value: "local_and_dify", key: "localAndDify" },
  { value: "dify", key: "dify" },
];

const SUGGESTED_PROMPT_KEYS = ["prompt1", "prompt2", "prompt3", "prompt4"] as const;

/** Render `[n]` markers as compact citation chips linked to the matching source. */
function renderWithCitations(content: string, citations: Citation[] | undefined) {
  if (!citations || citations.length === 0) return content;
  const byRef = new Map(citations.map((c) => [String(c.ref), c]));
  const parts = content.split(/(\[\d+\])/g);
  return parts.map((part, i) => {
    const m = /^\[(\d+)\]$/.exec(part);
    if (!m) return <Fragment key={i}>{part}</Fragment>;
    const c = byRef.get(m[1]);
    if (!c) return <Fragment key={i}>{part}</Fragment>;
    const label = m[1];
    if (c.document_id) {
      return (
        <Link key={i} href={`/documents/${c.document_id}`} className="cite-ref" title={c.title || label}>
          {label}
        </Link>
      );
    }
    if (c.source_url) {
      return (
        <a key={i} href={c.source_url} target="_blank" rel="noreferrer" className="cite-ref" title={c.title || label}>
          {label}
        </a>
      );
    }
    return (
      <span key={i} className="cite-ref" title={c.title || label}>
        {label}
      </span>
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
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadingPromptOnly, setLoadingPromptOnly] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);

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

  const ask = useCallback(
    async (raw: string) => {
      if (!token || loading) return;
      const q = raw.trim();
      const promptOnly = !q;
      setQuestion("");
      setMsgs((m) => [...m, { role: "user", content: promptOnly ? t("promptOnlyLabel") : q }]);
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
          },
          { signal: controller.signal },
        );
        setSessionId(res.session_id);
        setMsgs((m) => [...m, { role: "assistant", content: res.answer, citations: res.citations || [] }]);
      } catch (err) {
        const code = err instanceof Error ? err.message : "";
        if (code === "chat_cancelled") {
          setMsgs((m) => [...m, { role: "assistant", content: t("cancelled"), error: true }]);
        } else {
          const msg = code === "chat_timeout" ? t("timeout") : t("error");
          setMsgs((m) => [...m, { role: "assistant", content: msg, error: true }]);
        }
      } finally {
        abortRef.current = null;
        setLoading(false);
        setLoadingPromptOnly(false);
      }
    },
    [token, loading, sessionId, knowledge, locale, programme, topic, t],
  );

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void ask(question);
  }

  function onStop() {
    abortRef.current?.abort();
  }

  function onNewChat() {
    if (loading) abortRef.current?.abort();
    setMsgs([]);
    setSessionId(null);
    setQuestion("");
    textareaRef.current?.focus();
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
          <button type="button" className="btn secondary sm" onClick={onNewChat} disabled={msgs.length === 0 && !loading}>
            <Icon name="plus" />
            <span>{t("newChat")}</span>
          </button>
        </div>
      </header>

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
                  <button key={key} type="button" className="prompt-card" onClick={() => void ask(t(key))}>
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

          {msgs.map((m, i) => (
            <div key={i} className={`msg ${m.role}`}>
              <div className="msg-avatar" aria-hidden>
                {m.role === "assistant" ? <Icon name="sparkles" /> : <Icon name="user" />}
              </div>
              <div className="msg-body">
                <div className={`msg-bubble${m.error ? " error" : ""}`}>
                  {m.role === "assistant" ? renderWithCitations(m.content, m.citations) : m.content}
                </div>

                {m.role === "assistant" && m.citations && m.citations.length > 0 ? (
                  <div className="sources">
                    <span className="sources-head">
                      <Icon name="quote" />
                      {t("sourcesCount", { count: m.citations.length })}
                    </span>
                    <div className="source-grid">
                      {m.citations.map((c, j) => {
                        const inner = (
                          <>
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
                          </>
                        );
                        if (c.document_id) {
                          return (
                            <Link key={j} href={`/documents/${c.document_id}`} className="source-card">
                              {inner}
                            </Link>
                          );
                        }
                        if (c.source_url) {
                          return (
                            <a key={j} href={c.source_url} target="_blank" rel="noreferrer" className="source-card">
                              {inner}
                            </a>
                          );
                        }
                        return (
                          <div key={j} className="source-card">
                            {inner}
                          </div>
                        );
                      })}
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
          <label className="sr-only" htmlFor="q">
            {t("placeholder")}
          </label>
          <div className="composer-box">
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
              <button className="btn icon-only" type="submit" aria-label={t("send")} title={t("send")}>
                <Icon name="send" />
              </button>
            )}
          </div>
          <div className="composer-hint">
            <span>
              <kbd>Enter</kbd> {t("hintSend")} · <kbd>Shift</kbd> + <kbd>Enter</kbd> {t("hintNewline")}
            </span>
            {sessionId ? <span>{t("sessionActive")}</span> : null}
          </div>
        </form>
      </section>
    </div>
  );
}
