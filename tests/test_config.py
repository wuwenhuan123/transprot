from __future__ import annotations

import unittest
from pathlib import Path

from transprot.core.config import AppConfigStore
from transprot.core.models import (
    AppConfig,
    CaptureRegion,
    DEFAULT_CLEAR_HOTKEY,
    DEFAULT_HOTKEY,
    DEFAULT_OPENAI_BASE_URL,
    DEFAULT_OPENAI_MODEL,
    TranslationProvider,
)


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
            clear_hotkey="Ctrl+Shift+C",
            translation_provider=TranslationProvider.BASIC_HTTP,
            api_base_url="https://example.com/translate",
            api_key="secret",
            model="custom-model",
            timeout_sec=45,
            target_lang="en",
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
        self.assertEqual(loaded.clear_hotkey, "Ctrl+Shift+C")
        self.assertEqual(loaded.translation_provider, TranslationProvider.BASIC_HTTP)
        self.assertEqual(loaded.api_base_url, "https://example.com/translate")
        self.assertEqual(loaded.api_key, "secret")
        self.assertEqual(loaded.model, "custom-model")
        self.assertEqual(loaded.timeout_sec, 45)
        self.assertEqual(loaded.target_lang, "en")
        self.assertEqual(loaded.capture_region, config.capture_region)

        if config_path.exists():
            config_path.unlink()

    def test_load_accepts_utf8_bom_config(self) -> None:
        workspace_tmp = Path(__file__).resolve().parents[1] / ".tmp-tests"
        workspace_tmp.mkdir(exist_ok=True)
        config_path = workspace_tmp / "config-bom.json"
        if config_path.exists():
            config_path.unlink()

        config_path.write_text('{"api_key":"secret","target_lang":"ja"}', encoding="utf-8-sig")
        store = AppConfigStore(config_path)

        loaded = store.load()

        self.assertEqual(loaded.api_key, "secret")
        self.assertEqual(loaded.target_lang, "ja")

        if config_path.exists():
            config_path.unlink()

    def test_from_dict_recovers_member_descriptor_defaults(self) -> None:
        config = AppConfig.from_dict(
            {
                "hotkey": "<member 'hotkey' of 'AppConfig' objects>",
                "clear_hotkey": "<member 'clear_hotkey' of 'AppConfig' objects>",
                "api_base_url": "<member 'api_base_url' of 'AppConfig' objects>",
                "model": "<member 'model' of 'AppConfig' objects>",
                "target_lang": "",
            }
        )

        self.assertEqual(config.hotkey, DEFAULT_HOTKEY)
        self.assertEqual(config.clear_hotkey, DEFAULT_CLEAR_HOTKEY)
        self.assertEqual(config.api_base_url, DEFAULT_OPENAI_BASE_URL)
        self.assertEqual(config.model, DEFAULT_OPENAI_MODEL)
        self.assertEqual(config.target_lang, "zh-CN")


if __name__ == "__main__":
    unittest.main()
