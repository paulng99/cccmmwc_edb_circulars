# Crawl Live Progress + Gentle Stop — Design

Date: 2026-09-23  
Status: Approved for planning  
Locale: en + zh-HK; datetimes `yyyy-mm-dd HH:mm:ss` (Asia/Hong_Kong)

## Goal

On `/[locale]/status`, while a crawl is running, operators can see **which site/page/file is being processed** (current item + recent activity list) and can **gently stop** the crawl (finish the current file, then halt). Already-downloaded documents are kept.

## Decisions (locked)

| Topic | Choice |
|-------|--------|
| Live detail | Current item + recent ~40 events (UI); full event history stored |
| Storage | Dedicated `crawl_events` table (not JSONB-only on run) |
| Stop | Gentle: set `cancel_requested`; worker checks between files; status → `cancelled` |
| Auth | Same as today: any authenticated user |

## Non-goals

- Hard-kill / revoke mid-download HTTP (may add later)
- Streaming WebSocket (keep 2s poll)
- Full event UI for completed runs (recent runs stay summary-only; optional later)
- Per-file retry from UI

---

## Data model

### `crawl_events`

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | |
| `run_id` | UUID FK → `crawl_runs.id` ON DELETE CASCADE | indexed |
| `event_type` | `String(32)` | see enum below |
| `url` | `Text` nullable | page or file URL |
| `title` | `String(1024)` nullable | human label when known |
| `source_id` | `String(64)` nullable | denormalized for display |
| `created_at` | `timestamptz` | server default now() |

**Event types:** `discovering` | `page` | `download_start` | `download_ok` | `download_fail` | `done` | `cancelled`

### `crawl_runs` additions

| Column | Type | Notes |
|--------|------|-------|
| `cancel_requested` | `Boolean` default `false` | set by Stop API |
| `celery_task_id` | `String(64)` nullable | optional; store when enqueueing |

Bootstrap: `create_all` for new table; `ALTER TABLE crawl_runs ADD COLUMN IF NOT EXISTS cancel_requested ...` and `celery_task_id` (same pattern as `progress_message`).

---

## Backend behaviour

### Emit events (`pipeline` / collectors)

During `run_source_crawl` / file loop:

1. Run start → insert `discovering` (+ keep updating `progress_message` as today)
2. When listing/walking pages → `page` with page URL (rate-limit: do not flood; emit at meaningful page visits, not every tiny hop if high volume — prefer BFS “new page queued/fetched” at most once per unique page URL per run)
3. Before each file download → `download_start` (url, title)
4. After success/fail → `download_ok` / `download_fail`
5. Normal completion → `done`; gentle stop → `cancelled`

Event insert failures: log and continue crawl (do not fail the run solely for event I/O).

### Cancel checks

Before starting each new file download (and at start of each source in multi-source crawl):

- Reload run row (or query `cancel_requested`)
- If true: set `status=cancelled`, set `progress_message` / finished_at, insert `cancelled` event, break out of remaining files for that run
- Current in-flight download may complete; no new downloads after the flag is seen

### API

**`GET /api/ingest/status`** (extend existing)

For each item in `recent_runs` (especially `running`), attach:

```json
{
  "current": { "event_type": "...", "url": "...", "title": "...", "created_at": "..." } | null,
  "recent_events": [ /* up to 40 newest events for this run, newest first */ ],
  "cancel_requested": false
}
```

`current` = newest event among types `discovering` | `page` | `download_start` that is not yet superseded by a terminal outcome for that same file; practical rule: **newest event overall that is `download_start`, else newest `page`, else newest `discovering`**.

**`POST /api/ingest/crawl/stop`**

- Auth required
- Optional query/body `run_id`; if omitted, mark **all** `status=running` runs with `cancel_requested=true`
- Response: `{ "ok": true, "stopped": <count of runs flagged> }`
- If none running: `{ "ok": true, "stopped": 0 }`

**`POST /api/ingest/crawl`** (existing)

- When enqueueing, persist `celery_task_id` on the run if the run row is created before delay — if run is created inside worker, store task id on the API side only when a run id is known; otherwise skip (optional field). Prefer: worker creates run then updates `celery_task_id` is awkward; store task id from API only if we create a placeholder run in API. **YAGNI:** leave `celery_task_id` nullable unused in v1 if enqueue remains worker-created; column reserved for later hard-stop.

Clarify for implementers: **v1 Stop uses only `cancel_requested` on DB runs**; `celery_task_id` column may be added but not required to populate.

---

## Frontend (`status/page.tsx`)

### Live panel (when busy / running runs)

- Source name, status chip, counts, progress bar (existing)
- **Current:** label + url/title from `current`
- **Recent activity:** scrollable list (~max-height), up to 40 events; each row: HK datetime, type chip, title or truncated URL
- Buttons: **Stop crawl** (enabled when busy) + existing Crawl
- After Stop: show “Stopping after current file…”; keep polling until run leaves `running`

### i18n (`en` + `zh-HK`)

Keys at minimum: `stop`, `stopping`, `cancelled`, `currentFile`, `recentActivity`, `eventDiscovering`, `eventPage`, `eventDownloadStart`, `eventDownloadOk`, `eventDownloadFail`, `eventDone`, `eventCancelled`, `stopNone`

### API client

- `stopCrawl(token, runId?: string)` → `POST /api/ingest/crawl/stop`

---

## Testing (minimal)

1. Unit/service: emit event helper inserts row; cancel flag stops further downloads in a mocked loop
2. Manual: start crawl → see current URL + growing recent list; press Stop → after current file, run `cancelled`, no new downloads; documents already saved remain
3. Stop with no running run → `stopped: 0`

---

## File map

| Layer | Path |
|-------|------|
| Model | `apps/api/app/models/entities.py` (`CrawlEvent`, `CrawlRun` columns) |
| Bootstrap ALTER | `apps/api/app/bootstrap.py` |
| Pipeline emit + cancel | `apps/api/app/services/pipeline.py` (+ collectors if page events) |
| API status + stop | `apps/api/app/api/system.py` |
| Web status UI | `apps/web/src/app/[locale]/status/page.tsx` |
| API helpers / i18n | `apps/web/src/lib/api.ts`, `messages/en.json`, `zh-HK.json` |

## Out of scope follow-ups

- Hard revoke Celery task mid-download
- WebSocket push
- Event history viewer for finished runs
- Admin-only stop
