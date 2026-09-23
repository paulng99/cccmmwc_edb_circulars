# Settings Page (DB-backed Runtime Config) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Settings/Setup page and API so hot-reloadable app config (LLM, RAG, Dify, crawl, storage) is stored in Postgres, overrides `.env`, and can be edited without restarting for most keys.

**Architecture:** Singleton `app_settings` row (`values` JSONB). `runtime_settings` service seeds from env, merges DB over env, caches in memory, masks secrets on read. API `GET/PUT /api/settings`. Consumers (LLM, embeddings, chat, dify, storage, crawl, CORS) read merged runtime values. Web: `/[locale]/settings` form with i18n.

**Tech Stack:** FastAPI, SQLAlchemy async + PostgreSQL JSONB, Pydantic, Next.js App Router, next-intl (en + zh-HK), pytest for pure unit tests.

**Spec:** `docs/superpowers/specs/2026-09-23-settings-page-design.md`

## Global Constraints

- Locales: `en` + `zh-HK`; date display `yyyy-mm-dd` when showing `updated_at` date part
- DB overrides `.env`; env is bootstrap/fallback only for editable keys
- Never return plaintext secrets from API; empty PUT secret = keep existing
- Auth: any logged-in user for now; add `require_admin` stub unused
- Do not write `.env`; do not make JWT/DATABASE_URL/Redis/Celery editable
- Embedding dim change: allow + `warnings: ["reindex_required"]`; no auto-reindex
- Design look: keep existing panel/blue app chrome (no redesign of whole site)

---

## File map

| File | Responsibility |
|------|----------------|
| `apps/api/app/models/entities.py` | Add `AppSetting` model |
| `apps/api/app/models/__init__.py` | Export `AppSetting` |
| `apps/api/app/services/runtime_settings.py` | Keys, defaults, mask, merge, seed, get/put, cache |
| `apps/api/app/services/settings_schema.py` | Editable field definitions + patch validation (optional split; may live in runtime_settings if kept small) |
| `apps/api/app/api/schemas.py` | `SettingsResponse`, `SettingsUpdate`, `SecretFieldOut`, `SettingsMeta` |
| `apps/api/app/api/settings.py` | Router GET/PUT |
| `apps/api/app/api/deps.py` | `require_admin` stub |
| `apps/api/app/main.py` | Register router; dynamic CORS |
| `apps/api/app/bootstrap.py` | Import `AppSetting`; seed settings row after DB init |
| `apps/api/app/services/llm.py` | Read runtime LLM knobs + temperature/max_tokens per call |
| `apps/api/app/services/embeddings.py` | Read runtime Jina settings |
| `apps/api/app/services/chat.py` | system_prompt, cite_inline_refs, top_k from runtime |
| `apps/api/app/services/dify.py` | Runtime Dify settings |
| `apps/api/app/services/storage.py` | Runtime storage/MinIO settings |
| Collectors / pipeline | crawl_enabled, UA, rate from runtime where currently using `get_settings()` |
| `apps/api/tests/test_runtime_settings.py` | Unit tests (no DB) |
| `apps/api/requirements.txt` | Add `pytest`, `pytest-asyncio` |
| `apps/web/src/lib/api.ts` | `getSettings`, `updateSettings` |
| `apps/web/src/app/[locale]/settings/page.tsx` | Settings UI |
| `apps/web/src/components/AppShell.tsx` | Nav link |
| `apps/web/messages/en.json`, `zh-HK.json` | Strings |

---

### Task 1: Pure settings helpers + unit tests

**Files:**
- Create: `apps/api/app/services/runtime_settings.py` (helpers first; DB methods stubbed or later)
- Create: `apps/api/tests/test_runtime_settings.py`
- Create: `apps/api/tests/__init__.py` (empty)
- Modify: `apps/api/requirements.txt` — add `pytest==8.3.5` and `pytest-asyncio==0.26.0`

**Interfaces:**
- Produces:
  - `SECRET_KEYS: frozenset[str]`
  - `EDITABLE_KEYS: frozenset[str]`
  - `DEFAULT_SYSTEM_PROMPT: str` (copy of current chat SYSTEM_PROMPT)
  - `mask_secret(value: str | None) -> dict` → `{"configured": bool, "masked": str | None}`
  - `defaults_from_env(settings) -> dict[str, Any]`
  - `merge_values(env_defaults: dict, db_values: dict) -> dict` (DB wins for keys present in db)
  - `apply_patch(current: dict, patch: dict) -> tuple[dict, list[str]]` (returns new values + warnings; empty secrets keep old; unknown keys raise `ValueError`)

