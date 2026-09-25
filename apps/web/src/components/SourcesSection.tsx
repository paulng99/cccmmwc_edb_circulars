"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import {
  CrawlSource,
  getSourceConfig,
  saveSourceConfig,
  suggestSources,
} from "@/lib/api";
import { Icon } from "@/components/Icon";
import { Switch } from "@/components/Switch";

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

/** Surface FastAPI `{detail}` from `throw new Error(await res.text())`; keep i18n fallbacks. */
function apiErrorMessage(err: unknown, fallback: string, jinaMessage: string): string {
  const raw = (err instanceof Error ? err.message : String(err ?? "")).trim();
  if (!raw) return fallback;
  try {
    const parsed = JSON.parse(raw) as { detail?: unknown };
    const detail = parsed?.detail;
    if (detail === "jina_not_configured") return jinaMessage;
    if (detail === "suggest_timeout" || detail === "suggest_failed") return fallback;
    if (typeof detail === "string" && detail.trim()) return detail;
    if (detail != null) return typeof detail === "string" ? detail : JSON.stringify(detail);
  } catch {
    return raw;
  }
  return raw;
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
  const [editorError, setEditorError] = useState("");
  const [form, setForm] = useState<FormState>(emptyForm());
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);

  const [aiMode, setAiMode] = useState<"topic" | "url">("topic");
  const [aiQuery, setAiQuery] = useState("");
  const [suggesting, setSuggesting] = useState(false);
  const [aiOpen, setAiOpen] = useState(false);
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

  useEffect(() => {
    if (editorMode === "closed" && !aiOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeDrawer();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editorMode, aiOpen]);

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
    if (key === "id") setEditorError("");
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function openAdd() {
    setAiOpen(false);
    setEditorMode("add");
    setEditingOriginalId(null);
    setEditorError("");
    setForm(emptyForm());
    setSuccess("");
  }

  function openEdit(source: CrawlSource) {
    setAiOpen(false);
    setEditorMode("edit");
    setEditingOriginalId(source.id);
    setEditorError("");
    setForm(sourceToForm(source));
    setSuccess("");
  }

  function closeEditor() {
    setEditorMode("closed");
    setEditingOriginalId(null);
    setEditorError("");
  }

  function closeDrawer() {
    closeEditor();
    setAiOpen(false);
  }

  function onToggleEnabled(id: string, enabled: boolean) {
    setSources((prev) => prev.map((s) => (s.id === id ? { ...s, enabled } : s)));
    setSuccess("");
  }

  function onDelete(id: string) {
    setSources((prev) => prev.filter((s) => s.id !== id));
    if (editingOriginalId === id) closeEditor();
    setPendingDelete(null);
    setSuccess("");
  }

  function onSubmitEditor(e: FormEvent) {
    e.preventDefault();
    const next = formToSource(form);
    if (!next.id || !next.base_url) return;

    if (editorMode === "add") {
      if (sources.some((s) => s.id === next.id)) {
        setEditorError(t("sourcesDuplicateId"));
        return;
      }
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
    } catch (err) {
      setError(apiErrorMessage(err, t("sourcesSaveError"), t("sourcesSuggestError")));
    } finally {
      setSaving(false);
    }
  }

  function onDiscard() {
    try {
      setSources(JSON.parse(savedJson) as CrawlSource[]);
    } catch {
      /* ignore */
    }
    setSuccess("");
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
    } catch (err) {
      setSuggestError(apiErrorMessage(err, t("sourcesSuggestFailed"), t("sourcesSuggestError")));
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
  const enabledCount = sources.filter((s) => s.enabled).length;

  return (
    <>
      <div className="settings-savebar">
        <button className="btn" type="button" onClick={openAdd}>
          <Icon name="plus" />
          {t("sourcesAdd")}
        </button>
        <button
          className="btn soft"
          type="button"
          onClick={() => {
            closeEditor();
            setAiOpen(true);
          }}
        >
          <Icon name="wand" />
          {t("sourcesAi")}
        </button>
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
        {dirty && !success ? <span className="savebar-status">{t("sourcesUnsaved")}</span> : null}
        {dirty ? (
          <button className="btn ghost" type="button" onClick={onDiscard} disabled={saving}>
            {t("discard")}
          </button>
        ) : null}
        <button className="btn" type="button" onClick={onSave} disabled={!dirty || saving || loading}>
          {saving ? <span className="spinner" /> : <Icon name="check" />}
          {saving ? t("saving") : t("sourcesSave")}
        </button>
      </div>

      <section className="card" style={{ marginTop: "1rem" }}>
        <div className="card-head">
          <h2>
            <Icon name="database" />
            {t("sourcesTitle")}
            <span className="count">{t("sourcesEnabledCount", { enabled: enabledCount, total: sources.length })}</span>
          </h2>
        </div>
        <div className="card-pad" style={{ paddingBottom: 0 }}>
          <p className="section-desc">{t("sourcesHint")}</p>
        </div>

        {loading ? (
          <ul className="source-list" aria-busy="true">
            {Array.from({ length: 3 }, (_, i) => (
              <li key={i} className="source-row">
                <span className="skeleton" style={{ width: 40, height: 22, borderRadius: 999 }} />
                <div className="row-main">
                  <span className="skeleton" style={{ height: "0.95rem", width: `${45 + i * 10}%` }} />
                  <span className="skeleton" style={{ height: "0.75rem", width: "30%" }} />
                </div>
              </li>
            ))}
          </ul>
        ) : sources.length === 0 ? (
          <div className="empty">
            <div className="empty-icon">
              <Icon name="database" />
            </div>
            <h3>{t("sourcesEmptyTitle")}</h3>
            <p>{t("sourcesEmptyHint")}</p>
            <div className="empty-actions">
              <button className="btn" type="button" onClick={openAdd}>
                <Icon name="plus" />
                {t("sourcesAdd")}
              </button>
            </div>
          </div>
        ) : (
          <ul className="source-list">
            {sources.map((s) => (
              <li key={s.id} className={`source-row${s.enabled ? "" : " disabled"}`}>
                <Switch
                  checked={s.enabled}
                  onChange={(v) => onToggleEnabled(s.id, v)}
                  label={`${t("sourcesEnabled")}: ${s.name["zh-HK"] || s.name.en}`}
                />
                <div className="row-main">
                  <div className="row-title">
                    {s.name["zh-HK"] || s.name.en}
                    <code>{s.id}</code>
                    <span className={`badge ${s.type === "circular_aspnet" ? "blue" : "teal"}`}>
                      {s.type === "circular_aspnet" ? t("typeCircular") : t("typeSite")}
                    </span>
                  </div>
                  <div className="row-sub">
                    <span title={s.base_url}>
                      <Icon name="link" />
                      {s.base_url}
                    </span>
                    <span>
                      <Icon name="clock" />
                      {s.schedule}
                    </span>
                  </div>
                </div>
                <div className="row-actions">
                  {pendingDelete === s.id ? (
                    <>
                      <span className="muted" style={{ fontSize: "0.8rem" }}>
                        {t("sourcesDeleteConfirm")}
                      </span>
                      <button className="btn danger sm" type="button" onClick={() => onDelete(s.id)}>
                        <Icon name="trash" />
                        {t("sourcesDelete")}
                      </button>
                      <button className="btn ghost sm" type="button" onClick={() => setPendingDelete(null)}>
                        {t("sourcesCancel")}
                      </button>
                    </>
                  ) : (
                    <>
                      <button className="btn secondary sm" type="button" onClick={() => openEdit(s)}>
                        <Icon name="pencil" />
                        {t("sourcesEdit")}
                      </button>
                      <button
                        className="btn ghost sm icon-only"
                        type="button"
                        onClick={() => setPendingDelete(s.id)}
                        aria-label={t("sourcesDelete")}
                        title={t("sourcesDelete")}
                      >
                        <Icon name="trash" />
                      </button>
                    </>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      {editorMode !== "closed" || aiOpen ? <div className="drawer-backdrop" onClick={closeDrawer} /> : null}

      {editorMode !== "closed" ? (
        <form className="drawer" onSubmit={onSubmitEditor} role="dialog" aria-modal="true" aria-labelledby="src-drawer-title">
          <div className="drawer-head">
            <div>
              <h3 id="src-drawer-title">{editorMode === "add" ? t("sourcesAddTitle") : t("sourcesEditTitle")}</h3>
              <p>{editorMode === "add" ? t("sourcesAddHint") : form.id}</p>
            </div>
            <button type="button" className="btn ghost sm icon-only" onClick={closeDrawer} aria-label={t("sourcesCancel")}>
              <Icon name="x" />
            </button>
          </div>

          <div className="drawer-body">
            <div className="drawer-section">{t("sectionBasics")}</div>
            <div className="field">
              <label htmlFor="src-id">{t("sourcesId")}</label>
              <input
                id="src-id"
                value={form.id}
                onChange={(e) => updateForm("id", e.target.value)}
                disabled={idDisabled}
                required
                placeholder="e.g. edb_circulars"
              />
            </div>
            <div className="field-grid">
              <div className="field">
                <label htmlFor="src-name-zh">{t("sourcesNameZh")}</label>
                <input id="src-name-zh" value={form.nameZh} onChange={(e) => updateForm("nameZh", e.target.value)} required />
              </div>
              <div className="field">
                <label htmlFor="src-name-en">{t("sourcesNameEn")}</label>
                <input id="src-name-en" value={form.nameEn} onChange={(e) => updateForm("nameEn", e.target.value)} required />
              </div>
            </div>
            <div className="field">
              <label htmlFor="src-type">{t("sourcesType")}</label>
              <select id="src-type" value={form.type} onChange={(e) => updateForm("type", e.target.value as CrawlSource["type"])}>
                <option value="site_attachments">{t("typeSite")} (site_attachments)</option>
                <option value="circular_aspnet">{t("typeCircular")} (circular_aspnet)</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="src-base">{t("sourcesBaseUrl")}</label>
              <div className="input-wrap">
                <Icon name="link" />
                <input id="src-base" value={form.baseUrl} onChange={(e) => updateForm("baseUrl", e.target.value)} required placeholder="https://" />
              </div>
            </div>
            {editorMode === "edit" ? (
              <div className="switch-row">
                <div className="switch-row-text">
                  <strong>{t("sourcesEnabled")}</strong>
                  <span>{t("sourcesEnabledHint")}</span>
                </div>
                <Switch checked={form.enabled} onChange={(v) => updateForm("enabled", v)} label={t("sourcesEnabled")} />
              </div>
            ) : null}

            <div className="drawer-section">{t("sectionSchedule")}</div>
            <div className="field-grid">
              <div className="field">
                <label htmlFor="src-schedule">{t("sourcesSchedule")}</label>
                <input id="src-schedule" value={form.schedule} onChange={(e) => updateForm("schedule", e.target.value)} required />
                <span className="field-hint">{t("sourcesScheduleHint")}</span>
              </div>
              <div className="field">
                <label htmlFor="src-rate">{t("sourcesRateLimit")}</label>
                <input id="src-rate" type="number" step="0.1" min="0.5" value={form.rateLimit} onChange={(e) => updateForm("rateLimit", e.target.value)} />
              </div>
              <div className="field">
                <label htmlFor="src-priority">{t("sourcesPriority")}</label>
                <input id="src-priority" type="number" min="0" max="9" value={form.priority} onChange={(e) => updateForm("priority", e.target.value)} />
                <span className="field-hint">{t("sourcesPriorityHint")}</span>
              </div>
            </div>

            <div className="drawer-section">{t("sectionCrawlRules")}</div>
            {form.type === "site_attachments" ? (
              <>
                <div className="field">
                  <label htmlFor="src-hosts">{t("sourcesHosts")}</label>
                  <input id="src-hosts" value={form.hosts} onChange={(e) => updateForm("hosts", e.target.value)} />
                </div>
                <div className="field">
                  <label htmlFor="src-exts">{t("sourcesExts")}</label>
                  <input id="src-exts" value={form.exts} onChange={(e) => updateForm("exts", e.target.value)} />
                </div>
                <div className="field">
                  <label htmlFor="src-seeds">{t("sourcesSeeds")}</label>
                  <input id="src-seeds" value={form.seeds} onChange={(e) => updateForm("seeds", e.target.value)} />
                </div>
                <div className="field">
                  <label htmlFor="src-paths">{t("sourcesPaths")}</label>
                  <input id="src-paths" value={form.paths} onChange={(e) => updateForm("paths", e.target.value)} />
                </div>
                <div className="field">
                  <label htmlFor="src-max">{t("sourcesMaxPages")}</label>
                  <input id="src-max" type="number" min="1" max="5000" value={form.maxPages} onChange={(e) => updateForm("maxPages", e.target.value)} />
                </div>
              </>
            ) : (
              <>
                <div className="field">
                  <label htmlFor="src-langs">{t("sourcesLangs")}</label>
                  <input id="src-langs" value={form.langs} onChange={(e) => updateForm("langs", e.target.value)} />
                </div>
                <div className="field-grid">
                  <div className="field">
                    <label htmlFor="src-year-from">{t("sourcesYearFrom")}</label>
                    <input id="src-year-from" type="number" value={form.yearFrom} onChange={(e) => updateForm("yearFrom", e.target.value)} />
                  </div>
                  <div className="field">
                    <label htmlFor="src-year-to">{t("sourcesYearTo")}</label>
                    <input id="src-year-to" type="number" value={form.yearTo} onChange={(e) => updateForm("yearTo", e.target.value)} />
                  </div>
                </div>
              </>
            )}

            {editorError ? (
              <div className="alert danger" role="alert">
                <Icon name="alert-circle" />
                <span>{editorError}</span>
              </div>
            ) : null}
          </div>

          <div className="drawer-foot">
            <button className="btn ghost" type="button" onClick={closeDrawer}>
              {t("sourcesCancel")}
            </button>
            <button className="btn" type="submit">
              <Icon name="check" />
              {editorMode === "add" ? t("sourcesAdd") : t("sourcesApply")}
            </button>
          </div>
        </form>
      ) : null}

      {aiOpen ? (
        <section className="drawer" role="dialog" aria-modal="true" aria-labelledby="ai-drawer-title">
          <div className="drawer-head">
            <div>
              <h3 id="ai-drawer-title">{t("sourcesAi")}</h3>
              <p>{t("sourcesAiHint")}</p>
            </div>
            <button type="button" className="btn ghost sm icon-only" onClick={closeDrawer} aria-label={t("sourcesCancel")}>
              <Icon name="x" />
            </button>
          </div>

          <div className="drawer-body">
            <div className="field">
              <span className="label" id="ai-mode-label">
                {t("sourcesAiMode")}
              </span>
              <div className="segmented" role="group" aria-labelledby="ai-mode-label">
                <button type="button" aria-pressed={aiMode === "topic"} onClick={() => setAiMode("topic")}>
                  {t("sourcesModeTopic")}
                </button>
                <button type="button" aria-pressed={aiMode === "url"} onClick={() => setAiMode("url")}>
                  {t("sourcesModeUrl")}
                </button>
              </div>
            </div>
            <div className="field">
              <label htmlFor="ai-query">{aiMode === "topic" ? t("sourcesModeTopic") : t("sourcesModeUrl")}</label>
              <div className="input-wrap">
                <Icon name={aiMode === "topic" ? "search" : "link"} />
                <input
                  id="ai-query"
                  value={aiQuery}
                  onChange={(e) => setAiQuery(e.target.value)}
                  placeholder={aiMode === "topic" ? t("sourcesTopicPlaceholder") : "https://"}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      onSuggest();
                    }
                  }}
                />
              </div>
            </div>
            <button className="btn block" type="button" onClick={onSuggest} disabled={suggesting || !aiQuery.trim()}>
              {suggesting ? <span className="spinner" /> : <Icon name="wand" />}
              {suggesting ? t("sourcesSearching") : t("sourcesSearch")}
            </button>

            {suggestError ? (
              <div className="alert danger" role="alert" style={{ marginTop: "0.85rem" }}>
                <Icon name="alert-circle" />
                <span>{suggestError}</span>
              </div>
            ) : null}
            {dropped > 0 ? (
              <div className="alert" style={{ marginTop: "0.85rem" }}>
                <Icon name="info" />
                <span>{t("sourcesDropped", { count: dropped })}</span>
              </div>
            ) : null}

            {visibleSuggestions.length > 0 ? (
              <ul className="suggest-list">
                {visibleSuggestions.map((s) => {
                  const checked = selectedSuggestionIds.has(s.id);
                  return (
                    <li
                      key={s.id}
                      className={`suggest-item${checked ? " selected" : ""}`}
                      onClick={() => toggleSuggestion(s.id, !checked)}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={(e) => toggleSuggestion(s.id, e.target.checked)}
                        onClick={(e) => e.stopPropagation()}
                        aria-label={s.name["zh-HK"] || s.name.en}
                      />
                      <div className="t">
                        <strong>{s.name["zh-HK"] || s.name.en}</strong>
                        <code style={{ alignSelf: "flex-start" }}>{s.id}</code>
                        {/^https?:\/\//i.test(s.base_url) ? (
                          <a href={s.base_url} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()}>
                            {s.base_url}
                          </a>
                        ) : (
                          <span>{s.base_url}</span>
                        )}
                      </div>
                    </li>
                  );
                })}
              </ul>
            ) : null}
          </div>

          <div className="drawer-foot">
            <button className="btn ghost" type="button" onClick={closeDrawer}>
              {t("sourcesCancel")}
            </button>
            <button
              className="btn"
              type="button"
              onClick={addSelectedSuggestions}
              disabled={selectedSuggestionIds.size === 0}
            >
              <Icon name="plus" />
              {t("sourcesAddSelected")}
              {selectedSuggestionIds.size > 0 ? ` (${selectedSuggestionIds.size})` : ""}
            </button>
          </div>
        </section>
      ) : null}
    </>
  );
}
