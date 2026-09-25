"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Link, useRouter } from "@/i18n/routing";
import { listDocuments } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Icon } from "@/components/Icon";
import {
  PROGRAMME_OPTIONS,
  PROGRAMME_TONE,
  TOPIC_OPTIONS,
  TOPIC_TONE,
  langLabel,
  programmeLabel,
  topicLabel,
  type Programme,
  type Topic,
} from "@/lib/taxonomy";

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

type ListStatus = "idle" | "loading" | "success" | "empty" | "error";

const SKELETON_COUNT = 5;
const PAGE_SIZE = 20;

function docIconClass(prog?: string) {
  if (prog === "sister_school") return "doc-icon sister";
  if (prog === "lwlssg") return "doc-icon lwlssg";
  if (prog === "other") return "doc-icon other";
  return "doc-icon";
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
  const hasFilters = programme !== "all" || topic !== "all" || hasKeyword;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  function selectProgramme(next: Programme) {
    setProgramme(next);
    setPage(1);
  }

  function selectTopic(next: Topic) {
    setTopic(next);
    setPage(1);
  }

  function clearAll() {
    setQ("");
    setProgramme("all");
    setTopic("all");
    setPage(1);
  }

  const countLabel =
    programme === "circular"
      ? t("resultCountCirculars", { count: total })
      : t("resultCountProgramme", { count: total });

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>{t("title")}</h1>
          <p className="page-subtitle">{t("subtitle")}</p>
        </div>
      </header>

      <section className="card toolbar" aria-label={t("filtersLabel")}>
        <div className={`input-wrap${q ? " has-trailing" : ""}`}>
          <Icon name="search" />
          <input
            id="q"
            className="input"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={t("search")}
            autoComplete="off"
            aria-label={t("search")}
          />
          {q ? (
            <button type="button" className="input-trailing" onClick={() => setQ("")} aria-label={t("clearSearch")}>
              <Icon name="x" />
            </button>
          ) : null}
        </div>

        <div className="filter-row">
          <span className="label" id="prog-label">
            {t("programmeFilter")}
          </span>
          <div className="chips" role="group" aria-labelledby="prog-label">
            {PROGRAMME_OPTIONS.map(({ value, key }) => (
              <button
                key={value}
                type="button"
                className="chip"
                aria-pressed={programme === value}
                onClick={() => selectProgramme(value)}
              >
                {t(key)}
              </button>
            ))}
          </div>
        </div>

        <div className="filter-row">
          <span className="label" id="topic-label">
            {t("topicFilter")}
          </span>
          <div className="chips" role="group" aria-labelledby="topic-label">
            {TOPIC_OPTIONS.map(({ value, key }) => (
              <button
                key={value}
                type="button"
                className="chip"
                aria-pressed={topic === value}
                onClick={() => selectTopic(value)}
              >
                {t(key)}
              </button>
            ))}
          </div>
        </div>
      </section>

      {status === "success" || status === "empty" ? (
        <div className="list-head">
          <p className="result-count">
            <strong>{countLabel}</strong>
            {fileCount > total ? (
              <span className="result-count-sub"> · {t("fileCount", { count: fileCount })}</span>
            ) : null}
          </p>
          {hasFilters ? (
            <button type="button" className="btn ghost sm" onClick={clearAll}>
              <Icon name="x" />
              {t("clearFilters")}
            </button>
          ) : null}
        </div>
      ) : null}

      {status === "loading" || status === "idle" ? (
        <div className="card doc-list" aria-busy="true">
          {Array.from({ length: SKELETON_COUNT }, (_, i) => (
            <div key={i} className="doc-item" aria-hidden>
              <div className="doc-main">
                <span className="skeleton" style={{ width: 40, height: 40, borderRadius: 10 }} />
                <div className="doc-body">
                  <span className="skeleton" style={{ height: "1rem", width: `${60 + (i % 3) * 12}%` }} />
                  <div className="doc-meta">
                    <span className="skeleton" style={{ height: 22, width: 64 }} />
                    <span className="skeleton" style={{ height: 22, width: 90 }} />
                  </div>
                </div>
                <span className="skeleton" style={{ height: "0.85rem", width: 84 }} />
              </div>
            </div>
          ))}
        </div>
      ) : null}

      {status === "error" ? (
        <div className="card empty">
          <div className="empty-icon danger">
            <Icon name="alert-triangle" />
          </div>
          <h3>{t("loadError")}</h3>
          <div className="empty-actions">
            <button type="button" className="btn" onClick={() => setReloadKey((k) => k + 1)}>
              <Icon name="refresh-cw" />
              {t("retry")}
            </button>
          </div>
        </div>
      ) : null}

      {status === "empty" ? (
        <div className="card empty">
          <div className="empty-icon">
            <Icon name={hasKeyword ? "file-search" : "inbox"} />
          </div>
          {hasKeyword ? (
            <>
              <h3>{t("emptySearch", { query: debouncedQ })}</h3>
              <p>{t("emptySearchHint")}</p>
              <div className="empty-actions">
                <button type="button" className="btn secondary" onClick={clearAll}>
                  {t("clearFilters")}
                </button>
              </div>
            </>
          ) : (
            <>
              <h3>{t("emptyTitle")}</h3>
              <p>{t("empty")}</p>
              <div className="empty-actions">
                <Link className="btn" href="/status">
                  <Icon name="play" />
                  {t("goToStatus")}
                </Link>
              </div>
            </>
          )}
        </div>
      ) : null}

      {status === "success" ? (
        <div className="card doc-list">
          {items.map((group) => {
            const prog = group.programme || group.category;
            return (
              <article key={group.key} className="doc-item">
                <Link href={`/documents/${group.primary_id}`} className="doc-main">
                  <span className={docIconClass(prog)} aria-hidden>
                    <Icon name="file-text" />
                  </span>
                  <div className="doc-body">
                    <h3>{group.title}</h3>
                    <div className="doc-meta">
                      <span className={`badge ${PROGRAMME_TONE[prog || ""] || "slate"}`}>
                        {programmeLabel(prog, t)}
                      </span>
                      {(group.topics || []).slice(0, 3).map((tp) => (
                        <span key={tp} className={`badge outline ${TOPIC_TONE[tp] || "slate"}`}>
                          {topicLabel(tp, t)}
                        </span>
                      ))}
                      {group.circular_no ? (
                        <span className="circ">
                          <Icon name="hash" style={{ width: 12, height: 12 }} />
                          {group.circular_no}
                        </span>
                      ) : null}
                    </div>
                  </div>
                  <time className="doc-date" dateTime={group.issued_at || undefined}>
                    <Icon name="calendar" />
                    {group.issued_at || "—"}
                  </time>
                </Link>
                <div className="doc-langs" role="group" aria-label={t("languages")}>
                  <span className="label">{t("languages")}</span>
                  {group.variants.map((v) => (
                    <Link key={v.id} href={`/documents/${v.id}`} className="lang-pill" title={v.title}>
                      <Icon name="globe" />
                      {langLabel(v.language, t)}
                    </Link>
                  ))}
                </div>
              </article>
            );
          })}
        </div>
      ) : null}

      {status === "success" && totalPages > 1 ? (
        <nav className="pagination" aria-label={t("pagination")}>
          <button
            type="button"
            className="btn secondary sm"
            disabled={page <= 1}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
          >
            <Icon name="chevron-left" />
            {t("prevPage")}
          </button>
          <span className="pagination-info">{t("pageOf", { page, totalPages })}</span>
          <button
            type="button"
            className="btn secondary sm"
            disabled={page >= totalPages}
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
          >
            {t("nextPage")}
            <Icon name="chevron-right" />
          </button>
        </nav>
      ) : null}
    </div>
  );
}
