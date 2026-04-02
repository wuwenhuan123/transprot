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
        self.assertEqual(loaded.api_key, "secret")
        self.assertEqual(loaded.timeout_sec, 45)
        self.assertEqual(loaded.capture_region, config.capture_region)

        if config_path.exists():
            config_path.unlink()

    def test_from_dict_recovers_from_member_descriptor_strings(self) -> None:
        loaded = AppConfig.from_dict(
            {
                "hotkey": "<member 'hotkey' of 'AppConfig' objects>",
                "api_base_url": "<member 'api_base_url' of 'AppConfig' objects>",
                "model": "<member 'model' of 'AppConfig' objects>",
            }
        )

        self.assertEqual(loaded.hotkey, "Ctrl+Alt+T")
        self.assertEqual(loaded.api_base_url, "https://dashscope.aliyuncs.com/compatible-mode/v1")
        self.assertEqual(loaded.model, "qwen-mt-flash")


if __name__ == "__main__":
    unittest.main()

