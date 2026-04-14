from __future__ import annotations

import importlib.util
import json
import logging
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any

from transprot.core.config import resolve_log_dir
from transprot.core.errors import OCRUnavailableError
from transprot.core.models import OCRLine, OCRResult
from transprot.core.text import merge_ocr_lines

logger = logging.getLogger(__name__)

_DEFAULT_UNAVAILABLE_MESSAGE = (
    "\u672a\u68c0\u6d4b\u5230\u53ef\u7528\u7684 Paddle OCR \u8fd0\u884c\u73af\u5883\u3002"
    "\u8bf7\u6267\u884c `pip install -e .[ocr]`\uff0c"
    "\u6216\u8bbe\u7f6e `TRANSPROT_FAKE_OCR_TEXT` \u8fdb\u5165\u6f14\u793a\u6a21\u5f0f\u3002"
)
_FAST_MODEL_PROFILE = "ppocr-v4-mobile"
_SERVER_FALLBACK_PROFILE = "ppocr-v5-server"
_DEFAULT_REQUEST_TIMEOUT_SEC = 120
_DEFAULT_WARMUP_TIMEOUT_SEC = 300
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_OCR_PROFILE_REQUIREMENTS = {
    _FAST_MODEL_PROFILE: ("PP-OCRv4_mobile_det", "PP-OCRv4_mobile_rec"),
}
_OCR_PROFILE_SOURCE_LABELS = {
    "bundled": "\u5185\u7f6e\u79bb\u7ebf\u6a21\u578b",
    "cache": "\u672c\u5730\u7f13\u5b58",
}

def _runtime_root_candidates() -> list[Path]:
    return [
        resolve_log_dir().parent / "runtime",
        Path(__file__).resolve().parents[3] / ".tmp-runtime",
    ]


def _prepare_runtime_root() -> Path | None:
    for candidate in _runtime_root_candidates():
        try:
            candidate.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        return candidate
    return None


def _bundled_offline_ocr_root() -> Path | None:
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "offline-ocr-models")
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir / "offline-ocr-models")
        candidates.append(exe_dir / "_internal" / "offline-ocr-models")

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _seed_offline_models(paddlex_cache_dir: Path) -> None:
    bundled_root = _bundled_offline_ocr_root()
    if bundled_root is None:
        return

    target_root = paddlex_cache_dir / "official_models"
    target_root.mkdir(parents=True, exist_ok=True)
    for source_dir in bundled_root.iterdir():
        if not source_dir.is_dir():
            continue
        target_dir = target_root / source_dir.name
        if target_dir.exists():
            continue
        try:
            shutil.copytree(source_dir, target_dir)
            logger.info("Seeded bundled OCR model. source=%s target=%s", source_dir, target_dir)
        except OSError as exc:
            logger.warning("Failed to seed bundled OCR model. source=%s error=%s", source_dir, exc)


def list_available_ocr_models(
    search_roots: Sequence[tuple[Path, str]] | None = None,
) -> list[str]:
    if search_roots is None:
        _configure_paddle_environment()
        search_roots = []
        bundled_root = _bundled_offline_ocr_root()
        if bundled_root is not None:
            search_roots.append((bundled_root, "bundled"))
        cache_root = Path(os.environ["PADDLE_PDX_CACHE_HOME"]) / "official_models"
        if cache_root.exists():
            search_roots.append((cache_root, "cache"))

    available: list[str] = []
    seen_profiles: set[str] = set()
    for root, source_key in search_roots:
        if not root.exists():
            continue
        for profile_name, required_dirs in _OCR_PROFILE_REQUIREMENTS.items():
            if profile_name in seen_profiles:
                continue
            if all((root / required_dir).exists() for required_dir in required_dirs):
                source_label = _OCR_PROFILE_SOURCE_LABELS.get(source_key, source_key)
                available.append(f"{profile_name}\uff08{source_label}\uff09")
                seen_profiles.add(profile_name)
    return available


