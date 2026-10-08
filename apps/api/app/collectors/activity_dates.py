"""Extract calendar deadlines/starts and details from circular text (local regex only).

A document may contain several items: activities, enrolment, submission, and
reply deadlines. Each may have a start date, a deadline, or both, plus an
optional title, one-line summary, and venue.

Excluded from the calendar (recorded as rejected): issue/update stamps, school
years, effective-from dates, and background/supersession dates.
Reply-by / submit-by deadlines ARE included (legacy reply exclusion is revoked).
Education Bureau letterhead / signature addresses are never used as venues.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

_SCAN_CHARS = 20000

_MONTHS = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sept": 9,
    "sep": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}

# Horizontal whitespace only — never cross newlines inside labels.
_S = r"[^\S\n]*"

_SCHOOL_YEAR = re.compile(r"(?<!\d)(\d{4})\s*/\s*(\d{2})(?!\d)(?:\s*學年)?")

_ISSUE_LABEL = re.compile(
    r"(?:發出日期|發行日期|Issue\s+Date|Date\s+of\s+Issue)\s*[:：]?",
    re.IGNORECASE,
)
_REVISE_LABEL = re.compile(
    r"(?:最後更新日期|最後修訂日期|更新日期|修訂日期|"
    r"Last\s+Revision\s+Date|Last\s+Updated|Revision\s+Date|Updated\s+Date)\s*[:：]?",
    re.IGNORECASE,
)
_REVISE_STAMP = re.compile(
    r"[（(]"
    + _S
    + r"(?:\d{4}"
    + _S
    + r"年"
    + _S
    + r"\d{1,2}"
    + _S
    + r"月(?:"
    + _S
    + r"\d{1,2}"
    + _S
    + r"日)?"
    + _S
    + r"更新|"
    r"(?:Updated|Revised)\s+(?:on|in)\s+[^)）]+)\s*[)）]",
    re.IGNORECASE,
)
# HK circulars often shorten 回覆 to 覆. These are calendar deadlines (included).
_REPLY_BY_ZH = re.compile(
    r"請於.{0,40}前(?:交回|遞交|提交|呈交|回覆|覆本局|作出回覆|回覆確認|確認回覆|回覆有關|覆有關)"
)
_REPLY_BY_EN = re.compile(
    r"(?:please\s+)?(?:reply|respond|return(?:\s+the\s+reply)?|submit|hand\s+in)\s+"
    r"(?:to\s+(?:this|the)\s+(?:circular|letter)\s+)?"
    r"(?:by|before|on\s+or\s+before)\b",
    re.IGNORECASE,
)

# What is being submitted — used for titles like 「交回問卷」.
_SUBMIT_OBJECT_ZH = re.compile(
    r"(?:交回|遞交|提交|呈交)(?P<object>[^\n，。；;：:]{1,40})"
)

_DEFAULT_SUBMIT_TITLE = "交回文件"

# Effective-from dates — easy to over-extract; keep off the calendar.
_EFFECTIVE_LABEL = re.compile(
    r"(?:生效日期|Effective\s+Date)\s*[:：]?",
    re.IGNORECASE,
)
_EFFECTIVE_PHRASE = re.compile(
    r"(?:本通告|本通函|本公告|本文件).{0,24}自.{0,48}(?:起|開始)(?:生效|實施)|"
    r"(?:takes?\s+effect|comes?\s+into\s+(?:effect|force)|effective\s+(?:from|on))\b",
    re.IGNORECASE,
)

# Background / supersession dates — not calendar events.
_BACKGROUND_SUPERSEDE = re.compile(
    r"(?:取代|廢除|撤銷|代替).{0,60}(?:通告|通函|公告)|"
    r"(?:supersede[sd]?|replace[sd]?|revoke[sd]?|cancel(?:s|led)?).{0,80}"
    r"(?:circular|memorandum|notice)",
    re.IGNORECASE,
)

_YMD_ZH = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
_DMY_SLASH = re.compile(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})")
_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_EN_DATE = re.compile(
    r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})",
    re.IGNORECASE,
)
_EN_DATE_MDY = re.compile(
    r"([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?(?:,)?\s+(\d{4})",
    re.IGNORECASE,
)

_START_LABEL = re.compile(
    r"(?P<label>"
    r"活動開始日期|報名開始日期|申請開始日期|開始報名日期|開始日期|"
    r"活動日期|舉行日期|開課日期|"
    r"Start[^\S\n]+Date|Commencement[^\S\n]+Date|Starting[^\S\n]+Date|"
    r"Application[^\S\n]+Start[^\S\n]+Date|"
    r"Enrolment[^\S\n]+Start[^\S\n]+Date|Enrollment[^\S\n]+Start[^\S\n]+Date|"
    r"Event[^\S\n]+Date|Activity[^\S\n]+Date"
    r")"
    + _S
    + r"[:：]?"
    + _S,
    re.IGNORECASE,
)

_DEADLINE_LABEL = re.compile(
    r"(?P<label>"
    r"截止報名日期|報名截止日期|申請截止日期|遞交截止日期|提交截止日期|"
    r"交回截止日期|回覆截止日期|最後提交日期|最後遞交日期|活動截止日期|截止日期|"
    r"Closing[^\S\n]+Date(?:[^\S\n]+for[^\S\n]+Applications?)?|"
    r"Application[^\S\n]+Deadline|Submission[^\S\n]+Deadline|"
    r"Enrolment[^\S\n]+Deadline|Enrollment[^\S\n]+Deadline|"
    r"Reply[^\S\n]+Deadline|"
    r"Deadline(?:[^\S\n]+for[^\S\n]+Applications?)?"
    r")"
    + _S
    + r"[:：]?"
    + _S,
    re.IGNORECASE,
)

_RANGE_ZH = re.compile(
    r"(?P<label>申請期|報名期|活動期|推行期|進行期間|活動期間|有效期|實施期|"
    r"申請日期|報名日期)?"
    + _S
    + r"[:：]?"
    + _S
    + r"(?:由"
    + _S
    + r")?"
    r"(?P<start>\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)"
    + _S
    + r"(?:至|到|－|-|—|–)"
    + _S
    + r"(?P<end>\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)"
)

_RANGE_EN = re.compile(
    r"(?P<label>Application[^\S\n]+period|Enrolment[^\S\n]+period|"
    r"Enrollment[^\S\n]+period|Activity[^\S\n]+period|Event[^\S\n]+period|"
    r"Period|Valid[^\S\n]+period)?"
    + _S
    + r"[:：]?"
    + _S
    + r"(?:from[^\S\n]+)?"
    r"(?P<start>"
    r"\d{1,2}(?:st|nd|rd|th)?[^\S\n]+[A-Za-z]+[^\S\n]+\d{4}"
    r"|[A-Za-z]+[^\S\n]+\d{1,2}(?:st|nd|rd|th)?(?:,)?[^\S\n]+\d{4}"
    r"|\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}[/-]\d{1,2}[/-]\d{4}"
    r")"
    r"[^\S\n]+(?:to|until|through|-|–|—)[^\S\n]+"
    r"(?P<end>"
    r"\d{1,2}(?:st|nd|rd|th)?[^\S\n]+[A-Za-z]+[^\S\n]+\d{4}"
    r"|[A-Za-z]+[^\S\n]+\d{1,2}(?:st|nd|rd|th)?(?:,)?[^\S\n]+\d{4}"
    r"|\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}[/-]\d{1,2}[/-]\d{4}"
    r")",
    re.IGNORECASE,
)

_NAME_LABEL = re.compile(
    r"(?:活動名稱|項目名稱|計劃名稱|Activity[^\S\n]+Name|Programme[^\S\n]+Name|Program[^\S\n]+Name)"
    + _S
    + r"[:：]"
    + _S
    + r"(?P<name>[^\n。；;]{2,80})",
    re.IGNORECASE,
)

# One-line activity blurb — colon required so bare 「內容」 in body text is ignored.
_SUMMARY_LABEL = re.compile(
    r"(?:活動內容|活動簡介|內容概要|活動目的|活動詳情|簡介|詳情|內容|"
    r"Description|Summary|Details|Aim|Objective|Purpose)"
    + _S
    + r"[:：]"
    + _S
    + r"(?P<value>[^\n。；;]{2,100})",
    re.IGNORECASE,
)

# Only clear venue labels (not bare 地址 / Address — those are often letterhead).
_LOCATION_LABEL = re.compile(
    r"(?:舉行地點|活動地點|比賽地點|講座地點|報名地點|活動場地|比賽場地|舉行場地|"
    r"地點|"
    r"Venue(?:[^\S\n]+(?:of|for)[^\S\n]+(?:the[^\S\n]+)?"
    r"(?:activity|event|lecture|competition|enrolment|enrollment|seminar))?|"
    r"Location(?:[^\S\n]+(?:of|for)[^\S\n]+(?:the[^\S\n]+)?"
    r"(?:activity|event|lecture|competition|seminar))?|"
    r"(?:to[^\S\n]+be[^\S\n]+)?held[^\S\n]+(?:at|in))"
    + _S
    + r"[:：]?"
    + _S
    + r"(?P<value>[^\n。；;]{2,80})",
    re.IGNORECASE,
)

# Letterhead / signature / footer bureau addresses — never activity venues.
_BUREAU_ADDRESS = re.compile(
    r"(?:"
    r"皇后大道東|歸仁街|胡忠大廈|"
    r"Queen'?s?\s+Road\s+East|Kau\s+Yan\s+Street|Wu\s+Chung\s+House|"
    r"Education\s+Bureau.{0,60}(?:Office|Headquarters|Building|address)|"
    r"教育局.{0,30}(?:總部|辦公室|大廈|地址)"
    r")",
    re.IGNORECASE,
)

# Bare bureau office lines without a venue label (for sampling rejected addresses).
_BARE_BUREAU_LINE = re.compile(
    r"(?P<value>[^\n]{0,40}(?:皇后大道東|歸仁街|胡忠大廈|"
    r"Queen'?s?\s+Road\s+East|Kau\s+Yan\s+Street|Wu\s+Chung\s+House)[^\n]{0,40})",
    re.IGNORECASE,
)

_REJECT_REASONS = ("issued", "revised", "school_year", "effective", "background")

_GENERIC_LABELS = frozenset(
    {
        "開始日期",
        "截止日期",
        "活動日期",
        "舉行日期",
        "start date",
        "commencement date",
        "starting date",
        "event date",
        "activity date",
        "closing date",
        "deadline",
        "period",
        "valid period",
        "application period",
        "enrolment period",
        "enrollment period",
        "activity period",
        "event period",
    }
)


@dataclass(frozen=True)
class ActivityDates:
    name: str | None = None
    starts_at: date | None = None
    deadline_at: date | None = None
    summary: str | None = None
    location: str | None = None
    start_sentence: str | None = None
    deadline_sentence: str | None = None
    summary_sentence: str | None = None
    location_sentence: str | None = None


@dataclass(frozen=True)
class RejectedDate:
    value: date | None
    reason: str
    sentence: str


@dataclass(frozen=True)
class RejectedLocation:
    value: str
    reason: str
    sentence: str


@dataclass
class ActivityExtractionResult:
    activities: list[ActivityDates] = field(default_factory=list)
    rejected: list[RejectedDate] = field(default_factory=list)
    rejected_locations: list[RejectedLocation] = field(default_factory=list)


def _norm(text: str) -> str:
    cleaned = text.replace("\u3000", " ").replace("\xa0", " ").replace("\r\n", "\n")
    cleaned = re.sub(r"[^\S\n]+", " ", cleaned)
    return cleaned[:_SCAN_CHARS]


def _ymd(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _parse_zh_ymd(token: str) -> date | None:
    m = _YMD_ZH.search(token)
    if not m:
        return None
    return _ymd(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _parse_date_token(token: str) -> date | None:
    text = token.strip()
    if not text:
        return None
    m = _YMD_ZH.search(text)
    if m:
        return _ymd(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = _ISO.search(text)
    if m:
        return _ymd(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = _EN_DATE.search(text)
    if m:
        month = _MONTHS.get(m.group(2).strip().lower())
        if month:
            return _ymd(int(m.group(3)), month, int(m.group(1)))
    m = _EN_DATE_MDY.search(text)
    if m:
        month = _MONTHS.get(m.group(1).strip().lower())
        if month:
            return _ymd(int(m.group(3)), month, int(m.group(2)))
    m = _DMY_SLASH.search(text)
    if m:
        return _ymd(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    return None


def _sentence_around(text: str, start: int, end: int) -> str:
    """Return the single line that contains the match (for PR/debug sampling)."""
    left = text.rfind("\n", 0, start)
    right = text.find("\n", start)
    if left < 0:
        left = 0
    else:
        left += 1
    if right < 0:
        right = len(text)
    chunk = text[left:right].strip()
    if len(chunk) > 220:
        rel = max(0, start - left)
        lo = max(0, rel - 80)
        hi = min(len(chunk), max(rel, end - left) + 80)
        chunk = chunk[lo:hi].strip()
    return re.sub(r"\s+", " ", chunk)


def _clean_field(value: str | None, *, max_len: int) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip(" ：:.-–—、，,")
    if not cleaned:
        return None
    return cleaned[:max_len]


def _is_bureau_address(value: str) -> bool:
    return bool(_BUREAU_ADDRESS.search(value))


def _reject_location(
    rejected: list[RejectedLocation],
    *,
    value: str,
    reason: str,
    sentence: str,
) -> None:
    key = (value, reason, sentence)
    if any((r.value, r.reason, r.sentence) == key for r in rejected):
        return
    rejected.append(RejectedLocation(value=value, reason=reason, sentence=sentence))


def _label_to_name(label: str | None) -> str | None:
    if not label:
        return None
    cleaned = re.sub(r"\s+", " ", label.strip())
    if cleaned.casefold() in _GENERIC_LABELS:
        return None
    cleaned = re.sub(r"(日期|Date)$", "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned or None


def _find_nearby_name(text: str, pos: int) -> str | None:
    """Prefer an explicit activity/programme name near the date match.

    Look on recent preceding lines first; if none, accept a name that follows
    within a short distance (common when 申請期… sits above 活動名稱…).
    """
    window_start = max(0, pos - 300)
    preceding = list(_NAME_LABEL.finditer(text, window_start, pos + 1))
    if preceding:
        name = preceding[-1].group("name").strip(" ：:.-–—")
        return name[:80] if name else None
    following = _NAME_LABEL.search(text, pos, min(len(text), pos + 200))
    if following:
        name = following.group("name").strip(" ：:.-–—")
        return name[:80] if name else None
    return None


def _title_from_submit_sentence(sentence: str) -> str | None:
    """Build titles like 「交回問卷」 from a submit/reply sentence."""
    m = _SUBMIT_OBJECT_ZH.search(sentence)
    if not m:
        return None
    obj = _clean_field(m.group("object"), max_len=40)
    if not obj:
        return None
    obj = re.sub(
        r"(?:本局|有關安排|事宜|予本局|到本局|的截止日期|截止日期)$",
        "",
        obj,
    ).strip(" ：:.-–—、，,的")
    if not obj or len(obj) > 36:
        return None
    if obj.startswith("交回") or obj.startswith("遞交") or obj.startswith("提交"):
        return obj[:40]
    return f"交回{obj}"[:40]


def _resolve_name(
    text: str,
    pos: int,
    label: str | None,
    *,
    sentence: str | None = None,
) -> str | None:
    # Explicit 活動名稱 / Activity Name wins over submit-object / label names.
    return (
        _find_nearby_name(text, pos)
        or (_title_from_submit_sentence(sentence) if sentence else None)
        or _label_to_name(label)
    )


def _deadline_title(name: str | None) -> str:
    """Deadlines without an extracted title default to 「交回文件」 (not circular title)."""
    return name or _DEFAULT_SUBMIT_TITLE


def _activity_detail_window(text: str, pos: int) -> tuple[int, int]:
    """Limit summary/location search to the current activity block.

    Anchor on the nearest activity/programme name at or before ``pos``, or a
    name that follows within a short distance (range line then 活動名稱).
    The window runs to the next name so one activity cannot borrow another's
    Description / Venue.
    """
    names = list(_NAME_LABEL.finditer(text))
    if not names:
        return max(0, pos - 140), min(len(text), pos + 220)

    anchor_idx: int | None = None
    for i, m in enumerate(names):
        if m.start() <= pos:
            anchor_idx = i
        else:
            break
    if anchor_idx is None:
        for i, m in enumerate(names):
            if 0 <= m.start() - pos <= 200:
                anchor_idx = i
                break
    if anchor_idx is None:
        return max(0, pos - 140), min(len(text), pos + 220)

    start = names[anchor_idx].start()
    if pos < start:
        # Date/range line sits just above the name — keep it in-window.
        start = pos
    end = names[anchor_idx + 1].start() if anchor_idx + 1 < len(names) else len(text)
    if end <= start:
        end = min(len(text), pos + 220)
    return start, end


def _find_nearby_summary(text: str, pos: int) -> tuple[str | None, str | None]:
    window_start, window_end = _activity_detail_window(text, pos)
    window = text[window_start:window_end]
    best: re.Match[str] | None = None
    best_dist = 10**9
    for m in _SUMMARY_LABEL.finditer(window):
        abs_start = window_start + m.start()
        dist = abs(abs_start - pos)
        if dist < best_dist:
            best = m
            best_dist = dist
    if not best:
        return None, None
    value = _clean_field(best.group("value"), max_len=100)
    if not value:
        return None, None
    abs_start = window_start + best.start()
    abs_end = window_start + best.end()
    return value, _sentence_around(text, abs_start, abs_end)


def _find_nearby_location(
    text: str,
    pos: int,
    rejected_locations: list[RejectedLocation],
) -> tuple[str | None, str | None]:
    window_start, window_end = _activity_detail_window(text, pos)
    window = text[window_start:window_end]
    best: re.Match[str] | None = None
    best_dist = 10**9
    for m in _LOCATION_LABEL.finditer(window):
        abs_start = window_start + m.start()
        dist = abs(abs_start - pos)
        if dist < best_dist:
            best = m
            best_dist = dist
    if not best:
        return None, None
    value = _clean_field(best.group("value"), max_len=80)
    abs_start = window_start + best.start()
    abs_end = window_start + best.end()
    sentence = _sentence_around(text, abs_start, abs_end)
    if not value:
        return None, None
    if _is_bureau_address(value):
        _reject_location(
            rejected_locations,
            value=value,
            reason="bureau_address",
            sentence=sentence,
        )
        return None, None
    return value, sentence


def _collect_bureau_address_rejects(
    text: str,
    rejected_locations: list[RejectedLocation],
) -> None:
    """Record letterhead/signature bureau lines that must not become venues."""
    for m in _BARE_BUREAU_LINE.finditer(text):
        value = _clean_field(m.group("value"), max_len=80)
        if not value:
            continue
        sentence = _sentence_around(text, m.start(), m.end())
        _reject_location(
            rejected_locations,
            value=value,
            reason="bureau_address",
            sentence=sentence,
        )


def _attach_details(
    text: str,
    pos: int,
    rejected_locations: list[RejectedLocation],
    *,
    name: str | None,
    starts_at: date | None,
    deadline_at: date | None,
    start_sentence: str | None,
    deadline_sentence: str | None,
) -> ActivityDates:
    summary, summary_sentence = _find_nearby_summary(text, pos)
    location, location_sentence = _find_nearby_location(text, pos, rejected_locations)
    return ActivityDates(
        name=name,
        starts_at=starts_at,
        deadline_at=deadline_at,
        summary=summary,
        location=location,
        start_sentence=start_sentence,
        deadline_sentence=deadline_sentence,
        summary_sentence=summary_sentence,
        location_sentence=location_sentence,
    )


def _reject(
    rejected: list[RejectedDate],
    *,
    value: date | None,
    reason: str,
    sentence: str,
) -> None:
    if reason not in _REJECT_REASONS:
        reason = "issued"
    key = (value, reason, sentence)
    if any((r.value, r.reason, r.sentence) == key for r in rejected):
        return
    rejected.append(RejectedDate(value=value, reason=reason, sentence=sentence))


def _take_date_after_label(
    text: str,
    match: re.Match[str],
    rejected: list[RejectedDate],
) -> tuple[date | None, str]:
    """Parse the first date after an activity label; reject school-year tokens."""
    start = match.end()
    snippet = text[start : start + 80]
    sentence = _sentence_around(text, match.start(), min(len(text), start + 80))

    sy = _SCHOOL_YEAR.match(snippet.lstrip())
    if sy and not _YMD_ZH.match(snippet.lstrip()) and not _ISO.match(snippet.lstrip()):
        _reject(rejected, value=None, reason="school_year", sentence=sentence)
        return None, sentence

    # Explicit activity labels (開始日期 / Closing Date / …) are never reply-by
    # deadlines; those are collected separately from 請於…前覆 / please reply by.
    return _parse_date_token(snippet), sentence


def _collect_rejected_non_activity(text: str, rejected: list[RejectedDate]) -> None:
    """Scan dates that must stay off the calendar (for PR sampling)."""
    for m in _ISSUE_LABEL.finditer(text):
        parsed = _parse_date_token(text[m.end() : m.end() + 40])
        sentence = _sentence_around(text, m.start(), m.end() + 40)
        _reject(rejected, value=parsed, reason="issued", sentence=sentence)
    for m in _REVISE_LABEL.finditer(text):
        parsed = _parse_date_token(text[m.end() : m.end() + 40])
        sentence = _sentence_around(text, m.start(), m.end() + 40)
        _reject(rejected, value=parsed, reason="revised", sentence=sentence)
    for m in _REVISE_STAMP.finditer(text):
        parsed = _parse_date_token(m.group(0))
        sentence = _sentence_around(text, m.start(), m.end())
        _reject(rejected, value=parsed, reason="revised", sentence=sentence)
    for m in _SCHOOL_YEAR.finditer(text):
        around = text[max(0, m.start() - 5) : m.end() + 5]
        if _YMD_ZH.search(around) or _ISO.search(around):
            continue
        sentence = _sentence_around(text, m.start(), m.end())
        _reject(rejected, value=None, reason="school_year", sentence=sentence)
    for m in _EFFECTIVE_LABEL.finditer(text):
        parsed = _parse_date_token(text[m.end() : m.end() + 40])
        sentence = _sentence_around(text, m.start(), m.end() + 40)
        _reject(rejected, value=parsed, reason="effective", sentence=sentence)
    for m in _EFFECTIVE_PHRASE.finditer(text):
        parsed = _parse_date_token(m.group(0)) or _parse_date_token(
            text[m.start() : min(len(text), m.end() + 40)]
        )
        sentence = _sentence_around(text, m.start(), min(len(text), m.end() + 40))
        _reject(rejected, value=parsed, reason="effective", sentence=sentence)
    for m in _BACKGROUND_SUPERSEDE.finditer(text):
        parsed = _parse_date_token(m.group(0)) or _parse_date_token(
            text[max(0, m.start() - 20) : min(len(text), m.end() + 40)]
        )
        sentence = _sentence_around(text, m.start(), min(len(text), m.end() + 40))
        _reject(rejected, value=parsed, reason="background", sentence=sentence)


def _activity_key(act: ActivityDates) -> tuple:
    return (act.name or "", act.starts_at, act.deadline_at, act.summary or "", act.location or "")


def _merge_pair(start: ActivityDates, end: ActivityDates) -> ActivityDates:
    return ActivityDates(
        name=start.name or end.name,
        starts_at=start.starts_at,
        deadline_at=end.deadline_at,
        summary=start.summary or end.summary,
        location=start.location or end.location,
        start_sentence=start.start_sentence,
        deadline_sentence=end.deadline_sentence,
        summary_sentence=start.summary_sentence or end.summary_sentence,
        location_sentence=start.location_sentence or end.location_sentence,
    )


def _merge_activities(items: list[ActivityDates]) -> list[ActivityDates]:
    """Dedupe and pair start-only + deadline-only rows that share a name (or both nameless)."""
    usable = [a for a in items if a.starts_at or a.deadline_at]
    both = [a for a in usable if a.starts_at and a.deadline_at]
    starts = [a for a in usable if a.starts_at and not a.deadline_at]
    ends = [a for a in usable if a.deadline_at and not a.starts_at]

    merged: list[ActivityDates] = list(both)
    used_ends: set[int] = set()

    for s in starts:
        partner_idx = None
        for i, e in enumerate(ends):
            if i in used_ends:
                continue
            if s.name and e.name and s.name != e.name:
                continue
            if (s.name or e.name) or (s.name is None and e.name is None):
                # Prefer pairing when names match or both anonymous (adjacent labels).
                if s.name is None and e.name is None:
                    partner_idx = i
                    break
                if s.name and e.name and s.name == e.name:
                    partner_idx = i
                    break
                if s.name and not e.name:
                    partner_idx = i
                    break
                if e.name and not s.name:
                    partner_idx = i
                    break
        if partner_idx is not None:
            used_ends.add(partner_idx)
            merged.append(_merge_pair(s, ends[partner_idx]))
        else:
            merged.append(s)

    for i, e in enumerate(ends):
        if i not in used_ends:
            merged.append(e)

    out: list[ActivityDates] = []
    seen: set[tuple] = set()
    for act in merged:
        key = _activity_key(act)
        if key in seen:
            continue
        seen.add(key)
        out.append(act)
    out.sort(
        key=lambda a: (
            a.starts_at or a.deadline_at or date.max,
            a.deadline_at or date.max,
            a.name or "",
        )
    )
    return out


def _span_taken(used_spans: set[tuple[int, int]], start: int, end: int) -> bool:
    """True if this match overlaps a span already used (same sentence, multi-pattern)."""
    for a, b in used_spans:
        if start < b and end > a:
            return True
    return False


def _append_unique(
    found: list[ActivityDates],
    used_spans: set[tuple[int, int]],
    act: ActivityDates,
    *,
    span: tuple[int, int],
) -> None:
    """Keep at most one calendar item per source match span (not per identical wording)."""
    if _span_taken(used_spans, span[0], span[1]):
        return
    used_spans.add(span)
    found.append(act)


def _collect_reply_deadlines(
    text: str,
    found: list[ActivityDates],
    used_spans: set[tuple[int, int]],
    rejected_locations: list[RejectedLocation],
) -> None:
    """Include 請於…前覆 / please reply by as deadline rows (no longer excluded).

    Do not borrow a nearby 活動名稱 — reply/submit titles come from the sentence
    object (交回問卷) or default to 交回文件.
    """
    for rx in (_REPLY_BY_ZH, _REPLY_BY_EN):
        for m in rx.finditer(text):
            window_end = min(len(text), m.end() + 50)
            window = text[m.start() : window_end]
            parsed = _parse_date_token(window)
            sentence = _sentence_around(text, m.start(), window_end)
            if parsed is None:
                continue
            name = _deadline_title(_title_from_submit_sentence(sentence))
            _append_unique(
                found,
                used_spans,
                _attach_details(
                    text,
                    m.start(),
                    rejected_locations,
                    name=name,
                    starts_at=None,
                    deadline_at=parsed,
                    start_sentence=None,
                    deadline_sentence=sentence,
                ),
                span=(m.start(), window_end),
            )


def extract_activities(text: str | None) -> ActivityExtractionResult:
    """Pull calendar dates/details from stored circular text only (no external AI)."""
    if not text or not text.strip():
        return ActivityExtractionResult()
    sample = _norm(text)
    rejected: list[RejectedDate] = []
    rejected_locations: list[RejectedLocation] = []
    _collect_rejected_non_activity(sample, rejected)
    _collect_bureau_address_rejects(sample, rejected_locations)

    found: list[ActivityDates] = []
    used_spans: set[tuple[int, int]] = set()

    for m in _RANGE_ZH.finditer(sample):
        sentence = _sentence_around(sample, m.start(), m.end())
        start_d = _parse_zh_ymd(m.group("start"))
        end_d = _parse_zh_ymd(m.group("end"))
        if not start_d and not end_d:
            continue
        name = _resolve_name(sample, m.start(), m.group("label"), sentence=sentence)
        _append_unique(
            found,
            used_spans,
            _attach_details(
                sample,
                m.start(),
                rejected_locations,
                name=name,
                starts_at=start_d,
                deadline_at=end_d,
                start_sentence=sentence if start_d else None,
                deadline_sentence=sentence if end_d else None,
            ),
            span=(m.start(), m.end()),
        )

    for m in _RANGE_EN.finditer(sample):
        sentence = _sentence_around(sample, m.start(), m.end())
        start_d = _parse_date_token(m.group("start"))
        end_d = _parse_date_token(m.group("end"))
        if not start_d and not end_d:
            continue
        name = _resolve_name(sample, m.start(), m.group("label"), sentence=sentence)
        _append_unique(
            found,
            used_spans,
            _attach_details(
                sample,
                m.start(),
                rejected_locations,
                name=name,
                starts_at=start_d,
                deadline_at=end_d,
                start_sentence=sentence if start_d else None,
                deadline_sentence=sentence if end_d else None,
            ),
            span=(m.start(), m.end()),
        )

    for m in _START_LABEL.finditer(sample):
        parsed, sentence = _take_date_after_label(sample, m, rejected)
        if parsed is None:
            continue
        name = _resolve_name(sample, m.start(), m.group("label"), sentence=sentence)
        _append_unique(
            found,
            used_spans,
            _attach_details(
                sample,
                m.start(),
                rejected_locations,
                name=name,
                starts_at=parsed,
                deadline_at=None,
                start_sentence=sentence,
                deadline_sentence=None,
            ),
            span=(m.start(), m.end()),
        )

    for m in _DEADLINE_LABEL.finditer(sample):
        parsed, sentence = _take_date_after_label(sample, m, rejected)
        if parsed is None:
            continue
        name = _resolve_name(sample, m.start(), m.group("label"), sentence=sentence)
        # Deadline rows without a title use 「交回文件」 — never the circular title.
        if not name:
            name = _DEFAULT_SUBMIT_TITLE
        _append_unique(
            found,
            used_spans,
            _attach_details(
                sample,
                m.start(),
                rejected_locations,
                name=name,
                starts_at=None,
                deadline_at=parsed,
                start_sentence=None,
                deadline_sentence=sentence,
            ),
            span=(m.start(), m.end()),
        )

    _collect_reply_deadlines(sample, found, used_spans, rejected_locations)

    activities = _merge_activities(found)
    # After merge, deadline-bearing items still need a display title.
    activities = [
        ActivityDates(
            name=_deadline_title(a.name) if a.deadline_at and not a.name else a.name,
            starts_at=a.starts_at,
            deadline_at=a.deadline_at,
            summary=a.summary,
            location=a.location,
            start_sentence=a.start_sentence,
            deadline_sentence=a.deadline_sentence,
            summary_sentence=a.summary_sentence,
            location_sentence=a.location_sentence,
        )
        if a.deadline_at and not a.name
        else a
        for a in activities
    ]
    return ActivityExtractionResult(
        activities=activities,
        rejected=rejected,
        rejected_locations=rejected_locations,
    )


def activities_to_stored(result: ActivityExtractionResult) -> list[dict]:
    """Serialize activities for Document.activities JSONB (no sentence fields)."""
    out: list[dict] = []
    for act in result.activities:
        name = act.name
        if act.deadline_at and not name:
            name = _DEFAULT_SUBMIT_TITLE
        out.append(
            {
                "name": name,
                "starts_at": act.starts_at.isoformat() if act.starts_at else None,
                "deadline_at": act.deadline_at.isoformat() if act.deadline_at else None,
                "summary": act.summary,
                "location": act.location,
            }
        )
    return out


def apply_document_activities(doc: object, text: str | None) -> bool:
    """Replace document.activities from extracted text. Returns True if changed."""
    result = extract_activities(text)
    stored = activities_to_stored(result)
    current = getattr(doc, "activities", None) or []
    if current == stored:
        return False
    setattr(doc, "activities", stored)
    return True
