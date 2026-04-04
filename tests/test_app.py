from __future__ import annotations

import importlib.util
import types
import unittest

_PYSIDE6_AVAILABLE = importlib.util.find_spec("PySide6") is not None
if _PYSIDE6_AVAILABLE:
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon

    from transprot.app import TransProtDesktopApp
    from transprot.core.models import AppConfig, CaptureRegion, TranslationResult
else:
    QApplication = None
    QSystemTrayIcon = None
    TransProtDesktopApp = None
    CaptureRegion = None
    TranslationResult = None


class _FakeOverlay:
    def __init__(self) -> None:
        self.applied_regions: list[CaptureRegion] = []
        self.show_region_calls = 0
        self.results: list[tuple[str, bool]] = []
        self.hidden = False
        self.busy_states: list[bool] = []
        self.statuses: list[str] = []
        self.cleared = False
        self.frame_region = CaptureRegion(screen_name="Primary", x=100, y=120, width=420, height=180)
        self.capture_region = CaptureRegion(screen_name="Primary", x=104, y=124, width=412, height=172)

    def apply_region(self, region: CaptureRegion) -> None:
        self.applied_regions.append(region)

    def current_region(self) -> CaptureRegion:
        return self.frame_region

    def current_capture_region(self) -> CaptureRegion:
        return self.capture_region

    def clear_result(self) -> None:
        self.cleared = True

    def show_region(self) -> None:
        self.show_region_calls += 1

    def show_result(self, text: str, is_error: bool = False) -> None:
        self.results.append((text, is_error))

    def set_busy(self, busy: bool) -> None:
        self.busy_states.append(busy)

    def set_status(self, status: str) -> None:
        self.statuses.append(status)

    def hide(self) -> None:
        self.hidden = True

    def reset_to_idle(self) -> None:
        self.cleared = True
        self.busy_states.append(False)
        self.statuses.append("ready")


class _FakeTray:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str, object]] = []
        self.tooltips: list[str] = []

    def showMessage(self, title: str, message: str, icon=None) -> None:
        self.messages.append((title, message, icon))

    def setToolTip(self, text: str) -> None:
        self.tooltips.append(text)


