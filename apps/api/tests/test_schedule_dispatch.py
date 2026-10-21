from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.services.schedule_dispatch import (
    CATCH_UP_MAX_MINUTES,
    catch_up_window,
    dispatch_scheduled_crawls,
    sources_due_at,
    sources_due_between,
)

HK = ZoneInfo("Asia/Hong_Kong")


def test_sources_due_at_filters_and_sorts_by_priority():
    when = datetime(2026, 10, 10, 6, 0, tzinfo=HK)
    sources = [
        {"id": "b", "enabled": True, "priority": 2, "schedule": "0 6 * * *"},
        {"id": "a", "enabled": True, "priority": 0, "schedule": "0 6 * * *"},
        {"id": "c", "enabled": True, "priority": 1, "schedule": "30 6 * * *"},
        {"id": "off", "enabled": False, "priority": 0, "schedule": "0 6 * * *"},
    ]
    due = sources_due_at(sources, when)
    assert [s["id"] for s in due] == ["a", "b"]


def test_catch_up_window_resumes_after_last_checked():
    minute_now = datetime(2026, 10, 20, 6, 10, tzinfo=HK)
    last = datetime(2026, 10, 20, 5, 55, tzinfo=HK)
    start = catch_up_window(minute_now, last_checked=last)
    assert start == datetime(2026, 10, 20, 5, 56, tzinfo=HK)


def test_catch_up_window_caps_long_outage():
    minute_now = datetime(2026, 10, 20, 12, 0, tzinfo=HK)
    last = minute_now - timedelta(minutes=CATCH_UP_MAX_MINUTES + 120)
    start = catch_up_window(minute_now, last_checked=last)
    assert start == minute_now - timedelta(minutes=CATCH_UP_MAX_MINUTES)


def test_sources_due_between_catches_missed_cron_minute():
    """Late worker: now is 06:10 but cron was 06:00 — still due."""
    sources = [
        {"id": "edb_circulars", "enabled": True, "priority": 0, "schedule": "0 6 * * *"},
        {"id": "later", "enabled": True, "priority": 1, "schedule": "30 6 * * *"},
    ]
    window_start = datetime(2026, 10, 20, 5, 55, tzinfo=HK)
    minute_now = datetime(2026, 10, 20, 6, 10, tzinfo=HK)
    assert sources_due_between(sources, window_start, minute_now) == ["edb_circulars"]


def test_exact_minute_only_misses_when_late_without_window():
    """Documents the production failure mode before catch-up."""
    when_late = datetime(2026, 10, 20, 6, 10, tzinfo=HK)
    sources = [{"id": "edb_circulars", "enabled": True, "priority": 0, "schedule": "0 6 * * *"}]
    assert sources_due_at(sources, when_late) == []


@pytest.mark.asyncio
async def test_dispatch_skips_when_crawl_disabled():
    session = AsyncMock()
    with (
        patch(
            "app.services.schedule_dispatch.resolved_settings",
            new=AsyncMock(return_value={"crawl_enabled": False}),
        ),
        patch("app.services.schedule_dispatch.persist_last_dispatch") as persist,
        patch(
            "app.services.schedule_dispatch._sources_path_meta",
            return_value={"sources_path": "/config/sources.yaml", "sources_mtime": 1.0},
        ),
    ):
        result = await dispatch_scheduled_crawls(session)
    assert result["status"] == "skipped"
    assert result["reason"] == "crawl_disabled"
    persist.assert_called_once()


@pytest.mark.asyncio
async def test_dispatch_enqueues_due_and_skips_busy():
    session = AsyncMock()
    when = datetime(2026, 10, 10, 6, 0, tzinfo=HK)
    sources = [
        {"id": "ready", "enabled": True, "priority": 0, "schedule": "0 6 * * *"},
        {"id": "busy", "enabled": True, "priority": 1, "schedule": "0 6 * * *"},
    ]
    mock_delay = MagicMock(return_value=MagicMock(id="task-1"))

    with (
        patch(
            "app.services.schedule_dispatch.resolved_settings",
            new=AsyncMock(return_value={"crawl_enabled": True}),
        ),
        patch(
            "app.services.schedule_dispatch.get_enabled_sources",
            return_value=sources,
        ),
        patch(
            "app.services.schedule_dispatch.source_ids_blocked",
            new=AsyncMock(return_value={"busy"}),
        ),
        patch(
            "app.services.schedule_dispatch.load_last_dispatch",
            return_value={"checked_to": when.isoformat()},
        ),
        patch("app.services.schedule_dispatch.persist_last_dispatch") as persist,
        patch(
            "app.services.schedule_dispatch._sources_path_meta",
            return_value={"sources_path": "/config/sources.yaml", "sources_mtime": 1.0},
        ),
        patch("app.worker.crawl_source") as mock_crawl,
    ):
        mock_crawl.delay = mock_delay
        result = await dispatch_scheduled_crawls(session, now=when)

    mock_delay.assert_called_once_with("ready")
    assert result["enqueued"] == ["ready"]
    assert result["skipped_busy"] == ["busy"]
    assert result["due"] == ["ready", "busy"]
    assert result["status"] == "ok"
    persist.assert_called_once()
    stored = persist.call_args.args[0]
    assert stored["enqueued"] == ["ready"]


@pytest.mark.asyncio
async def test_dispatch_late_run_enqueues_missed_0600_slot():
    """Worker free at 06:10 after being busy — still enqueue 06:00 cron."""
    session = AsyncMock()
    when = datetime(2026, 10, 20, 6, 10, tzinfo=HK)
    last = {"checked_to": datetime(2026, 10, 20, 5, 50, tzinfo=HK).isoformat()}
    sources = [
        {"id": "edb_circulars", "enabled": True, "priority": 0, "schedule": "0 6 * * *"},
    ]
    mock_delay = MagicMock(return_value=MagicMock(id="task-late"))

    with (
        patch(
            "app.services.schedule_dispatch.resolved_settings",
            new=AsyncMock(return_value={"crawl_enabled": True}),
        ),
        patch(
            "app.services.schedule_dispatch.get_enabled_sources",
            return_value=sources,
        ),
        patch(
            "app.services.schedule_dispatch.source_ids_blocked",
            new=AsyncMock(return_value=set()),
        ),
        patch("app.services.schedule_dispatch.load_last_dispatch", return_value=last),
        patch("app.services.schedule_dispatch.persist_last_dispatch"),
        patch(
            "app.services.schedule_dispatch._sources_path_meta",
            return_value={"sources_path": "/config/sources.yaml", "sources_mtime": 1.0},
        ),
        patch("app.worker.crawl_source") as mock_crawl,
    ):
        mock_crawl.delay = mock_delay
        result = await dispatch_scheduled_crawls(session, now=when)

    mock_delay.assert_called_once_with("edb_circulars")
    assert result["due"] == ["edb_circulars"]
    assert result["enqueued"] == ["edb_circulars"]
    assert result["checked_from"] == datetime(2026, 10, 20, 5, 51, tzinfo=HK).isoformat()
    assert result["checked_to"] == when.replace(second=0, microsecond=0).isoformat()


def test_beat_schedule_uses_dispatcher():
    from app.worker import celery_app

    entry = celery_app.conf.beat_schedule["dispatch-scheduled-crawls"]
    assert entry["task"] == "app.worker.dispatch_scheduled_crawls"
    assert entry.get("options", {}).get("expires") == 120
    assert "daily-crawl-all" not in celery_app.conf.beat_schedule


def test_celery_app_is_default():
    from celery import current_app

    from app.worker import celery_app

    assert current_app._get_current_object() is celery_app