def describe_available_ocr_models() -> str:
    available = list_available_ocr_models()
    if not available:
        return "\u672a\u53d1\u73b0\u53ef\u7528 OCR \u6a21\u578b\uff0c\u9996\u6b21\u8bc6\u522b\u65f6\u4f1a\u81ea\u52a8\u51c6\u5907\u3002"
    return "\u3001".join(available)


def _configure_paddle_environment() -> None:
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    runtime_root = _prepare_runtime_root()
    if runtime_root is None:
        return

    profile_dir = runtime_root / "profile"
    cache_dir = runtime_root / "cache"
    temp_dir = runtime_root / "temp-work"
    paddlex_cache_dir = runtime_root / "paddlex-cache"
    paddle_home_dir = runtime_root / "paddle-home"

    for candidate in (profile_dir, cache_dir, temp_dir, paddlex_cache_dir, paddle_home_dir):
        try:
            candidate.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue

    os.environ.setdefault("HOME", str(profile_dir))
    os.environ.setdefault("USERPROFILE", str(profile_dir))
    os.environ.setdefault("XDG_CACHE_HOME", str(cache_dir))
    os.environ.setdefault("TEMP", str(temp_dir))
    os.environ.setdefault("TMP", str(temp_dir))
    os.environ.setdefault("PADDLE_HOME", str(paddle_home_dir))
    os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(paddlex_cache_dir))
    _seed_offline_models(paddlex_cache_dir)


def _missing_dependency_message(module_name: str | None = None) -> str:
    if module_name == "paddle":
        return "\u7f3a\u5c11 `paddlepaddle` \u8fd0\u884c\u5e93\u3002\u8bf7\u6267\u884c `pip install -e .[ocr]` \u540e\u91cd\u8bd5\u3002"
    if module_name == "paddleocr":
        return "\u7f3a\u5c11 `paddleocr` \u4f9d\u8d56\u3002\u8bf7\u6267\u884c `pip install -e .[ocr]` \u540e\u91cd\u8bd5\u3002"
    return _DEFAULT_UNAVAILABLE_MESSAGE


def _default_cpu_threads() -> int:
    cpu_count = os.cpu_count() or 2
    return max(2, min(4, cpu_count))


def _configured_timeout(name: str, fallback: int) -> int:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return fallback
    try:
        return max(1, int(raw_value))
    except ValueError:
        logger.warning("Ignoring invalid timeout override. %s=%s", name, raw_value)
        return fallback


def paddleocr_available() -> bool:
    _configure_paddle_environment()
    return (
        importlib.util.find_spec("paddle") is not None
        and importlib.util.find_spec("paddleocr") is not None
    )


def ocr_result_to_payload(result: OCRResult) -> dict[str, Any]:
    return {
        "full_text": result.full_text,
        "provider": result.provider,
        "lines": [
            {
                "text": line.text,
                "bbox": list(line.bbox),
            }
            for line in result.lines
        ],
    }


def ocr_result_from_payload(payload: Mapping[str, Any]) -> OCRResult:
    lines_raw = payload.get("lines")
    lines: list[OCRLine] = []
    if isinstance(lines_raw, Sequence) and not isinstance(lines_raw, (str, bytes)):
        for item in lines_raw:
            if not isinstance(item, Mapping):
                continue
            bbox_raw = item.get("bbox", (0, 0, 0, 0))
            bbox = tuple(int(value) for value in bbox_raw[:4]) if isinstance(bbox_raw, Sequence) else (0, 0, 0, 0)
            lines.append(OCRLine(text=str(item.get("text", "")).strip(), bbox=bbox))
    return OCRResult(
        full_text=str(payload.get("full_text", "")),
        lines=[line for line in lines if line.text],
        provider=str(payload.get("provider", "paddleocr")),
    )


class BaseOCRService:
    provider_name = "base"

    def warmup(self) -> None:
        return

    def shutdown(self) -> None:
        return

    def recognize(self, image_path: Path) -> OCRResult:
        raise NotImplementedError


