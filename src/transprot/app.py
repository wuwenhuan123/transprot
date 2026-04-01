from __future__ import annotations

import logging
import threading
import sys

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication, QDialog, QMenu, QStyle, QSystemTrayIcon

from transprot.core.config import AppConfigStore
from transprot.core.coordinator import CaptureCoordinator
from transprot.core.errors import HotkeyError
from transprot.core.logging_utils import configure_logging
from transprot.infra.hotkey import GlobalHotkeyManager
from transprot.infra.screenshot import ScreenshotService
from transprot.services.ocr import create_ocr_service
from transprot.services.translation import TranslatorRouter
from transprot.ui.selection_overlay import SelectionSession
from transprot.ui.settings_dialog import SettingsDialog
from transprot.ui.translation_overlay import TranslationOverlay

logger = logging.getLogger(__name__)


class TransProtDesktopApp(QObject):
    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self._app = app
        self._config_store = AppConfigStore()
        self._config = self._config_store.load()
        configure_logging(self._config.log_level)

        self._translator_router = TranslatorRouter()
        self._ocr_service = create_ocr_service()
        self._screenshot_service = ScreenshotService()
        self._coordinator = CaptureCoordinator(
            screenshot_service=self._screenshot_service,
            ocr_service=self._ocr_service,
            translator_router=self._translator_router,
            config_supplier=self._get_config,
        )
        self._coordinator.translation_ready.connect(self._on_translation_ready)
        self._coordinator.error_occurred.connect(self._on_error)
        self._coordinator.status_changed.connect(self._on_status_changed)

        self._hotkey_manager = GlobalHotkeyManager()
        self._hotkey_manager.activated.connect(self.start_capture)

        self._translation_overlay = TranslationOverlay(self._resolve_screen_rect)
        self._selection_session: SelectionSession | None = None
        self._settings_dialog: SettingsDialog | None = None

        self._tray = self._create_tray()
        self._register_hotkey(self._config.hotkey)
        self._coordinator.warmup_ocr()
        self._app.aboutToQuit.connect(self.shutdown)

    def start_capture(self) -> None:
        self._translation_overlay.hide_overlay()
        if self._selection_session is not None:
            return
        self._selection_session = SelectionSession(self._app.screens())
        self._selection_session.region_selected.connect(self._on_region_selected)
        self._selection_session.cancelled.connect(self._on_selection_cancelled)
        self._selection_session.start()

    def open_settings(self) -> None:
        dialog = SettingsDialog(self._config)
        dialog.test_connection_requested.connect(self._run_settings_test)
        self._settings_dialog = dialog
        if dialog.exec() == QDialog.Accepted:
            self._config = dialog.build_config()
            self._config_store.save(self._config)
            self._register_hotkey(self._config.hotkey)
            self._tray.showMessage("TransProt", "Settings saved.")
        self._settings_dialog = None

    def shutdown(self) -> None:
        self._hotkey_manager.unregister_hotkey()
        self._coordinator.shutdown()
        self._tray.hide()

    def _get_config(self):
        return self._config

    def _create_tray(self) -> QSystemTrayIcon:
        icon = self._app.style().standardIcon(QStyle.SP_ComputerIcon)
        tray = QSystemTrayIcon(icon, self._app)
        tray.setToolTip("TransProt")
        menu = QMenu()
        menu.addAction("Translate now", self.start_capture)
        menu.addAction("Settings", self.open_settings)
        menu.addSeparator()
        menu.addAction("Quit", self._app.quit)
        tray.setContextMenu(menu)
        tray.activated.connect(self._on_tray_activated)
        tray.show()
        return tray

    def _register_hotkey(self, hotkey: str) -> None:
        try:
            self._hotkey_manager.register_hotkey(hotkey)
        except HotkeyError as exc:
            logger.exception("Hotkey registration failed")
            self._tray.showMessage("TransProt", f"Hotkey registration failed: {exc}", QSystemTrayIcon.Warning)

    def _resolve_screen_rect(self, screen_name: str) -> tuple[int, int, int, int]:
        for screen in self._app.screens():
            if screen.name() == screen_name:
                geometry = screen.geometry()
                return geometry.x(), geometry.y(), geometry.width(), geometry.height()
        primary = self._app.primaryScreen()
        geometry = primary.geometry()
        return geometry.x(), geometry.y(), geometry.width(), geometry.height()

    def _on_region_selected(self, region) -> None:
        self._selection_session = None
        self._coordinator.handle_selection(region)

    def _on_selection_cancelled(self) -> None:
        self._selection_session = None

    def _on_translation_ready(self, region, translation) -> None:
        self._translation_overlay.show_translation(region, translation.translated_text)

    def _on_error(self, message: str) -> None:
        logger.warning(message)
        self._tray.showMessage("TransProt", message, QSystemTrayIcon.Warning)

    def _on_status_changed(self, status: str) -> None:
        self._tray.setToolTip(f"TransProt - {status}")

    def _run_settings_test(self, config) -> None:
        dialog = self._settings_dialog
        if dialog is None:
            return

        def worker() -> None:
            try:
                result = self._translator_router.smoke_test(config)
                preview = result.translated_text[:80]
                dialog.test_result_ready.emit(True, f"Connection succeeded: {preview}")
            except Exception as exc:
                dialog.test_result_ready.emit(False, f"Connection failed: {exc}")

        threading.Thread(target=worker, daemon=True).start()

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.DoubleClick:
            self.start_capture()


def launch_app() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("TransProt")
    app.setQuitOnLastWindowClosed(False)
    app.setProperty("transprot_controller", TransProtDesktopApp(app))
    return app.exec()
