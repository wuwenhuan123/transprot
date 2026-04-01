from __future__ import annotations

import tempfile
import time
from pathlib import Path

from PySide6.QtGui import QGuiApplication

from transprot.core.models import CaptureRegion, SelectionRegion
from transprot.infra.image_preprocess import preprocess_capture


class ScreenshotService:
    def __init__(self, temp_dir: Path | None = None) -> None:
        self._temp_dir = temp_dir or Path(tempfile.gettempdir()) / "transprot"
        self._temp_dir.mkdir(parents=True, exist_ok=True)

    def capture(self, region: CaptureRegion | SelectionRegion) -> Path:
        app = QGuiApplication.instance()
        if app is None:
            raise RuntimeError("QGuiApplication is not initialized.")

        screen = next((item for item in app.screens() if item.name() == region.screen_name), None)
        if screen is None:
            screen = app.primaryScreen()
        if screen is None:
            raise RuntimeError("No screen is available for capture.")

        screen_geometry = screen.geometry()
        relative_x = region.x - screen_geometry.x()
        relative_y = region.y - screen_geometry.y()
        pixmap = screen.grabWindow(0, relative_x, relative_y, region.width, region.height)
        if pixmap.isNull():
            raise RuntimeError("Failed to capture the selected screen region.")

        output_path = self._temp_dir / f"capture-{int(time.time() * 1000)}.png"
        if not pixmap.save(str(output_path), "PNG"):
            raise RuntimeError("Failed to save the captured image.")
        return preprocess_capture(output_path)
