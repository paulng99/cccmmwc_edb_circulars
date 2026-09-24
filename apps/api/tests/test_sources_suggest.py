import pytest

from app.services.sources_suggest import (
    build_search_query,
    filter_drafts,
    parse_llm_sources,
    suggest_sources,
)


def test_topic_query_adds_edb_sites():
    q = build_search_query("topic", "幼稚園課程")
    assert "幼稚園課程" in q
    assert "site:edb.gov.hk" in q
    assert "site:edcity.hk" in q


def test_url_query_rejects_non_http():
    assert build_search_query("url", "https://www.edb.gov.hk/tc/example").startswith("https://")
    with pytest.raises(ValueError):
        build_search_query("url", "not a url")


def test_parse_llm_json_array():
    text = '```json\n[{"id":"edb_kg","type":"site_attachments"}]\n```'
    parsed = parse_llm_sources(text)
    assert parsed[0]["id"] == "edb_kg"


def test_filter_drops_invalid_and_existing_url():
    existing = [
        {
            "id": "edb_example",
            "base_url": "https://www.edb.gov.hk/tc/example",
        }
    ]
    good = {
        "id": "edb_new",
        "name": {"en": "New", "zh-HK": "新"},
        "enabled": True,
        "priority": 2,
        "type": "site_attachments",
        "base_url": "https://www.edb.gov.hk/tc/new",
        "allow_hosts": ["www.edb.gov.hk"],
        "file_extensions": [".pdf"],
        "rate_limit_seconds": 1.5,
        "schedule": "0 8 * * 0",
        "max_pages": 100,
    }
    dup = dict(good)
    dup["id"] = "edb_dup"
    dup["base_url"] = "https://www.edb.gov.hk/tc/example/"
    kept, dropped = filter_drafts([good, {"id": "bad"}, dup], existing)
    assert dropped == 2
    assert len(kept) == 1
    assert kept[0]["enabled"] is False
    assert kept[0]["id"] == "edb_new"


@pytest.mark.asyncio
async def test_suggest_does_not_need_writer(tmp_path):
    async def search(query: str) -> str:
        assert "site:edb.gov.hk" in query
        return "search hit https://www.edb.gov.hk/tc/new"

    async def complete(prompt: str) -> str:
        assert "search hit" in prompt
        return """[
          {
            "id": "edb_new",
            "name": {"en": "New", "zh-HK": "新"},
            "enabled": true,
            "priority": 2,
            "type": "site_attachments",
            "base_url": "https://www.edb.gov.hk/tc/new",
            "allow_hosts": ["www.edb.gov.hk"],
            "file_extensions": [".pdf"],
            "rate_limit_seconds": 1.5,
            "schedule": "0 8 * * 0",
            "max_pages": 100
          },
          {"id": "nope"}
        ]"""

    result = await suggest_sources(
        mode="topic",
        query="新來源",
        existing=[],
        jina_api_key="test-key",
        search=search,
        complete=complete,
    )
    assert result["dropped"] == 1
    assert result["suggestions"][0]["enabled"] is False
    assert not (tmp_path / "sources.yaml").exists()
