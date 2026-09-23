from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.core.config import get_settings


@dataclass
class DiscoveredItem:
    title: str
    source_url: str
    file_url: str
    circular_no: str | None = None
    issued_at: date | None = None
    language: str = "zh-HK"
    mime_type: str = "application/pdf"
    meta: dict[str, Any] | None = None


class Collector(Protocol):
    async def discover(self, config: dict[str, Any]) -> list[DiscoveredItem]: ...


def _parse_hk_date(text: str) -> date | None:
    text = text.strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


class CircularAspNetCollector:
    """EDB Circulars ASP.NET search form collector."""

    async def discover(self, config: dict[str, Any]) -> list[DiscoveredItem]:
        settings = get_settings()
        base = config.get("base_url") or "https://applications.edb.gov.hk/circular/circular.aspx"
        langs = config.get("langs") or [2]
        rate = float(config.get("rate_limit_seconds") or settings.crawl_rate_limit_seconds)
        # default: last ~2 years in yearly slices for backfill friendliness
        year_from = int(config.get("year_from") or date.today().year - 1)
        year_to = int(config.get("year_to") or date.today().year)

        items: list[DiscoveredItem] = []
        seen: set[str] = set()
        headers = {"User-Agent": settings.crawl_user_agent}

        async with httpx.AsyncClient(headers=headers, timeout=90, follow_redirects=True) as client:
            for lang in langs:
                lang_url = f"{base}?langno={lang}"
                language = "en" if int(lang) == 1 else "zh-HK"
                for year in range(year_from, year_to + 1):
                    period_from = f"1/1/{year}"
                    period_to = f"31/12/{year}"
                    batch = await self._search_period(client, lang_url, period_from, period_to, language)
                    for it in batch:
                        if it.file_url in seen:
                            continue
                        seen.add(it.file_url)
                        items.append(it)
                    await asyncio.sleep(rate)
        return items

    async def _search_period(
        self,
        client: httpx.AsyncClient,
        url: str,
        period_from: str,
        period_to: str,
        language: str,
    ) -> list[DiscoveredItem]:
        r = await client.get(url)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")

        def hid(name: str) -> str:
            el = soup.find("input", {"name": name})
            return el.get("value", "") if el else ""

        data = {
            "__VIEWSTATE": hid("__VIEWSTATE"),
            "__VIEWSTATEGENERATOR": hid("__VIEWSTATEGENERATOR"),
            "__EVENTVALIDATION": hid("__EVENTVALIDATION"),
            "__EVENTTARGET": "",
            "__EVENTARGUMENT": "",
            "ctl00$currentSection": "2",
            "ctl00$MainContentPlaceHolder$txtKeyword": "",
            "ctl00$MainContentPlaceHolder$ddlSchoolType2": "",
            "ctl00$MainContentPlaceHolder$ddlCircularType": "",
            "ctl00$MainContentPlaceHolder$txtCircularNumber": "",
            "ctl00$MainContentPlaceHolder$txtPeriodFrom": period_from,
            "ctl00$MainContentPlaceHolder$txtPeriodTo": period_to,
            "ctl00$MainContentPlaceHolder$btnSearch2": "Search",
        }
        r2 = await client.post(url, data=data)
        r2.raise_for_status()
        return self._parse_results(r2.text, url, language)

    def _parse_results(self, html: str, page_url: str, language: str) -> list[DiscoveredItem]:
        soup = BeautifulSoup(html, "lxml")
        items: list[DiscoveredItem] = []
        # Prefer table rows with PDF links
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            if not href.lower().endswith(".pdf"):
                continue
            file_url = urljoin(page_url, href)
            fname = file_url.split("/")[-1]
            title = a.get_text(" ", strip=True) or fname
            row = a.find_parent("tr")
            row_text = row.get_text(" ", strip=True) if row else title
            circ = None
            # Prefer EDB file stem (EDBCM26157E) over date-like row text (09/2026)
            fm = re.search(r"(EDBC(?:M)?\d+[A-Za-z]?)", fname, re.I)
            if fm:
                circ = fm.group(1).upper()
            else:
                m = re.search(
                    r"(EDBC(?:M)?\s*\d+/\d+|No\.\s*\d+/\d+|\d+/\d{4})",
                    row_text,
                    re.I,
                )
                if m:
                    circ = m.group(1).replace(" ", "")
            issued = None
            dm = re.search(r"(\d{1,2}/\d{1,2}/\d{4})", row_text)
            if dm:
                issued = _parse_hk_date(dm.group(1))
            items.append(
                DiscoveredItem(
                    title=title[:1000],
                    source_url=page_url,
                    file_url=file_url,
                    circular_no=circ,
                    issued_at=issued,
                    language=language,
                    meta={"row_text": row_text[:500]},
                )
            )
        return items


