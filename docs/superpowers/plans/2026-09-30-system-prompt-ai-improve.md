# System Prompt AI Improve + Runtime Date/Time — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (or subagent-driven-development). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an AI improve control on Settings `system_prompt`, and inject Asia/Hong_Kong date/time into every chat system prompt at runtime.

**Architecture:** Runtime stamp via `build_system_prompt()`; improve via `POST /api/settings/improve-system-prompt` using existing LLM client; Settings UI overwrites draft only.

**Tech Stack:** FastAPI, existing LLM client, Next.js settings page, next-intl (en + zh-HK)

## Global Constraints

- Locale: en + zh-HK; dates `yyyy-mm-dd`; timezone `Asia/Hong_Kong`
- Date/time is runtime-only (not stored in Settings DB)
- Improve overwrites draft; Save still required
- Blue primary / professional UI; match Sources `wand` affordance

## File map

| File | Role |
|------|------|
| `apps/api/app/services/runtime_settings.py` | `hk_now_stamp()`, append stamp in `build_system_prompt` |
| `apps/api/app/services/prompt_improve.py` | Improve prompt via LLM (new) |
| `apps/api/app/api/settings.py` | New POST endpoint |
| `apps/api/app/api/schemas.py` | `ImproveSystemPromptBody` |
| `apps/api/app/services/usage.py` | Feature `settings_improve` |
| `apps/api/tests/test_runtime_settings.py` | Date stamp tests |
| `apps/api/tests/test_prompt_improve.py` | Improve API tests (new) |
| `apps/web/src/lib/api.ts` | `improveSystemPrompt()` |
| `apps/web/src/app/[locale]/settings/page.tsx` | AI button on system_prompt |
| `apps/web/messages/en.json` / `zh-HK.json` | i18n |
| `apps/web/src/app/[locale]/usage/page.tsx` | Feature row |

---

### Task 1: Runtime HK date/time in `build_system_prompt`

**Files:**
- Modify: `apps/api/app/services/runtime_settings.py`
- Test: `apps/api/tests/test_runtime_settings.py`

**Interfaces:**
- Produces: `hk_now_stamp() -> str` returning `yyyy-mm-dd HH:mm` in Asia/Hong_Kong
- Produces: `build_system_prompt(...)` always ends with `Current date/time (Asia/Hong_Kong): {stamp}`

- [ ] **Step 1: Write failing tests**

```python
def test_build_system_prompt_includes_hk_datetime(monkeypatch):
    monkeypatch.setattr(
        "app.services.runtime_settings.hk_now_stamp",
        lambda: "2026-09-30 22:15",
    )
    text = build_system_prompt({"system_prompt": "BASE", "cite_inline_refs": False})
    assert "Current date/time (Asia/Hong_Kong): 2026-09-30 22:15" in text
    assert text.startswith("BASE")


def test_build_system_prompt_cite_and_datetime(monkeypatch):
    monkeypatch.setattr(
        "app.services.runtime_settings.hk_now_stamp",
        lambda: "2026-09-30 22:15",
    )
    text = build_system_prompt({"system_prompt": "BASE", "cite_inline_refs": True})
    assert "[L1]" in text
    assert "Current date/time (Asia/Hong_Kong): 2026-09-30 22:15" in text
```

- [ ] **Step 2: Run tests — expect FAIL** (`hk_now_stamp` missing / stamp absent)

- [ ] **Step 3: Implement**

```python
from datetime import datetime
from zoneinfo import ZoneInfo

HK = ZoneInfo("Asia/Hong_Kong")

def hk_now_stamp() -> str:
    return datetime.now(HK).strftime("%Y-%m-%d %H:%M")
```

In `build_system_prompt`, after cite/scope appends:

```python
system = system + f"\nCurrent date/time (Asia/Hong_Kong): {hk_now_stamp()}"
return system
```

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit** `feat(chat): inject HK date/time into system prompt`

---

### Task 2: Improve system prompt API

**Files:**
- Create: `apps/api/app/services/prompt_improve.py`
- Modify: `apps/api/app/api/schemas.py`, `apps/api/app/api/settings.py`, `apps/api/app/services/usage.py`
- Test: `apps/api/tests/test_prompt_improve.py`

**Interfaces:**
- Consumes: `get_llm_client().chat(...)`, `usage_scope`, `usage_user`
- Produces: `improve_system_prompt(draft: str) -> str`
- Produces: `POST /api/settings/improve-system-prompt` → `{ "prompt": str }`

- [ ] **Step 1: Add schema**

```python
class ImproveSystemPromptBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str = Field(min_length=1, max_length=50000)
```

- [ ] **Step 2: Add `settings_improve` to `FEATURES` in `usage.py`

- [ ] **Step 3: Service `prompt_improve.py`**

Meta system instruction (constant): improve clarity/structure/rules; preserve intent and language (Chinese → zh-HK Traditional); output only the improved prompt.

```python
async def improve_system_prompt(draft: str) -> str:
    text = draft.strip()
    if not text:
        raise ValueError("prompt_empty")
    llm = get_llm_client()
    with usage_scope("settings_improve"):
        answer = await llm.chat(
            [
                {"role": "system", "content": IMPROVE_META},
                {"role": "user", "content": text},
            ],
            stream=False,
            reasoning=False,
        )
    if not isinstance(answer, str) or not answer.strip():
        raise RuntimeError("llm_empty")
    return answer.strip()
```

- [ ] **Step 4: Endpoint on settings router**

```python
@router.post("/improve-system-prompt")
async def improve_system_prompt_api(
    body: ImproveSystemPromptBody,
    user: Annotated[User, Depends(get_current_user)],
):
    draft = body.prompt.strip()
    if not draft:
        raise HTTPException(status_code=422, detail="prompt_empty")
    try:
        with usage_user(user.id):
            improved = await improve_system_prompt(draft)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="improve_failed") from exc
    return {"prompt": improved}
```

- [ ] **Step 5: Tests** — empty → 422; success mocks LLM → 200; does not call `update_settings`

- [ ] **Step 6: Commit** `feat(settings): add improve-system-prompt API`

---

### Task 3: Frontend + i18n + usage labels

**Files:**
- Modify: `apps/web/src/lib/api.ts`, `apps/web/src/app/[locale]/settings/page.tsx`, `apps/web/messages/en.json`, `apps/web/messages/zh-HK.json`, `apps/web/src/app/[locale]/usage/page.tsx`

- [ ] **Step 1: API helper**

```typescript
export async function improveSystemPrompt(token: string, prompt: string) {
  const res = await fetch(`${apiBase()}/api/settings/improve-system-prompt`, {
    method: "POST",
    headers: { ...authHeaders(token), "Content-Type": "application/json" },
    body: JSON.stringify({ prompt }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json() as Promise<{ prompt: string }>;
}
```

- [ ] **Step 2: Settings UI** — special-case `system_prompt`: label row with wand button when trim non-empty; `improvingPrompt` state; on success `updateDraft`; on failure set error

- [ ] **Step 3: i18n** — `improveSystemPrompt`, `improvingSystemPrompt`, `improveSystemPromptFailed` under `settings`; usage `featureSettingsImprove` / hint

- [ ] **Step 4: Usage FEATURES** entry for `settings_improve`

- [ ] **Step 5: Commit** `feat(settings): AI improve control for system prompt`

---

## Spec coverage

| Spec item | Task |
|-----------|------|
| Runtime HK datetime | Task 1 |
| Improve API | Task 2 |
| Draft overwrite UI | Task 3 |
| i18n + usage feature | Task 3 |
| Tests | Tasks 1–2 |
