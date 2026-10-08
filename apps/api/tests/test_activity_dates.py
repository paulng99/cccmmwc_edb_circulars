"""Unit tests for local multi-activity date extraction (no external services)."""

from datetime import date
from types import SimpleNamespace

from app.collectors.activity_dates import (
    apply_document_activities,
    extract_activities,
)


# --- Fixtures: synthetic circular-like text for tests (not live library files) ---

FIXTURE_MULTI_ZH = """
教育局通告第 12/2026 號
發出日期：2026年3月1日
（2026 年 5 月 10 日更新）
適用學年：2026/27

活動名稱：校本教師專業發展工作坊
開始日期：2026年9月15日
截止日期：2026年10月31日

活動名稱：家長講座報名
報名開始日期：2026年11月1日
報名截止日期：2026年11月20日

請於2026年12月15日前覆本局。
"""

FIXTURE_RANGE_ZH = """
教育局通告第 8/2025 號
發出日期：2025年8月20日

申請期由2025年9月1日至2025年9月30日
活動名稱：姊妹學校交流計劃申請
"""

FIXTURE_EN_MULTI = """
Education Bureau Circular No. 4/2026
Issue Date: 15 January 2026
(Updated on 20 March 2026)
School year: 2026/27

Activity Name: STEM Fair enrolment
Start Date: 1 September 2026
Closing Date: 30 September 2026

Activity Name: Grant claim submission
Application Deadline: 15 December 2026

Please reply to this circular by 28 February 2026.
"""

FIXTURE_EN_PERIOD = """
Education Bureau Circular No. 2/2026
Date of Issue: 10 February 2026

Application period: from 1 April 2026 to 30 April 2026
"""

FIXTURE_DEADLINE_ONLY = """
教育局通告第 3/2026 號
發出日期：2026年1月8日

截止報名日期：2026年6月30日
"""

FIXTURE_START_ONLY = """
Education Bureau Circular No. 7/2026
Issue Date: 1 March 2026

Commencement Date: 1 September 2026
"""

FIXTURE_NO_ACTIVITY = """
教育局通告第 1/2026 號
發出日期：2026年1月2日
（2026 年 2 月 1 日更新）
本通告適用於 2026/27 學年。
請於2026年3月31日前覆本局有關安排。
"""

FIXTURE_LABELED_RANGE = """
計劃名稱：全方位學習津貼匯報
申請期：2026年7月1日至2026年8月15日
更新日期：2026年6月1日
"""

FIXTURE_SAME_DAY_TWO_ACTIVITIES = """
教育局通告第 20/2026 號
發出日期：2026年4月1日

活動名稱：甲校聯校比賽報名
截止日期：2026年5月15日

活動名稱：乙校聯校比賽報名
截止日期：2026年5月15日
"""

FIXTURE_GENERIC_LABELS = """
教育局通告第 11/2026 號
發出日期：2026年2月12日

開始日期：2026年9月1日
截止日期：2026年9月30日
"""


def _deadlines(result):
    return [a.deadline_at for a in result.activities]


def _starts(result):
    return [a.starts_at for a in result.activities]


def _rejected_reasons(result):
    return {r.reason for r in result.rejected}


def test_chinese_multi_activity_dates():
    result = extract_activities(FIXTURE_MULTI_ZH)
    assert len(result.activities) == 2
    names = {a.name for a in result.activities}
    assert "校本教師專業發展工作坊" in names
    assert "家長講座報名" in names
    workshop = next(a for a in result.activities if a.name and "工作坊" in a.name)
    assert workshop.starts_at == date(2026, 9, 15)
    assert workshop.deadline_at == date(2026, 10, 31)
    lecture = next(a for a in result.activities if a.name and "家長" in a.name)
    assert lecture.starts_at == date(2026, 11, 1)
    assert lecture.deadline_at == date(2026, 11, 20)


