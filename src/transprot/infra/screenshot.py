from __future__ import annotations

import json
import logging
import shutil
import tempfile
import time
from pathlib import Path

from PySide6.QtGui import QGuiApplication

from transprot.core.config import resolve_debug_capture_dir
from transprot.core.models import CaptureRegion, OCRResult, SelectionRegion
from transprot.services.ocr import ocr_result_to_payload
from transprot.infra.image_preprocess import preprocess_capture

logger = logging.getLogger(__name__)


class ScreenshotService:
    def __init__(
        self,
        temp_dir: Path | None = None,
        debug_dir: Path | None = None,
        debug_enabled: bool = True,
    ) -> None:
        self._temp_dir = temp_dir or Path(tempfile.gettempdir()) / "transprot"
        self._temp_dir.mkdir(parents=True, exist_ok=True)
        self._debug_enabled = debug_enabled
        self._debug_dir = debug_dir or resolve_debug_capture_dir()
        if self._debug_enabled:
            self._debug_dir.mkdir(parents=True, exist_ok=True)

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

        timestamp = int(time.time() * 1000)
        output_path = self._temp_dir / f"capture-{timestamp}.png"
        if not pixmap.save(str(output_path), "PNG"):
            raise RuntimeError("Failed to save the captured image.")

        processed_path = preprocess_capture(output_path)
        self._write_debug_artifacts(
            capture_id=f"capture-{timestamp}",
            raw_path=output_path,
            processed_path=processed_path,
            region=region,
            screen_geometry=screen_geometry,
            screen_device_pixel_ratio=float(screen.devicePixelRatio()),
            pixmap_device_pixel_ratio=float(pixmap.devicePixelRatio()),
            pixmap_size=(int(pixmap.width()), int(pixmap.height())),
            relative_x=relative_x,
            relative_y=relative_y,
        )
        return processed_path

    def export_ocr_debug_artifacts(self, image_path: Path, ocr_result: OCRResult) -> None:
        if not self._debug_enabled:
            return

        capture_id = self._capture_id_from_path(image_path)
        if not capture_id:
            logger.warning("Unable to resolve capture id for OCR debug export. image_path=%s", image_path)
            return

        bundle_dir, latest_dir = self._ensure_debug_dirs(capture_id)
        ocr_text_path = bundle_dir / "ocr.txt"
        ocr_json_path = bundle_dir / "ocr.json"

        ocr_text_path.write_text(ocr_result.full_text, encoding="utf-8")
        ocr_json_path.write_text(
            json.dumps(ocr_result_to_payload(ocr_result), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        shutil.copyfile(ocr_text_path, latest_dir / "ocr.txt")
        shutil.copyfile(ocr_json_path, latest_dir / "ocr.json")
        self._update_metadata_paths(bundle_dir / "metadata.json", ocr_text_path, ocr_json_path)
        self._update_metadata_paths(latest_dir / "metadata.json", latest_dir / "ocr.txt", latest_dir / "ocr.json")

        logger.info(
            "Debug OCR exported. capture_id=%s ocr_text=%s ocr_json=%s",
            capture_id,
            ocr_text_path,
            ocr_json_path,
        )

    def _write_debug_artifacts(
        self,
        *,
        capture_id: str,
        raw_path: Path,
        processed_path: Path,
        region: CaptureRegion | SelectionRegion,
        screen_geometry,
        screen_device_pixel_ratio: float,
        pixmap_device_pixel_ratio: float,
        pixmap_size: tuple[int, int],
        relative_x: int,
        relative_y: int,
    ) -> None:
        if not self._debug_enabled:
            return

        bundle_dir, latest_dir = self._ensure_debug_dirs(capture_id)

        raw_debug_path = bundle_dir / "raw.png"
        processed_debug_path = bundle_dir / "processed.png"
        metadata_path = bundle_dir / "metadata.json"

        shutil.copyfile(raw_path, raw_debug_path)
        if processed_path.exists():
            shutil.copyfile(processed_path, processed_debug_path)
        else:
            shutil.copyfile(raw_path, processed_debug_path)

        metadata = {
            "capture_id": capture_id,
            "capture_region": {
                "screen_name": region.screen_name,
                "x": int(region.x),
                "y": int(region.y),
                "width": int(region.width),
                "height": int(region.height),
            },
            "screen_geometry": {
                "x": int(screen_geometry.x()),
                "y": int(screen_geometry.y()),
                "width": int(screen_geometry.width()),
                "height": int(screen_geometry.height()),
            },
            "screen_device_pixel_ratio": screen_device_pixel_ratio,
            "pixmap_device_pixel_ratio": pixmap_device_pixel_ratio,
            "pixmap_size": {
                "width": pixmap_size[0],
                "height": pixmap_size[1],
            },
            "relative_capture_origin": {
                "x": relative_x,
                "y": relative_y,
            },
            "raw_path": str(raw_debug_path),
            "processed_path": str(processed_debug_path),
        }
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

        shutil.copyfile(raw_debug_path, latest_dir / "raw.png")
        shutil.copyfile(processed_debug_path, latest_dir / "processed.png")
        shutil.copyfile(metadata_path, latest_dir / "metadata.json")

        logger.info(
            "Debug capture exported. capture_id=%s bundle_dir=%s raw=%s processed=%s metadata=%s",
            capture_id,
            bundle_dir,
            raw_debug_path,
            processed_debug_path,
            metadata_path,
        )

    def _ensure_debug_dirs(self, capture_id: str) -> tuple[Path, Path]:
        bundle_dir = self._debug_dir / capture_id
        latest_dir = self._debug_dir / "latest"
        bundle_dir.mkdir(parents=True, exist_ok=True)
        latest_dir.mkdir(parents=True, exist_ok=True)
        return bundle_dir, latest_dir

    @staticmethod
    def _capture_id_from_path(image_path: Path) -> str:
        stem = image_path.stem
        if stem.endswith("-preprocessed"):
            return stem[: -len("-preprocessed")]
        return stem

    @staticmethod
    def _update_metadata_paths(metadata_path: Path, ocr_text_path: Path, ocr_json_path: Path) -> None:
        if not metadata_path.exists():
            return
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["ocr_text_path"] = str(ocr_text_path)
        metadata["ocr_json_path"] = str(ocr_json_path)
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
