"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
} from "react";
import { useLocale, useTranslations } from "next-intl";
import { usePathname, useRouter } from "@/i18n/routing";
import {
  chatAsk,
  deleteChatSession,
  extractChatFile,
  getChatSession,
  listChatSessions,
  type ChatHistoryMessage,
  type ChatSessionSummary,
  type KnowledgeSource,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import {
  mergeTranscript,
  parseSnapshot,
  serializeSnapshot,
  type ChatSnapshot,
  type Citation,
  type Programme,
  type StoredAttachment,
  type StoredMsg,
  type Topic,
} from "@/lib/chat-snapshot";

export type { Citation };

const SESSION_KEY = "edb_chat_session";
const SNAPSHOT_KEY = "edb_chat_snapshot";
export const CHAT_MAX_FILES = 3;
const MAX_FILE_BYTES = 8 * 1024 * 1024;
const PROMPT_ONLY_STORED = "（僅系統提示）";

export type PendingFile = { filename: string; text: string; charCount: number };

type Msg = StoredMsg;

type ChatContextValue = {
  question: string;
  setQuestion: Dispatch<SetStateAction<string>>;
  knowledge: KnowledgeSource;
  setKnowledge: (value: KnowledgeSource) => void;
  programme: Programme;
  setProgramme: (value: Programme) => void;
  topic: Topic;
  setTopic: (value: Topic) => void;
  sessionId: string | null;
  sessions: ChatSessionSummary[];
  sessionsError: boolean;
  msgs: Msg[];
  loading: boolean;
  loadingPromptOnly: boolean;
  restoring: boolean;
  pending: PendingFile[];
  setPending: Dispatch<SetStateAction<PendingFile[]>>;
  extracting: boolean;
  attachError: string | null;
  setAttachError: Dispatch<SetStateAction<string | null>>;
  ask: (raw: string, files?: PendingFile[]) => Promise<void>;
  onNewChat: () => void;
  openSession: (id: string) => Promise<void>;
  deleteSession: (id: string) => Promise<boolean>;
  onStop: () => void;
  onPickFiles: (files: File[]) => Promise<void>;
};

const ChatContext = createContext<ChatContextValue | null>(null);

function newId() {
  return crypto.randomUUID();
}

function readStoredSessionId() {
  if (typeof window === "undefined") return null;
  return sessionStorage.getItem(SESSION_KEY);
}

function readUrlSessionId() {
  if (typeof window === "undefined") return null;
  if (!window.location.pathname.includes("/chat")) return null;
  return new URLSearchParams(window.location.search).get("session");
}

function attachmentsOf(files: PendingFile[]): StoredAttachment[] {
  return files.map((file) => ({ filename: file.filename, char_count: file.charCount }));
}

function mapHistory(messages: ChatHistoryMessage[], promptOnlyLabel: string): Msg[] {
  return (messages || []).map((message) => ({
    id: message.id || newId(),
    role: message.role === "assistant" ? "assistant" : "user",
    content: message.content === PROMPT_ONLY_STORED ? promptOnlyLabel : message.content,
    citations: (message.citations || []) as Citation[],
    attachments: message.attachments || [],
  }));
}

export function ChatProvider({ children }: { children: ReactNode }) {
  const t = useTranslations("chat");
  const locale = useLocale();
  const pathname = usePathname();
  const router = useRouter();
  const { token, ready } = useAuth();

  const [question, setQuestion] = useState("");
  const [knowledge, setKnowledge] = useState<KnowledgeSource>("local");
  const [programme, setProgramme] = useState<Programme>("all");
  const [topic, setTopic] = useState<Topic>("all");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<ChatSessionSummary[]>([]);
  const [sessionsError, setSessionsError] = useState(false);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadingPromptOnly, setLoadingPromptOnly] = useState(false);
  const [restoreState, setRestoreState] = useState<"pending" | "done">("pending");
  const [booted, setBooted] = useState(false);
  const [pending, setPending] = useState<PendingFile[]>([]);
  const [extracting, setExtracting] = useState(false);
  const [attachError, setAttachError] = useState<string | null>(null);

  const tokenRef = useRef(token);
  const sessionIdRef = useRef(sessionId);
  const msgsRef = useRef(msgs);
  const loadingRef = useRef(loading);
  const pendingRef = useRef(pending);
  const knowledgeRef = useRef(knowledge);
  const programmeRef = useRef(programme);
  const topicRef = useRef(topic);
  const tRef = useRef(t);
  const localeRef = useRef(locale);
  const abortRef = useRef<AbortController | null>(null);
  const viewGen = useRef(0);
  const restoredRef = useRef(false);

  tokenRef.current = token;
  sessionIdRef.current = sessionId;
  msgsRef.current = msgs;
  loadingRef.current = loading;
  pendingRef.current = pending;
  knowledgeRef.current = knowledge;
  programmeRef.current = programme;
  topicRef.current = topic;
  tRef.current = t;
  localeRef.current = locale;

  const applySnapshot = useCallback((snapshot: ChatSnapshot | null, urlSession: string | null) => {
    const session = urlSession || snapshot?.sessionId || readStoredSessionId();
    if (snapshot) {
      setQuestion(snapshot.question);
      setKnowledge(snapshot.knowledge);
      setProgramme(snapshot.programme);
      setTopic(snapshot.topic);
      const sameSession = !urlSession || !snapshot.sessionId || urlSession === snapshot.sessionId;
      setMsgs(sameSession ? snapshot.msgs : []);
    }
    setSessionId(session);
    setRestoreState(session ? "pending" : "done");
  }, []);

  useEffect(() => {
    const snapshot = parseSnapshot(sessionStorage.getItem(SNAPSHOT_KEY));
    applySnapshot(snapshot, readUrlSessionId());
    setBooted(true);
  }, [applySnapshot]);

  const persist = useCallback((snapshot: ChatSnapshot) => {
    try {
      const json = serializeSnapshot(snapshot);
      sessionStorage.setItem(SNAPSHOT_KEY, json);
      if (snapshot.sessionId) sessionStorage.setItem(SESSION_KEY, snapshot.sessionId);
      else sessionStorage.removeItem(SESSION_KEY);
    } catch {
      try {
        const slim: ChatSnapshot = {
          ...snapshot,
          msgs: snapshot.msgs.map((msg) => ({ ...msg, citations: undefined })),
        };
        sessionStorage.setItem(SNAPSHOT_KEY, serializeSnapshot(slim));
      } catch {
        /* quota exceeded — in-memory state still covers in-app navigation */
      }
    }
  }, []);

  useEffect(() => {
    if (!booted) return;
    persist({
      v: 1,
      sessionId,
      question,
      knowledge,
      programme,
      topic,
      msgs,
    });
  }, [booted, sessionId, question, knowledge, programme, topic, msgs, persist]);

  const clearLocal = useCallback(() => {
    viewGen.current += 1;
    abortRef.current?.abort();
    abortRef.current = null;
    setLoading(false);
    setLoadingPromptOnly(false);
    setMsgs([]);
    setSessionId(null);
    setQuestion("");
    setPending([]);
    setAttachError(null);
    setSessions([]);
    setRestoreState("done");
    restoredRef.current = false;
    try {
      sessionStorage.removeItem(SNAPSHOT_KEY);
      sessionStorage.removeItem(SESSION_KEY);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    if (!booted || !ready || token) return;
    clearLocal();
  }, [booted, ready, token, clearLocal]);

  const refreshSessions = useCallback(async () => {
    const current = tokenRef.current;
    if (!current) return;
    try {
      const data = await listChatSessions(current);
      setSessions(data.items || []);
      setSessionsError(false);
    } catch {
      setSessionsError(true);
    }
  }, []);

  useEffect(() => {
    if (!token || pathname !== "/chat") return;
    void refreshSessions();
  }, [token, pathname, refreshSessions]);

  const refreshFromServer = useCallback(async (id: string) => {
    const current = tokenRef.current;
    if (!current) return;
    const gen = viewGen.current;
    try {
      const data = await getChatSession(current, id);
      if (gen !== viewGen.current) return;
      if (data.knowledge_source === "local" || data.knowledge_source === "dify" || data.knowledge_source === "local_and_dify") {
        setKnowledge(data.knowledge_source);
      }
      const serverMsgs = mapHistory(data.messages || [], tRef.current("promptOnlyLabel"));
      setMsgs((local) => mergeTranscript(local, serverMsgs));
      setSessionId(id);
    } catch (err) {
      if (gen !== viewGen.current) return;
      const code = err instanceof Error ? err.message : "";
      if (code === "session_not_found") {
        setMsgs([]);
        setSessionId(null);
        return;
      }
      if (msgsRef.current.length === 0) setSessionId(null);
    } finally {
      if (gen === viewGen.current) setRestoreState("done");
    }
  }, []);

  useEffect(() => {
    if (!booted || !token) {
      if (!token) restoredRef.current = false;
      return;
    }
    if (restoredRef.current) return;
    restoredRef.current = true;
    const id = sessionIdRef.current;
    if (!id) {
      setRestoreState("done");
      return;
    }
    void refreshFromServer(id);
  }, [booted, token, refreshFromServer]);

  const onNewChat = useCallback(() => {
    viewGen.current += 1;
    if (loadingRef.current) abortRef.current?.abort();
    abortRef.current = null;
    setLoading(false);
    setLoadingPromptOnly(false);
    setMsgs([]);
    setSessionId(null);
    setQuestion("");
    setPending([]);
    setAttachError(null);
    setRestoreState("done");
  }, []);

  const openSession = useCallback(async (id: string) => {
    const current = tokenRef.current;
    if (!current) return;
    if (id === sessionIdRef.current && msgsRef.current.length > 0) return;
    viewGen.current += 1;
    const gen = viewGen.current;
    if (loadingRef.current) abortRef.current?.abort();
    abortRef.current = null;
    setLoading(false);
    setLoadingPromptOnly(false);
    setSessionId(id);
    setMsgs([]);
    setQuestion("");
    setPending([]);
    setAttachError(null);
    setRestoreState("pending");
    try {
      const data = await getChatSession(current, id);
      if (gen !== viewGen.current) return;
      if (data.knowledge_source === "local" || data.knowledge_source === "dify" || data.knowledge_source === "local_and_dify") {
        setKnowledge(data.knowledge_source);
      }
      setMsgs(mapHistory(data.messages || [], tRef.current("promptOnlyLabel")));
    } catch {
      if (gen !== viewGen.current) return;
      setMsgs([{ id: newId(), role: "assistant", content: tRef.current("historyLoadError"), error: true }]);
    } finally {
      if (gen === viewGen.current) setRestoreState("done");
    }
  }, []);

  useEffect(() => {
    if (!booted || pathname !== "/chat") return;
    const current = new URLSearchParams(window.location.search).get("session");
    // State is the source of truth after boot. Writing the query through the
    // App Router keeps the session on refresh without history.replaceState,
    // which Next.js can treat as a navigation and wipe the page.
    if ((current || null) === (sessionId || null)) return;
    const href = sessionId ? `/chat?session=${encodeURIComponent(sessionId)}` : "/chat";
    router.replace(href, { scroll: false });
  }, [booted, pathname, sessionId, router]);

  const ask = useCallback(async (raw: string, files?: PendingFile[]) => {
    const currentToken = tokenRef.current;
    if (!currentToken || loadingRef.current) return;
    const sentFiles = files ?? pendingRef.current;
    const gen = viewGen.current;
    const q = raw.trim();
    const promptOnly = !q && sentFiles.length === 0;
    setQuestion("");
    if (sentFiles.length) {
      setPending((current) => current.filter((file) => !sentFiles.includes(file)));
    }
    setAttachError(null);
    setMsgs((current) => [
      ...current,
      {
        id: newId(),
        role: "user",
        content: promptOnly ? tRef.current("promptOnlyLabel") : q,
        attachments: attachmentsOf(sentFiles),
      },
    ]);
    setLoadingPromptOnly(promptOnly);
    setLoading(true);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const res = await chatAsk(
        currentToken,
        {
          question: q,
          session_id: sessionIdRef.current,
          knowledge_source: knowledgeRef.current,
          locale: localeRef.current,
          programme: programmeRef.current === "all" ? null : programmeRef.current,
          topic: topicRef.current === "all" ? null : topicRef.current,
          attachments: sentFiles.map((file) => ({ filename: file.filename, text: file.text })),
        },
        { signal: controller.signal },
      );
      if (gen !== viewGen.current) return;
      setSessionId(res.session_id);
      setMsgs((current) => [
        ...current,
        { id: newId(), role: "assistant", content: res.answer, citations: res.citations || [] },
      ]);
      void refreshSessions();
    } catch (err) {
      if (gen !== viewGen.current) return;
      if (sentFiles.length) {
        setPending((current) => [...sentFiles.filter((file) => !current.includes(file)), ...current]);
      }
      const code = err instanceof Error ? err.message : "";
      if (code === "chat_cancelled") {
        setMsgs((current) => [...current, { id: newId(), role: "assistant", content: tRef.current("cancelled"), error: true }]);
      } else {
        const message = code === "chat_timeout" ? tRef.current("timeout") : tRef.current("error");
        setMsgs((current) => [...current, { id: newId(), role: "assistant", content: message, error: true }]);
      }
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
      if (gen === viewGen.current) {
        setLoading(false);
        setLoadingPromptOnly(false);
      }
    }
  }, [refreshSessions]);

  const deleteSession = useCallback(async (id: string) => {
    const current = tokenRef.current;
    if (!current) return false;
    try {
      await deleteChatSession(current, id);
      setSessions((items) => items.filter((item) => item.id !== id));
      if (sessionIdRef.current === id) {
        onNewChat();
        return true;
      }
      return false;
    } catch {
      setSessionsError(true);
      return false;
    }
  }, [onNewChat]);

  const onStop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const onPickFiles = useCallback(async (list: File[]) => {
    const current = tokenRef.current;
    if (!current || list.length === 0) return;
    const room = CHAT_MAX_FILES - pendingRef.current.length;
    if (room <= 0) {
      setAttachError(tRef.current("attachTooMany"));
      return;
    }
    const batch = list.slice(0, room);
    setAttachError(list.length > room ? tRef.current("attachTooMany") : null);
    setExtracting(true);
    try {
      for (const file of batch) {
        if (file.size > MAX_FILE_BYTES) {
          setAttachError(tRef.current("attachTooLarge"));
          continue;
        }
        try {
          const res = await extractChatFile(current, file);
          setPending((currentFiles) => {
            if (currentFiles.length >= CHAT_MAX_FILES) return currentFiles;
            return [...currentFiles, { filename: res.filename, text: res.text, charCount: res.char_count }];
          });
        } catch (err) {
          const code = err instanceof Error ? err.message : "";
          if (code === "no_text") setAttachError(tRef.current("attachEmpty"));
          else if (code === "file_too_large") setAttachError(tRef.current("attachTooLarge"));
          else if (code === "unsupported_type") setAttachError(tRef.current("attachType"));
          else setAttachError(tRef.current("attachFailed"));
        }
      }
    } finally {
      setExtracting(false);
    }
  }, []);

  const restoring = !booted || (restoreState !== "done" && msgs.length === 0);

  const value = useMemo<ChatContextValue>(
    () => ({
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
      setAttachError,
      ask,
      onNewChat,
      openSession,
      deleteSession,
      onStop,
      onPickFiles,
    }),
    [
      question,
      knowledge,
      programme,
      topic,
      sessionId,
      sessions,
      sessionsError,
      msgs,
      loading,
      loadingPromptOnly,
      restoring,
      pending,
      extracting,
      attachError,
      ask,
      onNewChat,
      openSession,
      deleteSession,
      onStop,
      onPickFiles,
    ],
  );

  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>;
}

export function useChat() {
  const ctx = useContext(ChatContext);
  if (!ctx) throw new Error("useChat outside provider");
  return ctx;
}