class FakeOCRService(BaseOCRService):
    provider_name = "fake-ocr"

    def __init__(self, text: str) -> None:
        self._text = text

    def recognize(self, image_path: Path) -> OCRResult:
        return OCRResult(
            full_text=self._text.strip(),
            lines=[OCRLine(text=line) for line in self._text.splitlines() if line.strip()],
            provider=self.provider_name,
        )


class UnavailableOCRService(BaseOCRService):
    provider_name = "unavailable"

    def __init__(self, message: str = _DEFAULT_UNAVAILABLE_MESSAGE) -> None:
        self._message = message

    def recognize(self, image_path: Path) -> OCRResult:
        raise OCRUnavailableError(self._message)


class PaddleOCRService(BaseOCRService):
    provider_name = "paddleocr"

    def __init__(self) -> None:
        _configure_paddle_environment()
        self._engine: Any | None = None
        self._engine_profile = "uninitialized"
        self._lock = Lock()

    @property
    def engine_profile(self) -> str:
        return self._engine_profile

    def warmup(self) -> None:
        self._get_engine()

    def _engine_profiles(self) -> list[tuple[str, dict[str, Any]]]:
        base_options = {
            "use_doc_orientation_classify": False,
            "use_doc_unwarping": False,
            "use_textline_orientation": False,
            "enable_mkldnn": False,
            "cpu_threads": _default_cpu_threads(),
        }
        return [
            (
                _FAST_MODEL_PROFILE,
                {
                    **base_options,
                    "lang": "ch",
                    "ocr_version": "PP-OCRv4",
                    "text_detection_model_name": "PP-OCRv4_mobile_det",
                    "text_recognition_model_name": "PP-OCRv4_mobile_rec",
                    "text_det_limit_side_len": 640,
                    "text_det_limit_type": "max",
                },
            ),
        ]

    def _get_engine(self) -> Any:
        if self._engine is not None:
            return self._engine
        with self._lock:
            if self._engine is None:
                self._engine = self._build_engine()
        return self._engine

    def _build_engine(self) -> Any:
        try:
            from paddleocr import PaddleOCR
        except ModuleNotFoundError as exc:
            raise OCRUnavailableError(_missing_dependency_message(exc.name)) from exc
        except Exception as exc:
            raise OCRUnavailableError(f"Paddle OCR \u8fd0\u884c\u73af\u5883\u521d\u59cb\u5316\u5931\u8d25\uff1a{exc}") from exc

        available_profile_names = {item.split("\uff08", 1)[0] for item in list_available_ocr_models()}
        errors: list[str] = []
        for profile_name, profile_options in self._engine_profiles():
            if profile_name not in available_profile_names:
                errors.append(f"{profile_name}: \u672a\u53d1\u73b0\u53ef\u7528\u7684\u79bb\u7ebf\u6a21\u578b\u6587\u4ef6")
                continue
            try:
                engine = PaddleOCR(**profile_options)
            except ModuleNotFoundError as exc:
                raise OCRUnavailableError(_missing_dependency_message(exc.name)) from exc
            except Exception as exc:
                logger.warning(
                    "Paddle OCR engine candidate failed. profile=%s error=%s",
                    profile_name,
                    exc,
                )
                errors.append(f"{profile_name}: {exc}")
                continue

            self._engine_profile = profile_name
            logger.info("Initialized Paddle OCR engine. profile=%s", profile_name)
            return engine

        detail = " | ".join(errors[-2:]) or "unknown error"
        raise OCRUnavailableError(f"Paddle OCR \u5f15\u64ce\u521d\u59cb\u5316\u5931\u8d25\uff1a{detail}")

    def recognize(self, image_path: Path) -> OCRResult:
        engine = self._get_engine()
        raw = self._run_engine(engine, image_path)
        lines = self._extract_lines(raw)
        return OCRResult(
            full_text=merge_ocr_lines(line.text for line in lines),
            lines=lines,
            provider=self.provider_name,
        )

    def _run_engine(self, engine: Any, image_path: Path) -> Any:
        image_arg = str(image_path)
        predict = getattr(engine, "predict", None)
        if callable(predict):
            return predict(image_arg)

        legacy_ocr = getattr(engine, "ocr", None)
        if callable(legacy_ocr):
            try:
                return legacy_ocr(image_arg, cls=True)
            except TypeError as exc:
                if "cls" not in str(exc):
                    raise
                return legacy_ocr(image_arg)

        raise OCRUnavailableError("\u5f53\u524d Paddle OCR \u5f15\u64ce\u4e0d\u652f\u6301\u53ef\u7528\u7684\u8bc6\u522b\u63a5\u53e3\u3002")

    def _extract_lines(self, payload: Any) -> list[OCRLine]:
        extracted: list[OCRLine] = []
        blocks = payload if isinstance(payload, list) else [payload]
        for block in blocks:
            if isinstance(block, Mapping):
                extracted.extend(self._extract_mapping_lines(block))
                continue
            if not isinstance(block, list):
                continue
            for item in block:
                if not isinstance(item, list) or len(item) < 2:
                    continue
                bbox_raw = item[0]
                text_info = item[1]
                text = ""
                if isinstance(text_info, tuple) and text_info:
                    text = str(text_info[0])
                elif isinstance(text_info, list) and text_info:
                    text = str(text_info[0])
                if not text.strip():
                    continue
                bbox = self._normalize_bbox(bbox_raw)
                extracted.append(OCRLine(text=text.strip(), bbox=bbox))
        return extracted

    def _extract_mapping_lines(self, payload: Mapping[str, Any]) -> list[OCRLine]:
        texts_raw = payload.get("rec_texts")
        polys_raw = payload.get("rec_polys") or payload.get("dt_polys") or payload.get("rec_boxes")
        if not isinstance(texts_raw, Sequence) or isinstance(texts_raw, (str, bytes)):
            return []

        polygons = list(polys_raw) if isinstance(polys_raw, Sequence) else []
        extracted: list[OCRLine] = []
        for index, text_value in enumerate(texts_raw):
            text = str(text_value).strip()
            if not text:
                continue
            bbox_raw = polygons[index] if index < len(polygons) else None
            extracted.append(OCRLine(text=text, bbox=self._normalize_bbox(bbox_raw)))
        return extracted

    @staticmethod
    def _normalize_bbox(bbox_raw: Any) -> tuple[int, int, int, int]:
        if bbox_raw is None:
            return 0, 0, 0, 0
        if hasattr(bbox_raw, "tolist"):
            bbox_raw = bbox_raw.tolist()

        if isinstance(bbox_raw, Sequence) and not isinstance(bbox_raw, (str, bytes)):
            if len(bbox_raw) >= 4 and all(isinstance(value, (int, float)) for value in bbox_raw[:4]):
                x1, y1, x2, y2 = [int(value) for value in bbox_raw[:4]]
                return x1, y1, max(0, x2 - x1), max(0, y2 - y1)

            points = [
                point
                for point in bbox_raw
                if isinstance(point, Sequence)
                and not isinstance(point, (str, bytes))
                and len(point) >= 2
                and isinstance(point[0], (int, float))
                and isinstance(point[1], (int, float))
            ]
            if points:
                xs = [int(point[0]) for point in points]
                ys = [int(point[1]) for point in points]
                return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)

        return 0, 0, 0, 0


