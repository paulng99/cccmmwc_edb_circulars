"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useParams } from "next/navigation";
import { Link, useRouter } from "@/i18n/routing";
import PdfPreview from "@/components/PdfPreview";
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
  index_error?: string | null;
  warning?: string | null;
};

type DetailStatus = "loading" | "success" | "not_found" | "error";

function pdfFilename(doc: Doc) {
  const fromUrl = doc.file_url?.split("/").pop();
  if (fromUrl && fromUrl.toLowerCase().endsWith(".pdf")) return fromUrl;
  const circ = (doc.circular_no || "").replaceAll("/", "-");
  return `${circ || doc.title || doc.id}.pdf`;
}

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

  const pdfApiUrl = useMemo(
    () => (params?.id ? fileUrl(params.id) : ""),
    [params?.id],
  );

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
      await downloadViaBlob(pdfFilename(doc));
    } catch {
      setPdfFailed(true);
    } finally {
      setPdfOpening(false);
    }
  }, [token, doc, downloadViaBlob]);

  const handleDownloadFallback = useCallback(async () => {
    if (!doc) return;
    try {
      await downloadViaBlob(pdfFilename(doc));
    } catch {
      if (doc.file_url) {
        window.open(doc.file_url, "_blank", "noopener,noreferrer");
        return;
      }
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
          {doc.status === "failed" && doc.index_error ? (
            <p className="error" style={{ marginBottom: "1rem" }}>
              {t("indexError")}: {doc.index_error}
            </p>
          ) : null}
          {doc.warning ? (
            <p className="hint" style={{ marginBottom: "1rem" }}>
              {doc.warning}
            </p>
          ) : null}
          <p>
            <a href={doc.source_url} target="_blank" rel="noreferrer">
              {doc.source_url}
            </a>
          </p>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem", marginTop: "1rem" }}>
            <button className="btn" type="button" onClick={() => void openPdf()} disabled={pdfOpening}>
              {pdfOpening ? t("pdfOpening") : t("download")}
            </button>
            {doc.file_url ? (
              <a className="btn secondary" href={doc.file_url} target="_blank" rel="noreferrer">
                {t("openSource")}
              </a>
            ) : null}
          </div>
          {pdfFailed ? (
            <div style={{ marginTop: "1rem" }}>
              <p className="error" style={{ marginBottom: "0.5rem" }}>
                {t("pdfOpenFail")}
              </p>
              <button className="btn secondary" type="button" onClick={() => void handleDownloadFallback()}>
                {t("pdfDownloadFallback")}
              </button>
            </div>
          ) : null}
          <div style={{ marginTop: "1.25rem" }}>
            <h2 style={{ fontSize: "1.05rem", margin: "0 0 0.75rem" }}>{t("preview")}</h2>
            <PdfPreview fileUrl={pdfApiUrl} token={token} />
          </div>
        </div>
      ) : null}
    </div>
  );
}
