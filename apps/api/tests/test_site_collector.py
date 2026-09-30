"""Site crawl must not report success when every page fetch failed."""

from __future__ import annotations

import httpx
import pytest

from app.collectors.base import SiteAttachmentsCollector

SEED = "https://www.edb.gov.hk/tc/curriculum-development/curriculum-area/life-wide-learning/LWLSSG/index.html"
IN_SCOPE = "https://www.edb.gov.hk/tc/curriculum-development/curriculum-area/life-wide-learning/LWLSSG/guide.html"
OUT_OF_SCOPE = "https://www.edb.gov.hk/tc/about-edb/info/welcome/index.html"
ATTACHMENT_PDF = "https://www.edb.gov.hk/attachment/tc/lwlssg/guide.pdf"
OFFSITE_PDF = "https://www.edb.gov.hk/tc/about-edb/report.pdf"


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


class _ScopedHtmlClient:
    """Seed page links to in-scope + site-nav out-of-scope + PDFs."""

    pages: dict[str, str] = {
        SEED: f"""
        <html><body>
          <a href="{IN_SCOPE}">Guide</a>
          <a href="{OUT_OF_SCOPE}">About EDB</a>
          <a href="{ATTACHMENT_PDF}">PDF</a>
          <a href="{OFFSITE_PDF}">Unrelated PDF</a>
        </body></html>
        """,
        IN_SCOPE: f"""
        <html><body>
          <a href="{OUT_OF_SCOPE}">Nav leak</a>
          <a href="{ATTACHMENT_PDF}">Same PDF</a>
        </body></html>
        """,
        OUT_OF_SCOPE: "<html><body><a href='/tc/index.html'>Home</a></body></html>",
    }

    def __init__(self, *args, **kwargs):
        self.fetched: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url):
        self.fetched.append(url)
        html = self.pages.get(url, "<html></html>")
        return httpx.Response(200, text=html, headers={"content-type": "text/html"}, request=httpx.Request("GET", url))


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


@pytest.mark.asyncio
async def test_path_prefixes_limit_html_bfs_and_allow_attachment_pdfs(monkeypatch):
    client = _ScopedHtmlClient()

    class _Factory:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return client

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr("app.collectors.base.httpx.AsyncClient", _Factory)
    monkeypatch.setattr(
        "app.collectors.base.resolved_settings",
        lambda: {"crawl_user_agent": "test", "crawl_rate_limit_seconds": 0},
    )
    collector = SiteAttachmentsCollector()
    items = await collector.discover(
        {
            "base_url": SEED,
            "seed_urls": [SEED],
            "allow_hosts": ["www.edb.gov.hk"],
            "file_extensions": [".pdf"],
            "path_prefixes": [
                "/tc/curriculum-development/curriculum-area/life-wide-learning/LWLSSG",
            ],
            "rate_limit_seconds": 0,
            "max_pages": 50,
        }
    )

    assert OUT_OF_SCOPE not in client.fetched
    assert SEED in client.fetched
    assert IN_SCOPE in client.fetched
    urls = {it.file_url for it in items}
    assert ATTACHMENT_PDF in urls
    assert OFFSITE_PDF not in urls
