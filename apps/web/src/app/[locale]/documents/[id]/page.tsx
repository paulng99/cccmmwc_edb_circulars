"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useParams } from "next/navigation";
import { Link, useRouter } from "@/i18n/routing";
import PdfPreview from "@/components/PdfPreview";
import { API_URL, fileUrl } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Icon } from "@/components/Icon";
import { langLabel, statusTone } from "@/lib/taxonomy";

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

function formatBytes(n: number) {
  if (!n || n <= 0) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
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

  const pdfApiUrl = useMemo(() => (params?.id ? fileUrl(params.id) : ""), [params?.id]);

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

  const statusLabelKey: Record<string, string> = {
    ready: "statusReady",
    indexing: "statusIndexing",
    stored: "statusStored",
    failed: "statusFailed",
  };

  return (
    <div className="page">
      <header className="page-head">
        <div style={{ minWidth: 0 }}>
          <Link href="/documents" className="page-back">
            <Icon name="arrow-left" />
            {t("backToList")}
          </Link>
          {status === "loading" ? (
            <span className="skeleton" style={{ height: "1.6rem", width: "min(70%, 28rem)" }} aria-hidden />
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
          {status === "success" && doc ? (
            <div className="doc-meta" style={{ marginTop: "0.6rem" }}>
              <span className={`badge ${statusTone(doc.status)}`}>
                {doc.status === "ready" ? <Icon name="check-circle" /> : null}
                {statusLabelKey[doc.status] ? t(statusLabelKey[doc.status]) : doc.status}
              </span>
              {doc.circular_no ? (
                <span className="badge">
                  <Icon name="hash" />
                  {doc.circular_no}
                </span>
              ) : null}
              <span className="badge">
                <Icon name="calendar" />
                {doc.issued_at || "—"}
              </span>
              <span className="badge">
                <Icon name="globe" />
                {langLabel(doc.language, t)}
              </span>
            </div>
          ) : null}
        </div>
      </header>

      {status === "loading" ? (
        <div className="detail-grid" aria-busy="true">
          <div className="card card-pad">
            <span className="skeleton" style={{ height: 420 }} />
          </div>
          <div className="card card-pad">
            <span className="skeleton" style={{ height: "0.9rem", width: "70%", marginBottom: "0.8rem" }} />
            <span className="skeleton" style={{ height: "0.9rem", width: "55%", marginBottom: "0.8rem" }} />
            <span className="skeleton" style={{ height: "0.9rem", width: "62%" }} />
          </div>
        </div>
      ) : null}

      {status === "not_found" ? (
        <div className="card empty">
          <div className="empty-icon">
            <Icon name="file-search" />
          </div>
          <h3>{t("notFound")}</h3>
          <div className="empty-actions">
            <Link className="btn" href="/documents">
              <Icon name="arrow-left" />
              {t("backToList")}
            </Link>
          </div>
        </div>
      ) : null}

      {status === "error" ? (
        <div className="card empty">
          <div className="empty-icon danger">
            <Icon name="alert-triangle" />
          </div>
          <h3>{t("detailLoadError")}</h3>
          <div className="empty-actions">
            <button type="button" className="btn" onClick={() => setReloadKey((k) => k + 1)}>
              <Icon name="refresh-cw" />
              {t("retry")}
            </button>
            <Link className="btn secondary" href="/documents">
              {t("backToList")}
            </Link>
          </div>
        </div>
      ) : null}

      {status === "success" && doc ? (
        <div className="detail-grid">
          <section className="card">
            <div className="card-head">
              <h2>
                <Icon name="file-text" />
                {t("preview")}
              </h2>
              <div className="row-actions">
                <button
                  className={`btn sm${pdfOpening ? " is-loading" : ""}`}
                  type="button"
                  onClick={() => void openPdf()}
                  disabled={pdfOpening}
                >
                  {pdfOpening ? <span className="spinner" /> : <Icon name="download" />}
                  {pdfOpening ? t("pdfOpening") : t("download")}
                </button>
              </div>
            </div>
            <div className="card-pad">
              {doc.status === "failed" && doc.index_error ? (
                <div className="alert danger" style={{ marginBottom: "1rem" }}>
                  <Icon name="alert-circle" />
                  <span>
                    <strong>{t("indexError")}:</strong> {doc.index_error}
                  </span>
                </div>
              ) : null}
              {doc.warning ? (
                <div className="alert warning" style={{ marginBottom: "1rem" }}>
                  <Icon name="alert-triangle" />
                  <span>{doc.warning}</span>
                </div>
              ) : null}
              {pdfFailed ? (
                <div className="alert danger" style={{ marginBottom: "1rem", alignItems: "center" }}>
                  <Icon name="alert-circle" />
                  <span style={{ flex: 1 }}>{t("pdfOpenFail")}</span>
                  <button className="btn secondary sm" type="button" onClick={() => void handleDownloadFallback()}>
                    {t("pdfDownloadFallback")}
                  </button>
                </div>
              ) : null}
              <PdfPreview fileUrl={pdfApiUrl} token={token} />
            </div>
          </section>

          <aside className="detail-side">
            <section className="card">
              <div className="card-head">
                <h2>
                  <Icon name="info" />
                  {t("details")}
                </h2>
              </div>
              <div className="card-pad" style={{ paddingTop: "0.35rem", paddingBottom: "0.5rem" }}>
                <dl className="meta-list">
                  <div>
                    <dt>{t("circularNo")}</dt>
                    <dd>{doc.circular_no || "—"}</dd>
                  </div>
                  <div>
                    <dt>{t("issuedAt")}</dt>
                    <dd>{doc.issued_at || "—"}</dd>
                  </div>
                  <div>
                    <dt>{t("language")}</dt>
                    <dd>{langLabel(doc.language, t)}</dd>
                  </div>
                  <div>
                    <dt>{t("status")}</dt>
                    <dd>{statusLabelKey[doc.status] ? t(statusLabelKey[doc.status]) : doc.status}</dd>
                  </div>
                  <div>
                    <dt>{t("fileSize")}</dt>
                    <dd>{formatBytes(doc.file_size)}</dd>
                  </div>
                  <div>
                    <dt>{t("source")}</dt>
                    <dd>
                      <code>{doc.source_id}</code>
                    </dd>
                  </div>
                </dl>
              </div>
            </section>

            <section className="card card-pad">
              <div className="detail-actions">
                <button
                  className={`btn${pdfOpening ? " is-loading" : ""}`}
                  type="button"
                  onClick={() => void openPdf()}
                  disabled={pdfOpening}
                >
                  {pdfOpening ? <span className="spinner" /> : <Icon name="download" />}
                  {pdfOpening ? t("pdfOpening") : t("download")}
                </button>
                {doc.file_url ? (
                  <a className="btn secondary" href={doc.file_url} target="_blank" rel="noreferrer">
                    <Icon name="external-link" />
                    {t("openSource")}
                  </a>
                ) : null}
              </div>
              <p className="detail-source" style={{ marginTop: "0.85rem" }}>
                <a href={doc.source_url} target="_blank" rel="noreferrer">
                  {doc.source_url}
                </a>
              </p>
            </section>
          </aside>
        </div>
      ) : null}
    </div>
  );
}