- [ ] **Step 1: Add pytest deps**

Append to `apps/api/requirements.txt`:

```
pytest==8.3.5
pytest-asyncio==0.26.0
```

- [ ] **Step 2: Write failing tests**

Create `apps/api/tests/test_runtime_settings.py`:

```python
import pytest

from app.core.config import Settings
from app.services.runtime_settings import (
    DEFAULT_SYSTEM_PROMPT,
    apply_patch,
    defaults_from_env,
    mask_secret,
    merge_values,
)


def test_mask_secret_empty():
    assert mask_secret("") == {"configured": False, "masked": None}
    assert mask_secret(None) == {"configured": False, "masked": None}


def test_mask_secret_short_and_long():
    assert mask_secret("abcd") == {"configured": True, "masked": "••••abcd"}
    assert mask_secret("sk-1234567890")["masked"].endswith("7890")
    assert mask_secret("sk-1234567890")["configured"] is True


def test_defaults_include_new_keys():
    s = Settings(
        openrouter_api_key="secret-key",
        openrouter_model="google/gemini-2.5-flash",
        llm_provider="openrouter",
    )
    d = defaults_from_env(s)
    assert d["temperature"] == 0.2
    assert d["max_tokens"] == 4096
    assert d["local_top_k"] == 8
    assert d["dify_top_k"] == 5
    assert d["cite_inline_refs"] is True
    assert d["system_prompt"] == DEFAULT_SYSTEM_PROMPT
    assert d["openrouter_api_key"] == "secret-key"
    assert d["llm_provider"] == "openrouter"


def test_merge_db_overrides_env():
    env = {"openrouter_model": "a", "temperature": 0.2}
    db = {"openrouter_model": "b"}
    m = merge_values(env, db)
    assert m["openrouter_model"] == "b"
    assert m["temperature"] == 0.2


def test_apply_patch_keeps_empty_secret():
    current = {"openrouter_api_key": "keep-me", "temperature": 0.2}
    new, warnings = apply_patch(current, {"openrouter_api_key": "", "temperature": 0.5})
    assert new["openrouter_api_key"] == "keep-me"
    assert new["temperature"] == 0.5
    assert warnings == []


def test_apply_patch_dim_warns():
    current = {"jina_embedding_dim": 1024}
    new, warnings = apply_patch(current, {"jina_embedding_dim": 768})
    assert new["jina_embedding_dim"] == 768
    assert "reindex_required" in warnings


def test_apply_patch_rejects_unknown():
    with pytest.raises(ValueError):
        apply_patch({"temperature": 0.2}, {"not_a_key": 1})
```

- [ ] **Step 3: Run tests — expect FAIL**

```bash
cd apps/api && pip install -q pytest==8.3.5 pytest-asyncio==0.26.0 && PYTHONPATH=. pytest tests/test_runtime_settings.py -v
```

Expected: `ModuleNotFoundError` or import errors for `runtime_settings`.

- [ ] **Step 4: Implement helpers in `runtime_settings.py`**

Implement at minimum (no DB yet):