class SiteAttachmentsCollector:
    """BFS crawl within allow_hosts for attachment-like files."""

    async def discover(self, config: dict[str, Any]) -> list[DiscoveredItem]:
        settings = get_settings()
        base = config["base_url"]
        seeds = list(config.get("seed_urls") or [base])
        allow_hosts = set(config.get("allow_hosts") or [urlparse(base).netloc])
        exts = [e.lower() for e in (config.get("file_extensions") or [".pdf"])]
        path_prefixes = config.get("path_prefixes") or []
        max_pages = int(config.get("max_pages") or 500)
        rate = float(config.get("rate_limit_seconds") or settings.crawl_rate_limit_seconds)

        headers = {"User-Agent": settings.crawl_user_agent}
        seen_pages: set[str] = set()
        seen_files: set[str] = set()
        queue: list[str] = list(seeds)
        items: list[DiscoveredItem] = []

        async with httpx.AsyncClient(headers=headers, timeout=60, follow_redirects=True) as client:
            while queue and len(seen_pages) < max_pages:
                url = queue.pop(0)
                if url in seen_pages:
                    continue
                parsed = urlparse(url)
                if parsed.netloc not in allow_hosts:
                    continue
                seen_pages.add(url)
                try:
                    resp = await client.get(url)
                    if resp.status_code >= 400:
                        continue
                    ctype = resp.headers.get("content-type", "")
                    if "html" not in ctype and not url.endswith((".htm", ".html", "/")):
                        continue
                    soup = BeautifulSoup(resp.text, "lxml")
                    for a in soup.select("a[href]"):
                        href = urljoin(url, a.get("href", ""))
                        p = urlparse(href)
                        if p.scheme not in ("http", "https"):
                            continue
                        path_l = p.path.lower()
                        if any(path_l.endswith(ext) for ext in exts):
                            if path_prefixes and not any(p.path.startswith(pref) for pref in path_prefixes):
                                # still allow if seed page linked it (common for LWLSSG)
                                if not path_prefixes or "/attachment/" in p.path or any(
                                    path_l.endswith(ext) for ext in exts
                                ):
                                    pass
                                else:
                                    continue
                            if href in seen_files:
                                continue
                            seen_files.add(href)
                            title = a.get_text(" ", strip=True) or p.path.split("/")[-1]
                            lang = "en" if "/en/" in p.path or "/attachment/en/" in p.path else "zh-HK"
                            items.append(
                                DiscoveredItem(
                                    title=title[:1000],
                                    source_url=url,
                                    file_url=href,
                                    language=lang,
                                )
                            )
                        elif p.netloc in allow_hosts and href not in seen_pages:
                            if path_prefixes:
                                if any(p.path.startswith(pref) for pref in path_prefixes) or p.path.endswith(
                                    (".html", ".htm", "/")
                                ):
                                    queue.append(href.split("#")[0])
                            else:
                                queue.append(href.split("#")[0])
                except Exception:
                    continue
                await asyncio.sleep(rate)
        return items


def get_collector(source_type: str) -> Collector:
    if source_type == "circular_aspnet":
        return CircularAspNetCollector()
    if source_type == "site_attachments":
        return SiteAttachmentsCollector()
    raise ValueError(f"Unknown collector type: {source_type}")
