# Settings Page (DB-backed Runtime Config) — Design

Date: 2026-09-23  
Status: Approved for planning  
Locale: en + zh-HK; dates yyyy-mm-dd

## Goal

Provide a **Setup / Settings** page so operators can change hot-reloadable application configuration (including LLM options) from the UI. Values persist in Postgres. Infrastructure secrets stay in `.env` and appear read-only on the page.

## Decisions (locked)

| Topic | Choice |
|-------|--------|
| Scope | Hot-reloadable app settings only; infra (DB/Redis/JWT/Celery) env-only, shown read-only |
| Access | Any authenticated user for now; reserve `require_admin` for later |
| LLM extras | Existing env knobs + `temperature`, `max_tokens`, `local_top_k`, `dify_top_k`, `system_prompt`, `cite_inline_refs`, embedding dim with strong warning |
| Precedence | **DB overrides `.env`**; first boot seeds DB from env; env is bootstrap/fallback |
| Storage | Single-row JSONB (`app_settings`, `id=1`) |

## Non-goals

- Writing back to the `.env` file
- Changing Postgres/Redis/JWT from the UI
- Full RBAC admin gate in this iteration (hook only)
- Automatic re-embedding when `jina_embedding_dim` changes

---

## Architecture

### Data model

Table `app_settings` (singleton):

| Column | Type | Notes |
|--------|------|-------|
| `id` | `SMALLINT` PK | Always `1` |
| `values` | `JSONB` NOT NULL | Editable settings bag |
| `updated_at` | `timestamptz` | |
| `updated_by` | `UUID` NULL FK → `users.id` | Optional audit |

Created via existing `create_all` bootstrap (no Alembic in this repo).

### Runtime resolution

New module `apps/api/app/services/runtime_settings.py`:

1. Load env `Settings` (existing pydantic).
2. Load `app_settings.values` (or seed if missing).
3. Merge: for each editable key, **DB value wins** if present; else env/default.
4. In-memory cache with invalidation on successful `PUT`.

Call sites that today use `get_settings()` for hot fields must use the runtime resolver (or a thin helper that returns merged values):

- `services/llm.py`
- `services/embeddings.py`
- `services/chat.py` (system prompt, top_k, cite_inline_refs)
- `services/dify.py`
- crawl / collectors (UA, rate limit, crawl_enabled)
- `storage.py` (backend + MinIO fields)
- CORS: replace static Starlette `CORSMiddleware` origins bound at import with a thin middleware (or wrapper) that reads **cached** runtime `cors_origins` and refreshes when the settings cache is invalidated. No process restart required for CORS changes.

Infrastructure fields (`database_url`, `jwt_secret`, etc.) always come from env `Settings` only.

### Embedding dim limitation (explicit)

`DocumentChunk.embedding` is declared as `Vector(jina_embedding_dim)` from **env at process import**. Changing `jina_embedding_dim` in DB:

- Updates runtime embed API calls to the new dim.
- Does **not** alter the existing pgvector column type or re-embed old chunks.
- UI + API must show `reindex_required`; operators must re-ingest/reindex (and may need a coordinated env/schema change later). Do not claim silent schema migration in this feature.

### Seed behaviour

On API startup / first `GET` or `PUT` of settings:

- If no row `id=1`, insert `values` copied from current env for all **editable** keys, plus new defaults for keys not in env (`temperature`, `max_tokens`, `local_top_k`, `dify_top_k`, `system_prompt`, `cite_inline_refs`).

### Secrets masking

API never returns plaintext secrets. Response uses:

- `configured: boolean` (true if non-empty stored value)
- `masked: string | null` (e.g. last 4 chars `••••abcd`, or `null` if empty)

On `PUT`, omit key or send empty/`null` ⇒ **keep existing secret**. Send non-empty string ⇒ replace.

Secret keys: `openrouter_api_key`, `jina_api_key`, `dify_dataset_api_key`, `dify_app_api_key`, `minio_access_key`, `minio_secret_key`, `google_client_secret`.

---

## Editable schema (`values` JSONB)

### App

- `app_name` (string)
- `cors_origins` (string, comma-separated)

### LLM

- `llm_provider`: `"openrouter" | "ollama"`
- `openrouter_api_key`, `openrouter_model`, `openrouter_base_url`
- `ollama_base_url`, `ollama_model`
- `temperature` (float, default `0.2`)
- `max_tokens` (int, default `4096`)

### Chat / RAG

- `system_prompt` (string; default = current hardcoded `SYSTEM_PROMPT` in `chat.py`)
- `cite_inline_refs` (bool, default `true`) — when true, append instruction: cite with `[L#]` / `[D#]` inline in the answer body
- `local_top_k` (int, default `8`)
- `dify_top_k` (int, default `5`)

### Embeddings