```python
from __future__ import annotations

from typing import Any

from app.core.config import Settings

DEFAULT_SYSTEM_PROMPT = """You are an assistant for Hong Kong Education Bureau (EDB) circulars and documents.
Answer in the same language as the user (prefer Traditional Chinese zh-HK when the user writes Chinese).
Use ONLY the provided context. If unsure, say you cannot find it in the retrieved materials.
Always cite circular numbers and issue dates (yyyy-mm-dd) when available.
Do not invent policies or dates.
"""

SECRET_KEYS = frozenset({
    "openrouter_api_key",
    "jina_api_key",
    "dify_dataset_api_key",
    "dify_app_api_key",
    "minio_access_key",
    "minio_secret_key",
    "google_client_secret",
})

# Full editable key list per spec — include every key from design editable schema
EDITABLE_KEYS = frozenset({
    "app_name", "cors_origins",
    "llm_provider", "openrouter_api_key", "openrouter_model", "openrouter_base_url",
    "ollama_base_url", "ollama_model", "temperature", "max_tokens",
    "system_prompt", "cite_inline_refs", "local_top_k", "dify_top_k",
    "jina_api_key", "jina_embedding_model", "jina_embedding_dim",
    "dify_enabled", "dify_api_url", "dify_dataset_api_key", "dify_app_api_key", "dify_dataset_id",
    "crawl_enabled", "crawl_user_agent", "crawl_rate_limit_seconds",
    "storage_backend", "local_storage_path",
    "minio_endpoint", "minio_access_key", "minio_secret_key", "minio_bucket",
    "minio_public_url", "minio_secure",
    "google_client_id", "google_client_secret",
})

INLINE_CITE_INSTRUCTION = (
    "When using a context block, include its reference tag "
    "(e.g. [L1], [D2]) inline next to the claim."
)


def mask_secret(value: str | None) -> dict[str, Any]:
    if not value:
        return {"configured": False, "masked": None}
    tail = value[-4:] if len(value) >= 4 else value
    return {"configured": True, "masked": f"••••{tail}"}


def defaults_from_env(settings: Settings) -> dict[str, Any]:
    return {
        "app_name": settings.app_name,
        "cors_origins": settings.cors_origins,
        "llm_provider": settings.llm_provider,
        "openrouter_api_key": settings.openrouter_api_key,
        "openrouter_model": settings.openrouter_model,
        "openrouter_base_url": settings.openrouter_base_url,
        "ollama_base_url": settings.ollama_base_url,
        "ollama_model": settings.ollama_model,
        "temperature": 0.2,
        "max_tokens": 4096,
        "system_prompt": DEFAULT_SYSTEM_PROMPT,
        "cite_inline_refs": True,
        "local_top_k": 8,
        "dify_top_k": 5,
        "jina_api_key": settings.jina_api_key,
        "jina_embedding_model": settings.jina_embedding_model,
        "jina_embedding_dim": settings.jina_embedding_dim,
        "dify_enabled": settings.dify_enabled,
        "dify_api_url": settings.dify_api_url,
        "dify_dataset_api_key": settings.dify_dataset_api_key,
        "dify_app_api_key": settings.dify_app_api_key,
        "dify_dataset_id": settings.dify_dataset_id,
        "crawl_enabled": settings.crawl_enabled,
        "crawl_user_agent": settings.crawl_user_agent,
        "crawl_rate_limit_seconds": settings.crawl_rate_limit_seconds,
        "storage_backend": settings.storage_backend,
        "local_storage_path": settings.local_storage_path,
        "minio_endpoint": settings.minio_endpoint,
        "minio_access_key": settings.minio_access_key,
        "minio_secret_key": settings.minio_secret_key,
        "minio_bucket": settings.minio_bucket,
        "minio_public_url": settings.minio_public_url,
        "minio_secure": settings.minio_secure,
        "google_client_id": settings.google_client_id,
        "google_client_secret": settings.google_client_secret,
    }


def merge_values(env_defaults: dict[str, Any], db_values: dict[str, Any]) -> dict[str, Any]:
    out = dict(env_defaults)
    for k, v in (db_values or {}).items():
        if k in EDITABLE_KEYS:
            out[k] = v
    return out


def apply_patch(current: dict[str, Any], patch: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    unknown = set(patch) - EDITABLE_KEYS
    if unknown:
        raise ValueError(f"Unknown settings keys: {sorted(unknown)}")
    new = dict(current)
    warnings: list[str] = []
    for k, v in patch.items():
        if k in SECRET_KEYS and (v is None or v == ""):
            continue
        if k == "jina_embedding_dim" and v != current.get("jina_embedding_dim"):
            warnings.append("reindex_required")
        if k == "temperature":
            if not isinstance(v, (int, float)) or not (0 <= float(v) <= 2):
                raise ValueError("temperature must be between 0 and 2")
            v = float(v)
        if k in ("max_tokens", "local_top_k", "dify_top_k", "jina_embedding_dim"):
            if not isinstance(v, int) or v < 1:
                raise ValueError(f"{k} must be int >= 1")
        if k == "llm_provider" and v not in ("openrouter", "ollama"):
            raise ValueError("llm_provider must be openrouter or ollama")
        if k == "storage_backend" and v not in ("local", "minio"):
            raise ValueError("storage_backend must be local or minio")
        new[k] = v
    return new, warnings
```

