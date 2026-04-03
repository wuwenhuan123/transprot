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

    def test_overlay_uses_translate_and_close_buttons(self) -> None:
        overlay = CaptureRegionOverlay(
            CaptureRegion(screen_name="Primary", x=100, y=120, width=420, height=180)
        )

        self.assertEqual(overlay._recognize_button.text(), "翻译")
        self.assertEqual(overlay._close_button.text(), "×")
        self.assertEqual(overlay._result_view.placeholderText(), "译文会显示在这里")

        overlay.show_region()
        self._app.processEvents()
        self.assertLessEqual(overlay._recognize_button.width(), 92)

        overlay.set_status("translating")
        self.assertEqual(overlay._recognize_button.text(), "翻译中...")
        overlay.set_busy(True)
        self.assertFalse(overlay._recognize_button.isEnabled())

    def test_action_buttons_stay_outside_overlay(self) -> None:
        overlay = CaptureRegionOverlay(
            CaptureRegion(screen_name="Primary", x=160, y=180, width=420, height=180)
        )

        overlay.show_region()
        self._app.processEvents()

        self.assertTrue(overlay._recognize_button.isVisible())
        self.assertTrue(overlay._close_button.isVisible())
        self.assertFalse(overlay.geometry().intersects(overlay._recognize_button.geometry()))
        self.assertFalse(overlay.geometry().intersects(overlay._close_button.geometry()))

    def test_capture_region_matches_highlighted_inner_frame(self) -> None:
        overlay = CaptureRegionOverlay(
            CaptureRegion(screen_name="Primary", x=160, y=180, width=420, height=180)
        )

        frame_region = overlay.current_region()
        capture_region = overlay.current_capture_region()

        self.assertEqual(capture_region.screen_name, frame_region.screen_name)
        self.assertEqual(capture_region.x, frame_region.x + 4)
        self.assertEqual(capture_region.y, frame_region.y + 4)
        self.assertEqual(capture_region.width, frame_region.width - 8)
        self.assertEqual(capture_region.height, frame_region.height - 8)

    def test_resize_geometry_can_shrink_below_previous_minimum(self) -> None:
        overlay = CaptureRegionOverlay(
            CaptureRegion(screen_name="Primary", x=160, y=180, width=420, height=180)
        )

        geometry = overlay._geometry_for_handle(
            overlay.geometry(),
            QPoint(-360, -150),
            "bottom_right",
        )

        self.assertLess(geometry.width(), 240)
        self.assertLess(geometry.height(), 120)

    def test_hide_request_emits_signal(self) -> None:
        overlay = CaptureRegionOverlay(
            CaptureRegion(screen_name="Primary", x=160, y=180, width=420, height=180)
        )
        calls: list[str] = []
        overlay.hide_requested.connect(lambda: calls.append("hide"))

        overlay._emit_hide_requested()

        self.assertEqual(calls, ["hide"])

    def test_clear_request_emits_signal_when_result_visible(self) -> None:
        overlay = CaptureRegionOverlay(
            CaptureRegion(screen_name="Primary", x=160, y=180, width=420, height=180)
        )
        calls: list[str] = []
        overlay.clear_requested.connect(lambda: calls.append("clear"))
        overlay.show_result("translated text")

        overlay._request_clear_result()

        self.assertEqual(calls, ["clear"])

    def test_reset_to_idle_clears_result_and_restores_ready_state(self) -> None:
        overlay = CaptureRegionOverlay(
            CaptureRegion(screen_name="Primary", x=160, y=180, width=420, height=180)
        )
        overlay.show_result("translated text")
        overlay.set_status("completed")
        overlay.set_busy(True)

        overlay.reset_to_idle()

        self.assertFalse(overlay._result_view.isVisible())
        self.assertEqual(overlay._recognize_button.text(), "翻译")
        self.assertTrue(overlay._recognize_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