- `jina_api_key`, `jina_embedding_model`, `jina_embedding_dim` (int, default `1024`)
- Changing dim is allowed; API returns `warnings: ["reindex_required"]`; UI shows confirm dialog. Existing vectors may become incompatible until re-ingest/reindex (operator responsibility).

### Dify

- `dify_enabled`, `dify_api_url`, `dify_dataset_api_key`, `dify_app_api_key`, `dify_dataset_id`

### Crawl

- `crawl_enabled`, `crawl_user_agent`, `crawl_rate_limit_seconds`

### Storage

- `storage_backend`: `"local" | "minio"`
- `local_storage_path`
- `minio_endpoint`, `minio_access_key`, `minio_secret_key`, `minio_bucket`, `minio_public_url`, `minio_secure`

### OAuth (stub-ready)

- `google_client_id`, `google_client_secret`

## Read-only (env only, display on page)

- `app_env`
- `jwt_secret` (masked), `jwt_expire_hours`
- `admin_username` (never show `admin_password`)
- `database_url` (masked), `redis_url` (masked)
- `celery_broker_url`, `celery_result_backend` (masked if credential-bearing)
- `sources_config_path`
- Note that `NEXT_PUBLIC_API_URL` / `NEXT_PUBLIC_DEFAULT_LOCALE` are web build-time env (not API DB)

---

## API

Router: `apps/api/app/api/settings.py`, prefix `/api/settings`, registered in `main.py`.  
Auth: `Depends(get_current_user)` now; comment + unused `require_admin` stub in `deps.py` for later.

### `GET /api/settings`

```json
{
  "editable": { "...": "values with secrets as { configured, masked } objects or plain scalars" },
  "readonly": { "...": "env-derived display fields, secrets masked" },
  "meta": {
    "updated_at": "2026-09-23T12:00:00+08:00",
    "updated_by": null
  },
  "warnings": []
}
```

Concrete shape for implementation: use a stable Pydantic response model where secret fields are objects `{ "configured": bool, "masked": str | null }` and non-secrets are plain typed values. Avoid returning raw secret strings under any key name.

### `PUT /api/settings`

- Body: partial patch of editable keys only (unknown keys → 422).
- Secret fields: string | null | omitted; empty/null = no change.
- Validates types/ranges (e.g. temperature 0–2, top_k ≥ 1, max_tokens ≥ 1).
- Response: same as GET, plus any `warnings`.
- Side effect: invalidate runtime settings cache.

---

## Frontend

- Page: `apps/web/src/app/[locale]/settings/page.tsx`
- Nav: add Settings in `AppShell.tsx`
- i18n: `messages/en.json`, `messages/zh-HK.json` (`nav.settings`, section labels, help text, warnings)
- API helpers in `apps/web/src/lib/api.ts`: `getSettings`, `updateSettings`
- UX: sectioned form (tabs or stacked panels), blue-primary existing look; one Save; confirm before dim change; show configured/masked for secrets
- Auth gate: redirect to login if no token (same as chat/status)

## Chat behaviour change

When `cite_inline_refs` is true, append to system prompt (or user context instruction):

> When using a context block, include its reference tag (e.g. `[L1]`, `[D2]`) inline next to the claim.

When false, keep current behaviour (citations list only; circular number/date in prose).

`system_prompt` replaces the hardcoded constant; locale hint (`zh-HK` / English) remains appended as today.

LLM `chat()` payload must pass `temperature` and `max_tokens` from runtime settings.

---

## Error handling

| Case | Behaviour |
|------|-----------|
| Unauthenticated | 401 |
| Invalid patch / unknown key | 422 |
| Empty secret field | Keep previous |
| Dim change | Persist + `warnings: ["reindex_required"]` |
| Missing OpenRouter/Jina keys | Existing demo/stub behaviour unchanged |

## Testing (minimal)

1. Fresh DB: first GET seeds from env; secrets masked.
2. PUT `openrouter_model` + `temperature` → subsequent chat/LLM uses new values without restart.
3. PUT empty `openrouter_api_key` → previous key retained.
4. Unauthenticated GET/PUT → 401.
5. `cite_inline_refs` true → system messages include inline-ref instruction (unit or integration assert on built messages).

## File map

| Layer | Path |
|-------|------|
| Model | `apps/api/app/models/entities.py` (`AppSetting`) |
| Schemas | `apps/api/app/api/schemas.py` |
| Router | `apps/api/app/api/settings.py` |
| Service | `apps/api/app/services/runtime_settings.py` |
| Deps stub | `apps/api/app/api/deps.py` (`require_admin` optional stub) |
| Wire-up | `apps/api/app/main.py`; consumers listed above |
| UI | `apps/web/src/app/[locale]/settings/page.tsx` |
| Nav / i18n / api client | `AppShell`, `messages/*`, `lib/api.ts` |

## Out of scope follow-ups

- Enforce `role == "admin"` on settings write
- Reindex job after embedding dim change
- Settings change audit log UI
