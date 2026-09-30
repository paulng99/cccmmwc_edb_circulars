# System Prompt AI Improve + Runtime Date/Time — Design

Date: 2026-09-30  
Status: Approved for planning  
Locale: en + zh-HK; dates yyyy-mm-dd; timezone Asia/Hong_Kong

## Goal

1. On the Settings page, when the `system_prompt` draft is non-empty, show an AI control that rewrites/improves the draft via the configured LLM.
2. At chat answer time, always append the current Hong Kong date/time to the assembled system prompt so the model knows “today”.

## Decisions (locked)

| Topic | Choice |
|-------|--------|
| Date/time placement | **Runtime injection** in `build_system_prompt()` — not stored in Settings DB |
| Timezone / format | `Asia/Hong_Kong`, `yyyy-mm-dd HH:mm` |
| AI apply behaviour | Overwrite textarea **draft** only; user must still press Save |
| Architecture | Dedicated `POST /api/settings/improve-system-prompt` using existing LLM client |
| Empty prompt | AI button hidden or disabled; empty body → 422 |
| Preview modal | No — direct overwrite of draft |
| Auto-save | No |

## Non-goals

- Persisting “today” into the saved `system_prompt` string
- Preview / diff UI before applying the improved prompt
- Changing cite-inline or programme/topic scope injection behaviour
- Admin-only gate beyond existing authenticated Settings access

---

## UI (Settings → Chat section)

- Field: existing `system_prompt` textarea (`field span-2`).
- When draft trim is non-empty, show an icon button (`wand` or `sparkles`) on the **label row** (same pattern as secret badges / trailing actions).
- Click → loading spinner on the button → call improve API with current draft → on success `updateDraft("system_prompt", result.prompt)`.
- On failure → existing settings error alert (message from API detail).
- i18n keys (en + zh-HK), e.g.:
  - `improveSystemPrompt` — button aria-label / tooltip
  - `improvingSystemPrompt` — loading label if needed
  - `improveSystemPromptFailed` — fallback error copy

Visual: professional multi-colour blue primary; match Sources AI button affordance.

---

## API

### `POST /api/settings/improve-system-prompt`

- Auth: `get_current_user` (same as GET/PUT settings).
- Request body:

```json
{ "prompt": "<current draft>" }
```

- Validation: `prompt` required; after strip, non-empty or **422**.
- Response:

```json
{ "prompt": "<improved full system prompt text>" }
```

- Implementation sketch:
  - Resolve LLM via `get_llm_client()` / current runtime settings (OpenRouter or Ollama).
  - Meta system instruction (fixed server-side): improve clarity, structure, and actionable rules; preserve intent and language (Chinese → Traditional Chinese zh-HK); output **only** the improved system prompt, no preamble.
  - User message: the submitted draft.
  - Call with `stream=False`, `reasoning=False` (same as source suggest).
  - Wrap in `usage_scope("settings_improve")` and bind `usage_user`.
- Errors:
  - Missing/invalid body → 422
  - LLM not configured / provider error → 400 or 502 with readable `detail`
- Does **not** write to `app_settings`; only returns text for the draft.

### Schemas

- `ImproveSystemPromptBody`: `prompt: str`
- Response model or plain dict `{ "prompt": str }`

### Usage feature

- Add `"settings_improve"` to `FEATURES` in `usage.py` and any usage UI feature label map (en + zh-HK) if present.

---

## Runtime date/time injection

Change `build_system_prompt(rs, *, programme=None, topic=None)` in `runtime_settings.py`:

1. Start from stored `system_prompt` (or default).
2. Append cite-inline instruction when enabled (unchanged).
3. Append filter scope when programme/topic set (unchanged).
4. **Always** append:

```
Current date/time (Asia/Hong_Kong): yyyy-mm-dd HH:mm
```

Use `ZoneInfo("Asia/Hong_Kong")` (reuse pattern from `usage.hk_today` / worker timezone). Prefer a small helper e.g. `hk_now_stamp() -> str` so tests can monkeypatch.

This line is **not** part of the Settings editable bag and must not appear in GET settings payloads as a separate field.

---

## Frontend wiring

- File: `apps/web/src/app/[locale]/settings/page.tsx`
- Special-case `system_prompt` in the textarea renderer: label + improve button + textarea + hint.
- State: `improvingPrompt: boolean` (local).
- Fetch: `POST ${apiBase()}/api/settings/improve-system-prompt` with Bearer token; body `{ prompt: displayString("system_prompt") }`.
- Dirty state: improved draft marks form dirty like any other `updateDraft`.

---

## Tests

| Case | Expectation |
|------|-------------|
| `build_system_prompt` | Result contains `Current date/time (Asia/Hong_Kong):` and a `yyyy-mm-dd HH:mm` stamp (monkeypatch clock) |
| Cite + date | Both cite instruction and date line present when `cite_inline_refs` true |
| Improve empty | 422 |
| Improve success | Mock LLM → 200 `{ prompt: "..." }` |
| Improve does not persist | After improve call, GET settings still has previous saved prompt until PUT |

---

## i18n

| Key area | en | zh-HK |
|----------|----|-------|
| Improve control | Improve system prompt | 改善系統提示詞 |
| Improving | Improving… | 改善中… |
| Failure | Could not improve the system prompt | 無法改善系統提示詞 |
| Usage feature (if shown) | Settings improve | 設定改善 |

---

## Out of scope / later

- Undo stack for improve
- Side-by-side diff
- Streaming improve tokens into the textarea
