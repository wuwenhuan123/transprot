from __future__ import annotations

import logging
import time
import sys

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtWidgets import QApplication, QMenu, QStyle, QSystemTrayIcon

from transprot.core.auto_mode import AutoTranslateState
from transprot.core.config import AppConfigStore
from transprot.core.layout import resolve_capture_region
from transprot.core.logging_utils import configure_logging
from transprot.core.models import AppConfig, CaptureRegion
from transprot.core.ocr_coordinator import OCRCoordinator
from transprot.core.text import normalize_source_compare_text
from transprot.infra.screenshot import ScreenshotService
from transprot.services.ocr import create_ocr_service
from transprot.services.translation import TranslatorRouter
from transprot.ui.capture_region_overlay import CaptureRegionOverlay
from transprot.ui.settings_dialog import SettingsDialog

logger = logging.getLogger(__name__)

_AUTO_POLL_INTERVAL_MS = 800
_AUTO_STABLE_DURATION_MS = 800
_STATUS_LABELS = {
    "idle": "就绪",
    "capturing": "截图中",
    "recognizing": "识别中",
    "translating": "翻译中",
    "completed": "已完成",
    "error": "出错",
}


class TransProtDesktopApp(QObject):
    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        self._app = app
        self._config_store = AppConfigStore()
        self._config = self._load_runtime_config()
        self._log_path = configure_logging(self._config.log_level)
        logger.info("Application initialized. log_path=%s", self._log_path)

        self._ocr_service = create_ocr_service()
        self._translator_router = TranslatorRouter()
        self._screenshot_service = ScreenshotService()
        self._coordinator = OCRCoordinator(
            screenshot_service=self._screenshot_service,
            ocr_service=self._ocr_service,
            translator_router=self._translator_router,
            config_supplier=self._load_runtime_config,
        )
        self._coordinator.capture_started.connect(self._on_capture_started)
        self._coordinator.recognition_started.connect(self._on_recognition_started)
        self._coordinator.translation_started.connect(self._on_translation_started)
        self._coordinator.ocr_ready.connect(self._on_ocr_ready)
        self._coordinator.translation_ready.connect(self._on_translation_ready)
        self._coordinator.translation_skipped.connect(self._on_translation_skipped)
        self._coordinator.error_occurred.connect(self._on_error)
        self._coordinator.status_changed.connect(self._on_status_changed)
        self._coordinator.session_finished.connect(self._on_capture_finished)

        self._settings_dialog: SettingsDialog | None = None
        self._capture_overlay_hidden_by_user = False
        self._capture_overlay_interacting = False
        self._busy = False
        self._current_trigger = "manual"
        self._last_status = "idle"
        self._auto_state = AutoTranslateState(_AUTO_STABLE_DURATION_MS)
        self._auto_probe_timer = QTimer(self)
        self._auto_probe_timer.setInterval(_AUTO_POLL_INTERVAL_MS)
        self._auto_probe_timer.timeout.connect(self._on_auto_probe_timeout)

        self._tray = self._create_tray()

        initial_region = self._resolve_capture_region()
        logger.info("Initial capture region resolved: %s", initial_region)
        self._capture_overlay = CaptureRegionOverlay(initial_region)
        self._capture_overlay.recognize_requested.connect(self.start_capture)
        self._capture_overlay.region_committed.connect(self._on_region_committed)
        self._capture_overlay.interaction_started.connect(self._on_overlay_interaction_started)
        self._capture_overlay.interaction_finished.connect(self._on_overlay_interaction_finished)
        self._capture_overlay.clear_requested.connect(self.clear_translation_result)
        self._capture_overlay.show_region()

        logger.info("Scheduling background OCR warmup")
        QTimer.singleShot(0, self._coordinator.warmup_ocr)
        self._app.aboutToQuit.connect(self.shutdown)
        self._update_auto_mode_state(force_reset=True, retain_success_source_text=False)
        self._refresh_tray_tooltip()

    def start_capture(self, region: CaptureRegion | None = None, trigger: str = "manual") -> None:
        if self._busy:
            logger.info("Capture request ignored because pipeline is busy. trigger=%s", trigger)
            return

        target_region = region or self._capture_overlay.current_region()
        logger.info("Starting translation pipeline. trigger=%s region=%s", trigger, target_region)
        self._busy = True
        self._current_trigger = trigger
        self._capture_overlay_hidden_by_user = False
        self._capture_overlay.clear_result()
        self._capture_overlay.set_busy(True)
        previous_source_text = (
            self._auto_state.last_success_source_text if trigger == "auto" else None
        )
        self._coordinator.recognize_region(
            target_region,
            trigger=trigger,
            previous_source_text=previous_source_text,
        )

    def open_settings(self) -> None:
        logger.info("Open settings requested")
        self._config = self._load_runtime_config()
        dialog = self._ensure_settings_dialog()
        dialog.apply_config(self._config)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        dialog.setFocus(Qt.ActiveWindowFocusReason)
        logger.info("Settings dialog shown. visible=%s", dialog.isVisible())

    def show_capture_region(self) -> None:
        logger.info("Show capture region requested")
        self._capture_overlay_hidden_by_user = False
        region = self._resolve_capture_region(self._capture_overlay.current_region())
        logger.info("Resolved capture region for show: %s", region)
        self._capture_overlay.apply_region(region)
        self._capture_overlay.clear_result()
        self._capture_overlay.set_busy(False)
        self._on_region_committed(region)
        self._capture_overlay.show_region()
        self._update_auto_mode_state(force_reset=True, retain_success_source_text=False)
        logger.info(
            "Capture overlay shown. visible=%s geometry=%s",
            self._capture_overlay.isVisible(),
            self._capture_overlay.geometry().getRect(),
        )

    def hide_capture_region(self) -> None:
        logger.info("Hide capture region requested")
        self._capture_overlay_hidden_by_user = True
        self._capture_overlay.hide()
        self._capture_overlay.set_busy(False)
        self._update_auto_mode_state(force_reset=True, retain_success_source_text=False)
        logger.info("Capture overlay hidden by user")

    def clear_translation_result(self) -> None:
        logger.info("Clearing translation result by user request")
        self._capture_overlay.clear_result()
        self._last_status = "idle"
        self._refresh_tray_tooltip()
        if self._config.auto_mode_enabled:
            fingerprint = self._probe_current_fingerprint()
            self._auto_state.suppress_current_fingerprint(fingerprint)

    def shutdown(self) -> None:
        logger.info("Application shutting down")
        self._auto_probe_timer.stop()
        self._coordinator.shutdown()
        self._tray.hide()

    def _create_tray(self) -> QSystemTrayIcon:
        icon = self._app.style().standardIcon(QStyle.SP_ComputerIcon)
        tray = QSystemTrayIcon(icon, self._app)
        tray.setToolTip("TransProt")
        menu = QMenu()
        menu.addAction("显示翻译区域", self._schedule_show_capture_region)
        menu.addAction("隐藏翻译区域", self._schedule_hide_capture_region)
        menu.addAction("设置", self._schedule_open_settings)
        menu.addSeparator()
        menu.addAction("退出", self._app.quit)
        tray.setContextMenu(menu)
        tray.activated.connect(self._on_tray_activated)
        tray.show()
        logger.info("System tray created and shown")
        return tray

    def _load_runtime_config(self) -> AppConfig:
        try:
            return self._config_store.load()
        except Exception:
            logger.exception("Failed to load config file, falling back to in-memory config")
            return getattr(self, "_config", AppConfig())

    def _resolve_capture_region(self, preferred_region: CaptureRegion | None = None) -> CaptureRegion:
        screens = []
        for screen in self._app.screens():
            geometry = screen.geometry()
            screens.append((screen.name(), (geometry.x(), geometry.y(), geometry.width(), geometry.height())))
        primary = self._app.primaryScreen() or (self._app.screens()[0] if self._app.screens() else None)
        if primary is None:
            raise RuntimeError("当前没有可用的屏幕。")
        saved_region = preferred_region or self._config.capture_region
        resolved = resolve_capture_region(saved_region, screens, primary.name())
        logger.info("Capture region resolved. preferred=%s resolved=%s", saved_region, resolved)
        return resolved

    def _on_region_committed(self, region: CaptureRegion) -> None:
        logger.info("Capture region committed: %s", region)
        if self._config.capture_region == region:
            return
        self._config.capture_region = region
        self._config_store.save(self._config)

    def _on_capture_started(self, region: CaptureRegion) -> None:
        logger.info("Capture started. region=%s", region)
        self._on_region_committed(region)
        self._capture_overlay.hide()

    def _on_recognition_started(self, region: CaptureRegion) -> None:
        logger.info("Recognition started. region=%s", region)
        if self._capture_overlay_hidden_by_user:
            return
        self._capture_overlay.apply_region(region)
        self._capture_overlay.show_region()

    def _on_translation_started(self, region: CaptureRegion, ocr_result) -> None:
        logger.info("Translation started. region=%s text_length=%s", region, len(ocr_result.full_text))

    def _on_ocr_ready(self, region: CaptureRegion, ocr_result) -> None:
        logger.info("OCR ready. region=%s text_length=%s", region, len(ocr_result.full_text))

    def _on_translation_ready(self, region: CaptureRegion, translation) -> None:
        logger.info("Translation ready. region=%s text_length=%s", region, len(translation.translated_text))
        self._capture_overlay.apply_region(region)
        self._capture_overlay.show_region()
        self._capture_overlay.show_result(translation.translated_text)
        self._auto_state.mark_success_source_text(
            normalize_source_compare_text(translation.source_text)
        )

    def _on_translation_skipped(self, region: CaptureRegion, ocr_result, reason: str) -> None:
        logger.info(
            "Translation skipped. region=%s reason=%s text_length=%s",
            region,
            reason,
            len(ocr_result.full_text),
        )

    def _on_error(self, message: str) -> None:
        logger.warning("Application error: %s", message)
        if not self._capture_overlay_hidden_by_user:
            self._capture_overlay.show_region()
            self._capture_overlay.show_result(message, is_error=True)
        self._tray.showMessage("TransProt", message, QSystemTrayIcon.Warning)

    def _on_capture_finished(self) -> None:
        logger.info("Capture finished")
        self._busy = False
        self._capture_overlay.set_busy(False)
        if not self._capture_overlay.isVisible() and not self._capture_overlay_hidden_by_user:
            self._capture_overlay.show_region()
        if self._config.auto_mode_enabled:
            self._auto_state.mark_attempt_finished(self._probe_current_fingerprint())
            self._update_auto_mode_state(force_reset=False, retain_success_source_text=True)
        self._current_trigger = "manual"
        if self._last_status == "completed":
            self._last_status = "idle"
        self._refresh_tray_tooltip()

    def _on_status_changed(self, status: str) -> None:
        logger.info("Status changed: %s", status)
        self._last_status = status
        self._refresh_tray_tooltip()

    def _on_overlay_interaction_started(self) -> None:
        logger.info("Overlay interaction started")
        self._capture_overlay_interacting = True
        if self._config.auto_mode_enabled:
            self._auto_state.reset(retain_success_source_text=True)

    def _on_overlay_interaction_finished(self, region: CaptureRegion) -> None:
        logger.info("Overlay interaction finished. region=%s", region)
        self._capture_overlay_interacting = False
        self._update_auto_mode_state(force_reset=True, retain_success_source_text=False)

    def _on_auto_probe_timeout(self) -> None:
        if (
            not self._config.auto_mode_enabled
            or self._busy
            or self._capture_overlay_hidden_by_user
            or self._capture_overlay_interacting
            or not self._capture_overlay.isVisible()
        ):
            return

        region = self._capture_overlay.current_region()
        try:
            fingerprint = self._screenshot_service.probe_fingerprint(region)
        except Exception:
            logger.exception("Auto mode fingerprint probe failed")
            return

        now_ms = int(time.monotonic() * 1000)
        if self._auto_state.observe(fingerprint, now_ms):
            logger.info("Auto mode detected stable frame change. region=%s fingerprint=%s", region, fingerprint)
            self.start_capture(region, trigger="auto")

    def _update_auto_mode_state(
        self,
        force_reset: bool,
        retain_success_source_text: bool,
    ) -> None:
        if force_reset:
            self._auto_state.reset(retain_success_source_text=retain_success_source_text)

        should_run = (
            self._config.auto_mode_enabled
            and not self._capture_overlay_hidden_by_user
            and self._capture_overlay.isVisible()
        )
        if should_run:
            if not self._auto_probe_timer.isActive():
                self._auto_probe_timer.start()
        else:
            self._auto_probe_timer.stop()
        self._refresh_tray_tooltip()

    def _probe_current_fingerprint(self) -> str | None:
        if self._capture_overlay_hidden_by_user or not self._capture_overlay.isVisible():
            return None
        try:
            return self._screenshot_service.probe_fingerprint(self._capture_overlay.current_region())
        except Exception:
            logger.exception("Failed to probe current fingerprint")
            return None

    def _refresh_tray_tooltip(self) -> None:
        if self._busy:
            label = _STATUS_LABELS.get(self._last_status, self._last_status)
            self._tray.setToolTip(f"TransProt - {label}")
            return
        if self._config.auto_mode_enabled:
            self._tray.setToolTip("TransProt - 自动模式已开启")
            return
        self._tray.setToolTip("TransProt - 就绪")

    def _on_tray_activated(self, reason) -> None:
        logger.info("Tray activated. reason=%s", self._tray_reason_name(reason))
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self._schedule_open_settings()

    def _schedule_show_capture_region(self) -> None:
        logger.info("Scheduling capture overlay show")
        QTimer.singleShot(150, self.show_capture_region)

    def _schedule_hide_capture_region(self) -> None:
        logger.info("Scheduling capture overlay hide")
        QTimer.singleShot(150, self.hide_capture_region)

    def _schedule_open_settings(self) -> None:
        logger.info("Scheduling settings dialog show")
        QTimer.singleShot(150, self.open_settings)

    def _ensure_settings_dialog(self) -> SettingsDialog:
        if self._settings_dialog is not None:
            return self._settings_dialog

        dialog = SettingsDialog(self._config, parent=self._capture_overlay)
        dialog.setModal(False)
        dialog.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        dialog.accepted.connect(self._save_settings_from_dialog)
        dialog.finished.connect(self._on_settings_dialog_finished)
        self._settings_dialog = dialog
        logger.info("Settings dialog created")
        return dialog

    def _save_settings_from_dialog(self) -> None:
        dialog = self._settings_dialog
        if dialog is None:
            return
        self._config = dialog.build_config()
        self._config.capture_region = self._capture_overlay.current_region()
        self._config_store.save(self._config)
        logger.info("Settings saved")
        self._update_auto_mode_state(force_reset=True, retain_success_source_text=False)
        self._tray.showMessage("TransProt", "设置已保存。")

    def _on_settings_dialog_finished(self, result: int) -> None:
        logger.info("Settings dialog finished. result=%s", result)
        if self._settings_dialog is not None:
            self._settings_dialog.deleteLater()
            self._settings_dialog = None

    @staticmethod
    def _tray_reason_name(reason) -> str:
        mapping = {
            QSystemTrayIcon.Unknown: "unknown",
            QSystemTrayIcon.Context: "context",
            QSystemTrayIcon.DoubleClick: "double_click",
            QSystemTrayIcon.Trigger: "trigger",
            QSystemTrayIcon.MiddleClick: "middle_click",
        }
        return mapping.get(reason, str(int(reason)))


def launch_app() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("TransProt")
    app.setQuitOnLastWindowClosed(False)
    controller = TransProtDesktopApp(app)
    app.setProperty("transprot_controller", controller)
    app._transprot_controller = controller
    return app.exec()
