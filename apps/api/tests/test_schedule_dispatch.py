from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.services.schedule_dispatch import dispatch_scheduled_crawls, sources_due_at

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


@pytest.mark.asyncio
async def test_dispatch_skips_when_crawl_disabled():
    session = AsyncMock()
    with patch(
        "app.services.schedule_dispatch.resolved_settings",
        new=AsyncMock(return_value={"crawl_enabled": False}),
    ):
        result = await dispatch_scheduled_crawls(session)
    assert result["status"] == "skipped"
    assert result["reason"] == "crawl_disabled"


@pytest.mark.asyncio
async def test_dispatch_enqueues_due_and_skips_busy():
    session = AsyncMock()
    when = datetime(2026, 10, 10, 6, 0, tzinfo=HK)
    sources = [
        {"id": "ready", "enabled": True, "priority": 0, "schedule": "0 6 * * *"},
        {"id": "busy", "enabled": True, "priority": 1, "schedule": "0 6 * * *"},
    ]
    mock_celery = MagicMock()

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
        patch("celery.current_app", mock_celery),
    ):
        result = await dispatch_scheduled_crawls(session, now=when)

    mock_celery.send_task.assert_called_once_with("app.worker.crawl_source", args=["ready"])
    assert result["enqueued"] == ["ready"]
    assert result["skipped_busy"] == ["busy"]
    assert result["due"] == ["ready", "busy"]


def test_beat_schedule_uses_dispatcher():
    from app.worker import celery_app

    entry = celery_app.conf.beat_schedule["dispatch-scheduled-crawls"]
    assert entry["task"] == "app.worker.dispatch_scheduled_crawls"
    assert "daily-crawl-all" not in celery_app.conf.beat_schedule
