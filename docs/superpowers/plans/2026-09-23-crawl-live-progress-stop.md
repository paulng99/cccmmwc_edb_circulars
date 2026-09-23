# Crawl Live Progress + Gentle Stop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let operators on the Status page see the current crawl URL/file plus a recent event list, and gently stop a running crawl (finish current file, then halt).

**Architecture:** New `crawl_events` table stores full event history. Pipeline emits events and checks `crawl_runs.cancel_requested` between file downloads. Status API returns `current` + `recent_events` (40). Stop API flags running runs. Status UI shows live list + Stop button; keep 2s polling.

**Tech Stack:** FastAPI, SQLAlchemy async, Celery worker, Next.js + next-intl (en + zh-HK), pytest.

**Spec:** `docs/superpowers/specs/2026-09-23-crawl-live-progress-stop-design.md`

## Global Constraints

- Locales: `en` + `zh-HK`; display datetimes via `formatHkDateTime` (`yyyy-mm-dd HH:mm:ss`, Asia/Hong_Kong)
- Gentle stop only (no Celery revoke in v1); keep downloaded docs
- Event insert failure must not fail the crawl
- Auth: any logged-in user (same as crawl trigger)
- UI shows current + ~40 recent events; table stores full history
- Preserve existing progress bar / counts / polling

---

## File map

| File | Responsibility |
|------|----------------|
| `apps/api/app/models/entities.py` | `CrawlEvent` model; `CrawlRun.cancel_requested` (+ optional `celery_task_id`) |
| `apps/api/app/models/__init__.py` | Export `CrawlEvent` |
| `apps/api/app/bootstrap.py` | Import model; ALTER columns |
| `apps/api/app/services/crawl_events.py` | `emit_event`, `pick_current`, `list_recent`, `request_cancel` helpers |
| `apps/api/app/services/pipeline.py` | Emit events; cancel check in download loop |
| `apps/api/app/api/system.py` | Extend status payload; `POST /ingest/crawl/stop` |
| `apps/api/tests/test_crawl_events.py` | Unit tests for helpers + cancel loop behaviour (mocked) |
| `apps/web/src/lib/api.ts` | `stopCrawl` |
| `apps/web/messages/en.json`, `zh-HK.json` | Status strings |
| `apps/web/src/app/[locale]/status/page.tsx` | Live current + recent list + Stop button |

---

### Task 1: Model + emit helpers + unit tests

**Files:**
- Create: `apps/api/app/services/crawl_events.py`
- Create: `apps/api/tests/test_crawl_events.py`
- Modify: `apps/api/app/models/entities.py`, `__init__.py`, `bootstrap.py`

**Interfaces:**
- Produces:
  - `CrawlEvent` model
  - `async def emit_event(session, *, run_id, event_type, url=None, title=None, source_id=None) -> None` (swallows errors after log)
  - `def pick_current(events: list[dict]) -> dict | None` — newest `download_start`, else `page`, else `discovering`
  - `async def list_recent(session, run_id, limit=40) -> list[dict]`
  - `async def request_cancel(session, run_id: uuid.UUID | None) -> int` — sets `cancel_requested` on matching running runs; returns count

- [ ] **Step 1: Write failing tests** in `apps/api/tests/test_crawl_events.py`:

```python
from app.services.crawl_events import pick_current

def test_pick_current_prefers_download_start():
    events = [
        {"event_type": "discovering", "url": None},
        {"event_type": "page", "url": "https://a/page"},
        {"event_type": "download_start", "url": "https://a/f.pdf", "title": "F"},
        {"event_type": "download_ok", "url": "https://a/f.pdf"},
    ]
    # newest-first input as returned by list_recent
    newest_first = list(reversed(events))
    cur = pick_current(newest_first)
    assert cur["event_type"] == "download_start"
    assert cur["url"] == "https://a/f.pdf"


def test_pick_current_falls_back_to_page():
    newest_first = [
        {"event_type": "page", "url": "https://a/p"},
        {"event_type": "discovering", "url": None},
    ]
    assert pick_current(newest_first)["event_type"] == "page"


def test_pick_current_empty():
    assert pick_current([]) is None
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
cd apps/api && PYTHONPATH=. .venv/bin/python -m pytest tests/test_crawl_events.py -v
```

(Create `.venv` / install deps if missing, same as settings work.)

- [ ] **Step 3: Add model**

On `CrawlRun` add:
```python
cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
celery_task_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
```

Add:
```python
class CrawlEvent(Base):
    __tablename__ = "crawl_events"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("crawl_runs.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(32))
    url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    source_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

Export + bootstrap import; ALTER:
```sql
ALTER TABLE crawl_runs ADD COLUMN IF NOT EXISTS cancel_requested BOOLEAN DEFAULT FALSE;
ALTER TABLE crawl_runs ADD COLUMN IF NOT EXISTS celery_task_id VARCHAR(64);
```

- [ ] **Step 4: Implement `crawl_events.py` helpers** including `pick_current` to pass tests; `emit_event` try/except log; `list_recent` order by `created_at.desc()` limit 40; `request_cancel` update running rows.

- [ ] **Step 5: Run tests — PASS**

- [ ] **Step 6: Commit**

```bash
git commit -m "feat(crawl): add CrawlEvent model and event helpers"
```

---

### Task 2: Pipeline emit + cancel checks

**Files:**
- Modify: `apps/api/app/services/pipeline.py`
- Modify: `apps/api/tests/test_crawl_events.py` — add mocked cancel-loop test if feasible without full collector

**Interfaces:**
- Consumes: `emit_event`, reload `cancel_requested`
- Produces: events during crawl; cancelled status

- [ ] **Step 1: After creating run**, `await emit_event(..., event_type="discovering", source_id=cfg["id"])`

- [ ] **Step 2: After `discover` returns**, optionally emit one `page` with `cfg["base_url"]` (or first item page_url if present) — keep simple: emit `page` with source `base_url` once after discovery starts counts.

- [ ] **Step 3: In the file loop**, before download:

```python
run = await session.get(CrawlRun, run.id)
if run and run.cancel_requested:
    run.status = "cancelled"
    run.progress_message = "Cancelled by user"
    await emit_event(session, run_id=run.id, event_type="cancelled", source_id=cfg["id"])
    break

