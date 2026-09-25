"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useRouter, Link } from "@/i18n/routing";
import { ingestStatus, listDocuments, stopCrawl, triggerClassify, triggerCrawl, triggerReindex } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatHkDateTime } from "@/lib/date";

type CrawlEvent = {
  event_type: string;
  url?: string | null;
  title?: string | null;
  created_at?: string | null;
  source_id?: string | null;
};

type Run = {
  id: string;
  source_id: string;
  job_type?: string;
  status: string;
  discovered: number;
  downloaded: number;
  skipped?: number;
  failed: number;
  progress_message?: string | null;
  error_message?: string | null;
  started_at: string | null;
  finished_at?: string | null;
  current?: CrawlEvent | null;
  recent_events?: CrawlEvent[];
  cancel_requested?: boolean;
};

type FailedDoc = {
  id: string;
  title: string;
  source_id: string;
  file_url?: string | null;
  status: string;
  index_error?: string | null;
};

type IngestData = {
  documents: {
    total: number;
    ready: number;
    indexing: number;
    stored?: number;
    failed: number;
  };
  active?: boolean;
  sources: Array<{
    id: string;
    enabled: boolean;
    last_crawl_at: string | null;
    name_en: string;
    name_zh_hk: string;
  }>;
  recent_runs: Run[];
};

const EVENT_I18N: Record<string, string> = {
  discovering: "eventDiscovering",
  page: "eventPage",
  download_start: "eventDownloadStart",
  download_ok: "eventDownloadOk",
  download_skip: "eventDownloadSkip",
  download_fail: "eventDownloadFail",
  index_start: "eventIndexStart",
  index_ok: "eventIndexOk",
  index_fail: "eventIndexFail",
  done: "eventDone",
  cancelled: "eventCancelled",
};

const REINDEX_SOURCE_ID = "system_reindex";

function truncateUrl(url: string, max = 72) {
  if (url.length <= max) return url;
  return `${url.slice(0, max - 1)}…`;
}

