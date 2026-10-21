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
REDIS_KEY = "edb:schedule_dispatch:last"
# Keep long enough for post-incident review without Coolify shell.
REDIS_TTL_SECONDS = 60 * 60 * 24 * 14


def _client() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url, decode_responses=True)


def persist_last_dispatch(result: dict[str, Any]) -> None:
    """Best-effort write; never raise into the Celery task caller."""
    try:
        payload = json.dumps(result, default=str)
        client = _client()
        try:
            client.set(REDIS_KEY, payload, ex=REDIS_TTL_SECONDS)
        finally:
            client.close()
    except Exception:
        logger.exception("failed to persist last schedule dispatch result")


def load_last_dispatch() -> dict[str, Any] | None:
    """Return the last persisted dispatch outcome, or None if missing/unreadable."""
    try:
        client = _client()
        try:
            raw = client.get(REDIS_KEY)
        finally:
            client.close()
    except Exception:
        logger.exception("failed to load last schedule dispatch result")
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("invalid JSON in %s", REDIS_KEY)
        return None
    return data if isinstance(data, dict) else None


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
