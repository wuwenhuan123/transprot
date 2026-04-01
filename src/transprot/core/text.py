from __future__ import annotations

from collections.abc import Iterable


def merge_ocr_lines(lines: Iterable[str]) -> str:
    cleaned = [line.strip() for line in lines if line and line.strip()]
    return "\n".join(cleaned)


def normalize_translation_text(text: str) -> str:
    return "\n".join(part.rstrip() for part in text.replace("\r\n", "\n").split("\n")).strip()

