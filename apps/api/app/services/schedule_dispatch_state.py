"""Persist last scheduled-dispatch outcome for operator diagnostics (Redis)."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import redis

from app.core.config import get_settings

logger = logging.getLogger(__name__)

HK = ZoneInfo("Asia/Hong_Kong")
# Watermark / catch-up cursor: overwritten every minute (often due=[]).
REDIS_KEY = "edb:schedule_dispatch:last"
# Most recent dispatch that had non-empty due and/or enqueued (acceptance signal).
REDIS_KEY_LAST_DUE = "edb:schedule_dispatch:last_due"
# Keep long enough for post-incident review without Coolify shell.
REDIS_TTL_SECONDS = 60 * 60 * 24 * 14


def _client() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url, decode_responses=True)


def _has_due_activity(result: dict[str, Any]) -> bool:
    due = result.get("due") or []
    enqueued = result.get("enqueued") or []
    return bool(due) or bool(enqueued)


def _set_json(key: str, result: dict[str, Any]) -> None:
    payload = json.dumps(result, default=str)
    client = _client()
    try:
        client.set(key, payload, ex=REDIS_TTL_SECONDS)
    finally:
        client.close()


def _get_json(key: str) -> dict[str, Any] | None:
    try:
        client = _client()
        try:
            raw = client.get(key)
        finally:
            client.close()
    except Exception:
        logger.exception("failed to load schedule dispatch key %s", key)
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("invalid JSON in %s", key)
        return None
    return data if isinstance(data, dict) else None


def persist_last_dispatch(result: dict[str, Any]) -> None:
    """Best-effort write; never raise into the Celery task caller.

    Always overwrites the watermark key (catch-up). When ``due`` or ``enqueued``
    is non-empty, also refreshes the separate last-due record so empty-minute
    snapshots do not erase the acceptance signal.
    """
    try:
        _set_json(REDIS_KEY, result)
        if _has_due_activity(result):
            _set_json(REDIS_KEY_LAST_DUE, result)
    except Exception:
        logger.exception("failed to persist last schedule dispatch result")


def load_last_dispatch() -> dict[str, Any] | None:
    """Return the last persisted dispatch outcome, or None if missing/unreadable."""
    return _get_json(REDIS_KEY)


def load_last_due_dispatch() -> dict[str, Any] | None:
    """Return the last dispatch with non-empty due/enqueued, or None."""
    return _get_json(REDIS_KEY_LAST_DUE)


def parse_checked_to(result: dict[str, Any] | None) -> datetime | None:
    """Parse ``checked_to`` (Asia/Hong_Kong wall minute) from a stored result."""
    if not result:
        return None
    raw = result.get("checked_to") or result.get("at")
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=HK)
    return dt.astimezone(HK)
