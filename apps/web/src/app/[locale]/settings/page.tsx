"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "@/i18n/routing";
import SourcesSection from "@/components/SourcesSection";
import { Icon, type IconName } from "@/components/Icon";
import { Switch } from "@/components/Switch";
import { getSettings, SecretField, SettingsResponse, updateSettings } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatHkDateTime } from "@/lib/date";

const SECRET_KEYS = new Set([
  "openrouter_api_key",
  "jina_api_key",
  "dify_dataset_api_key",
  "dify_app_api_key",
  "minio_access_key",
  "minio_secret_key",
  "google_client_secret",
]);

const NUMBER_KEYS = new Set([
  "temperature",
  "max_tokens",
  "local_top_k",
  "dify_top_k",
  "jina_embedding_dim",
  "crawl_rate_limit_seconds",
  "jwt_expire_hours",
]);

const BOOLEAN_KEYS = new Set([
  "cite_inline_refs",
  "dify_enabled",
  "crawl_enabled",
  "minio_secure",
]);

const SELECT_KEYS: Record<string, string[]> = {
  llm_provider: ["openrouter", "ollama"],
  storage_backend: ["local", "minio"],
};

const TEXTAREA_KEYS = new Set(["system_prompt", "cors_origins"]);

/** Fields that are long enough to deserve the full width of the grid. */
const WIDE_KEYS = new Set([
  "system_prompt",
  "cors_origins",
  "openrouter_base_url",
  "ollama_base_url",
  "dify_api_url",
  "crawl_user_agent",
  "local_storage_path",
  "minio_public_url",
  "google_client_id",
  "google_client_secret",
]);

function isSecretField(value: unknown): value is SecretField {
  return (
    typeof value === "object" &&
    value !== null &&
    "configured" in value &&
    typeof (value as SecretField).configured === "boolean"
  );
}

function isSecretKey(key: string) {
  return SECRET_KEYS.has(key);
}

const READONLY_KEYS = [
  "app_env",
  "jwt_secret",
  "jwt_expire_hours",
  "admin_username",
  "database_url",
  "redis_url",
  "celery_broker_url",
  "celery_result_backend",
  "sources_config_path",
];

type Group = "sources" | "chat" | "connect" | "system";

