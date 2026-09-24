# Sources YAML Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let operators add, edit, and remove crawl sources from the settings page, and confirm AI suggestions (Jina search + LLM) before they are written to `config/sources.yaml`.

**Architecture:** Pure helpers validate and atomically rewrite the YAML. A separate suggest helper searches Jina, asks the existing LLM for JSON drafts, and never writes the file. FastAPI exposes `GET/PUT /api/sources/config` and `POST /api/sources/suggest`. The settings page renders a form list; Save is the only write. New and suggested sources stay `enabled: false`.

**Tech Stack:** FastAPI, PyYAML, httpx, existing OpenRouter LLM client, Next.js + next-intl (en + zh-HK), pytest.

**Spec:** `docs/superpowers/specs/2026-09-24-sources-yaml-settings-design.md`

## Global Constraints

- Locales: `en` + `zh-HK`
- Collectors: only `circular_aspnet` and `site_attachments`
- New and AI drafts: `enabled: false`
- Suggest does not write `sources.yaml` and does not start a crawl
- Save does not start a crawl
- `PUT` upserts DB rows via existing `sync_sources_table`; it does not delete rows removed from YAML
- Auth: any logged-in user
- At most 40 sources
- API container config mount is writable; worker and beat stay read-only
- Tests must not call live Jina or OpenRouter
- Pytest command (repo root): `docker compose run --rm --no-deps -v "$(pwd)/apps/api:/app" api pytest <path> -v`

## File map

| File | Responsibility |
|------|----------------|
| `apps/api/app/services/sources_config.py` | Schema validation, load, atomic save |
| `apps/api/app/services/sources_suggest.py` | Search query, JSON parse, filter drafts, Jina + LLM orchestration |
| `apps/api/app/api/sources.py` | GET/PUT config, POST suggest |
| `apps/api/app/api/schemas.py` | Request bodies |
| `apps/api/app/main.py` | Register router |
| `apps/api/tests/test_sources_config.py` | Validation and YAML round-trip |
| `apps/api/tests/test_sources_suggest.py` | Suggest filtering without network |
| `docker-compose.yml` | API `./config:/config` (drop `:ro`) |
| `apps/web/src/lib/api.ts` | Client functions |
| `apps/web/src/components/SourcesSection.tsx` | Settings form list + AI panel |
| `apps/web/src/app/[locale]/settings/page.tsx` | Mount the section |
| `apps/web/messages/en.json`, `zh-HK.json` | Strings |

---

### Task 1: Validate one source and a source list

**Files:**
- Create: `apps/api/app/services/sources_config.py`
- Create: `apps/api/tests/test_sources_config.py`

**Interfaces:**
- Produces:
  - `class SourceConfigError(ValueError)`
  - `validate_source(raw: dict) -> dict`
  - `validate_sources(items: list) -> list[dict]`
  - `normalize_base_url(url: str) -> str`

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/test_sources_config.py`:

```python
import pytest

from app.services.sources_config import SourceConfigError, normalize_base_url, validate_source, validate_sources


def _site(**overrides):
    base = {
        "id": "edb_example",
        "name": {"en": "Example", "zh-HK": "例子"},
        "enabled": False,
        "priority": 1,
        "type": "site_attachments",
        "base_url": "https://www.edb.gov.hk/tc/example",
        "allow_hosts": ["www.edb.gov.hk"],
        "file_extensions": [".pdf"],
        "rate_limit_seconds": 1.5,
        "schedule": "0 7 * * 0",
        "max_pages": 200,
    }
    base.update(overrides)
    return base


def test_validate_site_attachments_ok():
    out = validate_source(_site())
    assert out["id"] == "edb_example"
    assert out["enabled"] is False
    assert out["file_extensions"] == [".pdf"]


def test_reject_bad_id_unknown_type_and_empty_hosts():
    with pytest.raises(SourceConfigError):
        validate_source(_site(id="Bad-ID"))
    with pytest.raises(SourceConfigError):
        validate_source(_site(type="rss"))
    with pytest.raises(SourceConfigError):
        validate_source(_site(allow_hosts=[]))


