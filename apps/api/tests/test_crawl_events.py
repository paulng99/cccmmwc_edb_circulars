import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.crawl_events import emit_event, list_recent, pick_current, request_cancel


def test_pick_current_prefers_download_start():
    events = [
        {"event_type": "discovering", "url": None},
        {"event_type": "page", "url": "https://a/page"},
        {"event_type": "download_start", "url": "https://a/f.pdf", "title": "F"},
        {"event_type": "download_ok", "url": "https://a/f.pdf"},
    ]
    # newest-first input as returned by list_recent
    newest_first = list(reversed(events))
    cur = pick_current(newest_first)
    assert cur["event_type"] == "download_start"
    assert cur["url"] == "https://a/f.pdf"


def test_pick_current_falls_back_to_page():
    newest_first = [
        {"event_type": "page", "url": "https://a/p"},
        {"event_type": "discovering", "url": None},
    ]
    assert pick_current(newest_first)["event_type"] == "page"


def test_pick_current_empty():
    assert pick_current([]) is None


@pytest.mark.asyncio
async def test_emit_event_inserts_and_commits():
    session = AsyncMock()
    run_id = uuid.uuid4()
    await emit_event(session, run_id=run_id, event_type="discovering")
    session.add.assert_called_once()
    event = session.add.call_args[0][0]
    assert event.run_id == run_id
    assert event.event_type == "discovering"
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_emit_event_swallows_errors():
    session = AsyncMock()
    session.commit.side_effect = RuntimeError("db down")
    with patch("app.services.crawl_events.logger") as mock_logger:
        await emit_event(session, run_id=uuid.uuid4(), event_type="page", url="https://x")
    mock_logger.exception.assert_called_once()


@pytest.mark.asyncio
async def test_list_recent_orders_newest_first():
    session = AsyncMock()
    run_id = uuid.uuid4()
    older = MagicMock(
        event_type="discovering",
        url=None,
        title=None,
        source_id=None,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    newer = MagicMock(
        event_type="page",
        url="https://a/p",
        title=None,
        source_id="edb",
        created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    scalars = MagicMock()
    scalars.all.return_value = [newer, older]
    result = MagicMock()
    result.scalars.return_value = scalars
    session.execute = AsyncMock(return_value=result)

    rows = await list_recent(session, run_id, limit=40)
    assert len(rows) == 2
    assert rows[0]["event_type"] == "page"
    assert rows[0]["url"] == "https://a/p"
    assert rows[1]["event_type"] == "discovering"
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_request_cancel_all_running():
    session = AsyncMock()
    result = MagicMock()
    result.rowcount = 2
    session.execute = AsyncMock(return_value=result)

    count = await request_cancel(session, None)
    assert count == 2
    session.execute.assert_awaited_once()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_request_cancel_specific_run():
    session = AsyncMock()
    result = MagicMock()
    result.rowcount = 1
    session.execute = AsyncMock(return_value=result)
    run_id = uuid.uuid4()

    count = await request_cancel(session, run_id)
    assert count == 1


@pytest.mark.asyncio
async def test_request_cancel_none_running():
    session = AsyncMock()
    result = MagicMock()
    result.rowcount = 0
    session.execute = AsyncMock(return_value=result)

    count = await request_cancel(session, None)
    assert count == 0


@pytest.mark.asyncio
@patch("app.services.pipeline.resolved_settings")
@patch("app.services.pipeline.sync_sources_table", new_callable=AsyncMock)
@patch("app.services.pipeline.get_enabled_sources")
@patch("app.services.pipeline.get_collector")
@patch("app.services.pipeline.download_and_store", new_callable=AsyncMock)
@patch("app.services.pipeline.index_document", new_callable=AsyncMock, return_value={"ok": True})
@patch("app.services.pipeline.emit_event", new_callable=AsyncMock)
async def test_run_source_crawl_honours_cancel(
    mock_emit,
    mock_index,
    mock_download,
    mock_get_collector,
    mock_get_sources,
    mock_sync,
    mock_settings,
):
    from app.collectors.base import DiscoveredItem
    from app.models.entities import CrawlRun, Source
    from app.services.pipeline import run_source_crawl

    mock_settings.return_value = {"crawl_enabled": True}
    mock_get_sources.return_value = [
        {"id": "src1", "type": "test", "base_url": "https://example.com", "enabled": True}
    ]
    items = [
        DiscoveredItem(title="A", source_url="https://example.com/a", file_url="https://example.com/a.pdf"),
        DiscoveredItem(title="B", source_url="https://example.com/b", file_url="https://example.com/b.pdf"),
        DiscoveredItem(title="C", source_url="https://example.com/c", file_url="https://example.com/c.pdf"),
    ]
    collector = MagicMock()
    collector.discover = AsyncMock(return_value=items)
    mock_get_collector.return_value = collector

    doc = MagicMock()
    doc.status = "stored"
    doc.id = uuid.uuid4()
    mock_download.return_value = doc

    run_obj: CrawlRun | None = None
    get_count = 0

    async def fake_get(model, _id):
        nonlocal get_count, run_obj
        if model is CrawlRun and run_obj is not None:
            get_count += 1
            if get_count >= 2:
                run_obj.cancel_requested = True
            return run_obj
        if model is Source:
            return None
        return None

    session = AsyncMock()
    session.get = AsyncMock(side_effect=fake_get)
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.rollback = AsyncMock()

    def fake_add(obj):
        nonlocal run_obj
        if isinstance(obj, CrawlRun):
            run_obj = obj

    session.add = MagicMock(side_effect=fake_add)

    result = await run_source_crawl(session)

    assert mock_download.await_count == 1
    assert result["runs"][0]["status"] == "cancelled"
    event_types = [call.kwargs["event_type"] for call in mock_emit.call_args_list]
    assert "cancelled" in event_types
    assert "done" not in event_types
