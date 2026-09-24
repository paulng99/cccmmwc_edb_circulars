"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "@/i18n/routing";
import { chatAsk, KnowledgeSource } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type Msg = {
  role: "user" | "assistant";
  content: string;
  citations?: Array<{
    ref: string;
    title?: string;
    circular_no?: string | null;
    issued_at?: string | null;
    source_url?: string;
    document_id?: string;
    backend?: string;
  }>;
};

type Programme = "all" | "circular" | "sister_school" | "lwlssg" | "other";
type Topic =
  | "all"
  | "grant_funding"
  | "curriculum"
  | "admin"
  | "student_activity"
  | "parent_home"
  | "other";

const PROGRAMME_OPTIONS: { value: Programme; key: string }[] = [
  { value: "all", key: "programmeAll" },
  { value: "circular", key: "programmeCircular" },
  { value: "sister_school", key: "programmeSisterSchool" },
  { value: "lwlssg", key: "programmeLwlssg" },
  { value: "other", key: "programmeOther" },
];

const TOPIC_OPTIONS: { value: Topic; key: string }[] = [
  { value: "all", key: "topicAll" },
  { value: "grant_funding", key: "topicGrantFunding" },
  { value: "curriculum", key: "topicCurriculum" },
  { value: "admin", key: "topicAdmin" },
  { value: "student_activity", key: "topicStudentActivity" },
  { value: "parent_home", key: "topicParentHome" },
  { value: "other", key: "topicOther" },
];

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
  const [filtersOpen, setFiltersOpen] = useState(true);
  const collapsedAfterReply = useRef(false);
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (ready && !token) router.replace("/login");
  }, [ready, token, router]);

  useEffect(() => {
    const el = logRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [msgs, loading]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!token || loading) return;
    const q = question.trim();
    const promptOnly = !q;
    setQuestion("");
    setMsgs((m) => [
      ...m,
      { role: "user", content: promptOnly ? t("promptOnlyLabel") : q },
    ]);
    setLoadingPromptOnly(promptOnly);
    setLoading(true);
    try {
      const res = await chatAsk(token, {
        question: q,
        session_id: sessionId,
        knowledge_source: knowledge,
        locale,
        programme: programme === "all" ? null : programme,
        topic: topic === "all" ? null : topic,
      });
      setSessionId(res.session_id);
      setMsgs((m) => [
        ...m,
        { role: "assistant", content: res.answer, citations: res.citations || [] },
      ]);
      if (!collapsedAfterReply.current) {
        collapsedAfterReply.current = true;
        setFiltersOpen(false);
      }
    } catch (err) {
      const msg =
        err instanceof Error && err.message === "chat_timeout" ? t("timeout") : t("error");
      setMsgs((m) => [...m, { role: "assistant", content: msg }]);
    } finally {
      setLoading(false);
      setLoadingPromptOnly(false);
    }
  }

  if (!token) return null;

  const knowledgeLabel =
    knowledge === "local"
      ? t("local")
      : knowledge === "local_and_dify"
        ? t("localAndDify")
        : t("dify");
  const programmeKey = PROGRAMME_OPTIONS.find((o) => o.value === programme)?.key || "programmeAll";
  const topicKey = TOPIC_OPTIONS.find((o) => o.value === topic)?.key || "topicAll";
  const scopeSummary = `${knowledgeLabel} · ${t(programmeKey)} · ${t(topicKey)}`;

  return (
    <div className="page-enter page-stack chat-page">
      <header className="page-header">
        <h1>{t("title")}</h1>
        <p className="page-subtitle">{t("subtitle")}</p>
      </header>

      <div className="panel chat-workspace">
        <div className="chat-scope">
          <button
            type="button"
            className="chat-scope-toggle"
            aria-expanded={filtersOpen}
            onClick={() => setFiltersOpen((v) => !v)}
          >
            <span className="chat-scope-toggle-text">
              <span className="chat-scope-label">{t("filters")}</span>
              {!filtersOpen ? (
                <span className="chat-scope-summary">{scopeSummary}</span>
              ) : null}
            </span>
            <span aria-hidden>{filtersOpen ? "▴" : "▾"}</span>
          </button>
          {filtersOpen ? (
            <div className="chat-scope-body">
              <div className="field chat-scope-field">
                <label htmlFor="ks">{t("knowledge")}</label>
                <select
                  id="ks"
                  value={knowledge}
                  onChange={(e) => setKnowledge(e.target.value as KnowledgeSource)}
                >
                  <option value="local">{t("local")}</option>
                  <option value="local_and_dify">{t("localAndDify")}</option>
                  <option value="dify">{t("dify")}</option>
                </select>
              </div>
              <div className="filter-block">
                <span className="category-label" id="chat-prog-label">
                  {t("programmeFilter")}
                </span>
                <div
                  className="lang-variants category-toggle"
                  role="group"
                  aria-labelledby="chat-prog-label"
                >
                  {PROGRAMME_OPTIONS.map(({ value, key }) => (
                    <button
                      key={value}
                      type="button"
                      className={`lang-chip${programme === value ? " active" : ""}`}
                      aria-pressed={programme === value}
                      onClick={() => setProgramme(value)}
                    >
                      {t(key)}
                    </button>
                  ))}
                </div>
              </div>
              <div className="filter-block">
                <span className="category-label" id="chat-topic-label">
                  {t("topicFilter")}
                </span>
                <div
                  className="lang-variants category-toggle"
                  role="group"
                  aria-labelledby="chat-topic-label"
                >
                  {TOPIC_OPTIONS.map(({ value, key }) => (
                    <button
                      key={value}
                      type="button"
                      className={`lang-chip${topic === value ? " active" : ""}`}
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

        <div className="chat-log" ref={logRef}>
          {msgs.length === 0 && !loading ? (
            <div className="chat-empty">
              <p>{t("subtitle")}</p>
              <p className="hint">{t("placeholder")}</p>
            </div>
          ) : null}
          {msgs.map((m, i) => (
            <div key={i} className={`bubble ${m.role}`}>
              {m.content}
              {m.citations && m.citations.length > 0 ? (
                <div className="citations">
                  <strong>{t("citations")}</strong>
                  <ul>
                    {m.citations.map((c, j) => (
                      <li key={j}>
                        [{c.ref}] {c.title || "—"}
                        {c.circular_no ? ` · ${c.circular_no}` : ""}
                        {c.issued_at ? ` · ${c.issued_at}` : ""}
                        {c.source_url ? (
                          <>
                            {" "}
                            <a href={c.source_url} target="_blank" rel="noreferrer">
                              link
                            </a>
                          </>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : m.role === "assistant" ? (
                <p className="hint" style={{ marginTop: "0.5rem" }}>
                  {t("noCitations")}
                </p>
              ) : null}
            </div>
          ))}
          {loading ? (
            <div className="bubble assistant thinking" aria-live="polite">
              {loadingPromptOnly ? t("thinkingPromptOnly") : t("thinking")}
            </div>
          ) : null}
        </div>

        <form className="chat-composer" onSubmit={onSubmit}>
          <label className="sr-only" htmlFor="q">
            {t("placeholder")}
          </label>
          <div className="chat-composer-row">
            <textarea
              id="q"
              rows={2}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder={t("placeholder")}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  (e.currentTarget.form as HTMLFormElement | null)?.requestSubmit();
                }
              }}
            />
            <button className={`btn${loading ? " is-loading" : ""}`} type="submit" disabled={loading}>
              {t("send")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
