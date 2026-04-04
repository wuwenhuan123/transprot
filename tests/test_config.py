from __future__ import annotations

import json
import unittest
from pathlib import Path

from transprot.core.config import AppConfigStore
from transprot.core.models import AppConfig, CaptureRegion, TranslationProvider


class _FakeSecretStore:
    def __init__(self, api_key: str = "") -> None:
        self.api_key = api_key
        self.save_calls: list[str] = []
        self.clear_calls = 0

    def load_api_key(self) -> str:
        return self.api_key

    def save_api_key(self, api_key: str) -> None:
        self.api_key = api_key
        self.save_calls.append(api_key)

    def clear_api_key(self) -> None:
        self.api_key = ""
        self.clear_calls += 1

    def has_api_key(self) -> bool:
        return bool(self.api_key)


class ConfigStoreTests(unittest.TestCase):
    def test_save_and_load_roundtrip_uses_secret_store(self) -> None:
        workspace_tmp = Path(__file__).resolve().parents[1] / ".tmp-tests"
        workspace_tmp.mkdir(exist_ok=True)
        config_path = workspace_tmp / "config-roundtrip.json"
        if config_path.exists():
            config_path.unlink()

        secret_store = _FakeSecretStore()
        store = AppConfigStore(config_path, secret_store=secret_store)
        config = AppConfig(
            hotkey="Ctrl+Shift+T",
            translation_provider=TranslationProvider.BASIC_HTTP,
            api_base_url="https://example.com/translate",
            api_key="secret",
            api_key_saved=False,
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
        saved_payload = json.loads(config_path.read_text(encoding="utf-8"))
        loaded = store.load()

        self.assertNotIn("api_key", saved_payload)
        self.assertEqual(saved_payload["api_key_saved"], True)
        self.assertEqual(secret_store.api_key, "secret")
        self.assertEqual(loaded.hotkey, "Ctrl+Shift+T")
        self.assertEqual(loaded.translation_provider, TranslationProvider.BASIC_HTTP)
        self.assertEqual(loaded.api_base_url, "https://example.com/translate")
        self.assertEqual(loaded.api_key, "secret")
        self.assertTrue(loaded.api_key_saved)
        self.assertEqual(loaded.timeout_sec, 45)
        self.assertEqual(loaded.capture_region, config.capture_region)

        if config_path.exists():
            config_path.unlink()

    def test_load_migrates_plaintext_api_key_from_legacy_config(self) -> None:
        workspace_tmp = Path(__file__).resolve().parents[1] / ".tmp-tests"
        workspace_tmp.mkdir(exist_ok=True)
        config_path = workspace_tmp / "config-legacy.json"
        if config_path.exists():
            config_path.unlink()

        config_path.write_text(
            json.dumps(
                {
                    "api_base_url": "https://example.com/translate",
                    "api_key": "legacy-secret",
                    "model": "qwen-test",
                    "timeout_sec": 30,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        secret_store = _FakeSecretStore()
        store = AppConfigStore(config_path, secret_store=secret_store)
        loaded = store.load()
        saved_payload = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual(secret_store.save_calls, ["legacy-secret"])
        self.assertEqual(loaded.api_key, "legacy-secret")
        self.assertTrue(loaded.api_key_saved)
        self.assertNotIn("api_key", saved_payload)
        self.assertEqual(saved_payload["api_key_saved"], True)

        if config_path.exists():
            config_path.unlink()

    def test_save_clears_secret_when_config_marks_api_key_unsaved(self) -> None:
        workspace_tmp = Path(__file__).resolve().parents[1] / ".tmp-tests"
        workspace_tmp.mkdir(exist_ok=True)
        config_path = workspace_tmp / "config-clear.json"
        if config_path.exists():
            config_path.unlink()

        secret_store = _FakeSecretStore(api_key="saved-secret")
        store = AppConfigStore(config_path, secret_store=secret_store)
        store.save(AppConfig(api_key="", api_key_saved=False))
        saved_payload = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual(secret_store.api_key, "")
        self.assertEqual(secret_store.clear_calls, 1)
        self.assertEqual(saved_payload["api_key_saved"], False)
        self.assertNotIn("api_key", saved_payload)

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
        self.assertFalse(loaded.api_key_saved)


if __name__ == "__main__":
    unittest.main()
