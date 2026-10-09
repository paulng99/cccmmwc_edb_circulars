"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useParams } from "next/navigation";
import { Link, useRouter } from "@/i18n/routing";
import DocumentChatPanel from "@/components/DocumentChatPanel";
import PdfPreview from "@/components/PdfPreview";
import { apiBase, fileUrl, reanalyzeDocuments, type DocumentActivity } from "@/lib/api";
import { agendaTitleLines } from "@/lib/agenda-title";
import { useAuth } from "@/lib/auth";
import { formatHkDate } from "@/lib/date";
import { displaySchoolAction } from "@/lib/school-action";
import { Icon } from "@/components/Icon";
import { langLabel, statusTone } from "@/lib/taxonomy";

type Doc = {
  id: string;
  title: string;
  circular_no?: string | null;
  issued_at?: string | null;
  revised_at?: string | null;
  downloaded_at?: string | null;
  activities?: DocumentActivity[];
  source_id: string;
  source_url: string;
  file_url?: string | null;
  status: string;
  language: string;
  file_size: number;
  chunk_count?: number;
  index_error?: string | null;
  warning?: string | null;
  school_action?: string | null;
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
  const [chatOpen, setChatOpen] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [reanalyzing, setReanalyzing] = useState(false);
  const [reanalyzeConfirmOpen, setReanalyzeConfirmOpen] = useState(false);
  const [reanalyzeNotice, setReanalyzeNotice] = useState<string | null>(null);

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
    if (!detailsOpen && !reanalyzeConfirmOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (reanalyzeConfirmOpen) setReanalyzeConfirmOpen(false);
      else setDetailsOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [detailsOpen, reanalyzeConfirmOpen]);

  useEffect(() => {
    if (!token || !params?.id) return;
    let cancelled = false;
    setStatus("loading");
    setDoc(null);
    setPdfFailed(false);
    setPdfOpening(false);
    fetch(`${apiBase()}/api/documents/${params.id}`, {
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

  const runAiReanalyze = useCallback(async () => {
    if (!token || !doc || reanalyzing) return;
    setReanalyzeConfirmOpen(false);
    setReanalyzing(true);
    setReanalyzeNotice(null);
    try {
      const data = await reanalyzeDocuments(token, [doc.id]);
      const hit = data.results[0];
      if (!hit) {
        setReanalyzeNotice(t("reanalyzeRequestFail"));
        return;
      }
      setDoc((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          school_action: hit.ok && hit.school_action ? hit.school_action : prev.school_action,
          activities: hit.activities ?? prev.activities,
        };
      });
      if (hit.ok) {
        setReanalyzeNotice(t("reanalyzeDone", { ok: 1, fail: 0 }));
      } else {
        setReanalyzeNotice(hit.message || t("reanalyzeFailKeep"));
      }
    } catch {
      setReanalyzeNotice(t("reanalyzeRequestFail"));
    } finally {
      setReanalyzing(false);
    }
  }, [token, doc, reanalyzing, t]);

  if (!token) return null;

  const schoolActionDisplay = displaySchoolAction(doc?.school_action);

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
                {formatHkDate(doc.issued_at)}
              </span>
              {doc.revised_at ? (
                <span className="badge">
                  <Icon name="refresh-cw" />
                  {formatHkDate(doc.revised_at)}
                </span>
              ) : null}
              <span className="badge">
                <Icon name="download" />
                {formatHkDate(doc.downloaded_at)}
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
        <div className={`detail-grid${chatOpen ? " has-chat" : ""}`}>
          <section className="card">
            <div className="card-head">
              <h2>
                <Icon name="file-text" />
                {t("preview")}
              </h2>
              <div className="row-actions">
                <button
                  className="btn sm secondary icon-only"
                  type="button"
                  onClick={() => setDetailsOpen(true)}
                  aria-label={t("details")}
                  title={t("details")}
                >
                  <Icon name="info" />
                </button>
                <button
                  className={`btn sm${chatOpen ? "" : " secondary"}`}
                  type="button"
                  onClick={() => setChatOpen((v) => !v)}
                  aria-pressed={chatOpen}
                >
                  <Icon name="message-square" />
                  {chatOpen ? t("chatClose") : t("ask")}
                </button>
                <button
                  className={`btn sm icon-only${pdfOpening ? " is-loading" : ""}`}
                  type="button"
                  onClick={() => void openPdf()}
                  disabled={pdfOpening}
                  aria-label={pdfOpening ? t("pdfOpening") : t("download")}
                  title={pdfOpening ? t("pdfOpening") : t("download")}
                >
                  {pdfOpening ? <span className="spinner" /> : <Icon name="download" />}
                </button>
                {doc.source_url ? (
                  <a
                    className="btn sm secondary icon-only"
                    href={doc.source_url}
                    target="_blank"
                    rel="noreferrer"
                    aria-label={t("openSource")}
                    title={t("openSource")}
                  >
                    <Icon name="external-link" />
                  </a>
                ) : null}
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
              <div className="doc-original" aria-label={t("originalText")}>
                <PdfPreview fileUrl={pdfApiUrl} token={token} />
              </div>
              <div className="doc-school-action-block">
                <div className="doc-school-action-head">
                  <h3>
                    <Icon name="file-text" />
                    {t("schoolAction")}
                  </h3>
                  <button
                    type="button"
                    className={`btn ghost sm icon-only school-action-ai${reanalyzing ? " is-loading" : ""}`}
                    onClick={() => setReanalyzeConfirmOpen(true)}
                    disabled={reanalyzing}
                    aria-label={reanalyzing ? t("reanalyzeAnalyzing") : t("reanalyzeAi")}
                    title={reanalyzing ? t("reanalyzeAnalyzing") : t("reanalyzeAi")}
                  >
                    {reanalyzing ? <span className="spinner" /> : <Icon name="sparkles" />}
                  </button>
                </div>
                {reanalyzeNotice ? (
                  <div className="alert info reanalyze-notice" role="status" style={{ marginBottom: "0.75rem" }}>
                    <Icon name="info" />
                    <span>{reanalyzeNotice}</span>
                  </div>
                ) : null}
                {schoolActionDisplay ? (
                  <p className="school-action-text">{schoolActionDisplay}</p>
                ) : (
                  <p className="muted">{t("schoolActionEmpty")}</p>
                )}
              </div>
              <div className="doc-activities">
                <h3>
                  <Icon name="calendar" />
                  {t("activities")}
                </h3>
                {(doc.activities || []).length === 0 ? (
                  <p className="muted">{t("activitiesEmpty")}</p>
                ) : (
                  <ul className="activity-blocks">
                    {(doc.activities || []).map((act, idx) => (
                      <li key={`${act.name || "a"}-${act.starts_at || ""}-${act.deadline_at || ""}-${idx}`}>
                        {agendaTitleLines(act.name, doc.title).map((line) => (
                          <strong key={line} className="activity-title">
                            {line}
                          </strong>
                        ))}
                        {act.summary?.trim() ? (
                          <p className="activity-summary">{act.summary.trim()}</p>
                        ) : null}
                        {act.location?.trim() ? (
                          <p className="activity-location">{act.location.trim()}</p>
                        ) : null}
                        <div>
                          <span>{t("activityStartsAt")}</span>
                          <span>{formatHkDate(act.starts_at, t("dateMissing"))}</span>
                        </div>
                        <div>
                          <span>{t("activityDeadlineAt")}</span>
                          <span>{formatHkDate(act.deadline_at, t("dateMissing"))}</span>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          </section>

          {chatOpen && token ? (
            <DocumentChatPanel
              documentId={doc.id}
              documentStatus={doc.status}
              token={token}
              onClose={() => setChatOpen(false)}
            />
          ) : null}

          {reanalyzeConfirmOpen ? (
            <>
              <div className="drawer-backdrop" onClick={() => setReanalyzeConfirmOpen(false)} />
              <div
                className="detail-meta-dialog reanalyze-confirm-dialog"
                role="dialog"
                aria-modal="true"
                aria-labelledby="reanalyze-confirm-title"
              >
                <div className="drawer-head">
                  <h3 id="reanalyze-confirm-title">{t("reanalyzeConfirmTitle")}</h3>
                  <button
                    type="button"
                    className="btn ghost sm icon-only"
                    onClick={() => setReanalyzeConfirmOpen(false)}
                    aria-label={t("reanalyzeCancel")}
                  >
                    <Icon name="x" />
                  </button>
                </div>
                <div className="detail-meta-dialog-body">
                  <p className="reanalyze-confirm-text">{t("reanalyzeConfirm")}</p>
                </div>
                <div className="drawer-foot reanalyze-confirm-actions">
                  <button
                    type="button"
                    className="btn secondary sm"
                    onClick={() => setReanalyzeConfirmOpen(false)}
                  >
                    {t("reanalyzeCancel")}
                  </button>
                  <button
                    type="button"
                    className="btn sm"
                    onClick={() => void runAiReanalyze()}
                    disabled={reanalyzing}
                  >
                    <Icon name="sparkles" />
                    {t("reanalyzeConfirmAction")}
                  </button>
                </div>
              </div>
            </>
          ) : null}

          {detailsOpen ? (
            <>
              <div className="drawer-backdrop" onClick={() => setDetailsOpen(false)} />
              <div
                className="detail-meta-dialog"
                role="dialog"
                aria-modal="true"
                aria-labelledby="doc-details-title"
              >
                <div className="drawer-head">
                  <h3 id="doc-details-title">{t("details")}</h3>
                  <button
                    type="button"
                    className="btn ghost sm icon-only"
                    onClick={() => setDetailsOpen(false)}
                    aria-label={t("detailsClose")}
                  >
                    <Icon name="x" />
                  </button>
                </div>
                <div className="detail-meta-dialog-body">
                  <dl className="meta-list">
                    <div>
                      <dt>{t("circularNo")}</dt>
                      <dd>{doc.circular_no || "—"}</dd>
                    </div>
                    <div>
                      <dt>{t("issuedAt")}</dt>
                      <dd>{formatHkDate(doc.issued_at, t("dateMissing"))}</dd>
                    </div>
                    <div>
                      <dt>{t("revisedAt")}</dt>
                      <dd>{formatHkDate(doc.revised_at, t("dateMissing"))}</dd>
                    </div>
                    <div>
                      <dt>{t("downloadedAt")}</dt>
                      <dd>{formatHkDate(doc.downloaded_at, t("dateMissing"))}</dd>
                    </div>
                    <div className="meta-activities">
                      <dt>{t("activities")}</dt>
                      <dd>
                        {(doc.activities || []).length === 0 ? (
                          <span>{t("activitiesEmpty")}</span>
                        ) : (
                          <ul className="activity-blocks">
                            {(doc.activities || []).map((act, idx) => (
                              <li key={`${act.name || "a"}-${act.starts_at || ""}-${act.deadline_at || ""}-${idx}`}>
                                {agendaTitleLines(act.name, doc.title).map((line) => (
                                  <strong key={line} className="activity-title">
                                    {line}
                                  </strong>
                                ))}
                                {act.summary?.trim() ? (
                                  <p className="activity-summary">{act.summary.trim()}</p>
                                ) : null}
                                {act.location?.trim() ? (
                                  <p className="activity-location">{act.location.trim()}</p>
                                ) : null}
                                <div>
                                  <span>{t("activityStartsAt")}</span>
                                  <span>{formatHkDate(act.starts_at, t("dateMissing"))}</span>
                                </div>
                                <div>
                                  <span>{t("activityDeadlineAt")}</span>
                                  <span>{formatHkDate(act.deadline_at, t("dateMissing"))}</span>
                                </div>
                              </li>
                            ))}
                          </ul>
                        )}
                      </dd>
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
                      <dt>{t("chunks")}</dt>
                      <dd>{doc.chunk_count ?? 0}</dd>
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
                    {doc.source_url ? (
                      <div>
                        <dt>{t("openSource")}</dt>
                        <dd>
                          <a href={doc.source_url} target="_blank" rel="noreferrer">
                            {doc.source_url}
                          </a>
                        </dd>
                      </div>
                    ) : null}
                  </dl>
                </div>
              </div>
            </>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
