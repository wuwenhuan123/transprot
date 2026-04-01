from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from threading import Lock
from typing import Any

from transprot.core.errors import OCRUnavailableError
from transprot.core.models import OCRLine, OCRResult
from transprot.core.text import merge_ocr_lines


def paddleocr_available() -> bool:
    return importlib.util.find_spec("paddleocr") is not None


class BaseOCRService:
    provider_name = "base"

    def warmup(self) -> None:
        return

    def recognize(self, image_path: Path) -> OCRResult:
        raise NotImplementedError


class FakeOCRService(BaseOCRService):
    provider_name = "fake-ocr"

    def __init__(self, text: str) -> None:
        self._text = text

    def recognize(self, image_path: Path) -> OCRResult:
        return OCRResult(
            full_text=self._text.strip(),
            lines=[OCRLine(text=line) for line in self._text.splitlines() if line.strip()],
            provider=self.provider_name,
        )


class UnavailableOCRService(BaseOCRService):
    provider_name = "unavailable"

    def recognize(self, image_path: Path) -> OCRResult:
        raise OCRUnavailableError(
            "PaddleOCR is not installed. Run `pip install -e .[ocr]` before using screen OCR, "
            "or set TRANSPROT_FAKE_OCR_TEXT for demo mode."
        )


class PaddleOCRService(BaseOCRService):
    provider_name = "paddleocr"

    def __init__(self) -> None:
        self._engine: Any | None = None
        self._lock = Lock()

    def warmup(self) -> None:
        self._get_engine()

    def _get_engine(self) -> Any:
        if self._engine is not None:
            return self._engine
        with self._lock:
            if self._engine is None:
                from paddleocr import PaddleOCR

                self._engine = PaddleOCR(use_angle_cls=True, lang="ch")
        return self._engine

    def recognize(self, image_path: Path) -> OCRResult:
        engine = self._get_engine()
        raw = engine.ocr(str(image_path), cls=True)
        lines = self._extract_lines(raw)
        return OCRResult(
            full_text=merge_ocr_lines(line.text for line in lines),
            lines=lines,
            provider=self.provider_name,
        )

    def _extract_lines(self, payload: Any) -> list[OCRLine]:
        extracted: list[OCRLine] = []
        blocks = payload if isinstance(payload, list) else [payload]
        for block in blocks:
            if not isinstance(block, list):
                continue
            for item in block:
                if not isinstance(item, list) or len(item) < 2:
                    continue
                bbox_raw = item[0]
                text_info = item[1]
                text = ""
                if isinstance(text_info, tuple) and text_info:
                    text = str(text_info[0])
                elif isinstance(text_info, list) and text_info:
                    text = str(text_info[0])
                if not text.strip():
                    continue
                bbox = self._normalize_bbox(bbox_raw)
                extracted.append(OCRLine(text=text.strip(), bbox=bbox))
        return extracted

    @staticmethod
    def _normalize_bbox(bbox_raw: Any) -> tuple[int, int, int, int]:
        if isinstance(bbox_raw, list) and len(bbox_raw) >= 4:
            xs = [int(point[0]) for point in bbox_raw if isinstance(point, (list, tuple)) and len(point) >= 2]
            ys = [int(point[1]) for point in bbox_raw if isinstance(point, (list, tuple)) and len(point) >= 2]
            if xs and ys:
                return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)
        return 0, 0, 0, 0


def create_ocr_service() -> BaseOCRService:
    fake_text = os.getenv("TRANSPROT_FAKE_OCR_TEXT", "").strip()
    if fake_text:
        return FakeOCRService(fake_text)
    if paddleocr_available():
        return PaddleOCRService()
    return UnavailableOCRService()
