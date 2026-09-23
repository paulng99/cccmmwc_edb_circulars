"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Link, useRouter } from "@/i18n/routing";
import { listDocuments } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type Doc = {
  id: string;
  title: string;
  circular_no?: string | null;
  issued_at?: string | null;
  source_id: string;
  status: string;
};

type ListStatus = "idle" | "loading" | "success" | "empty" | "error";

const SKELETON_COUNT = 4;

export default function DocumentsPage() {
  const t = useTranslations("documents");
  const { token, ready } = useAuth();
  const router = useRouter();
  const [q, setQ] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");
  const [items, setItems] = useState<Doc[]>([]);
  const [total, setTotal] = useState(0);
  const [status, setStatus] = useState<ListStatus>("idle");
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (ready && !token) router.replace("/login");
  }, [ready, token, router]);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQ(q.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [q]);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    setStatus("loading");
    listDocuments(token, { q: debouncedQ || undefined })
      .then((data) => {
        if (cancelled) return;
        const next = (data.items || []) as Doc[];
        setItems(next);
        setTotal(typeof data.total === "number" ? data.total : next.length);
        setStatus(next.length === 0 ? "empty" : "success");
      })
      .catch(() => {
        if (cancelled) return;
        setItems([]);
        setTotal(0);
        setStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, [token, debouncedQ, reloadKey]);

  if (!token) return null;

  const hasKeyword = Boolean(debouncedQ);

  return (
    <div className="page-enter">
      <div className="hero">
        <h1>{t("title")}</h1>
      </div>
      <div className="panel" style={{ marginBottom: "1rem" }}>
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
          <p className="result-count">{t("resultCount", { count: total })}</p>
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
          ? items.map((doc) => (
              <Link key={doc.id} href={`/documents/${doc.id}`} className="doc-row">
                <h3>{doc.title}</h3>
                <div className="meta">
                  <span className="chip">{doc.source_id}</span>
                  <span>
                    {t("circularNo")}: {doc.circular_no || "—"}
                  </span>
                  <span>
                    {t("issuedAt")}: {doc.issued_at || "—"}
                  </span>
                  <span>
                    {t("status")}: {doc.status}
                  </span>
                </div>
              </Link>
            ))
          : null}
      </div>
    </div>
  );
}
