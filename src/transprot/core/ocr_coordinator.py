from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

from transprot.core.job_guard import JobGuard
from transprot.core.models import AppConfig, CaptureRegion, OCRResult, TranslationResult

logger = logging.getLogger(__name__)


class _CoordinatorBridge(QObject):
    payload_ready = Signal(object)


class OCRCoordinator(QObject):
    capture_started = Signal(object)
    recognition_started = Signal(object)
    ocr_ready = Signal(object, object)
    translation_streamed = Signal(object, object, str)
    translation_ready = Signal(object, object, object)
    error_occurred = Signal(str)
    status_changed = Signal(str)
    session_finished = Signal()

    def __init__(
        self,
        screenshot_service,
        ocr_service,
        translator_router=None,
        config_supplier: Callable[[], AppConfig] | None = None,
        capture_delay_ms: int = 100,
    ) -> None:
        super().__init__()
        self._screenshot_service = screenshot_service
        self._ocr_service = ocr_service
        self._translator_router = translator_router
        self._config_supplier = config_supplier
        self._capture_delay_ms = capture_delay_ms
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="transprot-ocr")
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

    def recognize_region(self, region: CaptureRegion) -> None:
        job_id = self._job_guard.next_job()
        self.status_changed.emit("capturing")
        self.capture_started.emit(region)
        QTimer.singleShot(
            self._capture_delay_ms,
            lambda current_job=job_id, current_region=region: self._capture_and_submit(current_job, current_region),
        )

    def shutdown(self) -> None:
        try:
            self._executor.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            self._executor.shutdown(wait=False)
        try:
            self._ocr_service.shutdown()
        except Exception:
            logger.exception("OCR service shutdown failed")

    def _capture_and_submit(self, job_id: int, region: CaptureRegion) -> None:
        if not self._job_guard.is_current(job_id):
            return
        try:
            image_path = self._screenshot_service.capture(region)
        except Exception as exc:
            logger.exception("Capture failed")
            self.status_changed.emit("error")
            self.error_occurred.emit(f"截图失败：{exc}")
            self.session_finished.emit()
            return

        self.recognition_started.emit(region)
        self.status_changed.emit("recognizing")
        future = self._executor.submit(self._run_ocr, region, image_path)
        future.add_done_callback(
            lambda item: self._bridge.payload_ready.emit(
                self._pack_future(item, job_id, region, kind="ocr")
            )
        )

    def _run_ocr(self, region: CaptureRegion, image_path: Path) -> dict[str, Any]:
        ocr_result = self._ocr_service.recognize(image_path)
        if not ocr_result.full_text.strip():
            raise RuntimeError("当前区域没有识别到可用文字。")
        return {
            "region": region,
            "ocr_result": ocr_result,
        }

    def _run_translation(self, job_id: int, region: CaptureRegion, ocr_result: OCRResult) -> dict[str, Any]:
        if self._translator_router is None or self._config_supplier is None:
            return {
                "region": region,
                "ocr_result": ocr_result,
                "translation_result": None,
            }

        config = self._config_supplier()

        def handle_progress(partial_text: str) -> None:
            self._bridge.payload_ready.emit(
                {
                    "kind": "translation_progress",
                    "job_id": job_id,
                    "region": region,
                    "result": {
                        "region": region,
                        "ocr_result": ocr_result,
                        "partial_text": partial_text,
                    },
                    "error": None,
                }
            )

        translation_result = self._translator_router.translate(
            ocr_result.full_text,
            config,
            progress_callback=handle_progress,
        )
        return {
            "region": region,
            "ocr_result": ocr_result,
            "translation_result": translation_result,
        }

    def _pack_future(
        self,
        future: Future,
        job_id: int | None,
        region: CaptureRegion | None,
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
            self.status_changed.emit("error")
            self.error_occurred.emit(payload["error"])
            self.session_finished.emit()
            return

        result = payload["result"]
        region = result["region"]

        if payload["kind"] == "ocr":
            ocr_result: OCRResult = result["ocr_result"]
            self.ocr_ready.emit(region, ocr_result)
            if self._translator_router is None or self._config_supplier is None:
                self.status_changed.emit("completed")
                self.session_finished.emit()
                return
            self.status_changed.emit("translating")
            future = self._executor.submit(self._run_translation, job_id, region, ocr_result)
            future.add_done_callback(
                lambda item: self._bridge.payload_ready.emit(
                    self._pack_future(item, job_id, region, kind="translation")
                )
            )
            return

        if payload["kind"] == "translation_progress":
            self.translation_streamed.emit(region, result["ocr_result"], result["partial_text"])
            return

        if payload["kind"] == "translation":
            ocr_result = result["ocr_result"]
            translation_result: TranslationResult | None = result["translation_result"]
            if translation_result is not None:
                self.translation_ready.emit(region, ocr_result, translation_result)
            self.status_changed.emit("completed")
            self.session_finished.emit()