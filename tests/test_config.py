from __future__ import annotations

import unittest
from pathlib import Path

from transprot.core.config import AppConfigStore
from transprot.core.models import AppConfig, CaptureRegion, TranslationProvider


class ConfigStoreTests(unittest.TestCase):
    def test_save_and_load_roundtrip(self) -> None:
        workspace_tmp = Path(__file__).resolve().parents[1] / ".tmp-tests"
        workspace_tmp.mkdir(exist_ok=True)
        config_path = workspace_tmp / "config-roundtrip.json"
        if config_path.exists():
            config_path.unlink()

        store = AppConfigStore(config_path)
        config = AppConfig(
            hotkey="Ctrl+Shift+T",
            translation_provider=TranslationProvider.BASIC_HTTP,
            api_base_url="https://example.com/translate",
            api_key="secret",
            model="",
            timeout_sec=45,
            auto_mode_enabled=True,
            capture_region=CaptureRegion(
                screen_name="Display-1",
                x=120,
                y=80,
                width=640,
                height=280,
            ),
        )
        store.save(config)
        loaded = store.load()

        self.assertEqual(loaded.hotkey, "Ctrl+Shift+T")
        self.assertEqual(loaded.translation_provider, TranslationProvider.BASIC_HTTP)
        self.assertEqual(loaded.api_base_url, "https://example.com/translate")
        self.assertEqual(loaded.timeout_sec, 45)
        self.assertTrue(loaded.auto_mode_enabled)
        self.assertEqual(loaded.capture_region, config.capture_region)

        if config_path.exists():
            config_path.unlink()


if __name__ == "__main__":
    unittest.main()
