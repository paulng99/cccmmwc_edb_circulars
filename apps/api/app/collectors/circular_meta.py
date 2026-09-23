"""Parse EDB circular subject / number / language from HTML row text and PDF URLs."""

from __future__ import annotations

import re
from urllib.parse import unquote, urlparse

# Link labels used on applications.edb.gov.hk/circular
_LANG_LABELS: dict[str, str] = {
    "英文": "en",
    "english": "en",
    "繁體中文": "zh-HK",
    "繁體": "zh-HK",
    "traditional chinese": "zh-HK",
    "traditional": "zh-HK",
    "簡體中文": "zh-CN",
    "簡體": "zh-CN",
    "simplified chinese": "zh-CN",
    "simplified": "zh-CN",
}

LANG_LABEL_TEXTS = frozenset(_LANG_LABELS.keys()) | frozenset(
    {
        "英文",
        "繁體中文",
        "簡體中文",
        "English",
        "Traditional Chinese",
        "Simplified Chinese",
    }
)

_FILENAME_RE = re.compile(
    r"(EDBC(?:M)?)(\d{2})(\d{3})([CES])?(?:\.pdf)?$",
    re.IGNORECASE,
)
_CIRCULAR_IN_TEXT = re.compile(r"(EDBC(?:M)?)\s*(\d+)\s*/\s*(\d{4})", re.IGNORECASE)
_DATE_RE = re.compile(r"(\d{1,2}/\d{1,2}/\d{4})")


def is_language_label(title: str | None) -> bool:
    if not title:
        return True
    t = title.strip()
    if t in LANG_LABEL_TEXTS:
        return True
    return t.lower() in {x.lower() for x in LANG_LABEL_TEXTS}


def language_from_label(text: str | None) -> str | None:
    if not text:
        return None
    key = text.strip()
    if key in _LANG_LABELS:
        return _LANG_LABELS[key]
    return _LANG_LABELS.get(key.lower())


def language_from_filename(file_url: str | None) -> str | None:
    name = _filename(file_url)
    m = _FILENAME_RE.search(name)
    if not m:
        return None
    suffix = (m.group(4) or "").upper()
    return {"E": "en", "C": "zh-HK", "S": "zh-CN"}.get(suffix)


def circular_no_from_filename(file_url: str | None) -> str | None:
    name = _filename(file_url)
    m = _FILENAME_RE.search(name)
    if not m:
        return None
    prefix = m.group(1).upper()
    yy = int(m.group(2))
    num = m.group(3)
    year = 2000 + yy
    # Normalize: EDBCM048/2026 (drop leading zeros on number? keep 3-digit as published)
    return f"{prefix}{int(num):03d}/{year}"


def circular_no_from_text(text: str | None) -> str | None:
    if not text:
        return None
    m = _CIRCULAR_IN_TEXT.search(text)
    if not m:
        return None
    prefix = m.group(1).upper().replace(" ", "")
    num = int(m.group(2))
    year = int(m.group(3))
    return f"{prefix}{num:03d}/{year}"


def extract_subject(cell_text: str | None) -> str | None:
    """Pull the circular subject from an EDB results-table subject cell."""
    if not cell_text:
        return None
    text = re.sub(r"\s+", " ", cell_text).strip()
    text = re.sub(r"^(主題|Subject)\s*", "", text, flags=re.IGNORECASE)
    # Cut at circular-number / abstract markers
    cut = re.search(
        r"[\(（]?\s*(通告編號|Circular\s*No\.?|摘要|Abstract)\s*[：:)]?",
        text,
        re.IGNORECASE,
    )
    if cut:
        text = text[: cut.start()].strip(" ：:（()）")
    text = text.strip()
    if not text or is_language_label(text):
        return None
    return text[:1000]


def resolve_language(*, link_text: str | None, file_url: str | None, fallback: str = "zh-HK") -> str:
    return language_from_label(link_text) or language_from_filename(file_url) or fallback


def resolve_circular_no(*, row_text: str | None, file_url: str | None) -> str | None:
    return circular_no_from_text(row_text) or circular_no_from_filename(file_url)


def resolve_title(
    *,
    subject: str | None,
    row_text: str | None,
    link_text: str | None,
    file_url: str | None,
) -> str:
    if subject and not is_language_label(subject):
        return subject[:1000]
    from_row = extract_subject(row_text)
    if from_row:
        return from_row[:1000]
    if link_text and not is_language_label(link_text):
        return link_text[:1000]
    name = _filename(file_url)
    return (name or link_text or "Untitled")[:1000]


def _filename(file_url: str | None) -> str:
    if not file_url:
        return ""
    path = unquote(urlparse(file_url).path)
    return path.rsplit("/", 1)[-1]
