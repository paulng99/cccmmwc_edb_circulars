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