- [ ] **Step 5: Run tests — expect PASS**

```bash
cd apps/api && PYTHONPATH=. pytest tests/test_runtime_settings.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/api/requirements.txt apps/api/app/services/runtime_settings.py apps/api/tests
git commit -m "feat(settings): add runtime settings helpers and unit tests"
```

---

### Task 2: `AppSetting` model + DB seed/get/put + cache

**Files:**
- Modify: `apps/api/app/models/entities.py`
- Modify: `apps/api/app/models/__init__.py`
- Modify: `apps/api/app/services/runtime_settings.py` — add async DB API
- Modify: `apps/api/app/bootstrap.py` — seed on startup
- Test: extend `apps/api/tests/test_runtime_settings.py` with pure tests only; DB path verified manually or via thin mock if easy

**Interfaces:**
- Consumes: helpers from Task 1
- Produces:
  - `class AppSetting` table `app_settings`
  - `async def ensure_seeded(session) -> AppSetting`
  - `async def get_merged(session) -> dict[str, Any]` (uses cache)
  - `async def update_settings(session, patch, user_id) -> tuple[dict, list[str], AppSetting]`
  - `def invalidate_cache() -> None`
  - `def get_cached_merged() -> dict[str, Any] | None`

- [ ] **Step 1: Add model**

In `entities.py` after `User`:

```python
class AppSetting(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # always 1
    values: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
```

Export from `models/__init__.py`. Import in `bootstrap.py` so `create_all` picks it up.

- [ ] **Step 2: Implement DB + cache in `runtime_settings.py`**

```python
_cache: dict[str, Any] | None = None

def invalidate_cache() -> None:
    global _cache
    _cache = None

def get_cached_merged() -> dict[str, Any] | None:
    return _cache

async def ensure_seeded(session: AsyncSession) -> AppSetting:
    row = await session.get(AppSetting, 1)
    if row:
        return row
    row = AppSetting(id=1, values=defaults_from_env(get_settings()))
    session.add(row)
    await session.commit()
    await session.refresh(row)
    invalidate_cache()
    return row

async def get_merged(session: AsyncSession) -> dict[str, Any]:
    global _cache
    if _cache is not None:
        return _cache
    row = await ensure_seeded(session)
    env_defaults = defaults_from_env(get_settings())
    _cache = merge_values(env_defaults, row.values or {})
    return _cache

async def update_settings(
    session: AsyncSession,
    patch: dict[str, Any],
    user_id: uuid.UUID | None,
) -> tuple[dict[str, Any], list[str], AppSetting]:
    row = await ensure_seeded(session)
    env_defaults = defaults_from_env(get_settings())
    current = merge_values(env_defaults, row.values or {})
    new_values, warnings = apply_patch(current, patch)
    # Persist only editable bag (full merged editable snapshot)
    row.values = {k: new_values[k] for k in EDITABLE_KEYS if k in new_values}
    row.updated_by = user_id
    await session.commit()
    await session.refresh(row)
    invalidate_cache()
    merged = await get_merged(session)
    return merged, warnings, row
```

Wire `await ensure_seeded(session)` inside `bootstrap()` after `seed_admin`.

- [ ] **Step 3: Smoke-check import**

```bash
cd apps/api && PYTHONPATH=. python -c "from app.models import AppSetting; from app.services.runtime_settings import ensure_seeded; print('ok')"
```

Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add apps/api/app/models apps/api/app/services/runtime_settings.py apps/api/app/bootstrap.py
git commit -m "feat(settings): add AppSetting model and DB-backed runtime store"
```

---

### Task 3: Settings API (schemas + router + admin stub)

**Files:**
- Modify: `apps/api/app/api/schemas.py`
- Create: `apps/api/app/api/settings.py`
- Modify: `apps/api/app/api/deps.py`
- Modify: `apps/api/app/main.py` — `include_router(settings.router)`
- Modify: `apps/api/tests/test_runtime_settings.py` — add `test_public_payload_masks_secrets` if extracting `to_public_editable`

**Interfaces:**
- Consumes: `get_merged`, `update_settings`, `mask_secret`, `SECRET_KEYS`, `get_settings` for readonly
- Produces:
  - `GET /api/settings` → `SettingsResponse`
  - `PUT /api/settings` body = `dict` partial editable (secrets as `str | null`)
  - `async def require_admin(user: User = Depends(get_current_user)) -> User` stub that currently just returns user (with TODO comment) OR raises only if role check enabled via flag `False`

- [ ] **Step 1: Schemas**

```python
class SecretFieldOut(BaseModel):
    configured: bool
    masked: str | None = None

