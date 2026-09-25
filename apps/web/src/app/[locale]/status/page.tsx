"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useRouter, Link } from "@/i18n/routing";
import { ingestStatus, listDocuments, stopCrawl, triggerClassify, triggerCrawl, triggerReindex } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatHkDateTime } from "@/lib/date";
import { Icon } from "@/components/Icon";
import { statusTone } from "@/lib/taxonomy";

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

const EVENT_TONE: Record<string, string> = {
  download_ok: "green",
  index_ok: "green",
  done: "green",
  download_fail: "red",
  index_fail: "red",
  download_skip: "slate",
  cancelled: "slate",
  download_start: "blue",
  index_start: "amber",
  discovering: "blue",
  page: "blue",
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
  const [loadFailed, setLoadFailed] = useState(false);
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
    setLoadFailed(false);
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
      .catch(() => {
        setData(null);
        setLoadFailed(true);
      });
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
  const historyRuns = data?.recent_runs.filter((r) => r.status !== "running") || [];

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

  const runStatusLabel = (status: string) => {
    const map: Record<string, string> = {
      running: "runRunning",
      success: "runSuccess",
      done: "runSuccess",
      failed: "runFailed",
      cancelled: "runCancelled",
    };
    const key = map[status];
    return key ? t(key as "runRunning") : status;
  };

  const currentLabel = (ev: CrawlEvent) => ev.title || (ev.url ? truncateUrl(ev.url) : "—");

  const isReindexRun = (r: Run) => r.job_type === "reindex" || r.source_id === REINDEX_SOURCE_ID;

  const runCounts = (r: Run) =>
    isReindexRun(r) ? (
      <div className="run-counts">
        <span>
          {t("countTotal")} <b>{r.discovered}</b>
        </span>
        <span>
          {t("countIndexed")} <b>{r.downloaded}</b>
        </span>
        <span>
          {t("countFailed")} <b>{r.failed}</b>
        </span>
      </div>
    ) : (
      <div className="run-counts">
        <span>
          {t("countFound")} <b>{r.discovered}</b>
        </span>
        <span>
          {t("countNew")} <b>{r.downloaded}</b>
        </span>
        <span>
          {t("countSkipped")} <b>{r.skipped ?? 0}</b>
        </span>
        <span>
          {t("countFailed")} <b>{r.failed}</b>
        </span>
      </div>
    );

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>{t("title")}</h1>
          <p className="page-subtitle">{t("subtitle")}</p>
        </div>
        <div className="page-actions">
          <button
            className={`btn${busy && jobKind === "crawl" ? " is-loading" : ""}`}
            type="button"
            disabled={busy}
            onClick={() => onCrawl()}
            title={t("crawl")}
          >
            {busy && jobKind === "crawl" ? <span className="spinner" /> : <Icon name="play" />}
            <span>{busy && jobKind === "crawl" ? t("crawlingBtn") : t("crawl")}</span>
          </button>
          <button
            className={`btn secondary${busy && jobKind === "reindex" ? " is-loading" : ""}`}
            type="button"
            disabled={busy}
            onClick={() => onReindex()}
            title={t("reindex")}
          >
            {busy && jobKind === "reindex" ? <span className="spinner" /> : <Icon name="refresh-cw" />}
            <span>{busy && jobKind === "reindex" ? t("reindexingBtn") : t("reindex")}</span>
          </button>
          <button className="btn secondary" type="button" disabled={busy} onClick={() => onClassify()} title={t("classify")}>
            <Icon name="tags" />
            <span>{t("classify")}</span>
          </button>
          {busy ? (
            <button className="btn danger" type="button" disabled={stopping} onClick={() => onStop()} title={t("stop")}>
              <Icon name="square" />
              <span>{stopping ? t("stoppingShort") : t("stop")}</span>
            </button>
          ) : null}
        </div>
      </header>

      {error ? (
        <div className="alert danger" role="alert">
          <Icon name="alert-circle" />
          <span>{error}</span>
        </div>
      ) : msg ? (
        <div className={`alert ${busy ? "info" : "success"}`} role="status">
          {busy ? <span className="spinner" /> : <Icon name="check-circle" />}
          <span>{msg}</span>
        </div>
      ) : null}

      {busy || activeRuns.length > 0 ? (
        <section className="card live-card">
          <div className="card-head">
            <h2>
              <span className="dot blue pulse" aria-hidden />
              {t("liveProgress")}
            </h2>
          </div>
          <div className="card-pad">
            {activeRuns.length === 0 ? (
              <p className="typing">
                <span className="typing-dots" aria-hidden>
                  <i />
                  <i />
                  <i />
                </span>
                {t("starting")}
              </p>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
                {activeRuns.map((r) => {
                  const pct =
                    r.discovered > 0
                      ? Math.min(100, Math.round(((r.downloaded + (r.skipped ?? 0) + r.failed) / r.discovered) * 100))
                      : 0;
                  return (
                    <div key={r.id} className="run-live">
                      <div className="run-live-head">
                        <h3>
                          {sourceName(r.source_id)}
                          <span className="badge amber">{runStatusLabel(r.status)}</span>
                          {r.cancel_requested ? <span className="badge">{t("eventCancelled")}</span> : null}
                        </h3>
                        <span className="muted tnum" style={{ fontSize: "0.82rem" }}>
                          {formatHkDateTime(r.started_at)}
                        </span>
                      </div>
                      {runCounts(r)}
                      <div>
                        <div className="progress-track" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
                          <div className="progress-fill" style={{ width: `${pct}%` }} />
                        </div>
                        <div className="muted" style={{ marginTop: "0.4rem", fontSize: "0.8rem", display: "flex", justifyContent: "space-between", gap: "1rem" }}>
                          <span>{r.progress_message || (r.discovered === 0 ? t("discovering") : "")}</span>
                          <span className="tnum">{pct}%</span>
                        </div>
                      </div>

                      {r.current ? (
                        <div className="activity-row" style={{ gridTemplateColumns: "auto auto minmax(0,1fr)" }}>
                          <span className="label">{t("currentFile")}</span>
                          <span className={`badge ${EVENT_TONE[r.current.event_type] || "slate"}`}>{eventLabel(r.current.event_type)}</span>
                          <span className="what" title={r.current.url || undefined}>
                            {currentLabel(r.current)}
                          </span>
                        </div>
                      ) : null}

                      {r.recent_events && r.recent_events.length > 0 ? (
                        <div>
                          <span className="label">{t("recentActivity")}</span>
                          <div className="activity">
                            {r.recent_events.map((ev, idx) => (
                              <div key={`${r.id}-${idx}-${ev.created_at}-${ev.event_type}`} className="activity-row">
                                <time>{formatHkDateTime(ev.created_at)}</time>
                                <span className={`badge ${EVENT_TONE[ev.event_type] || "slate"}`}>{eventLabel(ev.event_type)}</span>
                                <span className="what" title={ev.url || undefined}>
                                  {currentLabel(ev)}
                                </span>
                              </div>
                            ))}
                          </div>
                        </div>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </section>
      ) : null}

      {loadFailed ? (
        <div className="card empty">
          <div className="empty-icon danger">
            <Icon name="alert-triangle" />
          </div>
          <h3>{t("loadError")}</h3>
          <div className="empty-actions">
            <button type="button" className="btn" onClick={() => refresh(token).catch(() => setLoadFailed(true))}>
              <Icon name="refresh-cw" />
              {t("retry")}
            </button>
          </div>
        </div>
      ) : null}

      {!data && !loadFailed ? (
        <div className="kpi-grid" aria-busy="true">
          {Array.from({ length: 4 }, (_, i) => (
            <div key={i} className="card kpi">
              <span className="skeleton" style={{ width: 42, height: 42, borderRadius: 12 }} />
              <div className="kpi-text" style={{ flex: 1 }}>
                <span className="skeleton" style={{ height: "1.4rem", width: "40%", marginBottom: "0.4rem" }} />
                <span className="skeleton" style={{ height: "0.75rem", width: "60%" }} />
              </div>
            </div>
          ))}
        </div>
      ) : null}

      {data ? (
        <>
          <div className="kpi-grid">
            <div className="card kpi">
              <span className="kpi-icon blue">
                <Icon name="file-text" />
              </span>
              <div className="kpi-text">
                <strong>{data.documents.total}</strong>
                <span>{t("total")}</span>
              </div>
            </div>
            <div className="card kpi">
              <span className="kpi-icon green">
                <Icon name="check-circle" />
              </span>
              <div className="kpi-text">
                <strong>{data.documents.ready}</strong>
                <span>{t("ready")}</span>
              </div>
            </div>
            <div className="card kpi">
              <span className="kpi-icon amber">
                <Icon name="clock" />
              </span>
              <div className="kpi-text">
                <strong>{data.documents.indexing}</strong>
                <span>{t("indexing")}</span>
              </div>
            </div>
            <button
              type="button"
              className={`card kpi${showFailed ? " selected" : ""}`}
              onClick={() => void onShowFailed()}
              title={t("failedHint")}
              disabled={data.documents.failed === 0}
              aria-expanded={showFailed}
            >
              <span className="kpi-icon red">
                <Icon name="alert-triangle" />
              </span>
              <div className="kpi-text">
                <strong>{data.documents.failed}</strong>
                <span>
                  {t("failed")}
                  {data.documents.failed > 0 ? ` · ${t("viewDetails")}` : ""}
                </span>
              </div>
            </button>
          </div>

          {showFailed ? (
            <section className="card" style={{ borderColor: "var(--danger-border)" }}>
              <div className="card-head">
                <h2>
                  <Icon name="alert-triangle" style={{ color: "var(--danger)" }} />
                  {t("failedListTitle")}
                  <span className="count">{failedDocs.length}</span>
                </h2>
                <button type="button" className="btn ghost sm icon-only" onClick={() => setShowFailed(false)} aria-label={t("close")}>
                  <Icon name="x" />
                </button>
              </div>
              <div className="card-pad" style={{ paddingBottom: "0.75rem" }}>
                <div className="alert warning">
                  <Icon name="info" />
                  <span>{t("failedTypeHint")}</span>
                </div>
              </div>
              {failedLoading ? (
                <p className="pdf-status" style={{ padding: "0 1.25rem 1rem" }}>
                  <span className="spinner" /> {t("loading")}
                </p>
              ) : null}
              {failedError ? (
                <div className="alert danger" style={{ margin: "0 1.25rem 1rem" }}>
                  <Icon name="alert-circle" />
                  <span>{failedError}</span>
                </div>
              ) : null}
              {!failedLoading && !failedError && failedDocs.length === 0 ? (
                <div className="empty" style={{ padding: "1.5rem" }}>
                  <p>{t("failedEmpty")}</p>
                </div>
              ) : null}
              {!failedLoading && failedDocs.length > 0 ? (
                <div className="rows" style={{ maxHeight: 420, overflowY: "auto" }}>
                  {failedDocs.map((d) => (
                    <div key={d.id} className="row">
                      <div className="row-main">
                        <div className="row-title">
                          <Link href={`/documents/${d.id}`} style={{ color: "var(--primary-text)" }}>
                            {d.title}
                          </Link>
                          <code>{d.source_id}</code>
                        </div>
                        {d.file_url ? (
                          <div className="row-sub">
                            <span title={d.file_url}>
                              <Icon name="link" />
                              {truncateUrl(d.file_url)}
                            </span>
                          </div>
                        ) : null}
                        <p className="row-error">
                          <strong>{t("failedReason")}:</strong> {d.index_error || "—"}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              ) : null}
            </section>
          ) : null}

          <section className="card">
            <div className="card-head">
              <h2>
                <Icon name="database" />
                {t("sources")}
                <span className="count">{data.sources.length}</span>
              </h2>
              <Link href="/settings" className="btn ghost sm">
                <Icon name="settings" />
                {t("manageSources")}
              </Link>
            </div>
            <div className="rows">
              {data.sources.map((s) => (
                <div key={s.id} className="row">
                  <span className={`dot ${s.enabled ? "green" : ""}`} aria-hidden />
                  <div className="row-main">
                    <div className="row-title">
                      {locale.startsWith("zh") ? s.name_zh_hk || s.name_en : s.name_en}
                      <code>{s.id}</code>
                      <span className={`badge ${s.enabled ? "green" : ""}`}>{s.enabled ? t("enabled") : t("disabled")}</span>
                    </div>
                    <div className="row-sub">
                      <span>
                        <Icon name="clock" />
                        {t("lastCrawl")}: {formatHkDateTime(s.last_crawl_at)}
                      </span>
                    </div>
                  </div>
                  <div className="row-actions">
                    <button className="btn secondary sm" type="button" disabled={busy || !s.enabled} onClick={() => onCrawl(s.id)}>
                      <Icon name="play" />
                      {t("crawl")}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section className="card">
            <div className="card-head">
              <h2>
                <Icon name="list-checks" />
                {t("recentRuns")}
                <span className="count">{historyRuns.length}</span>
              </h2>
            </div>
            {historyRuns.length === 0 ? (
              <div className="empty" style={{ padding: "1.75rem" }}>
                <p>{t("noRuns")}</p>
              </div>
            ) : (
              <div className="rows">
                {historyRuns.map((r) => (
                  <div key={r.id} className="row">
                    <span className={`dot ${statusTone(r.status)}`} aria-hidden />
                    <div className="row-main">
                      <div className="row-title">
                        {sourceName(r.source_id)}
                        <span className={`badge ${statusTone(r.status)}`}>{runStatusLabel(r.status)}</span>
                        {isReindexRun(r) ? <span className="badge sky">{t("reindexTag")}</span> : null}
                      </div>
                      {runCounts(r)}
                      {r.progress_message ? (
                        <p className="muted" style={{ fontSize: "0.8rem", marginTop: "0.2rem" }}>
                          {r.progress_message}
                        </p>
                      ) : null}
                      {r.error_message ? <p className="row-error">{r.error_message.slice(0, 240)}</p> : null}
                    </div>
                    <span className="muted tnum" style={{ fontSize: "0.8rem", whiteSpace: "nowrap" }}>
                      {formatHkDateTime(r.started_at)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </section>
        </>
      ) : null}
    </div>
  );
}