export default function StatusPage() {
  const t = useTranslations("status");
  const locale = useLocale();
  const { token, ready } = useAuth();
  const router = useRouter();
  const [data, setData] = useState<IngestData | null>(null);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [jobKind, setJobKind] = useState<"crawl" | "reindex" | null>(null);
  const [stopping, setStopping] = useState(false);
  const [error, setError] = useState("");
  const [showFailed, setShowFailed] = useState(false);
  const [failedDocs, setFailedDocs] = useState<FailedDoc[]>([]);
  const [failedLoading, setFailedLoading] = useState(false);
  const [failedError, setFailedError] = useState("");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const actionLock = useRef(false);

  const refresh = useCallback(async (tok: string) => {
    const s = (await ingestStatus(tok)) as IngestData;
    setData(s);
    const runningRuns = s.recent_runs.filter((r) => r.status === "running");
    const running = Boolean(s.active) || runningRuns.length > 0;
    setBusy(running);
    let kind: "crawl" | "reindex" | null = null;
    if (!running) {
      setStopping(false);
      setJobKind(null);
    } else {
      const isReindex = runningRuns.some(
        (r) => r.job_type === "reindex" || r.source_id === REINDEX_SOURCE_ID,
      );
      kind = isReindex ? "reindex" : "crawl";
      setJobKind(kind);
      if (runningRuns.some((r) => r.cancel_requested)) setStopping(true);
    }
    return { running, kind };
  }, []);

  const stopPoll = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const startPoll = useCallback(
    (tok: string, kind: "crawl" | "reindex") => {
      stopPoll();
      pollRef.current = setInterval(() => {
        refresh(tok)
          .then(({ running }) => {
            if (!running) {
              stopPoll();
              setMsg((prev) => {
                if (prev === t("stopping")) return t("cancelled");
                return kind === "reindex" ? t("reindexDone") : t("crawlDone");
              });
              setStopping(false);
              setJobKind(null);
            }
          })
          .catch(() => undefined);
      }, 2000);
    },
    [refresh, stopPoll, t],
  );

  useEffect(() => {
    if (ready && !token) router.replace("/login");
  }, [ready, token, router]);

  useEffect(() => {
    if (!token) return;
    refresh(token)
      .then(({ running, kind }) => {
        if (running && kind) startPoll(token, kind);
      })
      .catch(() => setData(null));
    return () => stopPoll();
  }, [token, refresh, startPoll, stopPoll]);

  async function onCrawl(sourceId?: string) {
    if (!token || busy || actionLock.current) return;
    actionLock.current = true;
    setError("");
    setStopping(false);
    setJobKind("crawl");
    setMsg(t("crawling"));
    setBusy(true);
    try {
      await triggerCrawl(token, sourceId);
      await refresh(token);
      startPoll(token, "crawl");
    } catch (e) {
      if (e instanceof Error && e.message === "busy") {
        setError(t("reindexBusy"));
        const status = await refresh(token).catch(() => null);
        if (status?.running && status.kind) {
          setMsg(status.kind === "reindex" ? t("reindexing") : t("crawling"));
          startPoll(token, status.kind);
        } else {
          setBusy(false);
          setJobKind(null);
          setMsg("");
        }
      } else {
        setBusy(false);
        setJobKind(null);
        setError(t("crawlError"));
        setMsg("");
      }
    } finally {
      actionLock.current = false;
    }
  }

  async function onReindex() {
    if (!token || busy) return;
    setError("");
    setStopping(false);
    setJobKind("reindex");
    setMsg(t("reindexing"));
    setBusy(true);
    try {
      await triggerReindex(token, "all");
      await refresh(token);
      startPoll(token, "reindex");
    } catch (e) {
      setBusy(false);
      setJobKind(null);
      setError(e instanceof Error && e.message === "busy" ? t("reindexBusy") : t("reindexError"));
      setMsg("");
    }
  }

  async function onClassify() {
    if (!token || busy) return;
    setError("");
    setMsg(t("classifying"));
    try {
      await triggerClassify(token, false);
      setMsg(t("classifyStarted"));
    } catch {
      setError(t("classifyError"));
      setMsg("");
    }
  }

  async function onStop() {
    if (!token || !busy || stopping) return;
    setError("");
    setStopping(true);
    setMsg(t("stopping"));
    try {
      const res = await stopCrawl(token);
      if (res.stopped === 0) {
        setMsg(t("stopNone"));
        setStopping(false);
      }
      await refresh(token);
      startPoll(token, jobKind || "crawl");
    } catch {
      setStopping(false);
      setError(t("stopError"));
    }
  }

  async function onShowFailed() {
    if (!token) return;
    const next = !showFailed;
    setShowFailed(next);
    if (!next) return;
    setFailedLoading(true);
    setFailedError("");
    try {
      const res = await listDocuments(token, {
        status: "failed",
        grouped: false,
        page: 1,
        page_size: 100,
      });
      setFailedDocs((res.items || []) as FailedDoc[]);
    } catch {
      setFailedDocs([]);
      setFailedError(t("failedLoadError"));
    } finally {
      setFailedLoading(false);
    }
  }

  if (!token) return null;

  const activeRuns = data?.recent_runs.filter((r) => r.status === "running") || [];
  const sourceName = (id: string) => {
    if (id === REINDEX_SOURCE_ID) return t("reindexJob");
    const s = data?.sources.find((x) => x.id === id);
    if (!s) return id;
    return locale.startsWith("zh") ? s.name_zh_hk || s.name_en : s.name_en;
  };

  const eventLabel = (type: string) => {
    const key = EVENT_I18N[type];
    return key ? t(key as "eventDiscovering") : type;
  };

  const currentLabel = (ev: CrawlEvent) => ev.title || (ev.url ? truncateUrl(ev.url) : "—");

  const progressLabel = (r: Run) => {
    const isReindex = r.job_type === "reindex" || r.source_id === REINDEX_SOURCE_ID;
    return t(isReindex ? "progressCountsIndex" : "progressCounts", {
      discovered: r.discovered,
      downloaded: r.downloaded,
      skipped: r.skipped ?? 0,
      failed: r.failed,
    });
  };

  return (
    <div className="page-enter page-stack">
      <header className="page-header">
        <h1>{t("title")}</h1>
        <p className="page-subtitle">{t("subtitle")}</p>
      </header>
      <div className="action-toolbar">
        <button className={`btn${busy && jobKind === "crawl" ? " is-loading" : ""}`} type="button" disabled={busy} onClick={() => onCrawl()}>
          {busy && jobKind === "crawl" ? t("crawlingBtn") : t("crawl")}
        </button>
        <button className={`btn${busy && jobKind === "reindex" ? " is-loading" : ""}`} type="button" disabled={busy} onClick={() => onReindex()}>
          {busy && jobKind === "reindex" ? t("reindexingBtn") : t("reindex")}
        </button>
        <button className="btn secondary" type="button" disabled={busy} onClick={() => onClassify()}>
          {t("classify")}
        </button>
        <button className="btn secondary" type="button" disabled={!busy || stopping} onClick={() => onStop()}>
          {stopping ? t("stopping") : t("stop")}
        </button>
        {msg ? <span className="hint">{msg}</span> : null}
        {error ? <span className="error">{error}</span> : null}
      </div>

      {busy || activeRuns.length > 0 ? (
        <div className="panel" style={{ marginBottom: "1rem", borderColor: "var(--blue-500)" }}>
          <h2 style={{ marginTop: 0 }}>{t("liveProgress")}</h2>
          {activeRuns.length === 0 ? (
            <p className="hint">{t("starting")}</p>
          ) : (
            <div className="list">
              {activeRuns.map((r) => {
                const pct =
                  r.discovered > 0
                    ? Math.min(
                        100,
                        Math.round(
                          ((r.downloaded + (r.skipped ?? 0) + r.failed) / r.discovered) * 100,
                        ),
                      )
                    : 0;
                return (
                  <div key={r.id} className="doc-row run-card">
                    <div style={{ width: "100%" }}>
                      <h3>
                        {sourceName(r.source_id)}{" "}
                        <span className="chip">{r.status}</span>
                        {r.cancel_requested ? <span className="chip">{t("eventCancelled")}</span> : null}
                      </h3>
                      <div className="meta">
                        <span>{progressLabel(r)}</span>
                        <span>{formatHkDateTime(r.started_at)}</span>
                      </div>
                      <div className="progress-track">
                        <div className="progress-fill" style={{ width: `${pct}%` }} />
                      </div>
                      <div className="hint" style={{ marginTop: "0.35rem" }}>
                        {r.progress_message || (r.discovered === 0 ? t("discovering") : `${pct}%`)}
                      </div>

                      {r.current ? (
                        <div style={{ marginTop: "0.85rem" }}>
                          <strong style={{ fontSize: "0.9rem" }}>{t("currentFile")}</strong>
                          <div className="meta" style={{ marginTop: "0.25rem" }}>
                            <span className="chip">{eventLabel(r.current.event_type)}</span>
                            <span title={r.current.url || undefined}>{currentLabel(r.current)}</span>
                          </div>
                        </div>
                      ) : null}

                      {r.recent_events && r.recent_events.length > 0 ? (
                        <div style={{ marginTop: "0.85rem" }}>
                          <strong style={{ fontSize: "0.9rem" }}>{t("recentActivity")}</strong>
                          <div
                            className="list"
                            style={{
                              marginTop: "0.4rem",
                              maxHeight: 220,
                              overflowY: "auto",
                              borderTop: "1px solid rgba(37,99,212,0.12)",
                              paddingTop: "0.35rem",
                            }}
                          >
                            {r.recent_events.map((ev, idx) => (
                              <div
                                key={`${r.id}-${idx}-${ev.created_at}-${ev.event_type}`}
                                className="meta"
                                style={{ padding: "0.25rem 0", gap: "0.5rem", flexWrap: "wrap" }}
                              >
                                <span>{formatHkDateTime(ev.created_at)}</span>
                                <span className="chip">{eventLabel(ev.event_type)}</span>
                                <span title={ev.url || undefined}>{currentLabel(ev)}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      ) : null}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      ) : null}

      {data ? (
        <>
          <div className="grid-stats" style={{ marginBottom: "1rem" }}>
            <div className="stat">
              <strong>{data.documents.total}</strong>
              <span>{t("total")}</span>
            </div>
            <div className="stat">
              <strong>{data.documents.ready}</strong>
              <span>{t("ready")}</span>
            </div>
            <div className="stat">
              <strong>{data.documents.indexing}</strong>
              <span>{t("indexing")}</span>
            </div>
            <button
              type="button"
              className="stat"
              onClick={() => void onShowFailed()}
              title={t("failedHint")}
              style={{
                cursor: data.documents.failed > 0 ? "pointer" : "default",
                borderColor: showFailed ? "var(--blue-500)" : undefined,
                textAlign: "left",
              }}
              disabled={data.documents.failed === 0}
            >
              <strong>{data.documents.failed}</strong>
              <span>{t("failed")}</span>
            </button>
          </div>

          {showFailed ? (
            <div className="panel" style={{ marginBottom: "1rem", borderColor: "rgba(185, 28, 28, 0.35)" }}>
              <h2 style={{ marginTop: 0 }}>{t("failedListTitle")}</h2>
              <p className="hint" style={{ marginBottom: "0.75rem" }}>
                {t("failedTypeHint")}
              </p>
              {failedLoading ? <p className="hint">…</p> : null}
              {failedError ? <p className="error">{failedError}</p> : null}
              {!failedLoading && !failedError && failedDocs.length === 0 ? (
                <p className="hint">{t("failedEmpty")}</p>
              ) : null}
              {!failedLoading && failedDocs.length > 0 ? (
                <div className="list" style={{ maxHeight: 360, overflowY: "auto" }}>
                  {failedDocs.map((d) => (
                    <div key={d.id} className="doc-row run-card">
                      <div style={{ width: "100%" }}>
                        <h3>
                          <Link href={`/documents/${d.id}`}>{d.title}</Link>
                        </h3>
                        <div className="meta">
                          <span className="chip">{d.source_id}</span>
                          {d.file_url ? (
                            <span title={d.file_url}>{truncateUrl(d.file_url)}</span>
                          ) : null}
                        </div>
                        <p className="error" style={{ marginTop: "0.4rem", fontSize: "0.85rem" }}>
                          {t("failedReason")}: {d.index_error || "—"}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}

          <div className="panel" style={{ marginBottom: "1rem" }}>
            <h2 style={{ marginTop: 0 }}>{t("sources")}</h2>
            <div className="list">
              {data.sources.map((s) => (
                <div key={s.id} className="doc-row run-card">
                  <div>
                    <h3>{locale.startsWith("zh") ? s.name_zh_hk || s.name_en : s.name_en}</h3>
                    <div className="meta">
                      <span className="chip">{s.id}</span>
                      <span>{s.enabled ? "on" : "off"}</span>
                      <span>{formatHkDateTime(s.last_crawl_at)}</span>
                    </div>
                  </div>
                  <button
                    className="btn secondary"
                    type="button"
                    disabled={busy || !s.enabled}
                    onClick={() => onCrawl(s.id)}
                  >
                    {t("crawl")}
                  </button>
                </div>
              ))}
            </div>
          </div>
          <div className="panel">
            <h2 style={{ marginTop: 0 }}>{t("recentRuns")}</h2>
            <div className="list">
              {data.recent_runs.map((r) => (
                <div key={r.id} className="doc-row run-card">
                  <div>
                    <h3>
                      {sourceName(r.source_id)}{" "}
                      <span className="chip">{r.status}</span>
                    </h3>
                    <div className="meta">
                      <span>{progressLabel(r)}</span>
                      <span>{formatHkDateTime(r.started_at)}</span>
                    </div>
                    {r.progress_message && r.status !== "running" ? (
                      <p className="hint" style={{ marginTop: "0.35rem" }}>
                        {r.progress_message}
                      </p>
                    ) : null}
                    {r.error_message ? (
                      <p className="error" style={{ marginTop: "0.4rem", fontSize: "0.85rem" }}>
                        {r.error_message.slice(0, 240)}
                      </p>
                    ) : null}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </>
      ) : (
        <div className="panel">…</div>
      )}
    </div>
  );
}
