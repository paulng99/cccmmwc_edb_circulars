"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "@/i18n/routing";
import SourcesSection from "@/components/SourcesSection";
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

type SectionConfig = {
  titleKey: string;
  keys: string[];
};

const SECTIONS: SectionConfig[] = [
  { titleKey: "sectionApp", keys: ["app_name", "cors_origins"] },
  {
    titleKey: "sectionLlm",
    keys: [
      "llm_provider",
      "openrouter_api_key",
      "openrouter_model",
      "openrouter_base_url",
      "ollama_base_url",
      "ollama_model",
      "temperature",
      "max_tokens",
    ],
  },
  {
    titleKey: "sectionChat",
    keys: ["system_prompt", "cite_inline_refs", "local_top_k", "dify_top_k"],
  },
  {
    titleKey: "sectionEmbeddings",
    keys: ["jina_api_key", "jina_embedding_model", "jina_embedding_dim"],
  },
  {
    titleKey: "sectionDify",
    keys: [
      "dify_enabled",
      "dify_api_url",
      "dify_dataset_api_key",
      "dify_app_api_key",
      "dify_dataset_id",
    ],
  },
  {
    titleKey: "sectionCrawl",
    keys: ["crawl_enabled", "crawl_user_agent", "crawl_rate_limit_seconds"],
  },
  {
    titleKey: "sectionStorage",
    keys: [
      "storage_backend",
      "local_storage_path",
      "minio_endpoint",
      "minio_access_key",
      "minio_secret_key",
      "minio_bucket",
      "minio_public_url",
      "minio_secure",
    ],
  },
  {
    titleKey: "sectionOauth",
    keys: ["google_client_id", "google_client_secret"],
  },
];

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

  function baseValue(key: string, readonly = false): unknown {
    if (readonly) return data?.readonly[key];
    return data?.editable[key];
  }

  function fieldLabel(key: string): string {
    const label = tx(`fields.${key}`);
    return label === `fields.${key}` ? key : label;
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

  function updateDraft(key: string, value: unknown) {
    setDraft((prev) => ({ ...prev, [key]: value }));
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

  function onCheckboxChange(key: string, checked: boolean) {
    updateDraft(key, checked);
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

  function renderField(key: string, readonly = false) {
    const base = baseValue(key, readonly);
    const label = fieldLabel(key);

    if (readonly) {
      let display = "—";
      if (isSecretField(base)) {
        display = base.configured && base.masked ? base.masked : t("secretEmpty");
      } else if (base !== null && base !== undefined) {
        display = String(base);
      }
      return (
        <div className="field" key={key}>
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
        </div>
      );
    }

    if (BOOLEAN_KEYS.has(key)) {
      return (
        <div className="field" key={key} style={{ flexDirection: "row", alignItems: "center", gap: "0.5rem" }}>
          <input
            id={key}
            type="checkbox"
            checked={checkedValue(key)}
            onChange={(e) => onCheckboxChange(key, e.target.checked)}
          />
          <label htmlFor={key} style={{ margin: 0 }}>
            {label}
          </label>
        </div>
      );
    }

    if (TEXTAREA_KEYS.has(key)) {
      return (
        <div className="field" key={key}>
          <label htmlFor={key}>{label}</label>
          <textarea
            id={key}
            rows={key === "system_prompt" ? 8 : 3}
            value={displayString(key)}
            onChange={(e) => updateDraft(key, e.target.value)}
            placeholder={isSecretKey(key) ? secretPlaceholder(key) : undefined}
          />
          {isSecretKey(key) ? <span className="hint">{t("secretKeepHint")}</span> : null}
        </div>
      );
    }

    return (
      <div className="field" key={key}>
        <label htmlFor={key}>{label}</label>
        <input
          id={key}
          type={isSecretKey(key) ? "password" : NUMBER_KEYS.has(key) ? "number" : "text"}
          value={displayString(key)}
          onChange={(e) => onInputChange(key, e.target.value)}
          placeholder={isSecretKey(key) ? secretPlaceholder(key) : undefined}
          step={key === "temperature" ? 0.1 : key === "crawl_rate_limit_seconds" ? 0.1 : undefined}
        />
        {isSecretKey(key) ? <span className="hint">{t("secretKeepHint")}</span> : null}
      </div>
    );
  }

  if (!token) return null;

  return (
    <div className="page-enter">
      <div className="hero">
        <h1>{t("title")}</h1>
      </div>

      <SourcesSection token={token} />

      <form onSubmit={onSubmit}>
        <div style={{ marginBottom: "1rem", display: "flex", gap: "0.75rem", alignItems: "center", flexWrap: "wrap" }}>
          <button className="btn" type="submit" disabled={saving || loading}>
            {saving ? t("saving") : t("save")}
          </button>
          {success ? <span className="hint" style={{ color: "var(--teal-500)", fontWeight: 600 }}>{success}</span> : null}
          {error ? <span className="error">{error}</span> : null}
          {loading ? <span className="hint">{t("loading")}</span> : null}
        </div>

        {warnings.length > 0 ? (
          <div
            className="panel"
            style={{ marginBottom: "1rem", borderColor: "var(--amber-500)", background: "rgba(245, 158, 11, 0.08)" }}
          >
            <ul style={{ margin: 0, paddingLeft: "1.2rem", color: "var(--muted)" }}>
              {warnings.map((w, i) => (
                <li key={i}>{formatWarning(w)}</li>
              ))}
            </ul>
          </div>
        ) : null}

        {SECTIONS.map((section) => (
          <section key={section.titleKey} className="panel" style={{ marginBottom: "1rem" }}>
            <h2 style={{ marginTop: 0, color: "var(--blue-900)" }}>{tx(section.titleKey)}</h2>
            {section.keys.map((key) => renderField(key))}
          </section>
        ))}

        <section className="panel" style={{ marginBottom: "1rem" }}>
          <h2 style={{ marginTop: 0, color: "var(--blue-900)" }}>{t("sectionReadonly")}</h2>
          <p className="hint" style={{ marginTop: 0, marginBottom: "0.5rem" }}>
            {t("readonlyHint")}
          </p>
          <p className="hint" style={{ marginTop: 0, marginBottom: "1rem" }}>
            {t("buildTimeHint")}
          </p>
          {READONLY_KEYS.map((key) => renderField(key, true))}
          {data ? (
            <div className="field" style={{ marginBottom: 0 }}>
              <label>{fieldLabel("updated_at")}</label>
              <input value={formatHkDateTime(data.meta.updated_at)} disabled readOnly />
            </div>
          ) : null}
        </section>
      </form>
    </div>
  );
}
