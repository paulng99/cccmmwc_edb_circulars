# School-action AI icon + activity re-extract — Implementation Plan

> **For agentic workers:** Implement task-by-task. Prefer tests before code where practical.

**Goal:** Replace「未核對」display with AI icon that confirms and re-runs school-action analysis + local activity date extraction.

**Architecture:** Extend `reanalyze_one` to call `apply_document_activities`; strip prefix in web display helpers; detail page sparkles button.

**Tech stack:** FastAPI / SQLAlchemy, Next.js App Router, next-intl, existing `sparkles` Icon.

## File map

| File | Role |
|------|------|
| `apps/api/app/services/reanalyze.py` | Re-extract activities; return them |
| `apps/api/app/api/schemas.py` | `activities` on `ReanalyzeItemOut` |
| `apps/api/app/api/documents.py` | Map activities into response items |
| `apps/api/tests/test_reanalyze.py` | Update / add cases |
| `apps/web/src/lib/school-action.ts` | Strip unverified prefix |
| `apps/web/src/lib/api.ts` | Typed `activities` on reanalyze result |
| `apps/web/src/app/[locale]/documents/[id]/page.tsx` | AI icon + confirm + refresh |
| `apps/web/src/app/[locale]/documents/page.tsx` | Display strip |
| `apps/web/messages/{zh-HK,en}.json` | Confirm / aria strings |
| `apps/web/src/app/globals.css` | Icon button in school-action block |

## Tasks

1. Backend: activities on reanalyze + tests  
2. Web: strip helper + detail AI icon + list display + i18n  
3. Rebuild / smoke check