def test_circular_requires_langs_and_years():
    out = validate_source(
        {
            "id": "edb_circulars",
            "name": {"en": "Circulars", "zh-HK": "通告"},
            "enabled": True,
            "priority": 0,
            "type": "circular_aspnet",
            "base_url": "https://applications.edb.gov.hk/circular/circular.aspx",
            "langs": [2, 1],
            "year_from": 2025,
            "year_to": 2026,
            "rate_limit_seconds": 1.5,
            "schedule": "0 6 * * *",
        }
    )
    assert out["langs"] == [2, 1]
    with pytest.raises(SourceConfigError):
        validate_source(
            {
                "id": "edb_circulars",
                "name": {"en": "Circulars", "zh-HK": "通告"},
                "enabled": True,
                "priority": 0,
                "type": "circular_aspnet",
                "base_url": "https://applications.edb.gov.hk/circular/circular.aspx",
                "langs": [2],
                "year_from": 2026,
                "year_to": 2025,
                "rate_limit_seconds": 1.5,
                "schedule": "0 6 * * *",
            }
        )


def test_duplicate_id_and_cap():
    with pytest.raises(SourceConfigError):
        validate_sources([_site(), _site()])
    with pytest.raises(SourceConfigError):
        validate_sources([_site(id=f"src_{i}") for i in range(41)])


def test_normalize_base_url():
    assert normalize_base_url("https://WWW.EDB.GOV.HK/tc/example/") == "https://www.edb.gov.hk/tc/example"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm --no-deps -v "$(pwd)/apps/api:/app" api pytest tests/test_sources_config.py -v`

Expected: FAIL with `ModuleNotFoundError` or `ImportError` for `app.services.sources_config`.

- [ ] **Step 3: Write minimal implementation**

Create `apps/api/app/services/sources_config.py` with validation only (load/save come in Task 2):

```python
from __future__ import annotations

import re
from urllib.parse import urlparse

ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,62}$")
CRON_RE = re.compile(r"^\S+(?:\s+\S+){4}$")
ALLOWED_EXTS = frozenset({".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"})
MAX_SOURCES = 40


class SourceConfigError(ValueError):
    pass


def normalize_base_url(url: str) -> str:
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    path = (parsed.path or "").rstrip("/")
    return f"{parsed.scheme}://{host}{path}"


