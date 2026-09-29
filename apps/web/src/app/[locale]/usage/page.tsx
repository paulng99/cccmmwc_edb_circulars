"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "@/i18n/routing";
import { getUsage, type UsageReport } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatHkDateTime } from "@/lib/date";
import { Icon } from "@/components/Icon";

const PERIODS = [
  { days: 1, label: "today" },
  { days: 7, label: "d7" },
  { days: 30, label: "d30" },
  { days: 90, label: "d90" },
] as const;

const FEATURES = [
  { id: "chat", label: "featureChat", hint: "featureChatHint", tone: "blue" },
  { id: "classify", label: "featureClassify", hint: "featureClassifyHint", tone: "violet" },
  { id: "source_suggest", label: "featureSourceSuggest", hint: "featureSourceSuggestHint", tone: "sky" },
  { id: "embed_index", label: "featureEmbedIndex", hint: "featureEmbedIndexHint", tone: "teal" },
  { id: "embed_query", label: "featureEmbedQuery", hint: "featureEmbedQueryHint", tone: "orange" },
  { id: "web_search", label: "featureWebSearch", hint: "featureWebSearchHint", tone: "amber" },
  { id: "other", label: "featureOther", hint: "featureOtherHint", tone: "slate" },
] as const;

type FeatureKey = (typeof FEATURES)[number]["label"];

function formatUsd(value: number): string {
  if (!Number.isFinite(value)) return "—";
  if (value === 0) return "US$0.00";
  const abs = Math.abs(value);
  const digits = abs >= 1 ? 2 : abs >= 0.01 ? 4 : abs >= 0.000001 ? 6 : 8;
  return `US$${value.toFixed(digits)}`;
}

function formatTokens(value: number): string {
  return new Intl.NumberFormat("en-HK").format(value || 0);
}

