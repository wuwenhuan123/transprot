from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path
from typing import Any

from transprot.services.ocr import PaddleOCRService, ocr_result_to_payload



def _run_recognize(service: PaddleOCRService, image_path: Path) -> dict[str, Any]:
    with contextlib.redirect_stdout(sys.stderr):
        result = service.recognize(image_path)
    return {"ok": True, "result": ocr_result_to_payload(result)}



def _handle_request(service: PaddleOCRService, payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    command = str(payload.get("command", "")).strip().lower()
    if command == "warmup":
        with contextlib.redirect_stdout(sys.stderr):
            service.warmup()
        return {"ok": True}, False
    if command == "recognize":
        raw_path = str(payload.get("image_path", "")).strip()
        if not raw_path:
            return {"ok": False, "error": "OCR worker missing image_path."}, False
        return _run_recognize(service, Path(raw_path)), False
    if command == "shutdown":
        return {"ok": True}, True
    return {"ok": False, "error": f"Unsupported OCR worker command: {command or '<empty>'}"}, False



def _run_stdio_worker() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)

    service = PaddleOCRService()
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue

        request_id = ""
        should_exit = False
        try:
            request = json.loads(line)
            request_id = str(request.get("id", "")).strip()
            response, should_exit = _handle_request(service, request)
        except Exception as exc:
            response = {"ok": False, "error": str(exc)}

        if request_id:
            response["id"] = request_id
        try:
            print(json.dumps(response, ensure_ascii=False), flush=True)
        except BrokenPipeError:
            return 0
        if should_exit:
            return 0

    return 0



def _run_single_image(image_path: Path) -> int:
    try:
        result = _run_recognize(PaddleOCRService(), image_path)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1

    print(json.dumps(result, ensure_ascii=False))
    return 0



def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--stdio"]:
        return _run_stdio_worker()
    if len(args) == 1:
        return _run_single_image(Path(args[0]))

    print(
        json.dumps(
            {"ok": False, "error": "OCR worker requires either --stdio or exactly one image path."},
            ensure_ascii=False,
        )
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())