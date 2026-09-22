from __future__ import annotations

import re
from io import BytesIO

from pypdf import PdfReader


def extract_text_from_pdf(data: bytes) -> str:
    reader = PdfReader(BytesIO(data))
    parts: list[str] = []
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        if text.strip():
            parts.append(text)
    return "\n\n".join(parts)


def chunk_text(text: str, chunk_size: int = 1200, overlap: int = 150) -> list[str]:
    cleaned = re.sub(r"\s+\n", "\n", text)
    cleaned = re.sub(r"[ \t]+", " ", cleaned).strip()
    if not cleaned:
        return []
    chunks: list[str] = []
    start = 0
    n = len(cleaned)
    while start < n:
        end = min(start + chunk_size, n)
        if end < n:
            # prefer break at paragraph/sentence
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