await emit_event(..., event_type="download_start", url=item.file_url, title=label, source_id=...)
# download...
await emit_event(..., event_type="download_ok" or "download_fail", ...)
```

- [ ] **Step 4: On normal complete** emit `done`; if status already `cancelled`, skip setting `completed`.

- [ ] **Step 5: At start of each source** in the `for cfg in sources` loop, if previous cancel — still check: for multi-source, before creating next run, check a global flag is awkward; only per-run cancel. If user stopped run A, run B in same `crawl_all` may still start — **spec:** stop flags all *running* runs; for not-yet-started sources in same worker task, check: after cancelling one run, before creating the next CrawlRun, query whether any cancel was requested recently OR pass a local `abort_remaining` flag set when a run cancels. Implement `abort_remaining = True` when a run hits cancel, and `break` out of the sources loop.

- [ ] **Step 6: Commit**

```bash
git commit -m "feat(crawl): emit live events and honour cancel_requested"
```

---

### Task 3: Status + Stop API

**Files:**
- Modify: `apps/api/app/api/system.py`

- [ ] **Step 1: In `ingest_status`**, for each recent run, load `list_recent(db, r.id)` when `r.status == "running"` (or always for last 15 if cheap). Attach `current`, `recent_events`, `cancel_requested`.

```python
events = await list_recent(db, r.id) if r.status == "running" else []
"current": pick_current(events),
"recent_events": events,
"cancel_requested": bool(r.cancel_requested),
```

- [ ] **Step 2: Add stop endpoint**

```python
@router.post("/ingest/crawl/stop")
async def stop_crawl(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    run_id: Optional[str] = None,
) -> dict:
    from uuid import UUID
    rid = UUID(run_id) if run_id else None
    n = await request_cancel(db, rid)
    return {"ok": True, "stopped": n}
```

- [ ] **Step 3: Smoke** (with stack up): stop with no runs → `stopped: 0`

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(crawl): expose stop endpoint and events on ingest status"
```

---

### Task 4: Web API + i18n + Status UI

**Files:**
- Modify: `apps/web/src/lib/api.ts`
- Modify: `apps/web/messages/en.json`, `zh-HK.json`
- Modify: `apps/web/src/app/[locale]/status/page.tsx`
- Optional small CSS in `globals.css` for scrollable activity list

- [ ] **Step 1: `stopCrawl`**

```typescript
export async function stopCrawl(token: string, runId?: string) {
  const url = runId
    ? `${API_URL}/api/ingest/crawl/stop?run_id=${encodeURIComponent(runId)}`
    : `${API_URL}/api/ingest/crawl/stop`;
  const res = await fetch(url, { method: "POST", headers: authHeaders(token) });
  if (!res.ok) throw new Error("stop_failed");
  return res.json() as Promise<{ ok: boolean; stopped: number }>;
}
```

- [ ] **Step 2: i18n keys** (both locales) per spec list.

- [ ] **Step 3: Extend `Run` type** with `current`, `recent_events`, `cancel_requested`.

- [ ] **Step 4: UI**
  - Stop button next to Crawl; `disabled={!busy || stopping}`
  - On click: `stopCrawl`, set stopping message, keep poll
  - In live panel: show `currentFile` + url/title; `recentActivity` list with `formatHkDateTime` and event type labels via t(`eventX`)
  - Truncate long URLs in display

- [ ] **Step 5: `npx tsc --noEmit`** in `apps/web` (or docker rebuild web)

- [ ] **Step 6: Commit**

```bash
git commit -m "feat(crawl): show live crawl activity and stop button on status page"
```

---

### Task 5: Manual verification

- [ ] Rebuild/restart api+worker+web (`docker compose up --build -d`)
- [ ] Start crawl on status page → see discovering / download_start URLs in list
- [ ] Press Stop → message stopping → run becomes `cancelled`; no new downloads after current
- [ ] Confirm previously downloaded docs still listed
- [ ] Stop with idle → no error (stopped 0)

- [ ] Commit only if verification fixes needed

---

## Self-review vs spec

| Spec item | Task |
|-----------|------|
| `crawl_events` table | 1 |
| `cancel_requested` | 1–2 |
| Emit event types | 2 |
| Gentle cancel between files + abort remaining sources | 2 |
| Status `current` + `recent_events` | 3 |
| Stop API | 3 |
| Status UI + i18n + stopCrawl | 4 |
| Manual checks | 5 |

`celery_task_id` column reserved unused in v1 (per spec YAGNI).
