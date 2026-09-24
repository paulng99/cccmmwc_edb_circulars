"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import {
  CrawlSource,
  getSourceConfig,
  saveSourceConfig,
  suggestSources,
} from "@/lib/api";

type Props = { token: string };

type EditorMode = "closed" | "add" | "edit";

type FormState = {
  id: string;
  nameEn: string;
  nameZh: string;
  enabled: boolean;
  priority: string;
  type: CrawlSource["type"];
  baseUrl: string;
  rateLimit: string;
  schedule: string;
  hosts: string;
  exts: string;
  seeds: string;
  paths: string;
  maxPages: string;
  langs: string;
  yearFrom: string;
  yearTo: string;
};

function splitCsv(raw: string): string[] {
  return raw
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

function splitIntCsv(raw: string): number[] {
  return splitCsv(raw)
    .map((s) => parseInt(s, 10))
    .filter((n) => !Number.isNaN(n));
}

function normalizeBaseUrl(url: string): string {
  const trimmed = url.trim().replace(/\/+$/, "");
  try {
    const u = new URL(trimmed);
    u.hostname = u.hostname.toLowerCase();
    return u.toString().replace(/\/+$/, "");
  } catch {
    return trimmed.toLowerCase();
  }
}

function emptyForm(type: CrawlSource["type"] = "site_attachments"): FormState {
  return {
    id: "",
    nameEn: "",
    nameZh: "",
    enabled: false,
    priority: "1",
    type,
    baseUrl: "",
    rateLimit: "1.5",
    schedule: "0 6 * * *",
    hosts: "",
    exts: ".pdf, .doc, .docx, .xls, .xlsx",
    seeds: "",
    paths: "",
    maxPages: "500",
    langs: "2, 1",
    yearFrom: "2025",
    yearTo: "2026",
  };
}

function sourceToForm(s: CrawlSource): FormState {
  return {
    id: s.id,
    nameEn: s.name.en,
    nameZh: s.name["zh-HK"],
    enabled: s.enabled,
    priority: String(s.priority),
    type: s.type,
    baseUrl: s.base_url,
    rateLimit: String(s.rate_limit_seconds),
    schedule: s.schedule,
    hosts: (s.allow_hosts || []).join(", "),
    exts: (s.file_extensions || []).join(", "),
    seeds: (s.seed_urls || []).join(", "),
    paths: (s.path_prefixes || []).join(", "),
    maxPages: String(s.max_pages ?? 500),
    langs: (s.langs || []).join(", "),
    yearFrom: String(s.year_from ?? 2025),
    yearTo: String(s.year_to ?? 2026),
  };
}

function formToSource(form: FormState): CrawlSource {
  const source: CrawlSource = {
    id: form.id.trim(),
    name: { en: form.nameEn.trim(), "zh-HK": form.nameZh.trim() },
    enabled: form.enabled,
    priority: parseInt(form.priority, 10) || 0,
    type: form.type,
    base_url: form.baseUrl.trim(),
    rate_limit_seconds: parseFloat(form.rateLimit) || 1.5,
    schedule: form.schedule.trim(),
  };

  if (form.type === "site_attachments") {
    source.allow_hosts = splitCsv(form.hosts);
    source.file_extensions = splitCsv(form.exts);
    const seeds = splitCsv(form.seeds);
    if (seeds.length) source.seed_urls = seeds;
    const paths = splitCsv(form.paths);
    if (paths.length) source.path_prefixes = paths;
    const maxPages = parseInt(form.maxPages, 10);
    source.max_pages = Number.isNaN(maxPages) ? 500 : maxPages;
  } else {
    source.langs = splitIntCsv(form.langs);
    source.year_from = parseInt(form.yearFrom, 10) || 2025;
    source.year_to = parseInt(form.yearTo, 10) || 2026;
  }

  return source;
}

export default function SourcesSection({ token }: Props) {
  const t = useTranslations("settings");

  const [sources, setSources] = useState<CrawlSource[]>([]);
  const [savedJson, setSavedJson] = useState("[]");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const [editorMode, setEditorMode] = useState<EditorMode>("closed");
  const [editingOriginalId, setEditingOriginalId] = useState<string | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm());

  const [aiMode, setAiMode] = useState<"topic" | "url">("topic");
  const [aiQuery, setAiQuery] = useState("");
  const [suggesting, setSuggesting] = useState(false);
  const [suggestions, setSuggestions] = useState<CrawlSource[]>([]);
  const [selectedSuggestionIds, setSelectedSuggestionIds] = useState<Set<string>>(new Set());
  const [dropped, setDropped] = useState(0);
  const [suggestError, setSuggestError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    getSourceConfig(token)
      .then((res) => {
        if (cancelled) return;
        setSources(res.sources);
        setSavedJson(JSON.stringify(res.sources));
      })
      .catch(() => {
        if (!cancelled) setError(t("sourcesLoadError"));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token, t]);

  const dirty = useMemo(() => JSON.stringify(sources) !== savedJson, [sources, savedJson]);

  const existingKeys = useMemo(() => {
    const ids = new Set(sources.map((s) => s.id));
    const urls = new Set(sources.map((s) => normalizeBaseUrl(s.base_url)));
    return { ids, urls };
  }, [sources]);

  const visibleSuggestions = useMemo(
    () =>
      suggestions.filter(
        (s) => !existingKeys.ids.has(s.id) && !existingKeys.urls.has(normalizeBaseUrl(s.base_url)),
      ),
    [suggestions, existingKeys],
  );

  function updateForm<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function openAdd() {
    setEditorMode("add");
    setEditingOriginalId(null);
    setForm(emptyForm());
    setSuccess("");
  }

  function openEdit(source: CrawlSource) {
    setEditorMode("edit");
    setEditingOriginalId(source.id);
    setForm(sourceToForm(source));
    setSuccess("");
  }

  function closeEditor() {
    setEditorMode("closed");
    setEditingOriginalId(null);
  }

  function onToggleEnabled(id: string, enabled: boolean) {
    setSources((prev) => prev.map((s) => (s.id === id ? { ...s, enabled } : s)));
    setSuccess("");
  }

  function onDelete(id: string) {
    setSources((prev) => prev.filter((s) => s.id !== id));
    if (editingOriginalId === id) closeEditor();
    setSuccess("");
  }

  function onSubmitEditor(e: FormEvent) {
    e.preventDefault();
    const next = formToSource(form);
    if (!next.id || !next.base_url) return;

    if (editorMode === "add") {
      setSources((prev) => [...prev, { ...next, enabled: false }]);
    } else if (editingOriginalId) {
      setSources((prev) =>
        prev.map((s) => (s.id === editingOriginalId ? { ...next, enabled: form.enabled } : s)),
      );
    }
    closeEditor();
    setSuccess("");
  }

  async function onSave() {
    if (!dirty || saving) return;
    setSaving(true);
    setError("");
    setSuccess("");
    try {
      const res = await saveSourceConfig(token, sources);
      setSources(res.sources);
      setSavedJson(JSON.stringify(res.sources));
      setSuccess(t("sourcesSaved"));
    } catch {
      setError(t("sourcesSaveError"));
    } finally {
      setSaving(false);
    }
  }

  async function onSuggest() {
    const query = aiQuery.trim();
    if (!query || suggesting) return;
    setSuggesting(true);
    setSuggestError("");
    setDropped(0);
    try {
      const res = await suggestSources(token, { mode: aiMode, query });
      setSuggestions(res.suggestions.map((s) => ({ ...s, enabled: false })));
      setSelectedSuggestionIds(new Set());
      setDropped(res.dropped);
    } catch {
      setSuggestError(t("sourcesSuggestError"));
    } finally {
      setSuggesting(false);
    }
  }

  function toggleSuggestion(id: string, checked: boolean) {
    setSelectedSuggestionIds((prev) => {
      const next = new Set(prev);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  function addSelectedSuggestions() {
    const toAdd = visibleSuggestions
      .filter((s) => selectedSuggestionIds.has(s.id))
      .map((s) => ({ ...s, enabled: false }));
    if (!toAdd.length) return;
    const addedIds = new Set(toAdd.map((s) => s.id));
    setSources((prev) => [...prev, ...toAdd]);
    setSuggestions((prev) => prev.filter((s) => !addedIds.has(s.id)));
    setSelectedSuggestionIds(new Set());
    setSuccess("");
  }

  const idDisabled = editorMode === "edit";

  return (
    <div className="panel" style={{ marginBottom: "1rem" }}>
      <h2 style={{ marginTop: 0, color: "var(--blue-900)" }}>{t("sourcesTitle")}</h2>
      <p className="hint" style={{ marginTop: 0 }}>
        {t("sourcesHint")}
      </p>

      <div style={{ display: "flex", gap: "0.75rem", alignItems: "center", flexWrap: "wrap", marginBottom: "1rem" }}>
        <button className="btn" type="button" onClick={openAdd}>
          {t("sourcesAdd")}
        </button>
        <button className="btn" type="button" onClick={onSave} disabled={!dirty || saving || loading}>
          {saving ? t("saving") : t("sourcesSave")}
        </button>
        {success ? (
          <span className="hint" style={{ color: "var(--teal-500)", fontWeight: 600 }}>
            {success}
          </span>
        ) : null}
        {error ? <span className="error">{error}</span> : null}
        {loading ? <span className="hint">{t("loading")}</span> : null}
      </div>

      <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
        {sources.map((s) => (
          <li
            key={s.id}
            style={{
              display: "flex",
              flexWrap: "wrap",
              gap: "0.75rem",
              alignItems: "center",
              padding: "0.65rem 0",
              borderBottom: "1px solid var(--border, rgba(15, 23, 42, 0.08))",
            }}
          >
            <label style={{ display: "flex", alignItems: "center", gap: "0.4rem", margin: 0 }}>
              <input
                type="checkbox"
                checked={s.enabled}
                onChange={(e) => onToggleEnabled(s.id, e.target.checked)}
              />
              <span>{t("sourcesEnabled")}</span>
            </label>
            <span style={{ fontWeight: 600, minWidth: "8rem" }}>{s.name["zh-HK"]}</span>
            <code style={{ fontSize: "0.85rem" }}>{s.id}</code>
            <span className="hint">{s.type}</span>
            <button className="btn" type="button" onClick={() => openEdit(s)} style={{ marginLeft: "auto" }}>
              {t("sourcesEdit")}
            </button>
            <button className="btn" type="button" onClick={() => onDelete(s.id)}>
              {t("sourcesDelete")}
            </button>
          </li>
        ))}
      </ul>

      {editorMode !== "closed" ? (
        <form
          onSubmit={onSubmitEditor}
          style={{ marginTop: "1rem", paddingTop: "1rem", borderTop: "1px solid var(--border, rgba(15, 23, 42, 0.08))" }}
        >
          <div className="field">
            <label htmlFor="src-id">{t("sourcesId")}</label>
            <input
              id="src-id"
              value={form.id}
              onChange={(e) => updateForm("id", e.target.value)}
              disabled={idDisabled}
              required
            />
          </div>
          <div className="field">
            <label htmlFor="src-name-en">{t("sourcesNameEn")}</label>
            <input
              id="src-name-en"
              value={form.nameEn}
              onChange={(e) => updateForm("nameEn", e.target.value)}
              required
            />
          </div>
          <div className="field">
            <label htmlFor="src-name-zh">{t("sourcesNameZh")}</label>
            <input
              id="src-name-zh"
              value={form.nameZh}
              onChange={(e) => updateForm("nameZh", e.target.value)}
              required
            />
          </div>
          <div className="field">
            <label htmlFor="src-type">{t("sourcesType")}</label>
            <select
              id="src-type"
              value={form.type}
              onChange={(e) => updateForm("type", e.target.value as CrawlSource["type"])}
            >
              <option value="site_attachments">site_attachments</option>
              <option value="circular_aspnet">circular_aspnet</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="src-base">{t("sourcesBaseUrl")}</label>
            <input
              id="src-base"
              value={form.baseUrl}
              onChange={(e) => updateForm("baseUrl", e.target.value)}
              required
            />
          </div>
          <div className="field">
            <label htmlFor="src-rate">{t("sourcesRateLimit")}</label>
            <input
              id="src-rate"
              type="number"
              step="0.1"
              min="0.5"
              value={form.rateLimit}
              onChange={(e) => updateForm("rateLimit", e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="src-schedule">{t("sourcesSchedule")}</label>
            <input
              id="src-schedule"
              value={form.schedule}
              onChange={(e) => updateForm("schedule", e.target.value)}
              required
            />
          </div>
          <div className="field">
            <label htmlFor="src-priority">{t("sourcesPriority")}</label>
            <input
              id="src-priority"
              type="number"
              min="0"
              max="9"
              value={form.priority}
              onChange={(e) => updateForm("priority", e.target.value)}
            />
          </div>
          {editorMode === "edit" ? (
            <div className="field" style={{ flexDirection: "row", alignItems: "center", gap: "0.5rem" }}>
              <input
                id="src-enabled"
                type="checkbox"
                checked={form.enabled}
                onChange={(e) => updateForm("enabled", e.target.checked)}
              />
              <label htmlFor="src-enabled" style={{ margin: 0 }}>
                {t("sourcesEnabled")}
              </label>
            </div>
          ) : null}

          {form.type === "site_attachments" ? (
            <>
              <div className="field">
                <label htmlFor="src-hosts">{t("sourcesHosts")}</label>
                <input
                  id="src-hosts"
                  value={form.hosts}
                  onChange={(e) => updateForm("hosts", e.target.value)}
                />
              </div>
              <div className="field">
                <label htmlFor="src-exts">{t("sourcesExts")}</label>
                <input
                  id="src-exts"
                  value={form.exts}
                  onChange={(e) => updateForm("exts", e.target.value)}
                />
              </div>
              <div className="field">
                <label htmlFor="src-seeds">{t("sourcesSeeds")}</label>
                <input
                  id="src-seeds"
                  value={form.seeds}
                  onChange={(e) => updateForm("seeds", e.target.value)}
                />
              </div>
              <div className="field">
                <label htmlFor="src-paths">{t("sourcesPaths")}</label>
                <input
                  id="src-paths"
                  value={form.paths}
                  onChange={(e) => updateForm("paths", e.target.value)}
                />
              </div>
              <div className="field">
                <label htmlFor="src-max">{t("sourcesMaxPages")}</label>
                <input
                  id="src-max"
                  type="number"
                  min="1"
                  max="5000"
                  value={form.maxPages}
                  onChange={(e) => updateForm("maxPages", e.target.value)}
                />
              </div>
            </>
          ) : (
            <>
              <div className="field">
                <label htmlFor="src-langs">{t("sourcesLangs")}</label>
                <input
                  id="src-langs"
                  value={form.langs}
                  onChange={(e) => updateForm("langs", e.target.value)}
                />
              </div>
              <div className="field">
                <label htmlFor="src-year-from">{t("sourcesYearFrom")}</label>
                <input
                  id="src-year-from"
                  type="number"
                  value={form.yearFrom}
                  onChange={(e) => updateForm("yearFrom", e.target.value)}
                />
              </div>
              <div className="field">
                <label htmlFor="src-year-to">{t("sourcesYearTo")}</label>
                <input
                  id="src-year-to"
                  type="number"
                  value={form.yearTo}
                  onChange={(e) => updateForm("yearTo", e.target.value)}
                />
              </div>
            </>
          )}

          <div style={{ display: "flex", gap: "0.75rem", marginTop: "0.5rem" }}>
            <button className="btn" type="submit">
              {editorMode === "add" ? t("sourcesAdd") : t("sourcesEdit")}
            </button>
            <button className="btn" type="button" onClick={closeEditor}>
              {t("sourcesCancel")}
            </button>
          </div>
        </form>
      ) : null}

      <section style={{ marginTop: "1.5rem", paddingTop: "1rem", borderTop: "1px solid var(--border, rgba(15, 23, 42, 0.08))" }}>
        <h3 style={{ marginTop: 0, color: "var(--blue-900)" }}>{t("sourcesAi")}</h3>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem", alignItems: "flex-end", marginBottom: "0.75rem" }}>
          <div className="field" style={{ marginBottom: 0, minWidth: "8rem" }}>
            <label htmlFor="ai-mode">{t("sourcesAi")}</label>
            <select
              id="ai-mode"
              value={aiMode}
              onChange={(e) => setAiMode(e.target.value as "topic" | "url")}
            >
              <option value="topic">{t("sourcesModeTopic")}</option>
              <option value="url">{t("sourcesModeUrl")}</option>
            </select>
          </div>
          <div className="field" style={{ marginBottom: 0, flex: "1 1 16rem" }}>
            <label htmlFor="ai-query">
              {aiMode === "topic" ? t("sourcesModeTopic") : t("sourcesModeUrl")}
            </label>
            <input
              id="ai-query"
              value={aiQuery}
              onChange={(e) => setAiQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  onSuggest();
                }
              }}
            />
          </div>
          <button className="btn" type="button" onClick={onSuggest} disabled={suggesting || !aiQuery.trim()}>
            {suggesting ? t("sourcesSearching") : t("sourcesSearch")}
          </button>
        </div>
        {suggestError ? <p className="error">{suggestError}</p> : null}
        {dropped > 0 ? <p className="hint">{t("sourcesDropped", { count: dropped })}</p> : null}

        {visibleSuggestions.length > 0 ? (
          <>
            <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {visibleSuggestions.map((s) => (
                <li
                  key={s.id}
                  style={{
                    display: "flex",
                    flexWrap: "wrap",
                    gap: "0.75rem",
                    alignItems: "center",
                    padding: "0.5rem 0",
                  }}
                >
                  <input
                    type="checkbox"
                    checked={selectedSuggestionIds.has(s.id)}
                    onChange={(e) => toggleSuggestion(s.id, e.target.checked)}
                  />
                  <span style={{ fontWeight: 600 }}>{s.name["zh-HK"] || s.name.en}</span>
                  <code style={{ fontSize: "0.85rem" }}>{s.id}</code>
                  <span className="hint">{s.type}</span>
                  <span className="hint" style={{ wordBreak: "break-all" }}>
                    {s.base_url}
                  </span>
                </li>
              ))}
            </ul>
            <button className="btn" type="button" onClick={addSelectedSuggestions} style={{ marginTop: "0.5rem" }}>
              {t("sourcesAddSelected")}
            </button>
          </>
        ) : null}
      </section>
    </div>
  );
}
