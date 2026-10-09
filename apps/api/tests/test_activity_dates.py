"""Unit tests for local calendar date/detail extraction (no external services)."""

from datetime import date
from types import SimpleNamespace

from app.collectors.activity_dates import (
    agenda_title_lines,
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
內容：為中學教師提供 STEM 教學培訓
地點：學校禮堂
開始日期：2026年9月15日
截止日期：2026年10月31日

活動名稱：家長講座報名
內容：介紹家校合作支援措施
舉行地點：社區會堂
報名開始日期：2026年11月1日
報名截止日期：2026年11月20日

請於2026年12月15日前覆本局。
"""

FIXTURE_RANGE_ZH = """
教育局通告第 8/2025 號
發出日期：2025年8月20日

申請期由2025年9月1日至2025年9月30日
活動名稱：姊妹學校交流計劃申請
內容：供學校申請姊妹學校交流資助
地點：各參與學校
"""

FIXTURE_EN_MULTI = """
Education Bureau Circular No. 4/2026
Issue Date: 15 January 2026
(Updated on 20 March 2026)
School year: 2026/27

Activity Name: STEM Fair enrolment
Description: Hands-on science booths for secondary students
Venue: City Hall Exhibition Gallery
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

FIXTURE_REPLY_ONLY = """
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

# Letterhead has bureau address; activity has a real venue — only venue is kept.
FIXTURE_LETTERHEAD_WITH_VENUE = """
教育局
Education Bureau
香港灣仔皇后大道東213號胡忠大廈13樓
發出日期：2026年4月8日

活動名稱：校內歌唱比賽
內容：中一至中三報名
地點：學校禮堂
開始日期：2026年10月12日
截止日期：2026年10月20日
"""

# Only bureau letterhead address — location must stay empty.
FIXTURE_LETTERHEAD_ONLY = """
教育局
Education Bureau
地址：香港灣仔皇后大道東213號胡忠大廈
發出日期：2026年5月2日

活動名稱：教師研討會報名
內容：分享課程規劃經驗
截止日期：2026年6月15日
"""

FIXTURE_EN_LETTERHEAD_ONLY = """
Education Bureau
Address: 213 Queen's Road East, Wan Chai, Wu Chung House
Issue Date: 3 June 2026

Activity Name: Coding workshop enrolment
Closing Date: 30 July 2026
"""

FIXTURE_SUBMIT_QUESTIONNAIRE = """
教育局通告第 30/2026 號
發出日期：2026年7月1日

請於2026年8月15日前交回問卷。
"""

FIXTURE_SUBMIT_FALLBACK = """
教育局通告第 31/2026 號
發出日期：2026年7月2日

截止日期：2026年9月1日
"""

# Same reply sentence must not create two calendar rows.
FIXTURE_SAME_SENTENCE_ONCE = """
教育局通告第 32/2026 號
發出日期：2026年7月3日

請於2026年10月1日前交回問卷。
"""

FIXTURE_EFFECTIVE_DATE = """
教育局通告第 40/2026 號
發出日期：2026年1月10日

生效日期：2026年2月1日
本通告自2026年2月1日起生效。

活動名稱：教師交流團報名
報名截止日期：2026年3月20日
"""

FIXTURE_BACKGROUND_SUPERSEDE = """
教育局通告第 41/2026 號
發出日期：2026年4月1日

本通告取代2025年6月15日的通告。

活動名稱：津貼申請
申請截止日期：2026年5月30日
"""


def _deadlines(result):
    return [a.deadline_at for a in result.activities]


def _starts(result):
    return [a.starts_at for a in result.activities]


def _rejected_reasons(result):
    return {r.reason for r in result.rejected}


def _rejected_location_values(result):
    return {r.value for r in result.rejected_locations}


def test_chinese_multi_activity_dates():
    result = extract_activities(FIXTURE_MULTI_ZH)
    assert len(result.activities) == 3
    names = {a.name for a in result.activities}
    assert "校本教師專業發展工作坊" in names
    assert "家長講座報名" in names
    workshop = next(a for a in result.activities if a.name and "工作坊" in a.name)
    assert workshop.starts_at == date(2026, 9, 15)
    assert workshop.deadline_at == date(2026, 10, 31)
    assert workshop.summary == "為中學教師提供 STEM 教學培訓"
    assert workshop.location == "學校禮堂"
    lecture = next(a for a in result.activities if a.name and "家長" in a.name)
    assert lecture.starts_at == date(2026, 11, 1)
    assert lecture.deadline_at == date(2026, 11, 20)
    assert lecture.summary == "介紹家校合作支援措施"
    assert lecture.location == "社區會堂"


def test_reply_deadline_is_listed_not_excluded():
    result = extract_activities(FIXTURE_MULTI_ZH)
    reasons = _rejected_reasons(result)
    assert "issued" in reasons
    assert "revised" in reasons
    assert "school_year" in reasons
    assert "reply_deadline" not in reasons
    # Reply-by date is now a calendar deadline
    assert date(2026, 12, 15) in _deadlines(result)
    reply = next(a for a in result.activities if a.deadline_at == date(2026, 12, 15))
    assert reply.name is None
    assert reply.starts_at is None
    assert date(2026, 3, 1) not in _starts(result)
    assert date(2026, 5, 10) not in _starts(result) + _deadlines(result)


def test_chinese_range_becomes_one_activity():
    result = extract_activities(FIXTURE_RANGE_ZH)
    assert len(result.activities) >= 1
    act = result.activities[0]
    assert act.name == "姊妹學校交流計劃申請"
    assert act.starts_at == date(2025, 9, 1)
    assert act.deadline_at == date(2025, 9, 30)
    assert act.summary == "供學校申請姊妹學校交流資助"
    assert act.location == "各參與學校"


def test_english_multi_activity():
    result = extract_activities(FIXTURE_EN_MULTI)
    assert len(result.activities) == 3
    stem = next(a for a in result.activities if a.name and "STEM" in a.name)
    assert stem.starts_at == date(2026, 9, 1)
    assert stem.deadline_at == date(2026, 9, 30)
    assert stem.summary == "Hands-on science booths for secondary students"
    assert stem.location == "City Hall Exhibition Gallery"
    grant = next(a for a in result.activities if a.deadline_at == date(2026, 12, 15))
    assert grant.starts_at is None
    assert grant.summary is None
    assert grant.location is None
    reply = next(a for a in result.activities if a.deadline_at == date(2026, 2, 28))
    assert reply.name is None
    assert "reply_deadline" not in _rejected_reasons(result)
    assert "issued" in _rejected_reasons(result)
    assert "school_year" in _rejected_reasons(result)


def test_english_application_period():
    result = extract_activities(FIXTURE_EN_PERIOD)
    assert len(result.activities) == 1
    assert result.activities[0].starts_at == date(2026, 4, 1)
    assert result.activities[0].deadline_at == date(2026, 4, 30)
    assert result.activities[0].summary is None
    assert result.activities[0].location is None


def test_deadline_only_and_start_only():
    only_end = extract_activities(FIXTURE_DEADLINE_ONLY)
    assert len(only_end.activities) == 1
    assert only_end.activities[0].starts_at is None
    assert only_end.activities[0].deadline_at == date(2026, 6, 30)
    assert only_end.activities[0].summary is None
    assert only_end.activities[0].location is None

    only_start = extract_activities(FIXTURE_START_ONLY)
    assert len(only_start.activities) == 1
    assert only_start.activities[0].starts_at == date(2026, 9, 1)
    assert only_start.activities[0].deadline_at is None


def test_reply_only_becomes_submit_deadline():
    result = extract_activities(FIXTURE_REPLY_ONLY)
    assert len(result.activities) == 1
    act = result.activities[0]
    assert act.deadline_at == date(2026, 3, 31)
    # No extractable item name — UI shows notice title only (not 「交回文件」).
    assert act.name is None
    reasons = _rejected_reasons(result)
    assert "issued" in reasons
    assert "revised" in reasons
    assert "school_year" in reasons
    assert "reply_deadline" not in reasons


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


def test_generic_deadline_leaves_name_unset():
    result = extract_activities(FIXTURE_GENERIC_LABELS)
    assert len(result.activities) == 1
    act = result.activities[0]
    assert act.starts_at == date(2026, 9, 1)
    assert act.deadline_at == date(2026, 9, 30)
    # No activity name → leave unset; UI shows notice title only.
    assert act.name is None
    assert act.summary is None
    assert act.location is None


def test_submit_questionnaire_title():
    result = extract_activities(FIXTURE_SUBMIT_QUESTIONNAIRE)
    assert len(result.activities) == 1
    act = result.activities[0]
    assert act.deadline_at == date(2026, 8, 15)
    assert act.name == "交回問卷"
    assert act.summary is None
    assert act.location is None


def test_submit_fallback_leaves_name_unset():
    result = extract_activities(FIXTURE_SUBMIT_FALLBACK)
    assert len(result.activities) == 1
    act = result.activities[0]
    assert act.deadline_at == date(2026, 9, 1)
    assert act.name is None


def test_same_sentence_listed_once():
    result = extract_activities(FIXTURE_SAME_SENTENCE_ONCE)
    assert len(result.activities) == 1
    assert result.activities[0].name == "交回問卷"
    assert result.activities[0].deadline_at == date(2026, 10, 1)


def test_effective_date_excluded_from_calendar():
    result = extract_activities(FIXTURE_EFFECTIVE_DATE)
    assert "effective" in _rejected_reasons(result)
    assert date(2026, 2, 1) not in _starts(result) + _deadlines(result)
    assert date(2026, 3, 20) in _deadlines(result)
    eff = [r for r in result.rejected if r.reason == "effective"]
    assert any("生效日期" in r.sentence or "起生效" in r.sentence for r in eff)


def test_background_supersede_excluded_from_calendar():
    result = extract_activities(FIXTURE_BACKGROUND_SUPERSEDE)
    assert "background" in _rejected_reasons(result)
    assert date(2025, 6, 15) not in _starts(result) + _deadlines(result)
    assert date(2026, 5, 30) in _deadlines(result)
    bg = [r for r in result.rejected if r.reason == "background"]
    assert any("取代" in r.sentence for r in bg)


def test_letterhead_with_real_venue_keeps_only_venue():
    result = extract_activities(FIXTURE_LETTERHEAD_WITH_VENUE)
    assert len(result.activities) == 1
    act = result.activities[0]
    assert act.name == "校內歌唱比賽"
    assert act.summary == "中一至中三報名"
    assert act.location == "學校禮堂"
    assert act.location_sentence and "學校禮堂" in act.location_sentence
    rejected = _rejected_location_values(result)
    assert any("皇后大道東" in v for v in rejected)
    assert "學校禮堂" not in rejected


def test_letterhead_only_leaves_location_empty():
    result = extract_activities(FIXTURE_LETTERHEAD_ONLY)
    assert len(result.activities) == 1
    act = result.activities[0]
    assert act.name == "教師研討會報名"
    assert act.summary == "分享課程規劃經驗"
    assert act.location is None
    rejected = _rejected_location_values(result)
    assert any("皇后大道東" in v for v in rejected)
    assert act.location in (None, "")


def test_english_letterhead_only_leaves_location_empty():
    result = extract_activities(FIXTURE_EN_LETTERHEAD_ONLY)
    assert len(result.activities) == 1
    act = result.activities[0]
    assert act.name == "Coding workshop enrolment"
    assert act.location is None
    rejected = _rejected_location_values(result)
    assert any("Queen" in v or "Wu Chung" in v for v in rejected)


def test_empty_text_returns_empty():
    result = extract_activities("   ")
    assert result.activities == []
    assert result.rejected == []
    assert result.rejected_locations == []
    assert extract_activities(None).activities == []


def test_apply_document_activities_sets_json():
    doc = SimpleNamespace(activities=[])
    assert apply_document_activities(doc, FIXTURE_DEADLINE_ONLY) is True
    assert doc.activities == [
        {
            "name": "截止報名",
            "starts_at": None,
            "deadline_at": "2026-06-30",
            "summary": None,
            "location": None,
        }
    ]
    assert apply_document_activities(doc, FIXTURE_DEADLINE_ONLY) is False


def test_apply_document_activities_stores_summary_and_location():
    doc = SimpleNamespace(activities=[])
    assert apply_document_activities(doc, FIXTURE_LETTERHEAD_WITH_VENUE) is True
    assert doc.activities == [
        {
            "name": "校內歌唱比賽",
            "starts_at": "2026-10-12",
            "deadline_at": "2026-10-20",
            "summary": "中一至中三報名",
            "location": "學校禮堂",
        }
    ]


def test_apply_stores_reply_without_default_submit_title():
    doc = SimpleNamespace(activities=[])
    assert apply_document_activities(doc, FIXTURE_REPLY_ONLY) is True
    assert doc.activities == [
        {
            "name": None,
            "starts_at": None,
            "deadline_at": "2026-03-31",
            "summary": None,
            "location": None,
        }
    ]


def test_agenda_title_lines_three_cases():
    # Synthetic fixtures for display titles (not live circular text).
    assert agenda_title_lines("交回問卷", "小學數學科評估安排") == [
        "交回問卷",
        "小學數學科評估安排",
    ]
    assert agenda_title_lines(None, "小學數學科評估安排") == ["小學數學科評估安排"]
    assert agenda_title_lines("校本教師專業發展工作坊", "校本教師專業發展工作坊") == [
        "校本教師專業發展工作坊"
    ]
    long_title = (
        "優化高中經濟科及公布《經濟課程及評估指引（中四至中六）》（2025年更新）"
        "及《補充文件》（2025年更新）"
    )
    assert agenda_title_lines("交回問卷", long_title) == ["交回問卷", long_title]
