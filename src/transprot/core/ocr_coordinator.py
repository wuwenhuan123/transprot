from __future__ import annotations

import logging
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, QTimer, Signal

from transprot.core.job_guard import JobGuard
from transprot.core.models import AppConfig, CaptureRegion, OCRResult, TranslationResult
from transprot.core.text import normalize_source_compare_text

logger = logging.getLogger(__name__)


class _CoordinatorBridge(QObject):
    payload_ready = Signal(object)


class OCRCoordinator(QObject):
    capture_started = Signal(object)
    recognition_started = Signal(object)
    translation_started = Signal(object, object)
    ocr_ready = Signal(object, object)
    translation_ready = Signal(object, object)
    translation_skipped = Signal(object, object, str)
    error_occurred = Signal(str)
    status_changed = Signal(str)
    session_finished = Signal()

    def __init__(
        self,
        screenshot_service,
        ocr_service,
        translator_router,
        config_supplier: Callable[[], AppConfig],
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

    def warmup_ocr(self) -> None:
        future = self._executor.submit(self._ocr_service.warmup)
        future.add_done_callback(
            lambda item: self._bridge.payload_ready.emit(
                self._pack_future(item, None, None, kind="warmup")
            )
        )

    def recognize_region(
        self,
        region: CaptureRegion,
        trigger: str = "manual",
        previous_source_text: str | None = None,
        fingerprint: str | None = None,
    ) -> None:
        job_id = self._job_guard.next_job()
        context = {
            "job_id": job_id,
            "region": region,
            "trigger": trigger,
            "previous_source_text": previous_source_text or "",
            "fingerprint": fingerprint,
        }
        self.status_changed.emit("capturing")
        self.capture_started.emit(region)
        QTimer.singleShot(
            self._capture_delay_ms,
            lambda current_job=job_id, current_context=context: self._capture_and_submit(
                current_job, current_context
            ),
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

    def _capture_and_submit(self, job_id: int, context: dict[str, Any]) -> None:
        if not self._job_guard.is_current(job_id):
            return
        region: CaptureRegion = context["region"]
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
                self._pack_future(item, job_id, context, kind="ocr")
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

    def _run_translation(
        self,
        region: CaptureRegion,
        ocr_result: OCRResult,
        config: AppConfig,
    ) -> dict[str, Any]:
        translation = self._translator_router.translate(ocr_result.full_text, config)
        return {
            "region": region,
            "ocr_result": ocr_result,
            "translation": translation,
        }

    def _pack_future(
        self,
        future: Future,
        job_id: int | None,
        context: dict[str, Any] | None,
        kind: str,
    ) -> dict[str, Any]:
        try:
            result = future.result()
            return {"kind": kind, "job_id": job_id, "context": context, "result": result, "error": None}
        except Exception as exc:
            logger.exception("Background job failed")
            return {"kind": kind, "job_id": job_id, "context": context, "result": None, "error": str(exc)}

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

        if payload["kind"] == "ocr":
            self._handle_ocr_payload(payload["context"], payload["result"])
            return

        if payload["kind"] == "translation":
            self._handle_translation_payload(payload["result"])

    def _handle_ocr_payload(self, context: dict[str, Any], result: dict[str, Any]) -> None:
        region: CaptureRegion = result["region"]
        ocr_result: OCRResult = result["ocr_result"]
        self.ocr_ready.emit(region, ocr_result)

        previous_source_text = normalize_source_compare_text(str(context.get("previous_source_text", "")))
        current_source_text = normalize_source_compare_text(ocr_result.full_text)
        if context.get("trigger") == "auto" and previous_source_text and current_source_text == previous_source_text:
            self.translation_skipped.emit(region, ocr_result, "same_source_text")
            self.status_changed.emit("completed")
            self.session_finished.emit()
            return

        self.translation_started.emit(region, ocr_result)
        self.status_changed.emit("translating")
        try:
            config = self._config_supplier()
        except Exception as exc:
            logger.exception("Failed to load runtime config")
            self.status_changed.emit("error")
            self.error_occurred.emit(f"读取配置失败：{exc}")
            self.session_finished.emit()
            return
        future = self._executor.submit(self._run_translation, region, ocr_result, config)
        future.add_done_callback(
            lambda item: self._bridge.payload_ready.emit(
                self._pack_future(item, context["job_id"], context, kind="translation")
            )
        )

    def _handle_translation_payload(self, result: dict[str, Any]) -> None:
        region: CaptureRegion = result["region"]
        translation: TranslationResult = result["translation"]
        self.translation_ready.emit(region, translation)
        self.status_changed.emit("completed")
        self.session_finished.emit()
