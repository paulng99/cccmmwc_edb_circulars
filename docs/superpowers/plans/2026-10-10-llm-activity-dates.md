# LLM activity dates (void local regex for calendar) — Implementation Plan

> **For agentic workers:** Implement task-by-task. Prefer tests before code where practical.

**Goal:** Replace local regex calendar date extraction for display and full-library backfill with LLM extraction of start/deadline activities. On failure, omit dates (no regex fallback, no UI「未有」). While backfill runs, calendar/homepage show「日期更新中」.

**Binding approval:** Paul「同意送出日期」in EDB room. Accuracy remains 未驗證 until UR rechecks EDBCM 140/2026 and 136/2026.

**Architecture:**
- Shared LLM activities helper (same `get_llm_client()` / answer-model as reanalyze).
- Bump `Document.extra.activities_parsed` to `llm-1`; clear stale local activities at backfill start.
- Persist `activities_llm_backfill` on `AppSetting.values` (`in_progress` | `done`); calendar APIs expose `dates_updating`.
- Ingest always runs LLM dates; school-action auto-analyze stays gated by source setting.
- No regex fallback on LLM failure for calendar/display paths.

**Out of scope:** Merge/deploy; reanalyze school-action prompts; permanent calendar hide; claiming real-library accuracy verified.

## File map

| File | Role |
|------|------|
| `apps/api/app/services/llm_activities.py` | Prompt, parse, call LLM, apply (no regex) |
| `apps/api/app/services/activity_dates.py` | Prepare + run full-library LLM backfill; status helpers |
| `apps/api/app/services/reanalyze.py` | Use LLM-only activities; drop regex fallback |
| `apps/api/app/services/rag.py` | Ingest: LLM dates instead of `apply_document_activities` |
| `apps/api/app/bootstrap.py` / `main.py` / `worker.py` | Clear stale + background/celery backfill |
| `apps/api/app/api/documents.py` | `dates_updating` on calendar endpoints |
| `apps/api/app/services/runtime_settings.py` | Preserve non-editable AppSetting keys |
| `apps/web` calendar/home + document activity rows + i18n | Backfill copy; hide null date rows |
| `apps/api/tests/test_llm_activities.py` (+ reanalyze/rag updates) | Multi-activity success, failure omits, backfill flag, ingest |

## Tasks

1. Tests for LLM extract / failure / backfill status / ingest path  
2. Implement `llm_activities` + wire reanalyze/backfill/ingest  
3. API `dates_updating` + web UX  
4. pytest + web tsc; PR with scope + 未驗證
