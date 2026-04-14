from __future__ import annotations

import importlib.util
import unittest
from unittest.mock import patch

_PYSIDE6_AVAILABLE = importlib.util.find_spec("PySide6") is not None
if _PYSIDE6_AVAILABLE:
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtWidgets import QApplication, QMenu

    from transprot.core.models import CaptureRegion
    from transprot.ui.capture_region_overlay import CaptureRegionOverlay
else:
    QApplication = None
    CaptureRegion = None
    CaptureRegionOverlay = None
    QPoint = None
    QPointF = None
    Qt = None
    QMenu = None


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
        overlay = self._create_overlay()
        overlay.show_result("translated text")

        clear_calls: list[str] = []
        overlay.clear_result = lambda: clear_calls.append("called")

        event = _FakeMouseEvent(QPoint(40, 40), QPoint(140, 160))
        overlay.mousePressEvent(event)

        self.assertTrue(event.accepted)
        self.assertEqual(clear_calls, [])
        self.assertEqual(overlay._result_view.toPlainText(), "translated text")

    def test_overlay_uses_single_translate_button_and_clean_labels(self) -> None:
        overlay = self._create_overlay()

        self.assertEqual(overlay._translate_button.text(), "\u7ffb\u8bd1")
        self.assertEqual(overlay._result_view.placeholderText(), "\u7ffb\u8bd1\u7ed3\u679c")
        overlay.set_busy(True)
        self.assertEqual(overlay._translate_button.text(), "\u7ffb\u8bd1\u4e2d...")

    def test_translate_button_stays_outside_overlay(self) -> None:
        overlay = self._create_overlay(x=160, y=180, width=420, height=180)

        overlay.show_region()
        self._app.processEvents()

        self.assertTrue(overlay._translate_button.isVisible())
        self.assertFalse(overlay.geometry().intersects(overlay._translate_button.geometry()))
        self.assertGreaterEqual(overlay._translate_button.geometry().right(), overlay.geometry().right() - 40)

    def test_capture_preview_suppression_keeps_overlay_visible_when_capture_exclusion_is_available(self) -> None:
        overlay = self._create_overlay(x=160, y=180, width=420, height=180)
        overlay.show_region()
        self._app.processEvents()

        overlay._capture_exclusion_supported = True
        overlay.show_result("??")
        overlay.set_capture_preview_suppressed(True)

        self.assertTrue(overlay._translate_button.isVisible())
        self.assertTrue(overlay._result_view.isVisible())
        self.assertEqual(overlay.windowOpacity(), 1.0)

        overlay.set_capture_preview_suppressed(False)
        self.assertTrue(overlay._translate_button.isVisible())
        self.assertTrue(overlay._result_view.isVisible())
        self.assertEqual(overlay.windowOpacity(), 1.0)

    def test_reset_to_idle_clears_result_and_restores_button_text(self) -> None:
        overlay = self._create_overlay(x=160, y=180, width=420, height=180)
        overlay.show_result("\u8bd1\u6587")
        overlay.set_busy(True)

        overlay.reset_to_idle()

        self.assertFalse(overlay._result_view.isVisible())
        self.assertEqual(overlay._result_view.toPlainText(), "")
        self.assertEqual(overlay._translate_button.text(), "\u7ffb\u8bd1")
        self.assertTrue(overlay._translate_button.isEnabled())

    def test_context_menu_requests_clear_when_result_exists(self) -> None:
        overlay = self._create_overlay(x=160, y=180, width=420, height=180)
        overlay.show_result("\u8bd1\u6587")
        events: list[str] = []
        overlay.clear_requested.connect(lambda: events.append("clear"))

        action_map = self._action_map(overlay)
        with patch.object(overlay, "_create_overlay_menu", return_value=(QMenu(overlay), action_map)), patch.object(
            overlay,
            "_exec_overlay_menu",
            return_value=action_map["clear"],
        ):
            overlay._show_overlay_menu(QPoint(5, 5))

        self.assertEqual(events, ["clear"])

    def test_context_menu_can_hide_overlay(self) -> None:
        overlay = self._create_overlay(x=160, y=180, width=420, height=180)
        events: list[str] = []
        overlay.hide_requested.connect(lambda: events.append("hide"))

        action_map = self._action_map(overlay)
        with patch.object(overlay, "_create_overlay_menu", return_value=(QMenu(overlay), action_map)), patch.object(
            overlay,
            "_exec_overlay_menu",
            return_value=action_map["hide"],
        ):
            overlay._show_overlay_menu(QPoint(5, 5))

        self.assertEqual(events, ["hide"])

    def test_context_menu_can_open_settings(self) -> None:
        overlay = self._create_overlay(x=160, y=180, width=420, height=180)
        events: list[str] = []
        overlay.settings_requested.connect(lambda: events.append("settings"))

        action_map = self._action_map(overlay)
        with patch.object(overlay, "_create_overlay_menu", return_value=(QMenu(overlay), action_map)), patch.object(
            overlay,
            "_exec_overlay_menu",
            return_value=action_map["settings"],
        ):
            overlay._show_overlay_menu(QPoint(5, 5))

        self.assertEqual(events, ["settings"])

    def test_result_font_scales_with_overlay_size_but_stays_reasonable(self) -> None:
        overlay = self._create_overlay(width=320, height=120)
        small_size = overlay._compute_result_font_point_size()

        overlay.apply_region(CaptureRegion(screen_name="Primary", x=100, y=120, width=960, height=300))
        large_size = overlay._compute_result_font_point_size()

        self.assertGreater(large_size, small_size)
        self.assertLessEqual(large_size, 16.0)

    def _create_overlay(self, x: int = 100, y: int = 120, width: int = 420, height: int = 180) -> CaptureRegionOverlay:
        return CaptureRegionOverlay(
            CaptureRegion(screen_name="Primary", x=x, y=y, width=width, height=height)
        )

    @staticmethod
    def _action_map(overlay: CaptureRegionOverlay) -> dict[str, object]:
        menu = QMenu(overlay)
        return {
            "clear": menu.addAction("\u6e05\u9664\u8bd1\u6587"),
            "hide": menu.addAction("\u9690\u85cf\u7ffb\u8bd1\u6846"),
            "settings": menu.addAction("\u8bbe\u7f6e"),
        }


if __name__ == "__main__":
    unittest.main()
