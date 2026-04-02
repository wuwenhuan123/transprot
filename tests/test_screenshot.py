from __future__ import annotations

import json
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from transprot.core.models import CaptureRegion, OCRLine, OCRResult
from transprot.infra.screenshot import ScreenshotService


class _FakeGeometry:
    def __init__(self, x: int, y: int, width: int, height: int) -> None:
        self._x = x
        self._y = y
        self._width = width
        self._height = height

    def x(self) -> int:
        return self._x

    def y(self) -> int:
        return self._y

    def width(self) -> int:
        return self._width

    def height(self) -> int:
        return self._height


class _FakePixmap:
    def __init__(self, width: int = 320, height: int = 160) -> None:
        self._width = width
        self._height = height
        self.saved_paths: list[Path] = []

    def isNull(self) -> bool:
        return False

    def save(self, path: str, fmt: str) -> bool:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b'raw-image')
        self.saved_paths.append(target)
        return True

    def devicePixelRatio(self) -> float:
        return 1.5

    def width(self) -> int:
        return self._width

    def height(self) -> int:
        return self._height


class _FakeScreen:
    def __init__(self, name: str, geometry: _FakeGeometry, pixmap: _FakePixmap) -> None:
        self._name = name
        self._geometry = geometry
        self._pixmap = pixmap
        self.calls: list[tuple[int, int, int, int, int]] = []

    def name(self) -> str:
        return self._name

    def geometry(self) -> _FakeGeometry:
        return self._geometry

    def devicePixelRatio(self) -> float:
        return 1.25

    def grabWindow(self, window_id: int, x: int, y: int, width: int, height: int) -> _FakePixmap:
        self.calls.append((window_id, x, y, width, height))
        return self._pixmap


class _FakeApplication:
    def __init__(self, screens, primary_screen) -> None:
        self._screens = screens
        self._primary_screen = primary_screen

    def screens(self):
        return self._screens

    def primaryScreen(self):
        return self._primary_screen


class ScreenshotServiceTests(unittest.TestCase):
    def test_capture_exports_debug_artifacts(self) -> None:
        region = CaptureRegion(screen_name='Primary', x=140, y=180, width=300, height=120)
        pixmap = _FakePixmap(width=300, height=120)
        geometry = _FakeGeometry(x=100, y=150, width=1920, height=1080)
        screen = _FakeScreen('Primary', geometry, pixmap)
        app = _FakeApplication([screen], screen)

        root = Path(__file__).resolve().parents[1] / '.tmp-test' / f'screenshot-{uuid.uuid4().hex}'
        temp_path = root / 'temp'
        debug_path = root / 'debug'
        temp_path.mkdir(parents=True, exist_ok=True)
        debug_path.mkdir(parents=True, exist_ok=True)
        processed_path = temp_path / 'capture-123-preprocessed.png'

        def _fake_preprocess(source: Path) -> Path:
            processed_path.write_bytes(b'processed-image')
            return processed_path

        try:
            service = ScreenshotService(temp_dir=temp_path, debug_dir=debug_path)
            with patch('transprot.infra.screenshot.QGuiApplication.instance', return_value=app), patch(
                'transprot.infra.screenshot.preprocess_capture',
                side_effect=_fake_preprocess,
            ), patch('transprot.infra.screenshot.time.time', return_value=0.123):
                result = service.capture(region)

            self.assertEqual(result, processed_path)
            self.assertEqual(screen.calls, [(0, 40, 30, 300, 120)])

            bundle_dir = debug_path / 'capture-123'
            latest_dir = debug_path / 'latest'
            metadata = json.loads((bundle_dir / 'metadata.json').read_text(encoding='utf-8'))

            self.assertTrue((bundle_dir / 'raw.png').exists())
            self.assertTrue((bundle_dir / 'processed.png').exists())
            self.assertTrue((latest_dir / 'raw.png').exists())
            self.assertTrue((latest_dir / 'processed.png').exists())
            self.assertEqual(metadata['capture_region']['x'], 140)
            self.assertEqual(metadata['capture_region']['y'], 180)
            self.assertEqual(metadata['capture_region']['width'], 300)
            self.assertEqual(metadata['capture_region']['height'], 120)
            self.assertEqual(metadata['screen_geometry']['x'], 100)
            self.assertEqual(metadata['screen_geometry']['y'], 150)
            self.assertEqual(metadata['relative_capture_origin']['x'], 40)
            self.assertEqual(metadata['relative_capture_origin']['y'], 30)
            self.assertEqual(metadata['pixmap_size']['width'], 300)
            self.assertEqual(metadata['pixmap_size']['height'], 120)
            ocr_result = OCRResult(
                full_text='line one\nline two',
                lines=[OCRLine(text='line one', bbox=(1, 2, 3, 4)), OCRLine(text='line two', bbox=(5, 6, 7, 8))],
            )
            service.export_ocr_debug_artifacts(processed_path, ocr_result)
            metadata = json.loads((bundle_dir / 'metadata.json').read_text(encoding='utf-8'))
            ocr_payload = json.loads((bundle_dir / 'ocr.json').read_text(encoding='utf-8'))

            self.assertEqual((bundle_dir / 'ocr.txt').read_text(encoding='utf-8'), 'line one\nline two')
            self.assertEqual((latest_dir / 'ocr.txt').read_text(encoding='utf-8'), 'line one\nline two')
            self.assertEqual(ocr_payload['full_text'], 'line one\nline two')
            self.assertEqual(ocr_payload['lines'][0]['text'], 'line one')
            self.assertEqual(ocr_payload['lines'][1]['bbox'], [5, 6, 7, 8])
            self.assertTrue(metadata['ocr_text_path'].endswith('ocr.txt'))
            self.assertTrue(metadata['ocr_json_path'].endswith('ocr.json'))
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
