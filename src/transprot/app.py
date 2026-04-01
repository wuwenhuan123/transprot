from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtWidgets import QApplication, QMenu, QStyle, QSystemTrayIcon

from transprot.core.config import AppConfigStore
from transprot.core.layout import resolve_capture_region
from transprot.core.logging_utils import configure_logging
from transprot.core.models import CaptureRegion
from transprot.core.ocr_coordinator import OCRCoordinator
from transprot.infra.screenshot import ScreenshotService
from transprot.services.ocr import create_ocr_service
from transprot.ui.capture_region_overlay import CaptureRegionOverlay
from transprot.ui.settings_dialog import SettingsDialog

logger = logging.getLogger(__name__)


class TransProtDesktopApp(QObject):
    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        self._app = app
        self._config_store = AppConfigStore()
        self._config = self._config_store.load()
        self._log_path = configure_logging(self._config.log_level)
        logger.info("Application initialized. log_path=%s", self._log_path)

        self._ocr_service = create_ocr_service()
        self._screenshot_service = ScreenshotService()
        self._coordinator = OCRCoordinator(
            screenshot_service=self._screenshot_service,
            ocr_service=self._ocr_service,
        )
        self._coordinator.capture_started.connect(self._on_capture_started)
        self._coordinator.recognition_started.connect(self._on_recognition_started)
        self._coordinator.ocr_ready.connect(self._on_ocr_ready)
        self._coordinator.error_occurred.connect(self._on_error)
        self._coordinator.status_changed.connect(self._on_status_changed)
        self._coordinator.session_finished.connect(self._on_capture_finished)

        self._settings_dialog: SettingsDialog | None = None
        self._capture_overlay_hidden_by_user = False
        self._tray = self._create_tray()

        initial_region = self._resolve_capture_region()
        logger.info("Initial capture region resolved: %s", initial_region)
        self._capture_overlay = CaptureRegionOverlay(initial_region)
        self._capture_overlay.recognize_requested.connect(self.start_capture)
        self._capture_overlay.region_committed.connect(self._on_region_committed)
        self._capture_overlay.show_region()

        logger.info("Scheduling background OCR warmup")
        QTimer.singleShot(0, self._coordinator.warmup_ocr)
        self._app.aboutToQuit.connect(self.shutdown)

    def start_capture(self, region: CaptureRegion | None = None) -> None:
        target_region = region or self._capture_overlay.current_region()
        logger.info("Starting OCR capture for region: %s", target_region)
        self._capture_overlay_hidden_by_user = False
        self._capture_overlay.clear_result()
        self._capture_overlay.set_busy(True)
        self._coordinator.recognize_region(target_region)

    def open_settings(self) -> None:
        logger.info("Open settings requested")
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
        logger.info("Capture overlay hidden by user")

    def shutdown(self) -> None:
        logger.info("Application shutting down")
        self._coordinator.shutdown()
        self._tray.hide()

    def _create_tray(self) -> QSystemTrayIcon:
        icon = self._app.style().standardIcon(QStyle.SP_ComputerIcon)
        tray = QSystemTrayIcon(icon, self._app)
        tray.setToolTip("TransProt OCR")
        menu = QMenu()
        menu.addAction("显示框选区域", self._schedule_show_capture_region)
        menu.addAction("隐藏框选区域", self._schedule_hide_capture_region)
        menu.addAction("设置", self._schedule_open_settings)
        menu.addSeparator()
        menu.addAction("退出", self._app.quit)
        tray.setContextMenu(menu)
        tray.activated.connect(self._on_tray_activated)
        tray.show()
        logger.info("System tray created and shown")
        return tray

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

    def _on_ocr_ready(self, region: CaptureRegion, ocr_result) -> None:
        logger.info("OCR ready. region=%s text_length=%s", region, len(ocr_result.full_text))
        self._capture_overlay.apply_region(region)
        self._capture_overlay.show_region()
        self._capture_overlay.show_result(ocr_result.full_text)

    def _on_error(self, message: str) -> None:
        logger.warning("Application error: %s", message)
        if not self._capture_overlay_hidden_by_user:
            self._capture_overlay.show_region()
            self._capture_overlay.show_result(message, is_error=True)
        self._tray.showMessage("TransProt OCR", message, QSystemTrayIcon.Warning)

    def _on_capture_finished(self) -> None:
        logger.info("Capture finished")
        self._capture_overlay.set_busy(False)
        if not self._capture_overlay.isVisible() and not self._capture_overlay_hidden_by_user:
            self._capture_overlay.show_region()

    def _on_status_changed(self, status: str) -> None:
        logger.info("Status changed: %s", status)
        self._tray.setToolTip(f"TransProt OCR - {status}")

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
        self._tray.showMessage("TransProt OCR", "设置已保存。")

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
