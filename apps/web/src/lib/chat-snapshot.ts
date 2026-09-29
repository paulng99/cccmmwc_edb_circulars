export type KnowledgeSource = "local" | "local_and_dify" | "dify";
export type Programme = "all" | "circular" | "sister_school" | "lwlssg" | "other";
export type Topic =
  | "all"
  | "grant_funding"
  | "curriculum"
  | "admin"
  | "student_activity"
  | "parent_home"
  | "other";

export type Citation = {
  ref: string;
  title?: string;
  circular_no?: string | null;
  issued_at?: string | null;
  source_url?: string;
  document_id?: string;
  backend?: string;
};

export type StoredAttachment = { filename: string; char_count: number };

export type StoredMsg = {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  attachments?: StoredAttachment[];
  error?: boolean;
};

export type ChatSnapshot = {
  v: 1;
  sessionId: string | null;
  question: string;
  knowledge: KnowledgeSource;
  programme: Programme;
  topic: Topic;
  msgs: StoredMsg[];
};

const KNOWLEDGE: KnowledgeSource[] = ["local", "local_and_dify", "dify"];
const PROGRAMMES: Programme[] = ["all", "circular", "sister_school", "lwlssg", "other"];
const TOPICS: Topic[] = [
  "all",
  "grant_funding",
  "curriculum",
  "admin",
  "student_activity",
  "parent_home",
  "other",
];

export function mergeTranscript<T>(local: T[], server: T[]): T[] {
  // A longer local list is an optimistic turn the server has not stored yet.
  if (server.length >= local.length) return server;
  return local;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function parseMsg(value: unknown): StoredMsg | null {
  if (!isRecord(value)) return null;
  if (value.role !== "user" && value.role !== "assistant") return null;
  if (typeof value.content !== "string") return null;
  const id = typeof value.id === "string" && value.id ? value.id : crypto.randomUUID();
  const msg: StoredMsg = { id, role: value.role, content: value.content };
  if (Array.isArray(value.citations)) msg.citations = value.citations as Citation[];
  if (Array.isArray(value.attachments)) {
    msg.attachments = value.attachments.filter(isRecord).map((att) => ({
      filename: typeof att.filename === "string" ? att.filename : "file",
      char_count: typeof att.char_count === "number" ? att.char_count : 0,
    }));
  }
  if (value.error === true) msg.error = true;
  return msg;
}

export function parseSnapshot(raw: string | null): ChatSnapshot | null {
  if (!raw) return null;
  try {
    const data = JSON.parse(raw) as unknown;
    if (!isRecord(data) || data.v !== 1) return null;
    const knowledge = KNOWLEDGE.includes(data.knowledge as KnowledgeSource)
      ? (data.knowledge as KnowledgeSource)
      : "local";
    const programme = PROGRAMMES.includes(data.programme as Programme) ? (data.programme as Programme) : "all";
    const topic = TOPICS.includes(data.topic as Topic) ? (data.topic as Topic) : "all";
    const msgs = Array.isArray(data.msgs) ? data.msgs.map(parseMsg).filter((msg): msg is StoredMsg => msg !== null) : [];
    return {
      v: 1,
      sessionId: typeof data.sessionId === "string" && data.sessionId ? data.sessionId : null,
      question: typeof data.question === "string" ? data.question : "",
      knowledge,
      programme,
      topic,
      msgs,
    };
  } catch {
    return null;
  }
}

export function serializeSnapshot(snapshot: ChatSnapshot): string {
  return JSON.stringify(snapshot);
}
