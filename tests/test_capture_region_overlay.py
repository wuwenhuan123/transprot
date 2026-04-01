from __future__ import annotations

import importlib.util
import unittest

_PYSIDE6_AVAILABLE = importlib.util.find_spec("PySide6") is not None
if _PYSIDE6_AVAILABLE:
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtWidgets import QApplication

    from transprot.core.models import CaptureRegion
    from transprot.ui.capture_region_overlay import CaptureRegionOverlay
else:
    QApplication = None
    CaptureRegion = None
    CaptureRegionOverlay = None
    QPoint = None
    QPointF = None
    Qt = None


class _FakeMouseEvent:
    def __init__(self, local_pos: QPoint, global_pos: QPoint) -> None:
        self._local_pos = QPointF(local_pos)
        self._global_pos = QPointF(global_pos)
        self.accepted = False

    def button(self):
        return Qt.LeftButton

    def position(self):
        return self._local_pos

    def globalPosition(self):
        return self._global_pos

    def accept(self) -> None:
        self.accepted = True


@unittest.skipUnless(_PYSIDE6_AVAILABLE, "PySide6 is required for capture overlay tests.")
class CaptureRegionOverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def tearDown(self) -> None:
        for widget in self._app.topLevelWidgets():
            widget.hide()
            widget.deleteLater()
        self._app.processEvents()

    def test_mouse_press_keeps_existing_result_content(self) -> None:
        overlay = CaptureRegionOverlay(
            CaptureRegion(screen_name="Primary", x=100, y=120, width=420, height=180)
        )
        overlay.show_result("recognized text")

        clear_calls: list[str] = []
        overlay.clear_result = lambda: clear_calls.append("called")

        event = _FakeMouseEvent(QPoint(40, 40), QPoint(140, 160))
        overlay.mousePressEvent(event)

        self.assertTrue(event.accepted)
        self.assertEqual(clear_calls, [])
        self.assertEqual(overlay._result_view.toPlainText(), "recognized text")

    def test_overlay_uses_readable_chinese_labels(self) -> None:
        overlay = CaptureRegionOverlay(
            CaptureRegion(screen_name="Primary", x=100, y=120, width=420, height=180)
        )

        self.assertEqual(
            overlay._hint_label.text(),
            "\u62d6\u52a8\u6216\u7f29\u653e\u8fd9\u4e2a\u533a\u57df\uff0c\u4f7f\u5b83\u8986\u76d6\u76ee\u6807\u6587\u5b57",
        )
        self.assertEqual(overlay._recognize_button.text(), "\u8bc6\u522b")
        self.assertEqual(overlay._result_view.placeholderText(), "OCR \u8bc6\u522b\u7ed3\u679c")
        overlay.set_busy(True)
        self.assertEqual(overlay._recognize_button.text(), "\u8bc6\u522b\u4e2d...")

    def test_recognize_button_stays_outside_overlay(self) -> None:
        overlay = CaptureRegionOverlay(
            CaptureRegion(screen_name="Primary", x=160, y=180, width=420, height=180)
        )

        overlay.show_region()
        self._app.processEvents()

        self.assertTrue(overlay._recognize_button.isVisible())
        self.assertFalse(overlay.geometry().intersects(overlay._recognize_button.geometry()))
        self.assertGreaterEqual(overlay._recognize_button.geometry().right(), overlay.geometry().right() - 40)


if __name__ == "__main__":
    unittest.main()