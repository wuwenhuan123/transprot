from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QMenu, QStyle, QSystemTrayIcon

from transprot.core.config import AppConfigStore
from transprot.core.layout import resolve_capture_region
from transprot.core.logging_utils import configure_logging
from transprot.core.models import AppConfig, CaptureRegion
from transprot.core.ocr_coordinator import OCRCoordinator
from transprot.infra.screenshot import ScreenshotService
from transprot.services.ocr import create_ocr_service
from transprot.services.translation import TranslatorRouter
from transprot.ui.capture_region_overlay import CaptureRegionOverlay
from transprot.ui.settings_dialog import SettingsDialog

logger = logging.getLogger(__name__)

_APP_NAME = "TransProt"
_TRAY_TITLE = "TransProt \u7ffb\u8bd1"
_TOOLTIP_TEMPLATE = _TRAY_TITLE + " - {status}"
_SHOW_REGION_TEXT = "\u663e\u793a\u7ffb\u8bd1\u6846"
_HIDE_REGION_TEXT = "\u9690\u85cf\u7ffb\u8bd1\u6846"
_SETTINGS_TEXT = "\u8bbe\u7f6e"
_QUIT_TEXT = "\u9000\u51fa"
_SETTINGS_SAVED_TEXT = "\u8bbe\u7f6e\u5df2\u4fdd\u5b58\u3002"
_NO_SCREEN_ERROR = "\u5f53\u524d\u6ca1\u6709\u53ef\u7528\u7684\u5c4f\u5e55\u3002"
_STATUS_LABELS = {
    "idle": "\u5f85\u547d",
    "capturing": "\u622a\u56fe\u4e2d",
    "recognizing": "\u8bc6\u522b\u4e2d",
    "translating": "\u7ffb\u8bd1\u4e2d",
    "completed": "\u5df2\u5b8c\u6210",
    "error": "\u51fa\u9519",
}


