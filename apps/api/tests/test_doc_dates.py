from datetime import date, datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.api.documents import SORT_REVISED, _normalize_sort, _to_groups
from app.collectors.base import CircularAspNetCollector
from app.collectors.doc_dates import apply_document_dates, extract_document_dates


ZH_UPDATED = """
(2026 年 7 月 30 日更新)

教育局通告第 9/2025 號
全方位學習及姊妹學校津貼
"""

ZH_MONTH = """
教育局通告第 6/2025 號
中學規劃未來路向優化方案
（2026 年 4 月更新）
"""

EN_UPDATED = """
(Updated on 30 July 2026)

Education Bureau
29 May 2025

Education Bureau Circular No. 9/2025
"""

LABELED = """
發出日期：2024年9月25日
更新日期：2026年1月8日
財務管理指引
"""


def test_chinese_update_stamp():
    found = extract_document_dates(ZH_UPDATED)
    assert found.revised_at == date(2026, 7, 30)
    assert found.issued_at is None


def test_chinese_month_stamp_uses_month_end():
    found = extract_document_dates(ZH_MONTH)
    assert found.revised_at == date(2026, 4, 30)


def test_english_update_and_letterhead_issue_date():
    found = extract_document_dates(EN_UPDATED)
    assert found.revised_at == date(2026, 7, 30)
    assert found.issued_at == date(2025, 5, 29)


def test_english_month_update_stamp():
    text = """
    Education Bureau

    27 May 2025

    Education Bureau Circular No. 6/2025
    (Updated in April 2026)
    """
    found = extract_document_dates(text)
    assert found.issued_at == date(2025, 5, 27)
    assert found.revised_at == date(2026, 4, 30)


def test_labeled_issue_and_update_dates():
    found = extract_document_dates(LABELED)
    assert found.issued_at == date(2024, 9, 25)
    assert found.revised_at == date(2026, 1, 8)


def test_prose_update_is_not_a_stamp():
    text = "因應中小學課程持續優化和更新，並於2025年9月更新課程框架。"
    found = extract_document_dates(text)
    assert found.revised_at is None
    assert found.issued_at is None


def test_superseded_date_in_a_sentence_is_not_the_issue_date():
    text = "This circular supersedes EDB Circular No. 17/2023 dated 25 August 2023."
    found = extract_document_dates(text)
    assert found.issued_at is None


def test_apply_keeps_crawl_issue_date_and_records_later_update():
    doc = SimpleNamespace(issued_at=date(2025, 5, 29), revised_at=None)
    assert apply_document_dates(doc, ZH_UPDATED) is True
    assert doc.issued_at == date(2025, 5, 29)
    assert doc.revised_at == date(2026, 7, 30)


def test_apply_ignores_update_that_is_not_after_issue():
    doc = SimpleNamespace(issued_at=date(2026, 8, 1), revised_at=None)
    assert apply_document_dates(doc, ZH_UPDATED) is False
    assert doc.revised_at is None


def test_apply_fills_missing_issue_date_from_text():
    doc = SimpleNamespace(issued_at=None, revised_at=None)
    assert apply_document_dates(doc, EN_UPDATED) is True
    assert doc.issued_at == date(2025, 5, 29)
    assert doc.revised_at == date(2026, 7, 30)


def test_circular_row_keeps_issue_date_and_update_stamp():
    html = """
    <table>
      <tr>
        <td>日期 29/05/2025</td>
        <td>主題 全方位學習 (2026 年 7 月 30 日更新) (通告編號：EDBC009/2025)</td>
        <td><a href="/circular/upload/EDBC/EDBC25009C.pdf">繁體中文</a></td>
      </tr>
    </table>
    """
    items = CircularAspNetCollector()._parse_results(
        html, "https://applications.edb.gov.hk/circular/circular.aspx", "zh-HK"
    )
    assert len(items) == 1
    assert items[0].issued_at == date(2025, 5, 29)
    assert items[0].revised_at == date(2026, 7, 30)


def test_normalize_sort_revised_newest():
    field, descending = _normalize_sort("revised_at", "desc")
    assert field == SORT_REVISED
    assert descending is True


def test_sort_groups_by_revised_at_nulls_last():
    updated = SimpleNamespace(
        id=uuid4(),
        source_id="edb_circulars",
        title="已更新",
        circular_no="EDBC009/2025",
        issued_at=date(2025, 5, 29),
        revised_at=date(2026, 7, 30),
        language="zh-HK",
        programme="circular",
        topics=[],
        status="ready",
        file_size=10,
        created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    original = SimpleNamespace(
        id=uuid4(),
        source_id="edb_circulars",
        title="未更新",
        circular_no="EDBC006/2025",
        issued_at=date(2025, 5, 27),
        revised_at=None,
        language="zh-HK",
        programme="circular",
        topics=[],
        status="ready",
        file_size=10,
        created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )
    groups = _to_groups([original, updated], sort_by=SORT_REVISED, descending=True)
    assert [g.circular_no for g in groups] == ["EDBC009/2025", "EDBC006/2025"]
    assert groups[0].revised_at == "2026-07-30"
    assert groups[1].revised_at is None


def test_group_uses_latest_update_across_languages():
    def doc(**kwargs):
        base = dict(
            id=uuid4(),
            source_id="edb_circulars",
            title="通告",
            circular_no="EDBC006/2025",
            issued_at=date(2025, 5, 27),
            revised_at=None,
            language="zh-HK",
            programme="circular",
            topics=[],
            status="ready",
            file_size=10,
            created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
        base.update(kwargs)
        return SimpleNamespace(**base)

    groups = _to_groups(
        [
            doc(language="zh-HK", revised_at=date(2026, 4, 30)),
            doc(language="en", title="Circular", revised_at=None),
        ]
    )
    assert len(groups) == 1
    assert groups[0].revised_at == "2026-04-30"
