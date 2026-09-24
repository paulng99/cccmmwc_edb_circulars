import pytest

from app.services.sources_config import SourceConfigError, normalize_base_url, validate_source, validate_sources


def _site(**overrides):
    base = {
        "id": "edb_example",
        "name": {"en": "Example", "zh-HK": "例子"},
        "enabled": False,
        "priority": 1,
        "type": "site_attachments",
        "base_url": "https://www.edb.gov.hk/tc/example",
        "allow_hosts": ["www.edb.gov.hk"],
        "file_extensions": [".pdf"],
        "rate_limit_seconds": 1.5,
        "schedule": "0 7 * * 0",
        "max_pages": 200,
    }
    base.update(overrides)
    return base


def test_validate_site_attachments_ok():
    out = validate_source(_site())
    assert out["id"] == "edb_example"
    assert out["enabled"] is False
    assert out["file_extensions"] == [".pdf"]


def test_reject_bad_id_unknown_type_and_empty_hosts():
    with pytest.raises(SourceConfigError):
        validate_source(_site(id="Bad-ID"))
    with pytest.raises(SourceConfigError):
        validate_source(_site(type="rss"))
    with pytest.raises(SourceConfigError):
        validate_source(_site(allow_hosts=[]))


def test_circular_requires_langs_and_years():
    out = validate_source(
        {
            "id": "edb_circulars",
            "name": {"en": "Circulars", "zh-HK": "通告"},
            "enabled": True,
            "priority": 0,
            "type": "circular_aspnet",
            "base_url": "https://applications.edb.gov.hk/circular/circular.aspx",
            "langs": [2, 1],
            "year_from": 2025,
            "year_to": 2026,
            "rate_limit_seconds": 1.5,
            "schedule": "0 6 * * *",
        }
    )
    assert out["langs"] == [2, 1]
    with pytest.raises(SourceConfigError):
        validate_source(
            {
                "id": "edb_circulars",
                "name": {"en": "Circulars", "zh-HK": "通告"},
                "enabled": True,
                "priority": 0,
                "type": "circular_aspnet",
                "base_url": "https://applications.edb.gov.hk/circular/circular.aspx",
                "langs": [2],
                "year_from": 2026,
                "year_to": 2025,
                "rate_limit_seconds": 1.5,
                "schedule": "0 6 * * *",
            }
        )


def test_duplicate_id_and_cap():
    with pytest.raises(SourceConfigError):
        validate_sources([_site(), _site()])
    with pytest.raises(SourceConfigError):
        validate_sources([_site(id=f"src_{i}") for i in range(41)])


def test_normalize_base_url():
    assert normalize_base_url("https://WWW.EDB.GOV.HK/tc/example/") == "https://www.edb.gov.hk/tc/example"
