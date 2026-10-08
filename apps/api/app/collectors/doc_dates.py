"""Read an issue date and a later update date from circular text.

EDB circulars often keep the original issue date, then add a stamp after a
revision, for example ``(2026 年 7 月 30 日更新)`` or ``(Updated on 30 July 2026)``.
A month-only stamp such as ``（2026 年 4 月更新）`` is stored as the last day of
that month so it still sorts after an issue date in the same month.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date

_SCAN_CHARS = 8000

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

# Full day, with or without parentheses: (2026 年 7 月 30 日更新)
_REVISED_YMD = re.compile(
    r"(?:[（(]\s*)?(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*更新\s*[)）]?"
)
# Month only must be parenthetical so prose like "2026年4月更新課程" is ignored.
_REVISED_YM = re.compile(
    r"[（(]\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*更新\s*[)）]"
)
_REVISED_EN = re.compile(
    r"(?:[（(]\s*)?(?:Updated|Revised)\s+on\s+(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})\s*[)）]?",
    re.IGNORECASE,
)
_REVISED_EN_MONTH = re.compile(
    r"[（(]\s*(?:Updated|Revised)\s+in\s+([A-Za-z]+)\s+(\d{4})\s*[)）]",
    re.IGNORECASE,
)
_REVISED_LABEL_YMD = re.compile(
    r"(?:最後更新日期|最後修訂日期|更新日期|修訂日期)\s*[:：]\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"
)
_REVISED_LABEL_DMY = re.compile(
    r"(?:最後更新日期|最後修訂日期|更新日期|修訂日期)\s*[:：]\s*(\d{1,2})[/-](\d{1,2})[/-](\d{4})"
)
_REVISED_LABEL_ISO = re.compile(
    r"(?:最後更新日期|最後修訂日期|更新日期|修訂日期)\s*[:：]\s*(\d{4})-(\d{2})-(\d{2})"
)
_REVISED_LABEL_EN = re.compile(
    r"(?:Last\s+Revision\s+Date|Last\s+Updated|Revision\s+Date|Updated\s+Date)\s*[:：]\s*"
    r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})",
    re.IGNORECASE,
)

_ISSUED_LABEL_YMD = re.compile(
    r"(?:發出日期|發行日期)\s*[:：]\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"
)
_ISSUED_LABEL_DMY = re.compile(
    r"(?:發出日期|發行日期)\s*[:：]\s*(\d{1,2})[/-](\d{1,2})[/-](\d{4})"
)
_ISSUED_LABEL_ISO = re.compile(
    r"(?:發出日期|發行日期)\s*[:：]\s*(\d{4})-(\d{2})-(\d{2})"
)
_ISSUED_LABEL_EN = re.compile(
    r"(?:Issue\s+Date|Date\s+of\s+Issue)\s*[:：]\s*"
    r"(?:(\d{4})-(\d{2})-(\d{2})|(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})|(\d{1,2})[/-](\d{1,2})[/-](\d{4}))",
    re.IGNORECASE,
)
_BARE_EN = re.compile(
    r"(?m)^\s*(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})\s*$"
)
_BARE_DMY = re.compile(r"(?m)^\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*$")
_HEADER_CHARS = 1500


@dataclass(frozen=True)
class DocumentDates:
    issued_at: date | None = None
    revised_at: date | None = None


def _norm(text: str) -> str:
    cleaned = text.replace("\u3000", " ").replace("\xa0", " ").replace("\r\n", "\n")
    cleaned = re.sub(r"[^\S\n]+", " ", cleaned)
    return cleaned[:_SCAN_CHARS]


def _ymd(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _end_of_month(year: int, month: int) -> date | None:
    try:
        last = calendar.monthrange(year, month)[1]
    except calendar.IllegalMonthError:
        return None
    return _ymd(year, month, last)


def _en_date(day: str, month_name: str, year: str) -> date | None:
    month = _MONTHS.get(month_name.strip().lower())
    if month is None:
        return None
    return _ymd(int(year), month, int(day))


def _dmy(day: str, month: str, year: str) -> date | None:
    return _ymd(int(year), int(month), int(day))


def _latest(values: list[date]) -> date | None:
    return max(values) if values else None


def _earliest(values: list[date]) -> date | None:
    return min(values) if values else None


def keep_later_revision(issued: date | None, revised: date | None) -> date | None:
    """Keep an update date only when it falls after the issue date."""
    if revised is None:
        return None
    if issued is not None and revised <= issued:
        return None
    return revised


def extract_document_dates(text: str | None) -> DocumentDates:
    if not text or not text.strip():
        return DocumentDates()
    sample = _norm(text)
    revised_on: list[date] = []
    issued_on: list[date] = []

    for match in _REVISED_YMD.finditer(sample):
        found = _ymd(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if found:
            revised_on.append(found)
    for match in _REVISED_YM.finditer(sample):
        found = _end_of_month(int(match.group(1)), int(match.group(2)))
        if found:
            revised_on.append(found)
    for match in _REVISED_EN.finditer(sample):
        found = _en_date(match.group(1), match.group(2), match.group(3))
        if found:
            revised_on.append(found)
    for match in _REVISED_EN_MONTH.finditer(sample):
        month = _MONTHS.get(match.group(1).strip().lower())
        found = _end_of_month(int(match.group(2)), month) if month else None
        if found:
            revised_on.append(found)
    for match in _REVISED_LABEL_YMD.finditer(sample):
        found = _ymd(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if found:
            revised_on.append(found)
    for match in _REVISED_LABEL_DMY.finditer(sample):
        found = _dmy(match.group(1), match.group(2), match.group(3))
        if found:
            revised_on.append(found)
    for match in _REVISED_LABEL_ISO.finditer(sample):
        found = _ymd(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if found:
            revised_on.append(found)
    for match in _REVISED_LABEL_EN.finditer(sample):
        found = _en_date(match.group(1), match.group(2), match.group(3))
        if found:
            revised_on.append(found)

    for match in _ISSUED_LABEL_YMD.finditer(sample):
        found = _ymd(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if found:
            issued_on.append(found)
    for match in _ISSUED_LABEL_DMY.finditer(sample):
        found = _dmy(match.group(1), match.group(2), match.group(3))
        if found:
            issued_on.append(found)
    for match in _ISSUED_LABEL_ISO.finditer(sample):
        found = _ymd(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if found:
            issued_on.append(found)
    for match in _ISSUED_LABEL_EN.finditer(sample):
        if match.group(1):
            found = _ymd(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        elif match.group(4):
            found = _en_date(match.group(4), match.group(5), match.group(6))
        else:
            found = _dmy(match.group(7), match.group(8), match.group(9))
        if found:
            issued_on.append(found)

    revised = _latest(revised_on)
    issued = _earliest(issued_on)
    if issued is None:
        header = sample[:_HEADER_CHARS]
        for match in _BARE_EN.finditer(header):
            found = _en_date(match.group(1), match.group(2), match.group(3))
            if found and found != revised:
                issued = found
                break
        if issued is None:
            for match in _BARE_DMY.finditer(header):
                found = _dmy(match.group(1), match.group(2), match.group(3))
                if found and found != revised:
                    issued = found
                    break
    return DocumentDates(issued_at=issued, revised_at=revised)


def apply_document_dates(doc: object, text: str | None) -> bool:
    """Fill a missing issue date, and record an update date only when it is later."""
    found = extract_document_dates(text)
    changed = False
    if found.issued_at is not None and getattr(doc, "issued_at", None) is None:
        setattr(doc, "issued_at", found.issued_at)
        changed = True
    revised = keep_later_revision(getattr(doc, "issued_at", None), found.revised_at)
    current = getattr(doc, "revised_at", None)
    if revised is not None and (current is None or revised > current):
        setattr(doc, "revised_at", revised)
        changed = True
    return changed