def test_chinese_rejects_issue_update_school_year_and_reply():
    result = extract_activities(FIXTURE_MULTI_ZH)
    reasons = _rejected_reasons(result)
    assert "issued" in reasons
    assert "revised" in reasons
    assert "school_year" in reasons
    assert "reply_deadline" in reasons
    # Reply-by date must not become an activity deadline
    assert date(2026, 12, 15) not in _deadlines(result)
    assert date(2026, 3, 1) not in _starts(result)
    assert date(2026, 5, 10) not in _starts(result) + _deadlines(result)


def test_chinese_range_becomes_one_activity():
    result = extract_activities(FIXTURE_RANGE_ZH)
    assert len(result.activities) >= 1
    act = result.activities[0]
    assert act.starts_at == date(2025, 9, 1)
    assert act.deadline_at == date(2025, 9, 30)


def test_english_multi_activity():
    result = extract_activities(FIXTURE_EN_MULTI)
    assert len(result.activities) == 2
    stem = next(a for a in result.activities if a.name and "STEM" in a.name)
    assert stem.starts_at == date(2026, 9, 1)
    assert stem.deadline_at == date(2026, 9, 30)
    grant = next(a for a in result.activities if a.deadline_at == date(2026, 12, 15))
    assert grant.starts_at is None
    assert date(2026, 2, 28) not in _deadlines(result)
    assert "reply_deadline" in _rejected_reasons(result)
    assert "issued" in _rejected_reasons(result)
    assert "school_year" in _rejected_reasons(result)


def test_english_application_period():
    result = extract_activities(FIXTURE_EN_PERIOD)
    assert len(result.activities) == 1
    assert result.activities[0].starts_at == date(2026, 4, 1)
    assert result.activities[0].deadline_at == date(2026, 4, 30)


def test_deadline_only_and_start_only():
    only_end = extract_activities(FIXTURE_DEADLINE_ONLY)
    assert len(only_end.activities) == 1
    assert only_end.activities[0].starts_at is None
    assert only_end.activities[0].deadline_at == date(2026, 6, 30)

    only_start = extract_activities(FIXTURE_START_ONLY)
    assert len(only_start.activities) == 1
    assert only_start.activities[0].starts_at == date(2026, 9, 1)
    assert only_start.activities[0].deadline_at is None


def test_no_activity_returns_empty_but_records_rejects():
    result = extract_activities(FIXTURE_NO_ACTIVITY)
    assert result.activities == []
    reasons = _rejected_reasons(result)
    assert "issued" in reasons
    assert "revised" in reasons
    assert "school_year" in reasons
    assert "reply_deadline" in reasons


def test_labeled_range_with_programme_name():
    result = extract_activities(FIXTURE_LABELED_RANGE)
    assert len(result.activities) == 1
    act = result.activities[0]
    assert act.starts_at == date(2026, 7, 1)
    assert act.deadline_at == date(2026, 8, 15)
    assert date(2026, 6, 1) not in _starts(result) + _deadlines(result)


def test_same_deadline_different_activities_stay_separate():
    result = extract_activities(FIXTURE_SAME_DAY_TWO_ACTIVITIES)
    assert len(result.activities) == 2
    assert all(a.deadline_at == date(2026, 5, 15) for a in result.activities)
    names = {a.name for a in result.activities}
    assert len(names) == 2


def test_generic_labels_ok_without_activity_name():
    result = extract_activities(FIXTURE_GENERIC_LABELS)
    assert len(result.activities) == 1
    act = result.activities[0]
    assert act.starts_at == date(2026, 9, 1)
    assert act.deadline_at == date(2026, 9, 30)
    # Generic "開始日期/截止日期" should not invent a name
    assert act.name is None


def test_empty_text_returns_empty():
    result = extract_activities("   ")
    assert result.activities == []
    assert result.rejected == []
    assert extract_activities(None).activities == []


def test_apply_document_activities_sets_json():
    doc = SimpleNamespace(activities=[])
    assert apply_document_activities(doc, FIXTURE_DEADLINE_ONLY) is True
    assert doc.activities == [
        {"name": "截止報名", "starts_at": None, "deadline_at": "2026-06-30"}
    ]
    assert apply_document_activities(doc, FIXTURE_DEADLINE_ONLY) is False
