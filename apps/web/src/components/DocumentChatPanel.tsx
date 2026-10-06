"use client";

import { FormEvent, useCallback, useEffect, useId, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import AssistantMarkdown from "@/components/AssistantMarkdown";
import GroupedSources from "@/components/GroupedSources";
import { Icon } from "@/components/Icon";
import { useRouter } from "@/i18n/routing";
import {
  chatAsk,
  getChatSession,
  listChatSessions,
  type ChatHistoryMessage,
} from "@/lib/api";
import type { Citation } from "@/lib/chat-store";

type PanelMsg = {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  error?: boolean;
};

type Props = {
  documentId: string;
  documentStatus: string;
  token: string;
  onClose: () => void;
};

function fromHistory(messages: ChatHistoryMessage[]): PanelMsg[] {
  return messages
    .filter((m) => m.role === "user" || m.role === "assistant")
    .map((m) => ({
      id: m.id,
      role: m.role,
      content: m.content,
      citations: (m.citations || []) as Citation[],
    }));
}

export default function DocumentChatPanel({
  documentId,
  documentStatus,
  token,
  onClose,
}: Props) {
  const t = useTranslations("documents");
  const tChat = useTranslations("chat");
  const locale = useLocale();
  const router = useRouter();
  const logRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const inputId = useId();

  const [msgs, setMsgs] = useState<PanelMsg[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [restoring, setRestoring] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setRestoring(true);
    setError(null);
    (async () => {
      try {
        const { items } = await listChatSessions(token);
        const match = items.find((s) => s.focus_document_id === documentId);
        if (!match) {
          if (!cancelled) {
            setMsgs([]);
            setSessionId(null);
          }
          return;
        }
        const detail = await getChatSession(token, match.id);
        if (cancelled) return;
        setSessionId(detail.id);
        setMsgs(fromHistory(detail.messages || []));
      } catch {
        if (!cancelled) setError(t("chatRestoreFail"));
      } finally {
        if (!cancelled) setRestoring(false);
      }
    })();
    return () => {
      cancelled = true;
      abortRef.current?.abort("user");
    };
  }, [token, documentId, t]);

  useEffect(() => {
    const el = logRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [msgs, loading, restoring]);

  const openCitation = useCallback(
    (c: Citation) => {
      if (c.document_id && c.document_id !== documentId) {
        router.push(`/documents/${c.document_id}`);
      }
    },
    [documentId, router],
  );

  const send = useCallback(
    async (text: string) => {
      const q = text.trim();
      if (!q || loading) return;
      setQuestion("");
      setError(null);
      const userId = `u-${Date.now()}`;
      setMsgs((prev) => [...prev, { id: userId, role: "user", content: q }]);
      setLoading(true);
      abortRef.current?.abort("user");
      const controller = new AbortController();
      abortRef.current = controller;
      try {
        const res = await chatAsk(
          token,
          {
            question: q,
            session_id: sessionId,
            focus_document_id: documentId,
            knowledge_source: "local",
            locale,
          },
          { signal: controller.signal },
        );
        setSessionId(res.session_id);
        setMsgs((prev) => [
          ...prev,
          {
            id: `a-${Date.now()}`,
            role: "assistant",
            content: res.answer,
            citations: (res.citations || []) as Citation[],
          },
        ]);
      } catch (e) {
        const code = e instanceof Error ? e.message : "chat_failed";
        if (code === "chat_cancelled") return;
        const label =
          code === "chat_timeout" ? t("chatTimeout") : t("chatFail");
        setMsgs((prev) => [
          ...prev,
          { id: `e-${Date.now()}`, role: "assistant", content: label, error: true },
        ]);
      } finally {
        setLoading(false);
        if (abortRef.current === controller) abortRef.current = null;
      }
    },
    [documentId, loading, locale, sessionId, t, token],
  );

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    void send(question);
  };

  const notReady = documentStatus !== "ready";

  return (
    <aside className="card document-chat-panel" aria-label={t("chatTitle")}>
      <div className="card-head">
        <h2>
          <Icon name="message-square" />
          {t("chatTitle")}
        </h2>
        <div className="row-actions">
          <button className="btn secondary sm" type="button" onClick={onClose} aria-label={t("chatClose")}>
            <Icon name="x" />
            {t("chatClose")}
          </button>
        </div>
      </div>

      {notReady ? (
        <div className="alert warning document-chat-banner">
          <Icon name="alert-triangle" />
          <span>{t("chatNotReady")}</span>
        </div>
      ) : null}

      {error ? (
        <div className="alert danger document-chat-banner">
          <Icon name="alert-circle" />
          <span>{error}</span>
        </div>
      ) : null}

      <div className="document-chat-log chat-log" ref={logRef} aria-live="polite">
        {restoring ? (
          <div className="chat-empty">
            <span className="spinner lg" />
            <p>{t("chatRestoring")}</p>
          </div>
        ) : null}

        {!restoring && msgs.length === 0 && !loading ? (
          <div className="chat-empty">
            <div className="chat-empty-mark">
              <Icon name="sparkles" />
            </div>
            <h2>{t("chatEmptyTitle")}</h2>
            <p>{t("chatEmptyLead")}</p>
          </div>
        ) : null}

        {msgs.map((m) => (
          <div key={m.id} className={`msg ${m.role}`}>
            <div className="msg-avatar" aria-hidden>
              {m.role === "assistant" ? <Icon name="sparkles" /> : <Icon name="user" />}
            </div>
            <div className="msg-body">
              {m.content ? (
                <div
                  className={`msg-bubble${m.error ? " error" : ""}${
                    m.role === "assistant" && !m.error ? " md" : ""
                  }`}
                >
                  {m.role === "assistant" && !m.error ? (
                    <AssistantMarkdown
                      content={m.content}
                      citations={m.citations}
                      onOpen={openCitation}
                    />
                  ) : (
                    m.content
                  )}
                </div>
              ) : null}
              {m.role === "assistant" && m.citations && m.citations.length > 0 ? (
                <GroupedSources
                  citations={m.citations}
                  answerContent={m.content}
                  onOpen={openCitation}
                  onClose={() => undefined}
                />
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
                  {tChat("thinking")}
                </span>
              </div>
            </div>
          </div>
        ) : null}
      </div>

      <form className="document-chat-composer" onSubmit={onSubmit}>
        <label className="sr-only" htmlFor={inputId}>
          {t("chatPlaceholder")}
        </label>
        <textarea
          id={inputId}
          rows={2}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder={t("chatPlaceholder")}
          disabled={loading || restoring}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void send(question);
            }
          }}
        />
        <div className="document-chat-actions">
          {loading ? (
            <button
              className="btn secondary sm"
              type="button"
              onClick={() => abortRef.current?.abort("user")}
            >
              <Icon name="square" />
              {tChat("stop")}
            </button>
          ) : (
            <button className="btn sm" type="submit" disabled={!question.trim() || restoring}>
              <Icon name="send" />
              {tChat("send")}
            </button>
          )}
        </div>
      </form>
    </aside>
  );
}
