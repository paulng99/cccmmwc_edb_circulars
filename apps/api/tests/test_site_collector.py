"""Site crawl must not report success when every page fetch failed."""

import httpx
import pytest

from app.collectors.base import SiteAttachmentsCollector


class _FailingClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url):
        err = httpx.ConnectError("temporary failure in name resolution")
        raise err


@pytest.mark.asyncio
async def test_site_collector_raises_when_every_fetch_fails(monkeypatch):
    monkeypatch.setattr("app.collectors.base.httpx.AsyncClient", _FailingClient)
    monkeypatch.setattr(
        "app.collectors.base.resolved_settings",
        lambda: {"crawl_user_agent": "test", "crawl_rate_limit_seconds": 0},
    )
    collector = SiteAttachmentsCollector()
    with pytest.raises(httpx.ConnectError):
        await collector.discover(
            {
                "base_url": "https://www.edb.gov.hk",
                "allow_hosts": ["www.edb.gov.hk"],
                "rate_limit_seconds": 0,
                "max_pages": 3,
            }
        )
