from datetime import date, datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.api.documents import SORT_DOWNLOADED, SORT_ISSUED, _normalize_sort, _to_groups


def _doc(**kwargs):
    defaults = dict(
        id=uuid4(),
        source_id="edb_circulars",
        title="通告",
        circular_no="EDBCM001/2026",
        issued_at=date(2026, 1, 1),
        revised_at=None,
        language="zh-HK",
        programme="circular",
        topics=[],
        status="ready",
        file_size=10,
        created_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_normalize_sort_defaults_to_issued_newest():
    field, descending = _normalize_sort(None, None)
    assert field == SORT_ISSUED
    assert descending is True


def test_normalize_sort_downloaded_oldest():
    field, descending = _normalize_sort("downloaded_at", "asc")
    assert field == SORT_DOWNLOADED
    assert descending is False


def test_group_uses_latest_created_at_as_downloaded_at():
    older = _doc(
        circular_no="EDBCM010/2026",
        language="zh-HK",
        created_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )
    newer = _doc(
        circular_no="EDBCM010/2026",
        language="en",
        title="Circular",
        created_at=datetime(2026, 10, 5, 8, 30, tzinfo=timezone.utc),
    )
    groups = _to_groups([older, newer])
    assert len(groups) == 1
    assert groups[0].downloaded_at == "2026-10-05T08:30:00+00:00"


def test_sort_groups_by_downloaded_at_desc():
    a = _doc(
        circular_no="EDBCM001/2026",
        issued_at=date(2026, 9, 1),
        created_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )
    b = _doc(
        circular_no="EDBCM002/2026",
        issued_at=date(2026, 8, 1),
        created_at=datetime(2026, 10, 6, tzinfo=timezone.utc),
    )
    groups = _to_groups([a, b], sort_by=SORT_DOWNLOADED, descending=True)
    assert [g.circular_no for g in groups] == ["EDBCM002/2026", "EDBCM001/2026"]


def test_sort_groups_by_issued_at_asc_nulls_last():
    dated = _doc(
        circular_no="EDBCM003/2026",
        issued_at=date(2025, 1, 1),
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    undated = _doc(
        circular_no="EDBCM004/2026",
        issued_at=None,
        created_at=datetime(2026, 10, 6, tzinfo=timezone.utc),
    )
    groups = _to_groups([undated, dated], sort_by=SORT_ISSUED, descending=False)
    assert [g.circular_no for g in groups] == ["EDBCM003/2026", "EDBCM004/2026"]