class SettingsMeta(BaseModel):
    updated_at: str | None = None
    updated_by: str | None = None

class SettingsResponse(BaseModel):
    editable: dict[str, Any]
    readonly: dict[str, Any]
    meta: SettingsMeta
    warnings: list[str] = []
```

Add helper `build_settings_response(merged, row, warnings=[])` in `runtime_settings.py` that:
- For each editable key: if secret → `mask_secret(value)`, else plain value
- Readonly from `get_settings()`: `app_env`, masked `jwt_secret`, `jwt_expire_hours`, `admin_username`, masked `database_url`/`redis_url`/`celery_*`, `sources_config_path`
- Never include `admin_password`

- [ ] **Step 2: Router**

```python
router = APIRouter(prefix="/api/settings", tags=["settings"])

@router.get("", response_model=SettingsResponse)
async def get_settings_api(
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    merged = await get_merged(session)
    row = await session.get(AppSetting, 1)
    return build_settings_response(merged, row)

@router.put("", response_model=SettingsResponse)
async def put_settings_api(
    body: dict[str, Any],
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    try:
        merged, warnings, row = await update_settings(session, body, user.id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return build_settings_response(merged, row, warnings=warnings)
```

Use a Pydantic model `SettingsUpdate` with all editable fields optional for OpenAPI clarity; reject extras with `model_config = ConfigDict(extra="forbid")`. Convert to dict excluding unset.

- [ ] **Step 3: deps stub**

```python
async def require_admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    # Reserved for later: enforce user.role == "admin"
    return user
```

- [ ] **Step 4: Register router in `main.py`**

- [ ] **Step 5: Unit test public masking**

```python
def test_build_settings_response_masks():
    merged = defaults_from_env(Settings(openrouter_api_key="super-secret-key"))
    payload = build_settings_response(merged, row=None)
    assert payload["editable"]["openrouter_api_key"]["configured"] is True
    assert "super-secret" not in str(payload)
```

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/api apps/api/app/services/runtime_settings.py apps/api/tests
git commit -m "feat(settings): expose GET/PUT /api/settings with masked secrets"
```

---

### Task 4: Wire consumers (LLM, chat, embeddings, dify, storage, crawl, CORS)

**Files:**
- Modify: `apps/api/app/services/llm.py`
- Modify: `apps/api/app/services/chat.py`
- Modify: `apps/api/app/services/embeddings.py`
- Modify: `apps/api/app/services/dify.py`
- Modify: `apps/api/app/services/storage.py`
- Modify: collectors/pipeline sites that read crawl settings from `get_settings()`
- Modify: `apps/api/app/main.py` — dynamic CORS
- Modify: `apps/api/app/api/system.py` health if it exposes llm_provider — use merged when session available, or cached

**Interfaces:**
- Consumes: `get_merged(session)` when a DB session exists; for sync/Celery/`get_llm_client()` without session use `get_cached_merged()` falling back to `defaults_from_env(get_settings())` via `def resolved_settings() -> dict`

Add:

```python
def resolved_settings() -> dict[str, Any]:
    cached = get_cached_merged()
    if cached is not None:
        return cached
    return defaults_from_env(get_settings())
```

Note: until first `get_merged`/`ensure_seeded` in a process, cache is empty → env defaults (correct). After bootstrap seeds and warms cache in lifespan:

```python
# in lifespan after bootstrap
async with SessionLocal() as session:
    await get_merged(session)
```

- [ ] **Step 1: Warm cache in lifespan** (`main.py` or `bootstrap.py`)

- [ ] **Step 2: LLM — read per call**

In `OpenRouterClient.chat` / `OllamaClient.chat`, use `rs = resolved_settings()` for key, model, base_url, and add to OpenRouter payload:

```python
payload["temperature"] = rs["temperature"]
payload["max_tokens"] = rs["max_tokens"]
```

`get_llm_client()` uses `resolved_settings()["llm_provider"]`.

- [ ] **Step 3: Chat**

Replace hardcoded `SYSTEM_PROMPT` usage:

```python
rs = await get_merged(session)  # session available in answer_question
system = rs["system_prompt"]
if rs.get("cite_inline_refs"):
    system = system + "\n" + INLINE_CITE_INSTRUCTION
# locale hint unchanged
local_hits = await get_local_knowledge().retrieve(session, question, top_k=int(rs["local_top_k"]))
dify_hits = await get_dify_knowledge().retrieve(session, question, top_k=int(rs["dify_top_k"]))
```

Keep `DEFAULT_SYSTEM_PROMPT` importable; remove duplicate constant from `chat.py` or re-export.

- [ ] **Step 4: Embeddings / Dify / storage / crawl**

Replace `get_settings().jina_*` / dify / minio / crawl fields with `resolved_settings()` (or pass session where async). For Celery worker processes, call `ensure_seeded`+`get_merged` at task start or accept env fallback until warmed — **minimum:** worker tasks that need settings call async `get_merged` once at start of crawl task.

- [ ] **Step 5: Dynamic CORS**

Subclass or wrap so `allow_origins` comes from `resolved_settings()["cors_origins"].split(",")`.

Example approach — custom middleware placed before routes:

```python
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

class DynamicCORSMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        origin = request.headers.get("origin")
        rs = resolved_settings()
        allowed = [o.strip() for o in str(rs.get("cors_origins", "")).split(",") if o.strip()]
        if request.method == "OPTIONS" and origin in allowed:
            return Response(
                status_code=200,
                headers={
                    "Access-Control-Allow-Origin": origin,
                    "Access-Control-Allow-Credentials": "true",
                    "Access-Control-Allow-Methods": "*",
                    "Access-Control-Allow-Headers": "*",
                },
            )
        response = await call_next(request)
        if origin in allowed:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
        return response
```

Remove static `CORSMiddleware` origins binding **or** keep it with `allow_origins=["*"]` only in dev — prefer DynamicCORS only to match spec.

- [ ] **Step 6: Add unit test for cite instruction builder**

```python
def test_build_system_prompt_with_cite():
    from app.services.runtime_settings import build_system_prompt
    text = build_system_prompt({"system_prompt": "BASE", "cite_inline_refs": True})
    assert "BASE" in text
    assert "[L1]" in text
```

Implement `build_system_prompt(rs: dict) -> str`.

- [ ] **Step 7: Commit**

```bash
git add apps/api/app
git commit -m "feat(settings): wire LLM/chat/RAG/storage/CORS to runtime settings"
```

---

### Task 5: Web API client + i18n + nav

**Files:**
- Modify: `apps/web/src/lib/api.ts`
- Modify: `apps/web/messages/en.json`
- Modify: `apps/web/messages/zh-HK.json`
- Modify: `apps/web/src/components/AppShell.tsx`

**Interfaces:**
- Produces: `getSettings(token)`, `updateSettings(token, body)`, `nav.settings`, `settings.*` message keys

- [ ] **Step 1: API helpers**

```typescript
export type SecretField = { configured: boolean; masked: string | null };
export type SettingsResponse = {
  editable: Record<string, unknown>;
  readonly: Record<string, unknown>;
  meta: { updated_at: string | null; updated_by: string | null };
  warnings: string[];
};

export async function getSettings(token: string) {
  const res = await fetch(`${API_URL}/api/settings`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error("settings_get_failed");
  return res.json() as Promise<SettingsResponse>;
}

export async function updateSettings(token: string, body: Record<string, unknown>) {
  const res = await fetch(`${API_URL}/api/settings`, {
    method: "PUT",
    headers: authHeaders(token),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error("settings_update_failed");
  return res.json() as Promise<SettingsResponse>;
}
```

- [ ] **Step 2: i18n keys** (both locales)

```json
"nav": { "settings": "Settings" },
"settings": {
  "title": "Setup / Settings",
  "save": "Save changes",
  "saved": "Settings saved",
  "loadError": "Failed to load settings",
  "saveError": "Failed to save settings",
  "sectionApp": "App",
  "sectionLlm": "LLM",
  "sectionChat": "Chat / RAG",
  "sectionEmbeddings": "Embeddings",
  "sectionDify": "Dify",
  "sectionCrawl": "Crawl",
  "sectionStorage": "Storage",
  "sectionOauth": "OAuth",
  "sectionReadonly": "Infrastructure (read-only)",
  "secretConfigured": "Configured ({masked})",
  "secretEmpty": "Not set",
  "secretKeepHint": "Leave blank to keep current value",
  "dimConfirm": "Changing embedding dimension requires re-indexing. Continue?",
  "reindexWarning": "Re-index required after embedding dimension change",
  "readonlyHint": "Change these via environment variables / .env and restart"
}
```

zh-HK equivalents (e.g. `"settings": "設定"`, `"title": "系統設定"`).

- [ ] **Step 3: Nav link** in `AppShell.tsx` next to Status:

```tsx
<Link href="/settings">{t("nav.settings")}</Link>
```

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/lib/api.ts apps/web/messages apps/web/src/components/AppShell.tsx
git commit -m "feat(settings): add web API client, i18n, and nav link"
```

---

### Task 6: Settings page UI

**Files:**
- Create: `apps/web/src/app/[locale]/settings/page.tsx`
- Modify: `apps/web/src/app/globals.css` only if small form helpers needed (prefer existing `.panel`, inputs)

**Interfaces:**
- Consumes: `getSettings`, `updateSettings`, `useAuth`, translations

- [ ] **Step 1: Page scaffold**

Mirror status/chat auth gate:

```tsx
useEffect(() => {
  if (ready && !token) router.replace("/login");
}, [ready, token, router]);
```

Load settings on mount; show sections as stacked `<section className="panel">` groups.

- [ ] **Step 2: Form state**

- Non-secret editable fields → controlled inputs/selects/checkboxes/textarea (`system_prompt`)
- Secret fields → password input, placeholder = masked or “Not set”; only include in PUT body if user typed non-empty
- Readonly section → disabled inputs / plain text

- [ ] **Step 3: Save**

On submit:
1. If `jina_embedding_dim` changed vs loaded value → `window.confirm(t("dimConfirm"))`
2. `updateSettings(token, patch)`
3. Show `warnings` (reindex) and success message
4. Refresh form from response (secrets reset to empty inputs; show new masked state)

- [ ] **Step 4: Manual UI check**

```bash
# with stack running
open http://localhost:4000/zh-HK/settings
```

Verify: load, change `openrouter_model`, save, reload, value persists; blank API key does not clear configured flag.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/app/\[locale\]/settings apps/web/src/app/globals.css
git commit -m "feat(settings): add settings page UI for runtime config"
```

---

### Task 7: End-to-end verification

**Files:** none required (manual / script)

- [ ] **Step 1: Run unit tests**

```bash
cd apps/api && PYTHONPATH=. pytest tests/test_runtime_settings.py -v
```

Expected: PASS

- [ ] **Step 2: API smoke (authenticated)**

```bash
TOKEN=$(curl -s -X POST "$API/api/auth/login" -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"000000"}' | jq -r .access_token)
curl -s -H "Authorization: Bearer $TOKEN" "$API/api/settings" | jq '.editable.openrouter_model, .editable.openrouter_api_key'
curl -s -X PUT -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"temperature":0.3,"openrouter_api_key":""}' "$API/api/settings" | jq '.editable.temperature, .warnings'
```

Expected: model visible; api_key object with `configured`; temperature 0.3; empty key keeps configured.

- [ ] **Step 3: Unauth check**

```bash
curl -s -o /dev/null -w "%{http_code}" "$API/api/settings"
```

Expected: `401`

- [ ] **Step 4: Final commit only if verification fixes were needed; otherwise done**

---

## Self-review (plan vs spec)

| Spec requirement | Task |
|------------------|------|
| Singleton JSONB `app_settings` | Task 2 |
| Seed from env; DB overrides | Tasks 1–2 |
| Mask secrets; empty keep | Tasks 1, 3 |
| GET/PUT `/api/settings` | Task 3 |
| Editable field set + new LLM/RAG knobs | Tasks 1, 3, 4 |
| Readonly infra display | Task 3, 6 |
| Wire LLM/chat/embeddings/dify/storage/crawl/CORS | Task 4 |
| `cite_inline_refs` + system_prompt | Task 4 |
| temperature / max_tokens | Task 4 |
| dim warning | Tasks 1, 3, 6 |
| Settings page + nav + i18n | Tasks 5–6 |
| Auth any user + require_admin stub | Task 3 |
| Tests listed in spec | Tasks 1, 3, 4, 7 |

No intentional TBD placeholders remain. Worker cache warm documented in Task 4.