@dataclass
class _PendingWorkerRequest:
    event: Event = field(default_factory=Event)
    payload: dict[str, Any] | None = None
    error: str | None = None


class SubprocessOCRService(BaseOCRService):
    provider_name = "paddleocr-subprocess"

    def __init__(
        self,
        timeout_sec: int = _configured_timeout("TRANSPROT_OCR_TIMEOUT_SEC", _DEFAULT_REQUEST_TIMEOUT_SEC),
        warmup_timeout_sec: int = _configured_timeout(
            "TRANSPROT_OCR_WARMUP_TIMEOUT_SEC",
            _DEFAULT_WARMUP_TIMEOUT_SEC,
        ),
    ) -> None:
        _configure_paddle_environment()
        self._timeout_sec = timeout_sec
        self._warmup_timeout_sec = warmup_timeout_sec
        self._process: subprocess.Popen[str] | None = None
        self._pending_requests: dict[str, _PendingWorkerRequest] = {}
        self._request_counter = 0
        self._lock = Lock()
        self._stdout_thread: Thread | None = None
        self._stderr_thread: Thread | None = None
        self._closed = False

    def warmup(self) -> None:
        self._send_request("warmup", timeout_sec=self._warmup_timeout_sec)

    def shutdown(self) -> None:
        with self._lock:
            self._closed = True
        self._stop_worker("OCR worker \u5df2\u5173\u95ed\u3002")

    def recognize(self, image_path: Path) -> OCRResult:
        payload = self._send_request(
            "recognize",
            timeout_sec=self._timeout_sec,
            image_path=str(image_path),
        )
        result_payload = payload.get("result")
        if not isinstance(result_payload, Mapping):
            raise RuntimeError("OCR \u5b50\u8fdb\u7a0b\u8fd4\u56de\u7684\u6570\u636e\u683c\u5f0f\u65e0\u6548\u3002")
        result = ocr_result_from_payload(result_payload)
        result.provider = self.provider_name
        return result

    def _send_request(self, command: str, timeout_sec: int, **extra: Any) -> dict[str, Any]:
        request = _PendingWorkerRequest()
        with self._lock:
            if self._closed:
                raise RuntimeError("OCR \u670d\u52a1\u5df2\u7ecf\u5173\u95ed\u3002")
            process = self._ensure_worker_locked()
            self._request_counter += 1
            request_id = str(self._request_counter)
            self._pending_requests[request_id] = request
            message = json.dumps({"id": request_id, "command": command, **extra}, ensure_ascii=False)
            try:
                if process.stdin is None:
                    raise OSError("OCR worker stdin is not available.")
                process.stdin.write(message + "\n")
                process.stdin.flush()
            except OSError as exc:
                self._pending_requests.pop(request_id, None)
                self._invalidate_worker_locked(f"\u65e0\u6cd5\u5411 OCR worker \u53d1\u9001\u8bf7\u6c42\uff1a{exc}")
                raise OCRUnavailableError(f"\u65e0\u6cd5\u4e0e OCR worker \u901a\u4fe1\uff1a{exc}") from exc

        if not request.event.wait(timeout_sec):
            if command == "warmup":
                self._stop_worker("OCR \u5f15\u64ce\u9884\u70ed\u8d85\u65f6\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002")
                raise OCRUnavailableError("OCR \u5f15\u64ce\u9884\u70ed\u8d85\u65f6\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002")
            self._stop_worker("OCR \u8bc6\u522b\u8d85\u65f6\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002")
            raise RuntimeError("OCR \u8bc6\u522b\u8d85\u65f6\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002")

        if request.error:
            if command == "warmup":
                raise OCRUnavailableError(request.error)
            raise RuntimeError(request.error)
        return request.payload or {}

    def _ensure_worker_locked(self) -> subprocess.Popen[str]:
        process = self._process
        if process is not None and process.poll() is None:
            return process
        return self._start_worker_locked()

    @staticmethod
    def _build_worker_command() -> list[str]:
        if getattr(sys, "frozen", False):
            return [sys.executable, "--ocr-worker-stdio"]
        return [sys.executable, "-m", "transprot.services.ocr_worker", "--stdio"]

    def _start_worker_locked(self) -> subprocess.Popen[str]:
        command = self._build_worker_command()
        env = os.environ.copy()
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
                creationflags=_CREATE_NO_WINDOW,
            )
        except OSError as exc:
            raise OCRUnavailableError(f"\u65e0\u6cd5\u542f\u52a8 OCR \u5b50\u8fdb\u7a0b\uff1a{exc}") from exc

        self._process = process
        self._stdout_thread = Thread(
            target=self._stdout_loop,
            args=(process,),
            name="transprot-ocr-worker-stdout",
            daemon=True,
        )
        self._stderr_thread = Thread(
            target=self._stderr_loop,
            args=(process,),
            name="transprot-ocr-worker-stderr",
            daemon=True,
        )
        self._stdout_thread.start()
        self._stderr_thread.start()
        logger.info("Started OCR worker process. pid=%s", process.pid)
        return process

    def _stdout_loop(self, process: subprocess.Popen[str]) -> None:
        try:
            if process.stdout is None:
                return
            for raw_line in process.stdout:
                line = raw_line.strip()
                if not line:
                    continue
                self._handle_worker_message(line)
        finally:
            self._handle_worker_exit(process)

    def _stderr_loop(self, process: subprocess.Popen[str]) -> None:
        if process.stderr is None:
            return
        for raw_line in process.stderr:
            line = raw_line.strip()
            if line:
                logger.debug("OCR worker stderr: %s", line)

    def _handle_worker_message(self, message: str) -> None:
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            logger.warning("Ignoring invalid OCR worker output: %s", message)
            return

        request_id = str(payload.get("id", "")).strip()
        if not request_id:
            logger.warning("Ignoring OCR worker message without request id: %s", payload)
            return

        with self._lock:
            request = self._pending_requests.pop(request_id, None)
        if request is None:
            logger.debug("Received late OCR worker response. id=%s", request_id)
            return

        if payload.get("ok", False):
            request.payload = payload
        else:
            request.error = str(payload.get("error") or "OCR \u8bc6\u522b\u5931\u8d25\u3002")
        request.event.set()

    def _handle_worker_exit(self, process: subprocess.Popen[str]) -> None:
        return_code = process.poll()
        message = "OCR worker \u5df2\u9000\u51fa\u3002"
        if return_code not in (None, 0):
            message = f"OCR worker \u5df2\u9000\u51fa\uff08code={return_code}\uff09\u3002"
        self._detach_worker(process, message)

    def _stop_worker(self, reason: str) -> None:
        process = self._detach_worker(None, reason)
        if process is None:
            return
        self._terminate_process(process)

    def _invalidate_worker_locked(self, reason: str) -> None:
        process = self._process
        self._process = None
        self._stdout_thread = None
        self._stderr_thread = None
        pending = list(self._pending_requests.values())
        self._pending_requests.clear()
        for request in pending:
            if request.error is None:
                request.error = reason
            request.event.set()
        if process is not None:
            logger.warning("Resetting OCR worker. pid=%s reason=%s", process.pid, reason)
            self._terminate_process(process)

    def _detach_worker(self, process: subprocess.Popen[str] | None, reason: str) -> subprocess.Popen[str] | None:
        with self._lock:
            current = self._process
            if current is None:
                return None
            if process is not None and process is not current:
                return None
            self._process = None
            self._stdout_thread = None
            self._stderr_thread = None
            pending = list(self._pending_requests.values())
            self._pending_requests.clear()

        for request in pending:
            if request.error is None:
                request.error = reason
            request.event.set()

        logger.info("Stopping OCR worker. pid=%s reason=%s", current.pid, reason)
        return current

    @staticmethod
    def _terminate_process(process: subprocess.Popen[str]) -> None:
        try:
            if process.stdin is not None:
                process.stdin.close()
        except OSError:
            pass

        if process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=5)
            except Exception:
                try:
                    process.kill()
                    process.wait(timeout=5)
                except Exception:
                    pass

        for stream in (process.stdout, process.stderr):
            try:
                if stream is not None:
                    stream.close()
            except OSError:
                pass


def create_ocr_service() -> BaseOCRService:
    fake_text = os.getenv("TRANSPROT_FAKE_OCR_TEXT", "").strip()
    if fake_text:
        return FakeOCRService(fake_text)
    if paddleocr_available():
        return SubprocessOCRService()
    missing_module = "paddle" if importlib.util.find_spec("paddle") is None else "paddleocr"
    return UnavailableOCRService(_missing_dependency_message(missing_module))