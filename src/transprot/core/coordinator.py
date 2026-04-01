from __future__ import annotations

import logging
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, QTimer, Signal

from transprot.core.job_guard import JobGuard
from transprot.core.models import AppConfig, SelectionRegion

logger = logging.getLogger(__name__)


class _CoordinatorBridge(QObject):
    payload_ready = Signal(object)


class CaptureCoordinator(QObject):
    translation_ready = Signal(object, object)
    error_occurred = Signal(str)
    status_changed = Signal(str)

    def __init__(
        self,
        screenshot_service,
        ocr_service,
        translator_router,
        config_supplier: Callable[[], AppConfig],
    ) -> None:
        super().__init__()
        self._screenshot_service = screenshot_service
        self._ocr_service = ocr_service
        self._translator_router = translator_router
        self._config_supplier = config_supplier
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="transprot")
        self._job_guard = JobGuard()
        self._bridge = _CoordinatorBridge()
        self._bridge.payload_ready.connect(self._handle_async_payload)

    def warmup_ocr(self) -> None:
        future = self._executor.submit(self._ocr_service.warmup)
        future.add_done_callback(
            lambda item: self._bridge.payload_ready.emit(
                self._pack_future(item, None, None, kind="warmup")
            )
        )

    def handle_selection(self, region: SelectionRegion) -> None:
        job_id = self._job_guard.next_job()
        self.status_changed.emit("capturing")
        QTimer.singleShot(
            80,
            lambda current_job=job_id, current_region=region: self._capture_and_submit(current_job, current_region),
        )

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _capture_and_submit(self, job_id: int, region: SelectionRegion) -> None:
        if not self._job_guard.is_current(job_id):
            return
        try:
            image_path = self._screenshot_service.capture(region)
        except Exception as exc:
            logger.exception("Capture failed")
            self.error_occurred.emit(f"Capture failed: {exc}")
            return

        self.status_changed.emit("recognizing")
        config = self._config_supplier()
        future = self._executor.submit(self._run_pipeline, job_id, region, image_path, config)
        future.add_done_callback(
            lambda item: self._bridge.payload_ready.emit(
                self._pack_future(item, job_id, region, kind="pipeline")
            )
        )

    def _run_pipeline(
        self,
        job_id: int,
        region: SelectionRegion,
        image_path: Path,
        config: AppConfig,
    ) -> dict[str, Any]:
        ocr_result = self._ocr_service.recognize(image_path)
        if not ocr_result.full_text.strip():
            raise RuntimeError("No translatable text was recognized.")
        translation = self._translator_router.translate(ocr_result.full_text, config)
        return {
            "job_id": job_id,
            "region": region,
            "translation": translation,
            "ocr_text": ocr_result.full_text,
            "provider": translation.provider,
        }

    def _pack_future(
        self,
        future: Future,
        job_id: int | None,
        region: SelectionRegion | None,
        kind: str,
    ) -> dict[str, Any]:
        try:
            result = future.result()
            return {"kind": kind, "job_id": job_id, "region": region, "result": result, "error": None}
        except Exception as exc:
            logger.exception("Background job failed")
            return {"kind": kind, "job_id": job_id, "region": region, "result": None, "error": str(exc)}

    def _handle_async_payload(self, payload: dict[str, Any]) -> None:
        if payload["kind"] == "warmup":
            if payload["error"]:
                logger.warning("OCR warmup failed: %s", payload["error"])
            return

        job_id = payload["job_id"]
        if job_id is None or not self._job_guard.is_current(job_id):
            return
        if payload["error"]:
            self.error_occurred.emit(payload["error"])
            return

        result = payload["result"]
        region = result["region"]
        translation = result["translation"]
        self.translation_ready.emit(region, translation)
        self.status_changed.emit("completed")
