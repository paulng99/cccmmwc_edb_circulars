"""Keep chat tests off the public web unless a test installs its own search double."""

from __future__ import annotations

import pytest

from app.services.web_search import WebSearchOutcome


@pytest.fixture(autouse=True)
def _stub_chat_web_search(monkeypatch):
    async def _empty(query: str, **kwargs):
        return WebSearchOutcome(results=[], attempted=False)

    monkeypatch.setattr("app.services.chat.search_web", _empty)
