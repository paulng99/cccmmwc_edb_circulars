"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Link, useRouter } from "@/i18n/routing";
import { listDocuments } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type Variant = {
  id: string;
  language: string;
  status: string;
  file_size: number;
  title: string;
};

type DocGroup = {
  key: string;
  title: string;
  circular_no?: string | null;
  issued_at?: string | null;
  source_id: string;
  primary_id: string;
  programme?: string;
  category?: string;
  topics?: string[];
  variants: Variant[];
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
type ListStatus = "idle" | "loading" | "success" | "empty" | "error";

const SKELETON_COUNT = 4;
const PAGE_SIZE = 20;

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

function langLabel(code: string, t: (key: string) => string): string {
  if (code === "zh-HK") return t("langZhHk");
  if (code === "zh-CN") return t("langZhCn");
  if (code === "en") return t("langEn");
  return code;
}

function programmeLabel(prog: string | undefined, t: (key: string) => string): string {
  const map: Record<string, string> = {
    circular: "programmeCircular",
    sister_school: "programmeSisterSchool",
    lwlssg: "programmeLwlssg",
    other: "programmeOther",
  };
  const key = map[prog || ""] || "programmeOther";
  return t(key);
}

function topicLabel(topic: string, t: (key: string) => string): string {
  const map: Record<string, string> = {
    grant_funding: "topicGrantFunding",
    curriculum: "topicCurriculum",
    admin: "topicAdmin",
    student_activity: "topicStudentActivity",
    parent_home: "topicParentHome",
    other: "topicOther",
  };
  return t(map[topic] || "topicOther");
}

export default function DocumentsPage() {
  const t = useTranslations("documents");
  const { token, ready } = useAuth();
  const router = useRouter();
  const [q, setQ] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");
  const [programme, setProgramme] = useState<Programme>("all");
  const [topic, setTopic] = useState<Topic>("all");
  const [items, setItems] = useState<DocGroup[]>([]);
  const [total, setTotal] = useState(0);
  const [fileCount, setFileCount] = useState(0);
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState<ListStatus>("idle");
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (ready && !token) router.replace("/login");
  }, [ready, token, router]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedQ(q.trim());
      setPage(1);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [q]);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    setStatus("loading");
    listDocuments(token, {
      q: debouncedQ || undefined,
      page,
      page_size: PAGE_SIZE,
      programme,
      topic,
    })
      .then((data) => {
        if (cancelled) return;
        const next = (data.items || []) as DocGroup[];
        setItems(next);
        setTotal(typeof data.total === "number" ? data.total : next.length);
        setFileCount(typeof data.file_count === "number" ? data.file_count : 0);
        setStatus(next.length === 0 ? "empty" : "success");
      })
      .catch(() => {
        if (cancelled) return;
        setItems([]);
        setTotal(0);
        setFileCount(0);
        setStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, [token, debouncedQ, page, programme, topic, reloadKey]);

  if (!token) return null;

  const hasKeyword = Boolean(debouncedQ);
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  function selectProgramme(next: Programme) {
    setProgramme(next);
    setPage(1);
  }

  function selectTopic(next: Topic) {
    setTopic(next);
    setPage(1);
  }

  const countLabel =
    programme === "circular"
      ? t("resultCountCirculars", { count: total })
      : t("resultCountProgramme", { count: total });

  return (
    <div className="page-enter">
      <div className="hero">
        <h1>{t("title")}</h1>
      </div>
      <div className="panel" style={{ marginBottom: "1rem" }}>
        <div className="field" style={{ marginBottom: "0.85rem" }}>
          <span className="category-label" id="prog-label">
            {t("programmeFilter")}
          </span>
          <div className="lang-variants category-toggle" role="group" aria-labelledby="prog-label">
            {PROGRAMME_OPTIONS.map(({ value, key }) => (
              <button
                key={value}
                type="button"
                className={`lang-chip${programme === value ? " active" : ""}`}
                aria-pressed={programme === value}
                onClick={() => selectProgramme(value)}
              >
                {t(key)}
              </button>
            ))}
          </div>
        </div>
        <div className="field" style={{ marginBottom: "0.85rem" }}>
          <span className="category-label" id="topic-label">
            {t("topicFilter")}
          </span>
          <div className="lang-variants category-toggle" role="group" aria-labelledby="topic-label">
            {TOPIC_OPTIONS.map(({ value, key }) => (
              <button
                key={value}
                type="button"
                className={`lang-chip${topic === value ? " active" : ""}`}
                aria-pressed={topic === value}
                onClick={() => selectTopic(value)}
              >
                {t(key)}
              </button>
            ))}
          </div>
        </div>
        <div className="field" style={{ marginBottom: 0 }}>
          <label htmlFor="q">{t("search")}</label>
          <input
            id="q"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={t("search")}
            autoComplete="off"
          />
        </div>
      </div>

      {status === "success" || status === "empty" ? (
        <div className="list-toolbar">
          <p className="result-count">
            {countLabel}
            {fileCount > total ? (
              <span className="result-count-sub"> · {t("fileCount", { count: fileCount })}</span>
            ) : null}
          </p>
        </div>
      ) : null}

      <div className="list">
        {status === "loading" || status === "idle"
          ? Array.from({ length: SKELETON_COUNT }, (_, i) => (
              <div key={i} className="doc-row skeleton-row" aria-hidden>
                <span className="skeleton-line title" />
                <span className="skeleton-line meta" />
              </div>
            ))
          : null}

        {status === "error" ? (
          <div className="panel state-panel">
            <p className="error" style={{ marginBottom: "0.5rem" }}>
              {t("loadError")}
            </p>
            <div className="state-actions">
              <button type="button" className="btn" onClick={() => setReloadKey((k) => k + 1)}>
                {t("retry")}
              </button>
            </div>
          </div>
        ) : null}

        {status === "empty" ? (
          <div className="panel state-panel">
            {hasKeyword ? (
              <>
                <p>{t("emptySearch", { query: debouncedQ })}</p>
                <p className="hint">{t("emptySearchHint")}</p>
                <div className="state-actions">
                  <button type="button" className="btn secondary" onClick={() => setQ("")}>
                    {t("clearSearch")}
                  </button>
                </div>
              </>
            ) : (
              <p>{t("empty")}</p>
            )}
          </div>
        ) : null}

        {status === "success"
          ? items.map((group) => (
              <div key={group.key} className="doc-row doc-group">
                <Link href={`/documents/${group.primary_id}`} className="doc-group-main">
                  <h3>{group.title}</h3>
                  <div className="meta">
                    <span className="chip category-chip">
                      {programmeLabel(group.programme || group.category, t)}
                    </span>
                    {(group.topics || []).slice(0, 3).map((tp) => (
                      <span key={tp} className="chip">
                        {topicLabel(tp, t)}
                      </span>
                    ))}
                    <span className="chip">{group.source_id}</span>
                    <span>
                      {t("circularNo")}: {group.circular_no || "—"}
                    </span>
                    <span>
                      {t("issuedAt")}: {group.issued_at || "—"}
                    </span>
                  </div>
                </Link>
                <div className="lang-variants" role="group" aria-label={t("languages")}>
                  {group.variants.map((v) => (
                    <Link
                      key={v.id}
                      href={`/documents/${v.id}`}
                      className="lang-chip"
                      title={v.title}
                    >
                      {langLabel(v.language, t)}
                    </Link>
                  ))}
                </div>
              </div>
            ))
          : null}
      </div>

      {status === "success" && totalPages > 1 ? (
        <div className="pagination">
          <button
            type="button"
            className="btn secondary"
            disabled={page <= 1}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
          >
            {t("prevPage")}
          </button>
          <span className="pagination-info">{t("pageOf", { page, totalPages })}</span>
          <button
            type="button"
            className="btn secondary"
            disabled={page >= totalPages}
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
          >
            {t("nextPage")}
          </button>
        </div>
      ) : null}
    </div>
  );
}
