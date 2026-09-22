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

export default function DocumentsPage() {
  const t = useTranslations("documents");
  const { token, ready } = useAuth();
  const router = useRouter();
  const [q, setQ] = useState("");
  const [items, setItems] = useState<Doc[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (ready && !token) router.replace("/login");
  }, [ready, token, router]);

  useEffect(() => {
    if (!token) return;
    setLoading(true);
    listDocuments(token, { q: q || undefined })
      .then((data) => setItems(data.items || []))
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  }, [token, q]);

  if (!token) return null;

  return (
    <div>
      <div className="hero">
        <h1>{t("title")}</h1>
      </div>
      <div className="panel" style={{ marginBottom: "1rem" }}>
        <div className="field" style={{ marginBottom: 0 }}>
          <label htmlFor="q">{t("search")}</label>
          <input id="q" value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("search")} />
        </div>
      </div>
      <div className="list">
        {loading ? <div className="panel">…</div> : null}
        {!loading && items.length === 0 ? <div className="panel">{t("empty")}</div> : null}
        {items.map((doc) => (
          <article key={doc.id} className="doc-row">
            <div>
              <h3>
                <Link href={`/documents/${doc.id}`}>{doc.title}</Link>
              </h3>
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
            </div>
            <div style={{ display: "flex", gap: "0.5rem", alignItems: "start" }}>
              <Link className="btn secondary" href={`/documents/${doc.id}`}>
                {t("open")}
              </Link>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}
