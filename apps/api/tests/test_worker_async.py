"""Celery worker must not reuse async DB connections across asyncio.run() loops."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from app.worker import _run_async


def test_run_async_disposes_engine_between_sequential_tasks():
    mock_engine = MagicMock()
    mock_engine.sync_engine.dispose = MagicMock()
    mock_engine.dispose = AsyncMock()

    with patch("app.core.db.engine", mock_engine):

        async def ping(value: str) -> str:
            return value

        assert _run_async(ping("a")) == "a"
        assert _run_async(ping("b")) == "b"

    assert mock_engine.sync_engine.dispose.call_count == 2
    for call in mock_engine.sync_engine.dispose.call_args_list:
        assert call.kwargs.get("close") is False
    assert mock_engine.dispose.await_count == 2
