from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.services.schedule_dispatch_state import (
    REDIS_KEY,
    load_last_dispatch,
    parse_checked_to,
    persist_last_dispatch,
)

HK = ZoneInfo("Asia/Hong_Kong")


def test_persist_and_load_roundtrip():
    store: dict[str, str] = {}
    client = MagicMock()
    client.set = lambda key, value, ex=None: store.__setitem__(key, value)
    client.get = lambda key: store.get(key)
    client.close = MagicMock()

    payload = {
        "status": "ok",
        "due": ["edb_circulars"],
        "enqueued": ["edb_circulars"],
        "skipped_busy": [],
        "checked_to": "2026-10-20T06:00:00+08:00",
    }
    with patch("app.services.schedule_dispatch_state._client", return_value=client):
        persist_last_dispatch(payload)
        loaded = load_last_dispatch()

    assert loaded == payload
    assert REDIS_KEY in store
    assert json.loads(store[REDIS_KEY])["enqueued"] == ["edb_circulars"]


def test_load_returns_none_when_missing():
    client = MagicMock()
    client.get.return_value = None
    client.close = MagicMock()
    with patch("app.services.schedule_dispatch_state._client", return_value=client):
        assert load_last_dispatch() is None


def test_parse_checked_to():
    dt = parse_checked_to({"checked_to": "2026-10-20T06:00:00+08:00"})
    assert dt == datetime(2026, 10, 20, 6, 0, tzinfo=HK)
    assert parse_checked_to(None) is None
    assert parse_checked_to({"checked_to": "not-a-date"}) is None


def test_persist_swallows_redis_errors():
    with patch(
        "app.services.schedule_dispatch_state._client",
        side_effect=OSError("redis down"),
    ):
        persist_last_dispatch({"status": "ok"})  # must not raise