def _require_http_url(value: str, field: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise SourceConfigError(f"{field} must be an http(s) URL")
    return value.strip()


def validate_source(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise SourceConfigError("source must be an object")
    allowed = {
        "id", "name", "enabled", "priority", "type", "base_url",
        "rate_limit_seconds", "schedule", "allow_hosts", "file_extensions",
        "seed_urls", "path_prefixes", "max_pages", "langs", "year_from", "year_to",
    }
    unknown = set(raw) - allowed
    if unknown:
        raise SourceConfigError(f"unknown keys: {sorted(unknown)}")

    sid = raw.get("id")
    if not isinstance(sid, str) or not ID_RE.match(sid):
        raise SourceConfigError("invalid id")
    name = raw.get("name")
    if not isinstance(name, dict):
        raise SourceConfigError("name is required")
    en = str(name.get("en") or "").strip()
    zh = str(name.get("zh-HK") or "").strip()
    if not en or not zh or len(en) > 200 or len(zh) > 200:
        raise SourceConfigError("name.en and name.zh-HK are required")
    if not isinstance(raw.get("enabled"), bool):
        raise SourceConfigError("enabled must be boolean")
    priority = raw.get("priority")
    if not isinstance(priority, int) or isinstance(priority, bool) or not 0 <= priority <= 9:
        raise SourceConfigError("priority must be 0-9")
    stype = raw.get("type")
    if stype not in ("circular_aspnet", "site_attachments"):
        raise SourceConfigError("unknown type")
    base_url = _require_http_url(str(raw.get("base_url") or ""), "base_url")
    rate = raw.get("rate_limit_seconds", 1.5)
    if isinstance(rate, bool) or not isinstance(rate, (int, float)) or float(rate) < 0.5:
        raise SourceConfigError("rate_limit_seconds must be >= 0.5")
    schedule = raw.get("schedule")
    if not isinstance(schedule, str) or not CRON_RE.match(schedule.strip()):
        raise SourceConfigError("schedule must be 5-field cron")

    out: dict = {
        "id": sid,
        "name": {"en": en, "zh-HK": zh},
        "enabled": raw["enabled"],
        "priority": priority,
        "type": stype,
        "base_url": base_url,
        "rate_limit_seconds": float(rate),
        "schedule": schedule.strip(),
    }

    if stype == "site_attachments":
        hosts = raw.get("allow_hosts")
        if not isinstance(hosts, list) or not hosts or not all(isinstance(h, str) and h.strip() for h in hosts):
            raise SourceConfigError("allow_hosts is required")
        exts = raw.get("file_extensions")
        if not isinstance(exts, list) or not exts or any(e not in ALLOWED_EXTS for e in exts):
            raise SourceConfigError("file_extensions is invalid")
        out["allow_hosts"] = [h.strip() for h in hosts]
        out["file_extensions"] = list(exts)
        seeds = raw.get("seed_urls") or []
        if seeds:
            if not isinstance(seeds, list):
                raise SourceConfigError("seed_urls must be a list")
            out["seed_urls"] = [_require_http_url(str(u), "seed_urls") for u in seeds]
        prefixes = raw.get("path_prefixes") or []
        if prefixes:
            if not isinstance(prefixes, list) or any(not isinstance(p, str) or not p.startswith("/") for p in prefixes):
                raise SourceConfigError("path_prefixes must start with /")
            out["path_prefixes"] = prefixes
        max_pages = raw.get("max_pages", 500)
        if isinstance(max_pages, bool) or not isinstance(max_pages, int) or not 1 <= max_pages <= 5000:
            raise SourceConfigError("max_pages must be 1-5000")
        out["max_pages"] = max_pages
    else:
        langs = raw.get("langs")
        if not isinstance(langs, list) or not langs or any(n not in (1, 2) for n in langs):
            raise SourceConfigError("langs must be 1 and/or 2")
        year_from = raw.get("year_from")
        year_to = raw.get("year_to")
        if isinstance(year_from, bool) or isinstance(year_to, bool):
            raise SourceConfigError("years must be integers")
        if not isinstance(year_from, int) or not isinstance(year_to, int):
            raise SourceConfigError("years must be integers")
        if not 1990 <= year_from <= 2100 or not 1990 <= year_to <= 2100 or year_from > year_to:
            raise SourceConfigError("invalid year range")
        out["langs"] = langs
        out["year_from"] = year_from
        out["year_to"] = year_to
    return out


def validate_sources(items: list) -> list[dict]:
    if not isinstance(items, list):
        raise SourceConfigError("sources must be a list")
    if len(items) > MAX_SOURCES:
        raise SourceConfigError("at most 40 sources")
    seen: set[str] = set()
    out: list[dict] = []
    for item in items:
        src = validate_source(item)
        if src["id"] in seen:
            raise SourceConfigError(f"duplicate id: {src['id']}")
        seen.add(src["id"])
        out.append(src)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose run --rm --no-deps -v "$(pwd)/apps/api:/app" api pytest tests/test_sources_config.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/sources_config.py apps/api/tests/test_sources_config.py
git commit -m "feat(sources): validate crawl source schema"
```

---

### Task 2: Load and atomically save sources.yaml

**Files:**
- Modify: `apps/api/app/services/sources_config.py`
- Modify: `apps/api/tests/test_sources_config.py`

**Interfaces:**
- Consumes: `validate_sources`, `SourceConfigError`
- Produces:
  - `HEADER: str` = `"# Source registry. Edited from Settings. Collectors read this at crawl time.\n"`
  - `load_sources(path: Path) -> list[dict]`
  - `save_sources(path: Path, sources: list[dict]) -> None`

- [ ] **Step 1: Write the failing test**

Append to `apps/api/tests/test_sources_config.py`:

```python
from pathlib import Path

from app.services.sources_config import load_sources, save_sources


def test_save_then_load_round_trip(tmp_path: Path):
    path = tmp_path / "sources.yaml"
    save_sources(path, validate_sources([_site(enabled=True)]))
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# Source registry. Edited from Settings.")
    loaded = load_sources(path)
    assert loaded[0]["id"] == "edb_example"
    assert loaded[0]["name"]["zh-HK"] == "例子"


def test_load_invalid_yaml_raises(tmp_path: Path):
    path = tmp_path / "sources.yaml"
    path.write_text("sources: [\n", encoding="utf-8")
    with pytest.raises(SourceConfigError):
        load_sources(path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm --no-deps -v "$(pwd)/apps/api:/app" api pytest tests/test_sources_config.py::test_save_then_load_round_trip tests/test_sources_config.py::test_load_invalid_yaml_raises -v`

Expected: FAIL with `ImportError` for `load_sources`.

- [ ] **Step 3: Write minimal implementation**

Append to `apps/api/app/services/sources_config.py`:

```python
from pathlib import Path

import yaml

HEADER = "# Source registry. Edited from Settings. Collectors read this at crawl time.\n"


def load_sources(path: Path) -> list[dict]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SourceConfigError(f"invalid sources file: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("sources"), list):
        raise SourceConfigError("sources file must contain a sources list")
    return validate_sources(data["sources"])


def save_sources(path: Path, sources: list[dict]) -> None:
    cleaned = validate_sources(sources)
    payload = HEADER + yaml.safe_dump(
        {"sources": cleaned},
        allow_unicode=True,
        sort_keys=False,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose run --rm --no-deps -v "$(pwd)/apps/api:/app" api pytest tests/test_sources_config.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/sources_config.py apps/api/tests/test_sources_config.py
git commit -m "feat(sources): load and atomically save sources.yaml"
```

---

### Task 3: Suggest drafts without writing the file

**Files:**
- Create: `apps/api/app/services/sources_suggest.py`
- Create: `apps/api/tests/test_sources_suggest.py`

**Interfaces:**
- Consumes: `validate_source`, `normalize_base_url`, `SourceConfigError`
- Produces:
  - `build_search_query(mode: str, query: str) -> str`
  - `parse_llm_sources(text: str) -> list`
  - `filter_drafts(drafts: list, existing: list[dict]) -> tuple[list[dict], int]`
  - `async suggest_sources(*, mode: str, query: str, existing: list[dict], jina_api_key: str, search, complete) -> dict`

`search` is `async (query: str) -> str`. `complete` is `async (prompt: str) -> str`. Return shape: `{"suggestions": list[dict], "dropped": int}`.

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/test_sources_suggest.py`:

```python
import pytest

from app.services.sources_suggest import (
    build_search_query,
    filter_drafts,
    parse_llm_sources,
    suggest_sources,
)


def test_topic_query_adds_edb_sites():
    q = build_search_query("topic", "幼稚園課程")
    assert "幼稚園課程" in q
    assert "site:edb.gov.hk" in q
    assert "site:edcity.hk" in q


def test_url_query_rejects_non_http():
    assert build_search_query("url", "https://www.edb.gov.hk/tc/example").startswith("https://")
    with pytest.raises(ValueError):
        build_search_query("url", "not a url")


def test_parse_llm_json_array():
    text = '```json\n[{"id":"edb_kg","type":"site_attachments"}]\n```'
    parsed = parse_llm_sources(text)
    assert parsed[0]["id"] == "edb_kg"


def test_filter_drops_invalid_and_existing_url():
    existing = [
        {
            "id": "edb_example",
            "base_url": "https://www.edb.gov.hk/tc/example",
        }
    ]
    good = {
        "id": "edb_new",
        "name": {"en": "New", "zh-HK": "新"},
        "enabled": True,
        "priority": 2,
        "type": "site_attachments",
        "base_url": "https://www.edb.gov.hk/tc/new",
        "allow_hosts": ["www.edb.gov.hk"],
        "file_extensions": [".pdf"],
        "rate_limit_seconds": 1.5,
        "schedule": "0 8 * * 0",
        "max_pages": 100,
    }
    dup = dict(good)
    dup["id"] = "edb_dup"
    dup["base_url"] = "https://www.edb.gov.hk/tc/example/"
    kept, dropped = filter_drafts([good, {"id": "bad"}, dup], existing)
    assert dropped == 2
    assert len(kept) == 1
    assert kept[0]["enabled"] is False
    assert kept[0]["id"] == "edb_new"


@pytest.mark.asyncio
async def test_suggest_does_not_need_writer(tmp_path):
    async def search(query: str) -> str:
        assert "site:edb.gov.hk" in query
        return "search hit https://www.edb.gov.hk/tc/new"

    async def complete(prompt: str) -> str:
        assert "search hit" in prompt
        return """[
          {
            "id": "edb_new",
            "name": {"en": "New", "zh-HK": "新"},
            "enabled": true,
            "priority": 2,
            "type": "site_attachments",
            "base_url": "https://www.edb.gov.hk/tc/new",
            "allow_hosts": ["www.edb.gov.hk"],
            "file_extensions": [".pdf"],
            "rate_limit_seconds": 1.5,
            "schedule": "0 8 * * 0",
            "max_pages": 100
          },
          {"id": "nope"}
        ]"""

    result = await suggest_sources(
        mode="topic",
        query="新來源",
        existing=[],
        jina_api_key="test-key",
        search=search,
        complete=complete,
    )
    assert result["dropped"] == 1
    assert result["suggestions"][0]["enabled"] is False
    assert not (tmp_path / "sources.yaml").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm --no-deps -v "$(pwd)/apps/api:/app" api pytest tests/test_sources_suggest.py -v`

Expected: FAIL with `ImportError` for `app.services.sources_suggest`.

- [ ] **Step 3: Write minimal implementation**

Create `apps/api/app/services/sources_suggest.py`:

```python
from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from urllib.parse import urlparse

from app.services.sources_config import SourceConfigError, normalize_base_url, validate_source

SearchFn = Callable[[str], Awaitable[str]]
CompleteFn = Callable[[str], Awaitable[str]]


def build_search_query(mode: str, query: str) -> str:
    text = query.strip()
    if mode == "topic":
        if not text:
            raise ValueError("query is required")
        return f"{text} site:edb.gov.hk OR site:edcity.hk"
    if mode == "url":
        parsed = urlparse(text)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("url must be http(s)")
        return text
    raise ValueError("mode must be topic or url")


def parse_llm_sources(text: str) -> list:
    raw = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", raw, re.S)
    if fence:
        raw = fence.group(1).strip()
    start = raw.find("[")
    end = raw.rfind("]")
    if start < 0 or end < start:
        raise ValueError("LLM did not return a JSON array")
    parsed = json.loads(raw[start : end + 1])
    if not isinstance(parsed, list):
        raise ValueError("LLM did not return a JSON array")
    return parsed[:5]


def filter_drafts(drafts: list, existing: list[dict]) -> tuple[list[dict], int]:
    known_ids = {str(s.get("id")) for s in existing}
    known_urls = set()
    for src in existing:
        url = src.get("base_url")
        if isinstance(url, str) and url.strip():
            known_urls.add(normalize_base_url(url))
    kept: list[dict] = []
    dropped = 0
    for draft in drafts:
        if not isinstance(draft, dict):
            dropped += 1
            continue
        try:
            cleaned = validate_source({**draft, "enabled": False})
        except SourceConfigError:
            dropped += 1
            continue
        if cleaned["id"] in known_ids or normalize_base_url(cleaned["base_url"]) in known_urls:
            dropped += 1
            continue
        known_ids.add(cleaned["id"])
        known_urls.add(normalize_base_url(cleaned["base_url"]))
        kept.append(cleaned)
    return kept, dropped


async def suggest_sources(
    *,
    mode: str,
    query: str,
    existing: list[dict],
    jina_api_key: str,
    search: SearchFn,
    complete: CompleteFn,
) -> dict:
    if not jina_api_key:
        raise SourceConfigError("jina_not_configured")
    search_query = build_search_query(mode, query)
    evidence = await search(search_query)
    prompt = (
        "Turn the search evidence into 1 to 5 crawl source objects as a JSON array only.\n"
        "Allowed type: site_attachments or circular_aspnet.\n"
        "site_attachments needs allow_hosts and file_extensions from "
        ".pdf .doc .docx .xls .xlsx .ppt .pptx.\n"
        "circular_aspnet needs langs [1 and/or 2] and year_from <= year_to.\n"
        "id must match ^[a-z][a-z0-9_]{1,62}$. Include name.en and name.zh-HK.\n"
        "Set enabled to false, priority 0-9, rate_limit_seconds 1.5, "
        "schedule a 5-field cron.\n"
        f"Evidence:\n{evidence[:8000]}"
    )
    raw = await complete(prompt)
    drafts = parse_llm_sources(raw)
    suggestions, dropped = filter_drafts(drafts, existing)
    return {"suggestions": suggestions, "dropped": dropped}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose run --rm --no-deps -v "$(pwd)/apps/api:/app" api pytest tests/test_sources_suggest.py tests/test_sources_config.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/sources_suggest.py apps/api/tests/test_sources_suggest.py
git commit -m "feat(sources): filter AI source drafts without writing YAML"
```

---

### Task 4: HTTP API

**Files:**
- Create: `apps/api/app/api/sources.py`
- Modify: `apps/api/app/api/schemas.py`
- Modify: `apps/api/app/main.py`
- Modify: `apps/api/tests/test_sources_config.py` (path helper only if needed)
- Create: `apps/api/tests/test_sources_api.py`

**Interfaces:**
- Consumes: `load_sources`, `save_sources`, `SourceConfigError`, `suggest_sources`, `sync_sources_table`, `get_current_user`, `resolved_settings`
- Produces:
  - `GET /api/sources/config` → `{ "sources": [...] }`
  - `PUT /api/sources/config` body `{ "sources": [...] }`
  - `POST /api/sources/suggest` body `{ "mode": "topic"|"url", "query": str }`
  - `sources_file_path() -> Path` reads `get_settings().sources_config_path`

Jina call inside the route (not in unit tests of Task 3): `GET https://s.jina.ai/{query}` with `Authorization: Bearer <jina_api_key>`, `Accept: application/json`, timeout 30s. LLM uses `get_llm_client().chat([...], stream=False)`.

Map `SourceConfigError` message `jina_not_configured` to HTTP 400. Other `SourceConfigError` to HTTP 422. Jina/LLM exceptions on suggest to HTTP 502. `PUT` calls `save_sources` then `sync_sources_table(session)`.

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/test_sources_api.py`:

```python
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api.sources import get_sources_config, put_sources_config, suggest_sources_api


def _site():
    return {
        "id": "edb_example",
        "name": {"en": "Example", "zh-HK": "例子"},
        "enabled": False,
        "priority": 1,
        "type": "site_attachments",
        "base_url": "https://www.edb.gov.hk/tc/example",
        "allow_hosts": ["www.edb.gov.hk"],
        "file_extensions": [".pdf"],
        "rate_limit_seconds": 1.5,
        "schedule": "0 7 * * 0",
        "max_pages": 200,
    }


@pytest.mark.asyncio
async def test_put_saves_and_syncs(tmp_path: Path, monkeypatch):
    path = tmp_path / "sources.yaml"
    monkeypatch.setattr("app.api.sources.sources_file_path", lambda: path)
    synced = AsyncMock()
    monkeypatch.setattr("app.api.sources.sync_sources_table", synced)
    body = type("Body", (), {"sources": [_site()]})()
    result = await put_sources_config(body, session=AsyncMock(), user=AsyncMock())
    assert result["sources"][0]["id"] == "edb_example"
    assert path.exists()
    synced.assert_awaited()


@pytest.mark.asyncio
async def test_get_invalid_file_is_422(tmp_path: Path, monkeypatch):
    path = tmp_path / "sources.yaml"
    path.write_text(":", encoding="utf-8")
    monkeypatch.setattr("app.api.sources.sources_file_path", lambda: path)
    with pytest.raises(HTTPException) as exc:
        await get_sources_config(user=AsyncMock())
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_suggest_missing_key_is_400(monkeypatch):
    monkeypatch.setattr(
        "app.api.sources.resolved_settings",
        lambda: {"jina_api_key": ""},
    )
    body = type("Body", (), {"mode": "topic", "query": "課程"})()
    with pytest.raises(HTTPException) as exc:
        await suggest_sources_api(body, user=AsyncMock())
    assert exc.value.status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm --no-deps -v "$(pwd)/apps/api:/app" api pytest tests/test_sources_api.py -v`

Expected: FAIL with `ImportError` for `app.api.sources`.

- [ ] **Step 3: Write minimal implementation**

Add to `apps/api/app/api/schemas.py`:

```python
class SourcesConfigBody(BaseModel):
    sources: list[dict[str, Any]]


class SourceSuggestBody(BaseModel):
    mode: str
    query: str = Field(min_length=1, max_length=500)
```

Create `apps/api/app/api/sources.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.schemas import SourceSuggestBody, SourcesConfigBody
from app.core.config import get_settings
from app.core.db import get_db
from app.models.entities import User
from app.services.llm import get_llm_client
from app.services.pipeline import sync_sources_table
from app.services.runtime_settings import resolved_settings
from app.services.sources_config import SourceConfigError, load_sources, save_sources
from app.services.sources_suggest import suggest_sources

router = APIRouter(prefix="/api/sources", tags=["sources"])


def sources_file_path() -> Path:
    return Path(get_settings().sources_config_path)


def _http_from_config_error(exc: SourceConfigError) -> HTTPException:
    if str(exc) == "jina_not_configured":
        return HTTPException(status_code=400, detail="jina_not_configured")
    return HTTPException(status_code=422, detail=str(exc))


@router.get("/config")
async def get_sources_config(
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    try:
        return {"sources": load_sources(sources_file_path())}
    except SourceConfigError as exc:
        raise _http_from_config_error(exc) from exc


@router.put("/config")
async def put_sources_config(
    body: SourcesConfigBody,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    try:
        save_sources(sources_file_path(), body.sources)
        await sync_sources_table(session)
    except SourceConfigError as exc:
        raise _http_from_config_error(exc) from exc
    return {"sources": load_sources(sources_file_path())}


async def _jina_search(query: str) -> str:
    rs = resolved_settings()
    url = "https://s.jina.ai/" + quote(query, safe="")
    headers = {
        "Authorization": f"Bearer {rs['jina_api_key']}",
        "Accept": "application/json",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.text


async def _llm_complete(prompt: str) -> str:
    llm = get_llm_client()
    answer = await llm.chat(
        [
            {"role": "system", "content": "You output only a JSON array."},
            {"role": "user", "content": prompt},
        ],
        stream=False,
    )
    if not isinstance(answer, str):
        raise RuntimeError("LLM returned no text")
    return answer


@router.post("/suggest")
async def suggest_sources_api(
    body: SourceSuggestBody,
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    rs = resolved_settings()
    try:
        existing = load_sources(sources_file_path())
    except SourceConfigError:
        existing = []
    try:
        return await suggest_sources(
            mode=body.mode,
            query=body.query,
            existing=existing,
            jina_api_key=str(rs.get("jina_api_key") or ""),
            search=_jina_search,
            complete=_llm_complete,
        )
    except SourceConfigError as exc:
        raise _http_from_config_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="suggest_failed") from exc
```

In `apps/api/app/main.py`, import `sources as sources_api` next to the other routers and add `app.include_router(sources_api.router)` before `return app`.

The test calls handlers directly. `put_sources_config` and `get_sources_config` use `Depends` defaults, so calling them with explicit arguments works. `suggest_sources_api` must read `resolved_settings` from `app.api.sources`.

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose run --rm --no-deps -v "$(pwd)/apps/api:/app" api pytest tests/test_sources_api.py tests/test_sources_config.py tests/test_sources_suggest.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/api/sources.py apps/api/app/api/schemas.py apps/api/app/main.py apps/api/tests/test_sources_api.py
git commit -m "feat(sources): add config and suggest API"
```

---

### Task 5: Make the API config mount writable

**Files:**
- Modify: `docker-compose.yml` (api service volumes only)

**Interfaces:**
- Consumes: `SOURCES_CONFIG_PATH=/config/sources.yaml` already set on `api`
- Produces: api container can replace `/config/sources.yaml`

- [ ] **Step 1: Change the api volume**

In the `api` service only, replace:

```yaml
      - ./config:/config:ro
```

with:

```yaml
      - ./config:/config
```

Leave `worker` and `beat` as `./config:/config:ro`.

- [ ] **Step 2: Commit**

```bash
git add docker-compose.yml
git commit -m "chore(docker): allow API to write sources.yaml"
```

---

### Task 6: Settings UI for sources and AI suggestions

**Files:**
- Modify: `apps/web/src/lib/api.ts`
- Create: `apps/web/src/components/SourcesSection.tsx`
- Modify: `apps/web/src/app/[locale]/settings/page.tsx`
- Modify: `apps/web/messages/zh-HK.json`
- Modify: `apps/web/messages/en.json`

**Interfaces:**
- Consumes: `GET/PUT /api/sources/config`, `POST /api/sources/suggest`
- Produces: a **知識來源 / Knowledge sources** block on the settings page

There is no web unit-test runner for this page. Verify by loading `/zh-HK/settings` after the API is rebuilt: the section lists current YAML sources; Save is disabled until the list is dirty; suggesting with an empty query does nothing.

- [ ] **Step 1: Add API client functions**

In `apps/web/src/lib/api.ts`:

```typescript
export type CrawlSource = {
  id: string;
  name: { en: string; "zh-HK": string };
  enabled: boolean;
  priority: number;
  type: "site_attachments" | "circular_aspnet";
  base_url: string;
  rate_limit_seconds: number;
  schedule: string;
  allow_hosts?: string[];
  file_extensions?: string[];
  seed_urls?: string[];
  path_prefixes?: string[];
  max_pages?: number;
  langs?: number[];
  year_from?: number;
  year_to?: number;
};

export async function getSourceConfig(token: string) {
  const res = await fetch(`${API_URL}/api/sources/config`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error(await res.text());
  return res.json() as Promise<{ sources: CrawlSource[] }>;
}

export async function saveSourceConfig(token: string, sources: CrawlSource[]) {
  const res = await fetch(`${API_URL}/api/sources/config`, {
    method: "PUT",
    headers: authHeaders(token),
    body: JSON.stringify({ sources }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json() as Promise<{ sources: CrawlSource[] }>;
}

export async function suggestSources(
  token: string,
  body: { mode: "topic" | "url"; query: string },
) {
  const res = await fetch(`${API_URL}/api/sources/suggest`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json() as Promise<{ suggestions: CrawlSource[]; dropped: number }>;
}
```

- [ ] **Step 2: Add i18n strings**

Under `settings` in `apps/web/messages/zh-HK.json`:

```json
"sourcesTitle": "知識來源",
"sourcesHint": "儲存後寫入 sources.yaml，不會立即爬取。新來源預設關閉。",
"sourcesAdd": "新增",
"sourcesSave": "儲存來源",
"sourcesSaved": "來源已儲存",
"sourcesDelete": "刪除",
"sourcesEdit": "編輯",
"sourcesEnabled": "啟用",
"sourcesId": "識別碼",
"sourcesNameEn": "英文名稱",
"sourcesNameZh": "中文名稱",
"sourcesType": "類型",
"sourcesBaseUrl": "網址",
"sourcesHosts": "允許網域（逗號分隔）",
"sourcesExts": "檔案類型（逗號分隔）",
"sourcesSchedule": "排程",
"sourcesLangs": "語言（1=英文，2=繁中，逗號分隔）",
"sourcesYearFrom": "由年份",
"sourcesYearTo": "至年份",
"sourcesAi": "AI 建議",
"sourcesModeTopic": "主題",
"sourcesModeUrl": "網址",
"sourcesSearch": "搜尋建議",
"sourcesSearching": "正在搜尋…",
"sourcesAddSelected": "加入所選",
"sourcesDropped": "已略過 {count} 個不合格或重複的建議",
"sourcesLoadError": "無法讀取來源",
"sourcesSaveError": "無法儲存來源",
"sourcesSuggestError": "無法取得建議。請確認已設定 Jina API key。"
```

Mirror the same keys in `apps/web/messages/en.json` with English labels: Knowledge sources, Save sources, Sources saved, Add, Delete, Edit, Enabled, Identifier, English name, Chinese name, Type, URL, Allowed hosts (comma-separated), File types (comma-separated), Schedule, Languages (1=English, 2=Traditional Chinese, comma-separated), Year from, Year to, AI suggestions, Topic, URL, Search, Searching…, Add selected, Skipped {count} invalid or duplicate suggestions, Could not load sources, Could not save sources, Could not get suggestions. Check that a Jina API key is set.

- [ ] **Step 3: Add the section component**

Create `apps/web/src/components/SourcesSection.tsx` as a client component:

- On mount, `getSourceConfig(token)` into `sources` state. Keep `savedJson` as `JSON.stringify(sources)` after load and after a successful save.
- List each source: zh-HK name, `id`, `type`, checkbox bound to `enabled`.
- Edit opens the same form used by Add. Fields: id (disabled when editing an existing id), both names, type select, base URL, rate limit, schedule, priority. If type is `site_attachments`, show hosts, extensions, optional seed URLs, optional path prefixes, max pages. If type is `circular_aspnet`, show langs, year from, year to. Comma-separated text inputs split on save of the form into arrays.
- Delete removes the row from local state only.
- Add and edit set `enabled` from the checkbox. The Add button creates `enabled: false`.
- AI panel: mode `topic` | `url`, query input, Search calls `suggestSources`. Render `suggestions` with checkboxes defaulting to unchecked. Hide any suggestion whose `id` or normalized `base_url` (strip trailing slash, lowercase host) already exists in the on-screen `sources` list, including unsaved rows. Add selected appends the checked visible drafts to `sources` with `enabled: false` and removes them from the suggestion list. Show `sourcesDropped` when `dropped > 0`.
- Save calls `saveSourceConfig` only when `JSON.stringify(sources) !== savedJson`. Disable the button otherwise.
- Errors from load, save, and suggest use the i18n strings above. Do not start a crawl.

Mount `<SourcesSection />` inside the settings page `<div className="panel">` above the existing settings `<form>`, passing `token`.

- [ ] **Step 4: Rebuild and check the page**

```bash
docker compose up --build -d api web
```

Open `http://localhost:3000/zh-HK/settings` (port from the web service). Confirm the knowledge-sources list matches `config/sources.yaml`, the Save button stays disabled until a field changes, and an empty AI query does not call the API.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/lib/api.ts apps/web/src/components/SourcesSection.tsx apps/web/src/app/[locale]/settings/page.tsx apps/web/messages/en.json apps/web/messages/zh-HK.json
git commit -m "feat(settings): edit crawl sources and confirm AI suggestions"
```