@unittest.skipUnless(_PYSIDE6_AVAILABLE, "PySide6 is required for app behavior tests.")
class AppBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_load_runtime_config_reads_config_file_and_preserves_visible_region(self) -> None:
        overlay = _FakeOverlay()
        stored_config = AppConfig(api_key="file-key", api_key_saved=True, model="file-model", timeout_sec=88)
        controller = types.SimpleNamespace(
            _config_store=types.SimpleNamespace(load=lambda: stored_config),
            _capture_overlay=overlay,
            _config=None,
        )

        config = TransProtDesktopApp._load_runtime_config(controller)

        self.assertIs(config, stored_config)
        self.assertEqual(config.api_key, "file-key")
        self.assertEqual(config.model, "file-model")
        self.assertEqual(config.capture_region, overlay.frame_region)
        self.assertIs(controller._config, stored_config)

    def test_start_capture_uses_effective_capture_region_by_default(self) -> None:
        overlay = _FakeOverlay()
        captured_regions: list[CaptureRegion] = []
        controller = types.SimpleNamespace(
            _capture_overlay=overlay,
            _capture_overlay_hidden_by_user=True,
            _coordinator=types.SimpleNamespace(recognize_region=lambda region: captured_regions.append(region)),
        )

        TransProtDesktopApp.start_capture(controller)

        self.assertFalse(controller._capture_overlay_hidden_by_user)
        self.assertTrue(overlay.cleared)
        self.assertEqual(overlay.busy_states[-1], True)
        self.assertEqual(captured_regions, [overlay.capture_region])

    def test_capture_started_does_not_persist_inset_capture_region(self) -> None:
        saved_regions: list[CaptureRegion] = []
        controller = types.SimpleNamespace(
            _on_region_committed=lambda region: saved_regions.append(region),
        )
        capture_region = CaptureRegion(screen_name="Primary", x=104, y=124, width=412, height=172)

        TransProtDesktopApp._on_capture_started(controller, capture_region)

        self.assertEqual(saved_regions, [])

    def test_translation_ready_keeps_current_overlay_position(self) -> None:
        overlay = _FakeOverlay()
        controller = types.SimpleNamespace(
            _capture_overlay=overlay,
            _capture_overlay_hidden_by_user=False,
        )
        region = CaptureRegion(screen_name="Primary", x=100, y=120, width=420, height=180)
        translation = TranslationResult(
            source_text="hello",
            translated_text="你好",
            provider="openai_compatible",
            latency_ms=12,
        )

        TransProtDesktopApp._on_translation_ready(controller, region, translation)

        self.assertEqual(overlay.applied_regions, [])
        self.assertEqual(overlay.show_region_calls, 1)
        self.assertEqual(overlay.results, [("你好", False)])

    def test_translation_progress_updates_overlay_text(self) -> None:
        overlay = _FakeOverlay()
        controller = types.SimpleNamespace(
            _capture_overlay=overlay,
            _capture_overlay_hidden_by_user=False,
        )
        region = CaptureRegion(screen_name="Primary", x=100, y=120, width=420, height=180)

        TransProtDesktopApp._on_translation_progress(controller, region, "正在翻译")

        self.assertEqual(overlay.results, [("正在翻译", False)])

    def test_minimize_capture_region_to_tray_hides_overlay_without_notification(self) -> None:
        overlay = _FakeOverlay()
        tray = _FakeTray()
        controller = types.SimpleNamespace(
            _capture_overlay=overlay,
            _capture_overlay_hidden_by_user=False,
            _tray=tray,
        )
        controller.hide_capture_region = lambda: TransProtDesktopApp.hide_capture_region(controller)

        TransProtDesktopApp._minimize_capture_region_to_tray(controller)

        self.assertTrue(controller._capture_overlay_hidden_by_user)
        self.assertTrue(overlay.hidden)
        self.assertEqual(overlay.busy_states[-1], False)
        self.assertEqual(tray.messages, [])

    def test_clear_translation_result_resets_overlay_and_tooltip(self) -> None:
        overlay = _FakeOverlay()
        tray = _FakeTray()
        controller = types.SimpleNamespace(
            _capture_overlay=overlay,
            _tray=tray,
            _current_status="completed",
        )

        TransProtDesktopApp._clear_translation_result(controller)

        self.assertEqual(controller._current_status, "ready")
        self.assertTrue(overlay.cleared)
        self.assertEqual(overlay.busy_states[-1], False)
        self.assertEqual(overlay.statuses[-1], "ready")
        self.assertEqual(tray.tooltips[-1], "TransProt - 就绪")

    def test_save_settings_from_dialog_reloads_runtime_config_from_store(self) -> None:
        overlay = _FakeOverlay()
        tray = _FakeTray()
        saved_configs: list[AppConfig] = []
        reloaded_config = AppConfig(api_key="secure-key", api_key_saved=True, model="qwen-secure")
        dialog = types.SimpleNamespace(build_config=lambda: AppConfig(api_key="", api_key_saved=True, model="qwen-test"))
        controller = types.SimpleNamespace(
            _settings_dialog=dialog,
            _capture_overlay=overlay,
            _config_store=types.SimpleNamespace(
                save=lambda config: saved_configs.append(config),
                load=lambda: reloaded_config,
            ),
            _tray=tray,
            _config=None,
        )

        TransProtDesktopApp._save_settings_from_dialog(controller)

        self.assertEqual(saved_configs[0].capture_region, overlay.frame_region)
        self.assertIs(controller._config, reloaded_config)
        self.assertEqual(tray.messages[-1][1], "设置已保存。")

    def test_tray_click_shows_capture_region(self) -> None:
        calls: list[str] = []
        controller = types.SimpleNamespace(
            show_capture_region=lambda: calls.append("show"),
            _tray_reason_name=lambda reason: "trigger",
        )

        TransProtDesktopApp._on_tray_activated(controller, QSystemTrayIcon.Trigger)

        self.assertEqual(calls, ["show"])

    def test_tray_double_click_shows_capture_region(self) -> None:
        calls: list[str] = []
        controller = types.SimpleNamespace(
            show_capture_region=lambda: calls.append("show"),
            _tray_reason_name=lambda reason: "double_click",
        )

        TransProtDesktopApp._on_tray_activated(controller, QSystemTrayIcon.DoubleClick)

        self.assertEqual(calls, ["show"])

    def test_status_tooltip_uses_chinese_text_and_updates_overlay(self) -> None:
        tray = _FakeTray()
        overlay = _FakeOverlay()
        controller = types.SimpleNamespace(_tray=tray, _capture_overlay=overlay)

        TransProtDesktopApp._on_status_changed(controller, "translating")

        self.assertEqual(tray.tooltips[-1], "TransProt - 翻译中")
        self.assertEqual(overlay.statuses[-1], "translating")


if __name__ == "__main__":
    unittest.main()
