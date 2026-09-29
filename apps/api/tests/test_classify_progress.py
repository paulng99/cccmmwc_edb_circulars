"""Classify backfill should expose live CrawlRun progress like re-index."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.classify import CLASSIFY_SOURCE_ID, backfill_classifications
from app.services.crawl_events import pick_current


def test_pick_current_prefers_classify_start():
    newest_first = [
        {"event_type": "classify_ok", "title": "done"},
        {"event_type": "classify_start", "title": "Doc A"},
        {"event_type": "discovering", "title": "n docs"},
    ]
    cur = pick_current(newest_first)
    assert cur is not None
    assert cur["event_type"] == "classify_start"
    assert cur["title"] == "Doc A"


@pytest.mark.asyncio
async def test_backfill_creates_running_crawl_run_and_progress():
    doc = MagicMock()
    doc.id = uuid.uuid4()
    doc.title = "Test circular"
    doc.circular_no = "EDB/1"
    doc.file_url = "https://example.com/a.pdf"
    doc.source_id = "edb_circulars"
    doc.topics = []

    run = MagicMock()
    run.id = uuid.uuid4()
    run.cancel_requested = False
    run.status = "running"

    session = AsyncMock()
    session.get = AsyncMock(side_effect=lambda model, key: None if key == CLASSIFY_SOURCE_ID else run)

    scalars_docs = MagicMock()
    scalars_docs.all.return_value = [doc]
    result_docs = MagicMock()
    result_docs.scalars.return_value = scalars_docs

    # First scalar: no running job; later get() returns run
    session.scalar = AsyncMock(return_value=None)
    session.scalars = AsyncMock(return_value=scalars_docs)
    session.refresh = AsyncMock()
    session.commit = AsyncMock()
    session.add = MagicMock()

    with (
        patch("app.services.classify.apply_classification", new=AsyncMock(return_value={
            "programme": "circular",
            "topics": ["admin"],
            "topics_skipped": False,
        })),
        patch("app.services.classify.emit_event", new=AsyncMock()) as emit,
        patch("app.services.classify._save_run_progress", new=AsyncMock()) as save_progress,
    ):
        result = await backfill_classifications(session, use_llm=False, force_topics=False)

    assert result["ok"] is True
    assert result["total"] == 1
    assert result["topics_classified"] == 1
    assert session.add.call_count >= 2  # Source + CrawlRun
    added_run = session.add.call_args_list[1][0][0]
    assert added_run.source_id == CLASSIFY_SOURCE_ID
    assert added_run.status == "running"
    assert added_run.discovered == 1
    save_progress.assert_awaited()
    event_types = [c.kwargs.get("event_type") for c in emit.await_args_list]
    assert "discovering" in event_types
    assert "classify_start" in event_types
    assert "classify_ok" in event_types
    assert "done" in event_types
