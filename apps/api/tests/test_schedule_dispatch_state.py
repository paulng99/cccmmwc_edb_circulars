from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.services.schedule_dispatch_state import (
    REDIS_KEY,
    REDIS_KEY_LAST_DUE,
    load_last_dispatch,
    load_last_due_dispatch,
    parse_checked_to,
    persist_last_dispatch,
)

HK = ZoneInfo("Asia/Hong_Kong")


def _mock_store_client(store: dict[str, str]) -> MagicMock:
    client = MagicMock()
    client.set = lambda key, value, ex=None: store.__setitem__(key, value)
    client.get = lambda key: store.get(key)
    client.close = MagicMock()
    return client


def test_persist_and_load_roundtrip():
    store: dict[str, str] = {}
    client = _mock_store_client(store)

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
        loaded_due = load_last_due_dispatch()

    assert loaded == payload
    assert loaded_due == payload
    assert REDIS_KEY in store
    assert REDIS_KEY_LAST_DUE in store
    assert json.loads(store[REDIS_KEY])["enqueued"] == ["edb_circulars"]
    assert json.loads(store[REDIS_KEY_LAST_DUE])["due"] == ["edb_circulars"]


def test_empty_due_minute_does_not_wipe_last_due():
    store: dict[str, str] = {}
    client = _mock_store_client(store)

    due_payload = {
        "status": "ok",
        "at": "2026-10-23T06:00:00+08:00",
        "checked_from": "2026-10-23T06:00:00+08:00",
        "checked_to": "2026-10-23T06:00:00+08:00",
        "due": ["edb_circulars"],
        "enqueued": ["edb_circulars"],
        "skipped_busy": [],
        "task_ids": {"edb_circulars": "task-1"},
    }
    empty_payload = {
        "status": "ok",
        "at": "2026-10-23T06:01:00+08:00",
        "checked_from": "2026-10-23T06:01:00+08:00",
        "checked_to": "2026-10-23T06:01:00+08:00",
        "due": [],
        "enqueued": [],
        "skipped_busy": [],
        "task_ids": {},
    }
    with patch("app.services.schedule_dispatch_state._client", return_value=client):
        persist_last_dispatch(due_payload)
        persist_last_dispatch(empty_payload)
        assert load_last_dispatch() == empty_payload
        assert load_last_due_dispatch() == due_payload


def test_enqueued_only_still_updates_last_due():
    """Non-empty enqueued alone is enough (due may be empty in edge payloads)."""
    store: dict[str, str] = {}
    client = _mock_store_client(store)
    payload = {
        "status": "ok",
        "due": [],
        "enqueued": ["edb_www"],
        "skipped_busy": [],
        "checked_to": "2026-10-23T06:30:00+08:00",
    }
    with patch("app.services.schedule_dispatch_state._client", return_value=client):
        persist_last_dispatch(payload)
        assert load_last_due_dispatch() == payload


def test_load_returns_none_when_missing():
    client = MagicMock()
    client.get.return_value = None
    client.close = MagicMock()
    with patch("app.services.schedule_dispatch_state._client", return_value=client):
        assert load_last_dispatch() is None
        assert load_last_due_dispatch() is None


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