export default function UsagePage() {
  const t = useTranslations("usage");
  const router = useRouter();
  const { token, ready } = useAuth();
  const [days, setDays] = useState(30);
  const [data, setData] = useState<UsageReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (ready && !token) router.replace("/login");
  }, [ready, token, router]);

  const load = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setFailed(false);
    try {
      setData(await getUsage(token, days));
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, [token, days]);

  useEffect(() => {
    load();
  }, [load]);

  if (!token) return null;

  const totals = data?.totals;
  const calls = totals?.calls ?? 0;
  const featureRows = FEATURES.map((item) => ({
    ...item,
    bucket: data?.by_feature.find((row) => row.feature === item.id),
  })).filter((item) => item.id !== "other" || (item.bucket?.calls ?? 0) > 0);

  const maxFeatureCost = Math.max(...featureRows.map((row) => row.bucket?.cost_usd ?? 0), 0);
  const dayMetric: "cost_usd" | "total_tokens" =
    (data?.by_day.some((day) => day.cost_usd > 0) ?? false) ? "cost_usd" : "total_tokens";
  const maxDay = Math.max(...(data?.by_day.map((day) => day[dayMetric]) ?? [0]), 0);
  const showDayLabels = (data?.by_day.length ?? 0) <= 14;

  const featureLabel = (id: string) => {
    const item = FEATURES.find((row) => row.id === id);
    return item ? t(item.label) : id;
  };

  const providerLabel = (id: string) => {
    if (id === "openrouter") return t("providerOpenrouter");
    if (id === "jina") return t("providerJina");
    if (id === "ollama") return t("providerOllama");
    return id;
  };

  const basisLabel = (source: string) => {
    if (source === "provider") return t("costProvider");
    if (source === "estimate") return t("costEstimate");
    if (source === "local") return t("costLocal");
    return t("costUnknown");
  };

  const userLabel = (username: string | null | undefined, userId: string | null | undefined) => {
    if (username) return username;
    if (userId) return t("deletedUser");
    return t("systemUser");
  };

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>{t("title")}</h1>
          <p className="page-subtitle">{t("subtitle")}</p>
        </div>
        <div className="segmented" role="group" aria-label={t("range", { from: data?.from ?? "", to: data?.to ?? "" })}>
          {PERIODS.map((period) => (
            <button
              key={period.days}
              type="button"
              aria-pressed={days === period.days}
              onClick={() => setDays(period.days)}
            >
              {t(period.label)}
            </button>
          ))}
        </div>
      </header>

      {data ? <p className="usage-range">{t("range", { from: data.from, to: data.to })}</p> : null}

      {failed ? (
        <div className="empty card card-pad">
          <h3>{t("loadError")}</h3>
          <div className="empty-actions">
            <button type="button" className="btn" onClick={() => load()}>
              {t("retry")}
            </button>
          </div>
        </div>
      ) : null}

      <section className="kpi-grid usage-kpis" aria-busy={loading}>
        <article className="kpi card">
          <span className="kpi-icon blue">
            <Icon name="bar-chart" />
          </span>
          <div className="kpi-text">
            <strong>{formatUsd(totals?.cost_usd ?? 0)}</strong>
            <span>{t("cost")}</span>
          </div>
        </article>
        <article className="kpi card">
          <span className="kpi-icon teal">
            <Icon name="activity" />
          </span>
          <div className="kpi-text">
            <strong>{formatTokens(totals?.total_tokens ?? 0)}</strong>
            <span>{t("tokens")}</span>
          </div>
        </article>
        <article className="kpi card">
          <span className="kpi-icon violet">
            <Icon name="message-square" />
          </span>
          <div className="kpi-text">
            <strong>{formatTokens(calls)}</strong>
            <span>{t("calls")}</span>
          </div>
        </article>
        <article className="kpi card">
          <span className="kpi-icon amber">
            <Icon name="tags" />
          </span>
          <div className="kpi-text">
            <strong>{calls ? formatUsd((totals?.cost_usd ?? 0) / calls) : "—"}</strong>
            <span>{t("avg")}</span>
          </div>
        </article>
      </section>

      <section className="card usage-note">
        <h2>{t("classifyTitle")}</h2>
        <p>{t("classifyBody")}</p>
        <ul>
          {FEATURES.filter((item) => item.id !== "other").map((item) => (
            <li key={item.id}>
              <span className={`usage-dot ${item.tone}`} />
              <strong>{t(item.label as FeatureKey)}</strong>
              <span>{t(item.hint)}</span>
            </li>
          ))}
        </ul>
      </section>

      {!failed && !loading && calls === 0 ? (
        <div className="empty card card-pad">
          <span className="empty-icon">
            <Icon name="bar-chart" />
          </span>
          <h3>{t("emptyTitle")}</h3>
          <p>{t("empty")}</p>
        </div>
      ) : null}

      <section className="card">
        <div className="card-head">
          <h2>
            <Icon name="user" />
            {t("byUser")}
          </h2>
        </div>
        <div className="usage-table-wrap">
          <table className="usage-table">
            <thead>
              <tr>
                <th>{t("user")}</th>
                <th>{t("calls")}</th>
                <th>{t("tokens")}</th>
                <th>{t("price")}</th>
                <th>{t("byFeature")}</th>
              </tr>
            </thead>
            <tbody>
              {(data?.by_user.length ?? 0) === 0 ? (
                <tr>
                  <td colSpan={5} className="usage-muted">
                    —
                  </td>
                </tr>
              ) : (
                data?.by_user.map((row) => (
                  <tr key={row.user_id ?? "system"}>
                    <td>
                      <strong>{userLabel(row.username, row.user_id)}</strong>
                    </td>
                    <td>{formatTokens(row.calls)}</td>
                    <td>{formatTokens(row.total_tokens)}</td>
                    <td>{formatUsd(row.cost_usd)}</td>
                    <td>
                      <div className="usage-feature-tags">
                        {row.by_feature
                          .filter((item) => item.calls > 0)
                          .map((item) => (
                            <span key={item.feature} className="usage-tag">
                              {featureLabel(item.feature)} {formatUsd(item.cost_usd)}
                            </span>
                          ))}
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      <div className="usage-grid">
        <section className="card">
          <div className="card-head">
            <h2>
              <Icon name="tags" />
              {t("byFeature")}
            </h2>
          </div>
          <div className="card-pad usage-bars">
            {featureRows.map((row) => {
              const bucket = row.bucket;
              const width = maxFeatureCost > 0 ? ((bucket?.cost_usd ?? 0) / maxFeatureCost) * 100 : 0;
              return (
                <div key={row.id} className="usage-bar-row">
                  <div className="usage-bar-label">
                    <span className={`usage-dot ${row.tone}`} />
                    <strong>{t(row.label)}</strong>
                    <span>{formatTokens(bucket?.calls ?? 0)}</span>
                  </div>
                  <div className="progress-track" aria-hidden>
                    <div className={`progress-fill tone-${row.tone}`} style={{ width: `${width}%` }} />
                  </div>
                  <div className="usage-bar-meta">
                    <span>{formatTokens(bucket?.total_tokens ?? 0)} {t("tokens")}</span>
                    <strong>{formatUsd(bucket?.cost_usd ?? 0)}</strong>
                  </div>
                </div>
              );
            })}
          </div>
        </section>

        <section className="card">
          <div className="card-head">
            <h2>
              <Icon name="server" />
              {t("byProvider")}
            </h2>
          </div>
          <div className="card-pad">
            {(data?.by_provider.length ?? 0) === 0 ? (
              <p className="usage-muted">—</p>
            ) : (
              <ul className="usage-split">
                {data?.by_provider.map((row) => (
                  <li key={row.provider}>
                    <strong>{providerLabel(row.provider)}</strong>
                    <span>{formatTokens(row.total_tokens)}</span>
                    <b>{formatUsd(row.cost_usd)}</b>
                  </li>
                ))}
              </ul>
            )}
            <h3 className="usage-subhead">{t("byModel")}</h3>
            {(data?.by_model.length ?? 0) === 0 ? (
              <p className="usage-muted">—</p>
            ) : (
              <ul className="usage-split">
                {data?.by_model.map((row) => (
                  <li key={`${row.provider}:${row.model}`}>
                    <strong title={row.model}>{row.model || "—"}</strong>
                    <span>{providerLabel(row.provider)}</span>
                    <b>{formatUsd(row.cost_usd)}</b>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>
      </div>

      <section className="card">
        <div className="card-head">
          <h2>
            <Icon name="activity" />
            {t("byDay")}
          </h2>
          <span className="usage-muted">{dayMetric === "cost_usd" ? t("cost") : t("tokens")}</span>
        </div>
        <div className="card-pad">
          <div className="usage-days" role="img" aria-label={t("byDay")}>
            {data?.by_day.map((day) => {
              const value = day[dayMetric];
              const height = maxDay > 0 ? Math.max((value / maxDay) * 100, value > 0 ? 6 : 0) : 0;
              return (
                <div key={day.date} className="usage-day" title={`${day.date} · ${formatTokens(day.total_tokens)} · ${formatUsd(day.cost_usd)}`}>
                  <div className="usage-day-track">
                    <div className="usage-day-fill" style={{ height: `${height}%` }} />
                  </div>
                  {showDayLabels ? <span>{day.date.slice(5)}</span> : null}
                </div>
              );
            })}
          </div>
          {data && !showDayLabels ? (
            <div className="usage-day-axis">
              <span>{data.from}</span>
              <span>{data.to}</span>
            </div>
          ) : null}
        </div>
      </section>

      <section className="card">
        <div className="card-head">
          <h2>
            <Icon name="file-text" />
            {t("recent")}
          </h2>
        </div>
        <div className="usage-table-wrap">
          <table className="usage-table">
            <thead>
              <tr>
                <th>{t("time")}</th>
                <th>{t("user")}</th>
                <th>{t("feature")}</th>
                <th>{t("provider")}</th>
                <th>{t("model")}</th>
                <th>{t("prompt")}</th>
                <th>{t("completion")}</th>
                <th>{t("price")}</th>
                <th>{t("basis")}</th>
              </tr>
            </thead>
            <tbody>
              {(data?.recent.length ?? 0) === 0 ? (
                <tr>
                  <td colSpan={9} className="usage-muted">
                    —
                  </td>
                </tr>
              ) : (
                data?.recent.map((row, index) => (
                  <tr key={`${row.created_at}-${index}`}>
                    <td>{formatHkDateTime(row.created_at)}</td>
                    <td>{userLabel(row.username, row.user_id)}</td>
                    <td>{featureLabel(row.feature)}</td>
                    <td>{providerLabel(row.provider)}</td>
                    <td className="usage-model">{row.model || "—"}</td>
                    <td>{formatTokens(row.prompt_tokens)}</td>
                    <td>{formatTokens(row.completion_tokens)}</td>
                    <td>{formatUsd(row.cost_usd)}</td>
                    <td>
                      <span className={row.cost_source === "estimate" ? "usage-tag estimate" : "usage-tag"}>
                        {basisLabel(row.cost_source)}
                      </span>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      <p className="usage-footnote">
        {t("estimateNote")}
        {(totals?.estimated_cost_usd ?? 0) > 0 ? ` ${t("estimateTag")} ${formatUsd(totals?.estimated_cost_usd ?? 0)}.` : ""}
      </p>
    </div>
  );
}
