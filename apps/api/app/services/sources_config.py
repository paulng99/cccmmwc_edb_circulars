from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

import yaml

ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,62}$")
CRON_RE = re.compile(r"^\S+(?:\s+\S+){4}$")
ALLOWED_EXTS = frozenset({".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"})
MAX_SOURCES = 40
HEADER = "# Source registry. Edited from Settings. Collectors read this at crawl time.\n"


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