class TransProtDesktopApp(QObject):
    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        self._app = app
        self._config_store = AppConfigStore()
        self._config = self._config_store.load()
        self._log_path = configure_logging(self._config.log_level)
        logger.info(
            "Application initialized. log_path=%s config_path=%s has_api_key=%s",
            self._log_path,
            self._config_store.config_path,
            bool(self._config.api_key),
        )

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
        self._coordinator.translation_streamed.connect(self._on_translation_streamed)
        self._coordinator.translation_ready.connect(self._on_translation_ready)
        self._coordinator.error_occurred.connect(self._on_error)
        self._coordinator.status_changed.connect(self._on_status_changed)
        self._coordinator.session_finished.connect(self._on_capture_finished)

        self._settings_dialog: SettingsDialog | None = None
        self._capture_overlay_hidden_by_user = False
        self._shortcuts_suspended = False
        self._translate_shortcut: QShortcut | None = None
        self._clear_shortcut: QShortcut | None = None
        self._tray = self._create_tray()

        initial_region = self._resolve_capture_region()
        logger.info("Initial capture region resolved: %s", initial_region)
        self._capture_overlay = CaptureRegionOverlay(initial_region)
        self._capture_overlay.recognize_requested.connect(self.start_capture)
        self._capture_overlay.region_committed.connect(self._on_region_committed)
        self._capture_overlay.clear_requested.connect(self._clear_translation_result)
        self._capture_overlay.hide_requested.connect(self._schedule_hide_capture_region)
        self._capture_overlay.settings_requested.connect(self._schedule_open_settings)
        self._capture_overlay.show_region()
        self._configure_action_shortcuts()

        logger.info("Scheduling background OCR warmup")
        QTimer.singleShot(0, self._coordinator.warmup_ocr)
        self._app.aboutToQuit.connect(self.shutdown)

    def start_capture(self, region: CaptureRegion | None = None) -> None:
        target_region = region or self._capture_overlay.current_region()
        logger.info("Starting translation capture for region: %s", target_region)
        self._capture_overlay_hidden_by_user = False
        self._capture_overlay.clear_result()
        self._capture_overlay.set_busy(True)
        self._coordinator.recognize_region(target_region)

    def open_settings(self) -> None:
        logger.info("Open settings requested")
        self._config = self._config_store.load()
        self._set_action_shortcuts_suspended(True)
        logger.info(
            "Runtime config loaded from file. provider=%s model=%s timeout_sec=%s has_api_key=%s",
            self._config.translation_provider.value,
            self._config.model,
            self._config.timeout_sec,
            bool(self._config.api_key),
        )
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
        tray.setToolTip(_tooltip_text("idle"))

        menu = QMenu()
        menu.addAction(_SHOW_REGION_TEXT, self._schedule_show_capture_region)
        menu.addAction(_HIDE_REGION_TEXT, self._schedule_hide_capture_region)
        menu.addAction(_SETTINGS_TEXT, self._schedule_open_settings)
        menu.addSeparator()
        menu.addAction(_QUIT_TEXT, self._app.quit)

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
            raise RuntimeError(_NO_SCREEN_ERROR)

        saved_region = preferred_region or self._config.capture_region
        resolved = resolve_capture_region(saved_region, screens, primary.name())
        logger.info("Capture region resolved. preferred=%s resolved=%s", saved_region, resolved)
        return resolved

    def _load_runtime_config(self) -> AppConfig:
        self._config = self._config_store.load()
        if self._config.capture_region is None:
            self._config.capture_region = self._capture_overlay.current_region()
        logger.info(
            "Runtime config loaded from file. provider=%s model=%s timeout_sec=%s has_api_key=%s",
            self._config.translation_provider.value,
            self._config.model,
            self._config.timeout_sec,
            bool(self._config.api_key),
        )
        return self._config

    def _configure_action_shortcuts(self) -> None:
        self._translate_shortcut = self._upsert_shortcut(
            self._translate_shortcut,
            self._config.hotkey,
            self._activate_translate_shortcut,
        )
        self._clear_shortcut = self._upsert_shortcut(
            self._clear_shortcut,
            self._config.clear_hotkey,
            self._activate_clear_shortcut,
        )
        self._apply_shortcut_enabled_state()
        logger.info(
            "Action shortcuts configured. translate=%s clear=%s",
            self._config.hotkey,
            self._config.clear_hotkey,
        )

    def _upsert_shortcut(self, shortcut: QShortcut | None, sequence_text: str, handler) -> QShortcut:
        sequence = QKeySequence(sequence_text)
        if shortcut is None:
            shortcut = QShortcut(sequence, self._capture_overlay)
            shortcut.setContext(Qt.ApplicationShortcut)
            shortcut.activated.connect(handler)
        else:
            shortcut.setKey(sequence)
        return shortcut

    def _set_action_shortcuts_suspended(self, suspended: bool) -> None:
        self._shortcuts_suspended = suspended
        self._apply_shortcut_enabled_state()

    def _apply_shortcut_enabled_state(self) -> None:
        if self._translate_shortcut is not None:
            self._translate_shortcut.setEnabled(
                (not self._shortcuts_suspended)
                and bool(self._translate_shortcut.key().toString(QKeySequence.PortableText).strip())
            )
        if self._clear_shortcut is not None:
            self._clear_shortcut.setEnabled(
                (not self._shortcuts_suspended)
                and bool(self._clear_shortcut.key().toString(QKeySequence.PortableText).strip())
            )

    def _activate_translate_shortcut(self) -> None:
        logger.info("Translate shortcut activated")
        if self._settings_dialog is not None and self._settings_dialog.isVisible():
            return
        if self._capture_overlay.is_busy():
            return
        if self._capture_overlay_hidden_by_user or not self._capture_overlay.isVisible():
            self.show_capture_region()
        self.start_capture()

    def _activate_clear_shortcut(self) -> None:
        logger.info("Clear shortcut activated")
        if self._settings_dialog is not None and self._settings_dialog.isVisible():
            return
        if self._capture_overlay.is_busy() or not self._capture_overlay.has_result_text():
            return
        self._clear_translation_result()

    def _on_region_committed(self, region: CaptureRegion) -> None:
        logger.info("Capture region committed: %s", region)
        if self._config.capture_region == region:
            return
        self._config.capture_region = region
        self._config_store.save(self._config)

    def _on_capture_started(self, region: CaptureRegion) -> None:
        logger.info("Capture started. region=%s", region)
        self._on_region_committed(region)
        if not self._capture_overlay_hidden_by_user:
            self._capture_overlay.show_region()

    def _on_recognition_started(self, region: CaptureRegion) -> None:
        logger.info("Recognition started. region=%s", region)
        if self._capture_overlay_hidden_by_user:
            return
        self._capture_overlay.show_region()

    def _on_translation_streamed(self, region: CaptureRegion, ocr_result, partial_text: str) -> None:
        logger.info("Translation streamed. region=%s partial_length=%s", region, len(partial_text))
        if self._capture_overlay_hidden_by_user or not partial_text:
            return
        self._capture_overlay.show_region()
        self._capture_overlay.show_result(partial_text, streaming=True)

    def _on_translation_ready(self, region: CaptureRegion, ocr_result, translation_result) -> None:
        logger.info(
            "Translation ready. region=%s ocr_length=%s translated_length=%s",
            region,
            len(ocr_result.full_text),
            len(translation_result.translated_text),
        )
        if self._capture_overlay_hidden_by_user:
            return
        self._capture_overlay.show_region()
        self._capture_overlay.show_result(translation_result.translated_text)

    def _on_error(self, message: str) -> None:
        logger.warning("Application error: %s", message)
        if not self._capture_overlay_hidden_by_user:
            self._capture_overlay.show_region()
            self._capture_overlay.show_result(message, is_error=True)
        self._tray.showMessage(_TRAY_TITLE, message, QSystemTrayIcon.Warning)

    def _on_capture_finished(self) -> None:
        logger.info("Capture finished")
        self._capture_overlay.set_busy(False)
        if not self._capture_overlay.isVisible() and not self._capture_overlay_hidden_by_user:
            self._capture_overlay.show_region()

    def _on_status_changed(self, status: str) -> None:
        logger.info("Status changed: %s", status)
        self._tray.setToolTip(_tooltip_text(status))

    def _on_tray_activated(self, reason) -> None:
        logger.info("Tray activated. reason=%s", self._tray_reason_name(reason))
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self._schedule_show_capture_region()

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

        existing_config = self._config_store.load()
        new_config = dialog.build_config()
        if not new_config.api_key and existing_config.api_key:
            new_config.api_key = existing_config.api_key
            logger.info("Preserved existing API key because the settings input was blank")

        self._config = new_config
        self._config.capture_region = self._capture_overlay.current_region()
        self._config_store.save(self._config)
        self._configure_action_shortcuts()
        logger.info(
            "Settings saved. config_path=%s has_api_key=%s",
            self._config_store.config_path,
            bool(self._config.api_key),
        )
        self._tray.showMessage(_TRAY_TITLE, _SETTINGS_SAVED_TEXT)

    def _on_settings_dialog_finished(self, result: int) -> None:
        logger.info("Settings dialog finished. result=%s", result)
        self._set_action_shortcuts_suspended(False)
        if self._settings_dialog is not None:
            self._settings_dialog.deleteLater()
            self._settings_dialog = None

    def _clear_translation_result(self) -> None:
        logger.info("Clear translation result requested")
        self._capture_overlay.reset_to_idle()
        self._tray.setToolTip(_tooltip_text("idle"))

    @staticmethod
    def _tray_reason_name(reason) -> str:
        mapping = {
            QSystemTrayIcon.Unknown: "unknown",
            QSystemTrayIcon.Context: "context",
            QSystemTrayIcon.DoubleClick: "double_click",
            QSystemTrayIcon.Trigger: "trigger",
            QSystemTrayIcon.MiddleClick: "middle_click",
        }
        if reason in mapping:
            return mapping[reason]
        value = getattr(reason, "value", None)
        if isinstance(value, int):
            return str(value)
        try:
            return str(int(reason))
        except (TypeError, ValueError):
            return str(reason)


def _tooltip_text(status: str) -> str:
    return _TOOLTIP_TEMPLATE.format(status=_STATUS_LABELS.get(status, status))


def launch_app() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(_APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    controller = TransProtDesktopApp(app)
    app.setProperty("transprot_controller", controller)
    app._transprot_controller = controller
    return app.exec()
