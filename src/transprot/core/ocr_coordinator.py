from __future__ import annotations

import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

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
    translation_progress = Signal(object, str)
    translation_ready = Signal(object, object)
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
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="transprot-pipeline")
        self._job_guard = JobGuard()
        self._bridge = _CoordinatorBridge()
        self._bridge.payload_ready.connect(self._handle_async_payload)
        self._timings: dict[int, dict[str, float]] = {}

    def warmup_ocr(self) -> None:
        future = self._executor.submit(self._ocr_service.warmup)
        future.add_done_callback(
            lambda item: self._bridge.payload_ready.emit(
                self._pack_future(item, None, None, kind="warmup")
            )
        )

    def recognize_region(self, region: CaptureRegion) -> None:
        job_id = self._job_guard.next_job()
        self._timings[job_id] = {"pipeline_started": time.perf_counter()}
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
            self._timings.pop(job_id, None)
            return
        try:
            image_path = self._screenshot_service.capture(region)
        except Exception as exc:
            logger.exception("Capture failed")
            self.status_changed.emit("error")
            self.error_occurred.emit(f"截图失败：{exc}")
            self._timings.pop(job_id, None)
            self.session_finished.emit()
            return

        timing = self._timings.setdefault(job_id, {})
        timing["capture_finished"] = time.perf_counter()
        timing["ocr_started"] = timing["capture_finished"]
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
            "image_path": image_path,
            "ocr_result": ocr_result,
        }

    def _run_translation(self, job_id: int, region: CaptureRegion, ocr_result: OCRResult, config: AppConfig) -> dict[str, Any]:
        if self._translator_router is None:
            raise RuntimeError("Translation router is not configured.")

        def _on_progress(partial_text: str) -> None:
            self._bridge.payload_ready.emit(
                {
                    "kind": "translation_progress",
                    "job_id": job_id,
                    "region": region,
                    "result": {"text": partial_text},
                    "error": None,
                }
            )

        translation = self._translator_router.translate_stream(ocr_result.full_text, config, on_progress=_on_progress)
        return {
            "region": region,
            "ocr_result": ocr_result,
            "translation": translation,
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
            if job_id is not None and payload["kind"] != "translation_progress":
                self._timings.pop(job_id, None)
            return
        if payload["error"]:
            self.status_changed.emit("error")
            self.error_occurred.emit(payload["error"])
            self._timings.pop(job_id, None)
            self.session_finished.emit()
            return

        if payload["kind"] == "ocr":
            result = payload["result"]
            region = result["region"]
            image_path = result.get("image_path")
            ocr_result: OCRResult = result["ocr_result"]
            export_ocr_debug = getattr(self._screenshot_service, "export_ocr_debug_artifacts", None)
            if callable(export_ocr_debug) and isinstance(image_path, Path):
                try:
                    export_ocr_debug(image_path, ocr_result)
                except Exception:
                    logger.exception("Failed to export OCR debug artifacts")
            self.ocr_ready.emit(region, ocr_result)

            timing = self._timings.setdefault(job_id, {})
            timing["ocr_finished"] = time.perf_counter()
            capture_ms = int((timing.get("capture_finished", timing["ocr_finished"]) - timing.get("pipeline_started", timing["ocr_finished"])) * 1000)
            ocr_ms = int((timing["ocr_finished"] - timing.get("ocr_started", timing["ocr_finished"])) * 1000)
            logger.info("Pipeline timing. job_id=%s capture_ms=%s ocr_ms=%s", job_id, capture_ms, ocr_ms)

            if self._translator_router is None or self._config_supplier is None:
                self.status_changed.emit("completed")
                self._timings.pop(job_id, None)
                self.session_finished.emit()
                return

            config = self._config_supplier()
            timing["translation_started"] = time.perf_counter()
            self.status_changed.emit("translating")
            future = self._executor.submit(self._run_translation, job_id, region, ocr_result, config)
            future.add_done_callback(
                lambda item: self._bridge.payload_ready.emit(
                    self._pack_future(item, job_id, region, kind="translation")
                )
            )
            return

        if payload["kind"] == "translation_progress":
            result = payload["result"]
            partial_text = str(result["text"])
            timing = self._timings.setdefault(job_id, {})
            if "translation_first_chunk" not in timing:
                timing["translation_first_chunk"] = time.perf_counter()
                started = timing.get("translation_started", timing["translation_first_chunk"])
                first_chunk_ms = int((timing["translation_first_chunk"] - started) * 1000)
                logger.info("Pipeline timing. job_id=%s translation_first_chunk_ms=%s", job_id, first_chunk_ms)
            self.translation_progress.emit(payload["region"], partial_text)
            return

        if payload["kind"] == "translation":
            result = payload["result"]
            region = result["region"]
            translation: TranslationResult = result["translation"]
            timing = self._timings.pop(job_id, {})
            translation_finished = time.perf_counter()
            translation_ms = int((translation_finished - timing.get("translation_started", translation_finished)) * 1000)
            total_ms = int((translation_finished - timing.get("pipeline_started", translation_finished)) * 1000)
            logger.info(
                "Pipeline timing. job_id=%s translation_ms=%s total_ms=%s provider=%s latency_ms=%s",
                job_id,
                translation_ms,
                total_ms,
                translation.provider,
                translation.latency_ms,
            )
            self.translation_ready.emit(region, translation)
            self.status_changed.emit("completed")
            self.session_finished.emit()
