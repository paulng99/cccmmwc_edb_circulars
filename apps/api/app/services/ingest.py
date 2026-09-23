from __future__ import annotations

import re
from io import BytesIO

from pypdf import PdfReader


def sanitize_text(text: str) -> str:
    """Remove null bytes and other non-UTF8-safe control chars for Postgres."""
    if not text:
        return ""
    text = text.replace("\x00", "")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", text)
    return text


def extract_text_from_pdf(data: bytes) -> str:
    reader = PdfReader(BytesIO(data))
    parts: list[str] = []
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        text = sanitize_text(text)
        if text.strip():
            parts.append(text)
    return "\n\n".join(parts)


def chunk_text(text: str, chunk_size: int = 1200, overlap: int = 150) -> list[str]:
    cleaned = sanitize_text(text)
    cleaned = re.sub(r"\s+\n", "\n", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned).strip()
    if not cleaned:
        return []
    # Skip mostly-binary garbage (very low printable ratio)
    printable = sum(1 for c in cleaned if c.isprintable() or c in "\n\t")
    if printable / max(len(cleaned), 1) < 0.7:
        return []

    chunks: list[str] = []
    start = 0
    n = len(cleaned)
    while start < n:
        end = min(start + chunk_size, n)
        if end < n:
            window = cleaned[start:end]
            break_at = max(window.rfind("\n\n"), window.rfind("。"), window.rfind(". "))
            if break_at > chunk_size // 3:
                end = start + break_at + 1
        piece = cleaned[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return chunks
