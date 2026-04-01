from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from transprot.services.ocr import PaddleOCRService, SubprocessOCRService


class PaddleOCRServiceTests(unittest.TestCase):
    def test_extract_lines_supports_legacy_payload(self) -> None:
        service = PaddleOCRService()
        payload = [
            [
                [
                    [[10, 20], [70, 20], [70, 44], [10, 44]],
                    ("legacy text", 0.99),
                ]
            ]
        ]

        lines = service._extract_lines(payload)

        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].text, "legacy text")
        self.assertEqual(lines[0].bbox, (10, 20, 60, 24))

    def test_extract_lines_supports_paddleocr_v3_payload(self) -> None:
        service = PaddleOCRService()
        payload = [
            {
                "rec_texts": ["hello 123", ""],
                "rec_boxes": [
                    [19, 39, 111, 51],
                    [0, 0, 0, 0],
                ],
            }
        ]

        lines = service._extract_lines(payload)

        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].text, "hello 123")
        self.assertEqual(lines[0].bbox, (19, 39, 92, 12))

    def test_engine_profiles_prefer_mobile_models(self) -> None:
        profiles = PaddleOCRService()._engine_profiles()

        self.assertEqual(profiles[0][0], "ppocr-v4-mobile")
        self.assertEqual(profiles[0][1]["text_detection_model_name"], "PP-OCRv4_mobile_det")
        self.assertEqual(profiles[0][1]["text_recognition_model_name"], "PP-OCRv4_mobile_rec")
        self.assertEqual(profiles[1][0], "ppocr-v5-server")


class SubprocessOCRServiceTests(unittest.TestCase):
    def test_recognize_parses_worker_payload(self) -> None:
        service = SubprocessOCRService(timeout_sec=5, warmup_timeout_sec=30)
        payload = {
            "ok": True,
            "result": {
                "full_text": "\u4f60\u597d",
                "provider": "paddleocr",
                "lines": [{"text": "\u4f60\u597d", "bbox": [1, 2, 30, 12]}],
            },
        }

        with patch.object(service, "_send_request", return_value=payload) as request_mock:
            result = service.recognize(Path("capture.png"))

        self.assertEqual(result.full_text, "\u4f60\u597d")
        self.assertEqual(result.provider, "paddleocr-subprocess")
        self.assertEqual(result.lines[0].bbox, (1, 2, 30, 12))
        request_mock.assert_called_once_with("recognize", timeout_sec=5, image_path="capture.png")

    def test_warmup_uses_longer_timeout(self) -> None:
        service = SubprocessOCRService(timeout_sec=5, warmup_timeout_sec=30)

        with patch.object(service, "_send_request", return_value={"ok": True}) as request_mock:
            service.warmup()

        request_mock.assert_called_once_with("warmup", timeout_sec=30)

    def test_recognize_surfaces_worker_error(self) -> None:
        service = SubprocessOCRService(timeout_sec=5, warmup_timeout_sec=30)

        with patch.object(service, "_send_request", side_effect=RuntimeError("boom")):
            with self.assertRaisesRegex(RuntimeError, "boom"):
                service.recognize(Path("capture.png"))


if __name__ == "__main__":
    unittest.main()