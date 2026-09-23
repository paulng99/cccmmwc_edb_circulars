"use client";

import { FormEvent, useEffect, useState } from "react";
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

  useEffect(() => {
    if (ready && !token) router.replace("/login");
  }, [ready, token, router]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!token || !question.trim() || loading) return;
    const q = question.trim();
    setQuestion("");
    setMsgs((m) => [...m, { role: "user", content: q }]);
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
    } catch (err) {
      const msg =
        err instanceof Error && err.message === "chat_timeout" ? t("timeout") : t("error");
      setMsgs((m) => [...m, { role: "assistant", content: msg }]);
    } finally {
      setLoading(false);
    }
  }

  if (!token) return null;

  return (
    <div>
      <div className="hero">
        <h1>{t("title")}</h1>
      </div>
      <div className="panel">
        <div className="chat-log">
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
          {loading ? <div className="bubble assistant">{t("thinking")}</div> : null}
        </div>
        <form onSubmit={onSubmit}>
          <div className="field">
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
          <div className="field">
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
          <div className="field">
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
          <div className="field">
            <label htmlFor="q">{t("placeholder")}</label>
            <textarea
              id="q"
              rows={3}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder={t("placeholder")}
            />
          </div>
          <button className="btn" type="submit" disabled={loading}>
            {t("send")}
          </button>
        </form>
      </div>
    </div>
  );
}
