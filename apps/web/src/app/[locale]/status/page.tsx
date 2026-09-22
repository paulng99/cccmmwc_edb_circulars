"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "@/i18n/routing";
import { ingestStatus, triggerCrawl } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type IngestData = {
  documents: { total: number; ready: number; indexing: number; failed: number };
  sources: Array<{
    id: string;
    enabled: boolean;
    last_crawl_at: string | null;
    name_en: string;
    name_zh_hk: string;
  }>;
  recent_runs: Array<{
    id: string;
    source_id: string;
    status: string;
    discovered: number;
    downloaded: number;
    failed: number;
    started_at: string | null;
  }>;
};

export default function StatusPage() {
  const t = useTranslations("status");
  const { token, ready } = useAuth();
  const router = useRouter();
  const [data, setData] = useState<IngestData | null>(null);
  const [msg, setMsg] = useState("");

  async function refresh(tok: string) {
    const s = (await ingestStatus(tok)) as IngestData;
    setData(s);
  }

  useEffect(() => {
    if (ready && !token) router.replace("/login");
  }, [ready, token, router]);

  useEffect(() => {
    if (!token) return;
    refresh(token).catch(() => setData(null));
  }, [token]);

  if (!token) return null;

  return (
    <div>
      <div className="hero">
        <h1>{t("title")}</h1>
      </div>
      <div style={{ marginBottom: "1rem", display: "flex", gap: "0.75rem", alignItems: "center" }}>
        <button
          className="btn"
          type="button"
          onClick={async () => {
            await triggerCrawl(token);
            setMsg(t("crawling"));
            setTimeout(() => refresh(token), 2000);
          }}
        >
          {t("crawl")}
        </button>
        {msg ? <span className="hint">{msg}</span> : null}
      </div>
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
                    <h3>{s.name_zh_hk || s.name_en}</h3>
                    <div className="meta">
                      <span className="chip">{s.id}</span>
                      <span>{s.enabled ? "on" : "off"}</span>
                      <span>{s.last_crawl_at || "—"}</span>
                    </div>
                  </div>
                  <button
                    className="btn secondary"
                    type="button"
                    onClick={async () => {
                      await triggerCrawl(token, s.id);
                      setMsg(t("crawling"));
                    }}
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
                    <h3>{r.source_id}</h3>
                    <div className="meta">
                      <span className="chip">{r.status}</span>
                      <span>
                        {r.discovered}/{r.downloaded}/{r.failed}
                      </span>
                      <span>{r.started_at}</span>
                    </div>
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
