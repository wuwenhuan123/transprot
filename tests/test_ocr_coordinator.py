from __future__ import annotations

import importlib.util
import unittest
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import patch

from transprot.core.models import AppConfig, CaptureRegion, OCRResult, TranslationResult

_PYSIDE6_AVAILABLE = importlib.util.find_spec("PySide6") is not None
if _PYSIDE6_AVAILABLE:
    from PySide6.QtCore import QCoreApplication
    from transprot.core.ocr_coordinator import OCRCoordinator
else:
    QCoreApplication = None
    OCRCoordinator = None


class _ImmediateExecutor:
    def submit(self, fn, *args, **kwargs):
        future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except Exception as exc:
            future.set_exception(exc)
        return future

    def shutdown(self, wait: bool = False, cancel_futures: bool = True) -> None:
        return None


class _FakeScreenshotService:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def capture(self, region: CaptureRegion) -> Path:
        self._events.append("capture")
        return Path("capture.png")


class _FakeOCRService:
    def __init__(self, events: list[str], result_text: str) -> None:
        self._events = events
        self._result_text = result_text

    def warmup(self) -> None:
        return None

    def shutdown(self) -> None:
        return None

    def recognize(self, image_path: Path) -> OCRResult:
        self._events.append("ocr")
        return OCRResult(full_text=self._result_text)


class _FakeTranslatorRouter:
    def __init__(self, events: list[str], translated_text: str = "translated text") -> None:
        self._events = events
        self._translated_text = translated_text

    def translate(self, text: str, config: AppConfig) -> TranslationResult:
        self._events.append("translate")
        return TranslationResult(
            source_text=text,
            translated_text=self._translated_text,
            provider="fake",
            latency_ms=12,
        )


@unittest.skipUnless(_PYSIDE6_AVAILABLE, "PySide6 is required for OCR coordinator signal tests.")
class OCRCoordinatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QCoreApplication.instance() or QCoreApplication([])

    def _build_coordinator(
        self,
        events: list[str],
        ocr_text: str,
        translated_text: str = "translated text",
    ) -> OCRCoordinator:
        coordinator = OCRCoordinator(
            screenshot_service=_FakeScreenshotService(events),
            ocr_service=_FakeOCRService(events, ocr_text),
            translator_router=_FakeTranslatorRouter(events, translated_text),
            config_supplier=lambda: AppConfig(
                api_base_url="https://example.com/v1",
                model="demo-model",
            ),
            capture_delay_ms=0,
        )
        coordinator._executor = _ImmediateExecutor()
        return coordinator

    def test_recognize_region_runs_ocr_then_translation(self) -> None:
        events: list[str] = []
        statuses: list[str] = []
        translations: list[tuple[CaptureRegion, TranslationResult]] = []
        region = CaptureRegion(screen_name="Primary", x=100, y=120, width=420, height=180)
        coordinator = self._build_coordinator(events, "recognized text")
        coordinator.capture_started.connect(lambda emitted_region: events.append("capture_started"))
        coordinator.recognition_started.connect(lambda emitted_region: events.append("recognition_started"))
        coordinator.translation_started.connect(lambda emitted_region, result: events.append("translation_started"))
        coordinator.translation_ready.connect(
            lambda emitted_region, result: translations.append((emitted_region, result))
        )
        coordinator.translation_ready.connect(lambda emitted_region, result: events.append("translation_ready"))
        coordinator.session_finished.connect(lambda: events.append("finished"))
        coordinator.status_changed.connect(statuses.append)

        with patch("transprot.core.ocr_coordinator.QTimer.singleShot", side_effect=lambda delay, fn: fn()):
            coordinator.recognize_region(region)
            self._app.processEvents()

        self.assertEqual(events[:4], ["capture_started", "capture", "recognition_started", "ocr"])
        self.assertIn("translate", events)
        self.assertIn("translation_started", events)
        self.assertIn("translation_ready", events)
        self.assertEqual(translations[0][0], region)
        self.assertEqual(translations[0][1].translated_text, "translated text")
        self.assertEqual(statuses, ["capturing", "recognizing", "translating", "completed"])

    def test_recognize_region_surfaces_blank_ocr_as_error(self) -> None:
        events: list[str] = []
        errors: list[str] = []
        statuses: list[str] = []
        region = CaptureRegion(screen_name="Primary", x=100, y=120, width=420, height=180)
        coordinator = self._build_coordinator(events, "  \n  ")
        coordinator.capture_started.connect(lambda emitted_region: events.append("capture_started"))
        coordinator.error_occurred.connect(errors.append)
        coordinator.session_finished.connect(lambda: events.append("finished"))
        coordinator.status_changed.connect(statuses.append)

        with patch("transprot.core.ocr_coordinator.QTimer.singleShot", side_effect=lambda delay, fn: fn()):
            coordinator.recognize_region(region)
            self._app.processEvents()

        self.assertEqual(events[:4], ["capture_started", "capture", "recognition_started", "ocr"])
        self.assertEqual(errors, ["当前区域没有识别到可用文字。"])
        self.assertIn("finished", events)
        self.assertEqual(statuses, ["capturing", "recognizing", "error"])

    def test_auto_mode_skips_translation_when_ocr_text_matches_previous_success(self) -> None:
        events: list[str] = []
        skipped: list[str] = []
        statuses: list[str] = []
        region = CaptureRegion(screen_name="Primary", x=100, y=120, width=420, height=180)
        coordinator = self._build_coordinator(events, "recognized text")
        coordinator.translation_skipped.connect(lambda emitted_region, result, reason: skipped.append(reason))
        coordinator.session_finished.connect(lambda: events.append("finished"))
        coordinator.status_changed.connect(statuses.append)

        with patch("transprot.core.ocr_coordinator.QTimer.singleShot", side_effect=lambda delay, fn: fn()):
            coordinator.recognize_region(
                region,
                trigger="auto",
                previous_source_text="recognized text",
            )
            self._app.processEvents()

        self.assertEqual(skipped, ["same_source_text"])
        self.assertNotIn("translate", events)
        self.assertIn("finished", events)
        self.assertEqual(statuses, ["capturing", "recognizing", "completed"])


if __name__ == "__main__":
    unittest.main()
