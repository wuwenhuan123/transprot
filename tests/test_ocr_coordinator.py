from __future__ import annotations

import importlib.util
import unittest
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import patch

from transprot.core.models import CaptureRegion, OCRResult

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

    def recognize(self, image_path: Path) -> OCRResult:
        self._events.append("ocr")
        return OCRResult(full_text=self._result_text)


@unittest.skipUnless(_PYSIDE6_AVAILABLE, "PySide6 is required for OCR coordinator signal tests.")
class OCRCoordinatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QCoreApplication.instance() or QCoreApplication([])

    def test_recognize_region_hides_before_capture_and_returns_ocr_result(self) -> None:
        events: list[str] = []
        statuses: list[str] = []
        results: list[tuple[CaptureRegion, OCRResult]] = []
        region = CaptureRegion(screen_name="Primary", x=100, y=120, width=420, height=180)
        coordinator = OCRCoordinator(
            screenshot_service=_FakeScreenshotService(events),
            ocr_service=_FakeOCRService(events, "recognized text"),
            capture_delay_ms=0,
        )
        coordinator._executor = _ImmediateExecutor()
        coordinator.capture_started.connect(lambda emitted_region: events.append("capture_started"))
        coordinator.ocr_ready.connect(lambda emitted_region, result: results.append((emitted_region, result)))
        coordinator.ocr_ready.connect(lambda emitted_region, result: events.append("ocr_ready"))
        coordinator.session_finished.connect(lambda: events.append("finished"))
        coordinator.status_changed.connect(statuses.append)

        with patch("transprot.core.ocr_coordinator.QTimer.singleShot", side_effect=lambda delay, fn: fn()):
            coordinator.recognize_region(region)
            self._app.processEvents()

        self.assertEqual(events[:3], ["capture_started", "capture", "ocr"])
        self.assertIn("ocr_ready", events)
        self.assertIn("finished", events)
        self.assertEqual(results[0][0], region)
        self.assertEqual(results[0][1].full_text, "recognized text")
        self.assertEqual(statuses, ["capturing", "recognizing", "completed"])
        self.assertFalse(hasattr(coordinator, "_translator_router"))

    def test_recognize_region_surfaces_blank_ocr_as_error(self) -> None:
        events: list[str] = []
        errors: list[str] = []
        statuses: list[str] = []
        region = CaptureRegion(screen_name="Primary", x=100, y=120, width=420, height=180)
        coordinator = OCRCoordinator(
            screenshot_service=_FakeScreenshotService(events),
            ocr_service=_FakeOCRService(events, "  \n  "),
            capture_delay_ms=0,
        )
        coordinator._executor = _ImmediateExecutor()
        coordinator.capture_started.connect(lambda emitted_region: events.append("capture_started"))
        coordinator.error_occurred.connect(errors.append)
        coordinator.session_finished.connect(lambda: events.append("finished"))
        coordinator.status_changed.connect(statuses.append)

        with patch("transprot.core.ocr_coordinator.QTimer.singleShot", side_effect=lambda delay, fn: fn()):
            coordinator.recognize_region(region)
            self._app.processEvents()

        self.assertEqual(events[:3], ["capture_started", "capture", "ocr"])
        self.assertEqual(errors, ["当前区域没有识别到可用文字。"])
        self.assertIn("finished", events)
        self.assertEqual(statuses, ["capturing", "recognizing", "error"])


if __name__ == "__main__":
    unittest.main()