export default function SettingsPage() {
  const t = useTranslations("settings");
  const tx = useMemo(
    () => t as unknown as (key: string, values?: Record<string, unknown>) => string,
    [t],
  );
  const { token, ready } = useAuth();
  const router = useRouter();

  const [data, setData] = useState<SettingsResponse | null>(null);
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [warnings, setWarnings] = useState<string[]>([]);
  const [group, setGroup] = useState<Group>("sources");
  const [query, setQuery] = useState("");
  const [revealed, setRevealed] = useState<Record<string, boolean>>({});

  useEffect(() => {
    if (ready && !token) router.replace("/login");
  }, [ready, token, router]);

  useEffect(() => {
    if (!token) return;
    setLoading(true);
    setError("");
    setSuccess("");
    setWarnings([]);
    getSettings(token)
      .then((res) => {
        setData(res);
        setDraft({});
      })
      .catch(() => setError(t("loadError")))
      .finally(() => setLoading(false));
  }, [token, t]);

  const originalDim = useMemo(() => {
    const val = data?.editable.jina_embedding_dim;
    return typeof val === "number" ? val : undefined;
  }, [data]);

  const dirtyCount = useMemo(() => {
    if (!data) return 0;
    let n = 0;
    for (const key of Object.keys(draft)) {
      if (isSecretKey(key)) {
        if (typeof draft[key] === "string" && (draft[key] as string).trim() !== "") n += 1;
        continue;
      }
      if (draft[key] !== data.editable[key]) n += 1;
    }
    return n;
  }, [draft, data]);

  function baseValue(key: string, readonly = false): unknown {
    if (readonly) return data?.readonly[key];
    return data?.editable[key];
  }

  function fieldLabel(key: string): string {
    const label = tx(`fields.${key}`);
    return label === `fields.${key}` ? key : label;
  }

  function fieldHelp(key: string): string | null {
    const help = tx(`help.${key}`);
    return help === `help.${key}` ? null : help;
  }

  function formatWarning(code: string): string {
    if (code === "reindex_required") return t("reindexWarning");
    return code;
  }

  function displayString(key: string): string {
    const base = baseValue(key);
    if (isSecretKey(key)) {
      if (typeof draft[key] === "string") return draft[key] as string;
      return "";
    }
    if (typeof draft[key] !== "undefined") {
      return String(draft[key] ?? "");
    }
    if (base === null || base === undefined) return "";
    if (typeof base === "boolean") return base ? "true" : "false";
    return String(base);
  }

  function checkedValue(key: string): boolean {
    const base = baseValue(key);
    if (typeof draft[key] === "boolean") return draft[key] as boolean;
    if (typeof base === "boolean") return base;
    return false;
  }

  function secretPlaceholder(key: string): string {
    const base = baseValue(key);
    if (isSecretField(base) && base.configured && base.masked) {
      return t("secretConfigured", { masked: base.masked });
    }
    return t("secretEmpty");
  }

  function secretConfigured(key: string): boolean {
    const base = baseValue(key);
    return isSecretField(base) && base.configured;
  }

  function updateDraft(key: string, value: unknown) {
    setDraft((prev) => ({ ...prev, [key]: value }));
    setSuccess("");
  }

  function onInputChange(key: string, raw: string) {
    if (isSecretKey(key)) {
      updateDraft(key, raw);
      return;
    }
    if (NUMBER_KEYS.has(key)) {
      if (raw === "") {
        updateDraft(key, "");
        return;
      }
      const parsed = key === "temperature" || key === "crawl_rate_limit_seconds" ? parseFloat(raw) : parseInt(raw, 10);
      updateDraft(key, Number.isNaN(parsed) ? raw : parsed);
      return;
    }
    updateDraft(key, raw);
  }

  function buildPatch(): Record<string, unknown> | null {
    if (!data) return null;
    const patch: Record<string, unknown> = {};

    for (const key of Object.keys(data.editable)) {
      if (!Object.prototype.hasOwnProperty.call(data.editable, key)) continue;
      if (isSecretKey(key)) {
        const typed = draft[key];
        if (typeof typed === "string" && typed.trim() !== "") {
          patch[key] = typed.trim();
        }
        continue;
      }

      if (!(key in draft)) continue;
      const current = data.editable[key];
      const next = draft[key];
      if (next === current) continue;
      if (next === "" && (current === null || current === undefined || current === "")) continue;

      if (BOOLEAN_KEYS.has(key)) {
        patch[key] = Boolean(next);
      } else if (NUMBER_KEYS.has(key)) {
        if (next === "" || next === null || next === undefined) continue;
        const num = typeof next === "number" ? next : parseFloat(String(next));
        if (Number.isNaN(num)) continue;
        patch[key] = num;
      } else {
        patch[key] = next;
      }
    }

    return patch;
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!token || !data || saving) return;

    const patch = buildPatch();
    if (!patch || Object.keys(patch).length === 0) {
      setSuccess(t("saved"));
      setWarnings([]);
      return;
    }

    const nextDim = patch.jina_embedding_dim;
    if (typeof nextDim === "number" && typeof originalDim === "number" && nextDim !== originalDim) {
      if (!window.confirm(t("dimConfirm"))) return;
    }

    setSaving(true);
    setError("");
    setSuccess("");
    setWarnings([]);

    try {
      const res = await updateSettings(token, patch);
      setData(res);
      setDraft({});
      setSuccess(t("saved"));
      setWarnings(res.warnings || []);
    } catch {
      setError(t("saveError"));
    } finally {
      setSaving(false);
    }
  }

  function onDiscard() {
    setDraft({});
    setSuccess("");
    setError("");
  }

  function renderField(key: string, readonly = false) {
    const base = baseValue(key, readonly);
    const label = fieldLabel(key);
    const help = fieldHelp(key);
    const wide = WIDE_KEYS.has(key) || readonly;

    if (readonly) {
      let display = "—";
      if (isSecretField(base)) {
        display = base.configured && base.masked ? base.masked : t("secretEmpty");
      } else if (base !== null && base !== undefined) {
        display = String(base);
      }
      return (
        <div className={`field${wide ? " span-2" : ""}`} key={key}>
          <label>{label}</label>
          <input value={display} disabled readOnly />
        </div>
      );
    }

    if (SELECT_KEYS[key]) {
      return (
        <div className="field" key={key}>
          <label htmlFor={key}>{label}</label>
          <select id={key} value={displayString(key)} onChange={(e) => updateDraft(key, e.target.value)}>
            {SELECT_KEYS[key].map((opt) => (
              <option key={opt} value={opt}>
                {opt}
              </option>
            ))}
          </select>
          {help ? <span className="field-hint">{help}</span> : null}
        </div>
      );
    }

    if (BOOLEAN_KEYS.has(key)) {
      return (
        <div className="switch-row span-2" key={key} style={{ gridColumn: "1 / -1" }}>
          <div className="switch-row-text">
            <strong id={`${key}-label`}>{label}</strong>
            {help ? <span>{help}</span> : null}
          </div>
          <Switch id={key} checked={checkedValue(key)} onChange={(v) => updateDraft(key, v)} label={label} />
        </div>
      );
    }

    if (TEXTAREA_KEYS.has(key)) {
      return (
        <div className="field span-2" key={key}>
          <label htmlFor={key}>{label}</label>
          <textarea
            id={key}
            rows={key === "system_prompt" ? 8 : 3}
            value={displayString(key)}
            onChange={(e) => updateDraft(key, e.target.value)}
            placeholder={isSecretKey(key) ? secretPlaceholder(key) : undefined}
          />
          {help ? <span className="field-hint">{help}</span> : null}
        </div>
      );
    }

    if (isSecretKey(key)) {
      const configured = secretConfigured(key);
      return (
        <div className={`field${wide ? " span-2" : ""}`} key={key}>
          <label htmlFor={key} style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            {label}
            <span className={`badge ${configured ? "green" : "amber"}`}>
              {configured ? <Icon name="check" /> : <Icon name="alert-circle" />}
              {configured ? t("secretSet") : t("secretEmpty")}
            </span>
          </label>
          <div className="input-wrap has-trailing">
            <Icon name="lock" />
            <input
              id={key}
              type={revealed[key] ? "text" : "password"}
              value={displayString(key)}
              onChange={(e) => onInputChange(key, e.target.value)}
              placeholder={secretPlaceholder(key)}
              autoComplete="off"
            />
            <button
              type="button"
              className="input-trailing"
              onClick={() => setRevealed((r) => ({ ...r, [key]: !r[key] }))}
              aria-label={revealed[key] ? t("hideSecret") : t("showSecret")}
            >
              <Icon name={revealed[key] ? "eye-off" : "eye"} />
            </button>
          </div>
          <span className="field-hint">{t("secretKeepHint")}</span>
        </div>
      );
    }

    return (
      <div className={`field${wide ? " span-2" : ""}`} key={key}>
        <label htmlFor={key}>{label}</label>
        <input
          id={key}
          type={NUMBER_KEYS.has(key) ? "number" : "text"}
          value={displayString(key)}
          onChange={(e) => onInputChange(key, e.target.value)}
          step={key === "temperature" ? 0.1 : key === "crawl_rate_limit_seconds" ? 0.1 : undefined}
        />
        {help ? <span className="field-hint">{help}</span> : null}
      </div>
    );
  }

  if (!token) return null;

  const provider = displayString("llm_provider") || "openrouter";
  const storageBackend = displayString("storage_backend") || "local";
  const difyOn = checkedValue("dify_enabled");
  const q = query.trim().toLowerCase();

  const connectKeys = [
    "llm_provider",
    ...(provider === "ollama"
      ? ["ollama_base_url", "ollama_model"]
      : ["openrouter_api_key", "openrouter_model", "openrouter_base_url"]),
    "temperature",
    "max_tokens",
    "jina_api_key",
    "jina_embedding_model",
    "jina_embedding_dim",
    "dify_enabled",
    ...(difyOn
      ? ["dify_api_url", "dify_dataset_api_key", "dify_app_api_key", "dify_dataset_id"]
      : []),
  ];
  const systemKeys = [
    "app_name",
    "cors_origins",
    "crawl_enabled",
    "crawl_user_agent",
    "crawl_rate_limit_seconds",
    "storage_backend",
    ...(storageBackend === "minio"
      ? [
          "minio_endpoint",
          "minio_access_key",
          "minio_secret_key",
          "minio_bucket",
          "minio_public_url",
          "minio_secure",
        ]
      : ["local_storage_path"]),
    "google_client_id",
    "google_client_secret",
  ];
  const chatKeys = ["system_prompt", "cite_inline_refs", "local_top_k", "dify_top_k"];

  function matches(label: string) {
    return !q || label.toLowerCase().includes(q);
  }

  const groups: { id: Group; title: string; desc: string; icon: IconName }[] = [
    { id: "sources", title: t("groupSources"), desc: t("groupSourcesDesc"), icon: "database" },
    { id: "chat", title: t("groupChat"), desc: t("groupChatDesc"), icon: "message-square" },
    { id: "connect", title: t("groupConnect"), desc: t("groupConnectDesc"), icon: "plug-zap" },
    { id: "system", title: t("groupSystem"), desc: t("groupSystemDesc"), icon: "server" },
  ];

  const visibleChat = chatKeys.filter((key) => matches(fieldLabel(key)) || matches(t("groupChat")));
  const visibleConnect = connectKeys.filter((key) => matches(fieldLabel(key)) || matches(t("groupConnect")));
  const visibleSystem = systemKeys.filter((key) => matches(fieldLabel(key)) || matches(t("groupSystem")));
  const groupHasMatch = {
    sources: !q || matches(t("groupSources")) || matches(t("sourcesTitle")),
    chat: visibleChat.length > 0,
    connect: visibleConnect.length > 0,
    system: visibleSystem.length > 0 || (!q ? false : matches(t("sectionReadonly")) || matches(t("advanced"))),
  };

  const current = groups.find((g) => g.id === group)!;

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>{t("title")}</h1>
          <p className="page-subtitle">{t("subtitle")}</p>
        </div>
      </header>

      <div className="settings-shell">
        <aside className="settings-nav">
          <div className="input-wrap">
            <Icon name="search" />
            <input
              className="input"
              value={query}
              onChange={(e) => {
                const next = e.target.value;
                setQuery(next);
                const needle = next.trim().toLowerCase();
                if (!needle) return;
                const hit = groups.find((item) => {
                  if (item.id === "sources") return item.title.toLowerCase().includes(needle);
                  if (item.id === "chat") return chatKeys.some((key) => fieldLabel(key).toLowerCase().includes(needle)) || item.title.toLowerCase().includes(needle);
                  if (item.id === "connect") return connectKeys.some((key) => fieldLabel(key).toLowerCase().includes(needle)) || item.title.toLowerCase().includes(needle);
                  return systemKeys.some((key) => fieldLabel(key).toLowerCase().includes(needle)) || item.title.toLowerCase().includes(needle) || t("advanced").toLowerCase().includes(needle);
                });
                if (hit) setGroup(hit.id);
              }}
              placeholder={t("searchSettings")}
              aria-label={t("searchSettings")}
            />
          </div>
          <div className="settings-nav-list" role="tablist" aria-label={t("title")}>
            {groups.map((item) => (
              <button
                key={item.id}
                type="button"
                role="tab"
                aria-selected={group === item.id}
                className={`settings-nav-btn${group === item.id ? " active" : ""}`}
                onClick={() => setGroup(item.id)}
                style={q && !groupHasMatch[item.id] ? { opacity: 0.45 } : undefined}
              >
                <Icon name={item.icon} />
                {item.title}
              </button>
            ))}
          </div>
        </aside>

        <div className="settings-main">
          {group === "sources" ? <SourcesSection token={token} /> : null}

          {group !== "sources" ? (
            <form onSubmit={onSubmit}>
              <div className="settings-savebar">
                <button className={`btn${saving ? " is-loading" : ""}`} type="submit" disabled={saving || loading}>
                  {saving ? <span className="spinner" /> : <Icon name="check" />}
                  {saving ? t("saving") : dirtyCount > 0 ? t("saveCount", { count: dirtyCount }) : t("save")}
                </button>
                {dirtyCount > 0 ? (
                  <button className="btn ghost" type="button" onClick={onDiscard} disabled={saving}>
                    {t("discard")}
                  </button>
                ) : null}
                <span className="savebar-spacer" />
                {loading ? (
                  <span className="savebar-status">
                    <span className="spinner" /> {t("loading")}
                  </span>
                ) : null}
                {success ? (
                  <span className="savebar-status ok">
                    <Icon name="check-circle" /> {success}
                  </span>
                ) : null}
                {error ? (
                  <span className="savebar-status err">
                    <Icon name="alert-circle" /> {error}
                  </span>
                ) : null}
                {!success && !error && !loading && dirtyCount > 0 ? (
                  <span className="savebar-status">{t("unsaved", { count: dirtyCount })}</span>
                ) : null}
              </div>

              {warnings.length > 0 ? (
                <div className="alert warning" style={{ margin: "1rem 0" }}>
                  <Icon name="alert-triangle" />
                  <ul>
                    {warnings.map((w, i) => (
                      <li key={i}>{formatWarning(w)}</li>
                    ))}
                  </ul>
                </div>
              ) : null}

              <section className="card" style={{ marginTop: "1rem" }}>
                <div className="card-head">
                  <h2>
                    <Icon name={current.icon} />
                    {current.title}
                  </h2>
                </div>
                <div className="card-pad">
                  <p className="section-desc">{current.desc}</p>

                  {group === "chat" ? (
                    visibleChat.length === 0 ? (
                      <p className="muted">{t("searchEmpty")}</p>
                    ) : (
                      <div className="field-grid">{visibleChat.map((key) => renderField(key))}</div>
                    )
                  ) : null}

                  {group === "connect" ? (
                    visibleConnect.length === 0 ? (
                      <p className="muted">{t("searchEmpty")}</p>
                    ) : (
                      <div className="field-grid">{visibleConnect.map((key) => renderField(key))}</div>
                    )
                  ) : null}

                  {group === "system" ? (
                    visibleSystem.length === 0 && q ? (
                      <p className="muted">{t("searchEmpty")}</p>
                    ) : (
                      <div className="field-grid">{visibleSystem.map((key) => renderField(key))}</div>
                    )
                  ) : null}
                </div>
              </section>

              {group === "system" && (!q || groupHasMatch.system) ? (
                <details className="settings-advanced" style={{ marginTop: "1rem" }}>
                  <summary>
                    <Icon name="chevron-down" className="chev" />
                    {t("advanced")}
                    <span className="muted" style={{ fontWeight: 400, fontSize: "0.8rem" }}>
                      · {t("sectionReadonly")}
                    </span>
                  </summary>
                  <div className="settings-advanced-body">
                    <div className="alert" style={{ marginBottom: "1rem" }}>
                      <Icon name="info" />
                      <span>
                        {t("readonlyHint")} {t("buildTimeHint")}
                      </span>
                    </div>
                    <div className="field-grid">
                      {READONLY_KEYS.map((key) => renderField(key, true))}
                      {data ? (
                        <div className="field span-2" style={{ marginBottom: 0 }}>
                          <label>{fieldLabel("updated_at")}</label>
                          <input value={formatHkDateTime(data.meta.updated_at)} disabled readOnly />
                        </div>
                      ) : null}
                    </div>
                  </div>
                </details>
              ) : null}
            </form>
          ) : null}
        </div>
      </div>
    </div>
  );
}
