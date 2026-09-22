"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useParams } from "next/navigation";
import { Link, useRouter } from "@/i18n/routing";
import { API_URL, fileUrl } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type Doc = {
  id: string;
  title: string;
  circular_no?: string | null;
  issued_at?: string | null;
  source_id: string;
  source_url: string;
  file_url?: string | null;
  status: string;
  language: string;
  file_size: number;
};

export default function DocumentDetailPage() {
  const t = useTranslations("documents");
  const { token, ready } = useAuth();
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const [doc, setDoc] = useState<Doc | null>(null);

  useEffect(() => {
    if (ready && !token) router.replace("/login");
  }, [ready, token, router]);

  useEffect(() => {
    if (!token || !params?.id) return;
    fetch(`${API_URL}/api/documents/${params.id}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((r) => (r.ok ? r.json() : null))
      .then(setDoc)
      .catch(() => setDoc(null));
  }, [token, params?.id]);

  if (!token) return null;

  return (
    <div>
      <div className="hero">
        <p>
          <Link href="/documents">{t("title")}</Link>
        </p>
        <h1>{doc?.title || "…"}</h1>
      </div>
      {doc ? (
        <div className="panel">
          <div className="meta" style={{ marginBottom: "1rem" }}>
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
            <span>
              {t("source")}: {doc.language}
            </span>
          </div>
          <p>
            <a href={doc.source_url} target="_blank" rel="noreferrer">
              {doc.source_url}
            </a>
          </p>
          <div style={{ display: "flex", gap: "0.75rem", marginTop: "1rem" }}>
            <button
              className="btn"
              type="button"
              onClick={() => {
                fetch(fileUrl(doc.id), { headers: { Authorization: `Bearer ${token}` } })
                  .then((r) => r.blob())
                  .then((blob) => {
                    const url = URL.createObjectURL(blob);
                    window.open(url, "_blank");
                  });
              }}
            >
              {t("open")}
            </button>
            {doc.file_url ? (
              <a className="btn secondary" href={doc.file_url} target="_blank" rel="noreferrer">
                {t("download")}
              </a>
            ) : null}
          </div>
        </div>
      ) : (
        <div className="panel">…</div>
      )}
    </div>
  );
}
