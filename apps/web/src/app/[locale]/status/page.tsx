"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "@/i18n/routing";
import { ingestStatus, stopCrawl, triggerCrawl } from "@/lib/api";
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
  status: string;
  discovered: number;
  downloaded: number;
  failed: number;
  progress_message?: string | null;
  error_message?: string | null;
  started_at: string | null;
  finished_at?: string | null;
  current?: CrawlEvent | null;
  recent_events?: CrawlEvent[];
  cancel_requested?: boolean;
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
  download_fail: "eventDownloadFail",
  done: "eventDone",
  cancelled: "eventCancelled",
};

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
  const [stopping, setStopping] = useState(false);
  const [error, setError] = useState("");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async (tok: string) => {
    const s = (await ingestStatus(tok)) as IngestData;
    setData(s);
    const running = Boolean(s.active) || s.recent_runs.some((r) => r.status === "running");
    setBusy(running);
    if (!running) setStopping(false);
    else if (s.recent_runs.some((r) => r.status === "running" && r.cancel_requested)) {
      setStopping(true);
    }
    return running;
  }, []);

  const stopPoll = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const startPoll = useCallback(
    (tok: string) => {
      stopPoll();
      pollRef.current = setInterval(() => {
        refresh(tok)
          .then((running) => {
            if (!running) {
              stopPoll();
              setMsg((prev) => (prev === t("stopping") ? t("cancelled") : t("crawlDone")));
              setStopping(false);
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
      .then((running) => {
        if (running) startPoll(token);
      })
      .catch(() => setData(null));
    return () => stopPoll();
  }, [token, refresh, startPoll, stopPoll]);

  async function onCrawl(sourceId?: string) {
    if (!token || busy) return;
    setError("");
    setStopping(false);
    setMsg(t("crawling"));
    setBusy(true);
    try {
      await triggerCrawl(token, sourceId);
      await refresh(token);
      startPoll(token);
    } catch {
      setBusy(false);
      setError(t("crawlError"));
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
      startPoll(token);
    } catch {
      setStopping(false);
      setError(t("stopError"));
    }
  }

  if (!token) return null;

  const activeRuns = data?.recent_runs.filter((r) => r.status === "running") || [];
  const sourceName = (id: string) => {
    const s = data?.sources.find((x) => x.id === id);
    if (!s) return id;
    return locale.startsWith("zh") ? s.name_zh_hk || s.name_en : s.name_en;
  };

  const eventLabel = (type: string) => {
    const key = EVENT_I18N[type];
    return key ? t(key as "eventDiscovering") : type;
  };

  const currentLabel = (ev: CrawlEvent) => ev.title || (ev.url ? truncateUrl(ev.url) : "—");

  return (
    <div>
      <div className="hero">
        <h1>{t("title")}</h1>
      </div>
      <div style={{ marginBottom: "1rem", display: "flex", gap: "0.75rem", alignItems: "center", flexWrap: "wrap" }}>
        <button className="btn" type="button" disabled={busy} onClick={() => onCrawl()}>
          {busy ? t("crawlingBtn") : t("crawl")}
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
                    ? Math.min(100, Math.round(((r.downloaded + r.failed) / r.discovered) * 100))
                    : 0;
                return (
                  <div key={r.id} className="doc-row">
                    <div style={{ width: "100%" }}>
                      <h3>
                        {sourceName(r.source_id)}{" "}
                        <span className="chip">{r.status}</span>
                        {r.cancel_requested ? <span className="chip">{t("eventCancelled")}</span> : null}
                      </h3>
                      <div className="meta">
                        <span>
                          {t("progressCounts", {
                            discovered: r.discovered,
                            downloaded: r.downloaded,
                            failed: r.failed,
                          })}
                        </span>
                        <span>{formatHkDateTime(r.started_at)}</span>
                      </div>
                      <div
                        style={{
                          marginTop: "0.6rem",
                          height: 10,
                          borderRadius: 999,
                          background: "rgba(37,99,212,0.12)",
                          overflow: "hidden",
                        }}
                      >
                        <div
                          style={{
                            width: `${pct}%`,
                            height: "100%",
                            background: "linear-gradient(90deg, var(--blue-700), var(--cyan-500))",
                            transition: "width 0.4s ease",
                          }}
                        />
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
            <div className="stat">
              <strong>{data.documents.failed}</strong>
              <span>{t("failed")}</span>
            </div>
          </div>
          <div className="panel" style={{ marginBottom: "1rem" }}>
            <h2 style={{ marginTop: 0 }}>{t("sources")}</h2>
            <div className="list">
              {data.sources.map((s) => (
                <div key={s.id} className="doc-row">
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
                <div key={r.id} className="doc-row">
                  <div>
                    <h3>
                      {r.source_id}{" "}
                      <span className="chip">{r.status}</span>
                    </h3>
                    <div className="meta">
                      <span>
                        {r.discovered}/{r.downloaded}/{r.failed}
                      </span>
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
