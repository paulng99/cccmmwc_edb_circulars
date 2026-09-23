"use client";

import { useCallback, useEffect, useState } from "react";
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

type DetailStatus = "loading" | "success" | "not_found" | "error";

export default function DocumentDetailPage() {
  const t = useTranslations("documents");
  const { token, ready } = useAuth();
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const [doc, setDoc] = useState<Doc | null>(null);
  const [status, setStatus] = useState<DetailStatus>("loading");
  const [reloadKey, setReloadKey] = useState(0);
  const [pdfOpening, setPdfOpening] = useState(false);
  const [pdfFailed, setPdfFailed] = useState(false);
  const [blobDownloadUrl, setBlobDownloadUrl] = useState<string | null>(null);

  useEffect(() => {
    if (ready && !token) router.replace("/login");
  }, [ready, token, router]);

  useEffect(() => {
    return () => {
      if (blobDownloadUrl) URL.revokeObjectURL(blobDownloadUrl);
    };
  }, [blobDownloadUrl]);

  useEffect(() => {
    if (!token || !params?.id) return;
    let cancelled = false;
    setStatus("loading");
    setDoc(null);
    setPdfFailed(false);
    setPdfOpening(false);
    fetch(`${API_URL}/api/documents/${params.id}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(async (r) => {
        if (cancelled) return;
        if (r.status === 404) {
          setStatus("not_found");
          return;
        }
        if (!r.ok) throw new Error("detail_failed");
        const data = (await r.json()) as Doc;
        setDoc(data);
        setStatus("success");
      })
      .catch(() => {
        if (cancelled) return;
        setDoc(null);
        setStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, [token, params?.id, reloadKey]);

  const downloadViaBlob = useCallback(
    async (filename: string) => {
      if (!token || !params?.id) return;
      const res = await fetch(fileUrl(params.id), {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error("download_failed");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      setBlobDownloadUrl((prev) => {
        if (prev) URL.revokeObjectURL(prev);
        return url;
      });
      const a = document.createElement("a");
      a.href = url;
      a.download = filename.endsWith(".pdf") ? filename : `${filename || "document"}.pdf`;
      a.rel = "noopener";
      document.body.appendChild(a);
      a.click();
      a.remove();
    },
    [token, params?.id],
  );

  const openPdf = useCallback(async () => {
    if (!token || !doc) return;
    setPdfOpening(true);
    setPdfFailed(false);
    try {
      const res = await fetch(fileUrl(doc.id), {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error("open_failed");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      setBlobDownloadUrl((prev) => {
        if (prev) URL.revokeObjectURL(prev);
        return url;
      });
      const win = window.open(url, "_blank");
      if (!win) {
        setPdfFailed(true);
      }
    } catch {
      setPdfFailed(true);
    } finally {
      setPdfOpening(false);
    }
  }, [token, doc]);

  const handleDownloadFallback = useCallback(async () => {
    if (!doc) return;
    try {
      if (doc.file_url) {
        window.open(doc.file_url, "_blank", "noopener,noreferrer");
        return;
      }
      await downloadViaBlob(doc.title || doc.id);
    } catch {
      setPdfFailed(true);
    }
  }, [doc, downloadViaBlob]);

  if (!token) return null;

  return (
    <div className="page-enter">
      <div className="hero">
        <p>
          <Link href="/documents">{t("title")}</Link>
        </p>
        {status === "loading" ? (
          <span className="skeleton-line hero-title" aria-hidden />
        ) : (
          <h1>
            {status === "success" && doc
              ? doc.title
              : status === "not_found"
                ? t("notFound")
                : status === "error"
                  ? t("detailLoadError")
                  : null}
          </h1>
        )}
      </div>

      {status === "loading" ? (
        <div className="panel">
          <div className="meta" style={{ marginBottom: "1rem" }}>
            <span className="skeleton-line meta" style={{ width: "5rem", display: "inline-block" }} />
            <span className="skeleton-line meta" style={{ width: "8rem", display: "inline-block" }} />
            <span className="skeleton-line meta" style={{ width: "7rem", display: "inline-block" }} />
          </div>
          <span className="skeleton-line title" style={{ width: "90%" }} />
        </div>
      ) : null}

      {status === "not_found" ? (
        <div className="panel state-panel">
          <p>{t("notFound")}</p>
          <div className="state-actions">
            <Link className="btn" href="/documents">
              {t("backToList")}
            </Link>
          </div>
        </div>
      ) : null}

      {status === "error" ? (
        <div className="panel state-panel">
          <p className="error" style={{ marginBottom: "0.5rem" }}>
            {t("detailLoadError")}
          </p>
          <div className="state-actions">
            <button type="button" className="btn" onClick={() => setReloadKey((k) => k + 1)}>
              {t("retry")}
            </button>
            <Link className="btn secondary" href="/documents">
              {t("backToList")}
            </Link>
          </div>
        </div>
      ) : null}

      {status === "success" && doc ? (
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
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem", marginTop: "1rem" }}>
            <button className="btn" type="button" onClick={openPdf} disabled={pdfOpening}>
              {pdfOpening ? t("pdfOpening") : t("open")}
            </button>
            {doc.file_url ? (
              <a className="btn secondary" href={doc.file_url} target="_blank" rel="noreferrer">
                {t("download")}
              </a>
            ) : (
              <button className="btn secondary" type="button" onClick={handleDownloadFallback}>
                {t("download")}
              </button>
            )}
          </div>
          {pdfFailed ? (
            <div style={{ marginTop: "1rem" }}>
              <p className="error" style={{ marginBottom: "0.5rem" }}>
                {t("pdfOpenFail")}
              </p>
              <button className="btn secondary" type="button" onClick={handleDownloadFallback}>
                {t("pdfDownloadFallback")}
              </button>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
