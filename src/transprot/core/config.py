from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from transprot.core.models import AppConfig
from transprot.core.secrets import SecretStore, create_secret_store

APP_NAME = "TransProt"
logger = logging.getLogger(__name__)


def _resolve_windows_dir(env_name: str, fallback: str) -> Path:
    base = os.getenv(env_name)
    if base:
        return Path(base)
    return Path.home() / fallback


def resolve_config_path() -> Path:
    return _resolve_windows_dir("APPDATA", "AppData/Roaming") / APP_NAME / "config.json"


def resolve_log_dir() -> Path:
    return _resolve_windows_dir("LOCALAPPDATA", "AppData/Local") / APP_NAME / "logs"


def resolve_debug_capture_dir() -> Path:
    return _resolve_windows_dir("LOCALAPPDATA", "AppData/Local") / APP_NAME / "debug-captures"


class AppConfigStore:
    def __init__(self, config_path: Path | None = None, secret_store: SecretStore | None = None) -> None:
        self._config_path = config_path or resolve_config_path()
        self._secret_store = secret_store or create_secret_store()

    @property
    def config_path(self) -> Path:
        return self._config_path

    def load(self) -> AppConfig:
        raw: dict[str, object] = {}
        if self._config_path.exists():
            raw = json.loads(self._config_path.read_text(encoding="utf-8"))

        config = AppConfig.from_dict(raw)
        legacy_api_key = config.api_key.strip()
        stored_api_key = self._secret_store.load_api_key().strip()
        had_plaintext_api_key = "api_key" in raw
        persisted_saved_flag = bool(raw.get("api_key_saved", False))

        if legacy_api_key:
            if stored_api_key != legacy_api_key:
                self._secret_store.save_api_key(legacy_api_key)
            stored_api_key = legacy_api_key
            logger.info("已完成旧配置中的 API Key 迁移。")

        config.api_key = stored_api_key
        config.api_key_saved = bool(stored_api_key)

        if had_plaintext_api_key or config.api_key_saved != persisted_saved_flag:
            self._write_public_config(config)

        return config

    def save(self, config: AppConfig) -> None:
        normalized_key = config.api_key.strip()
        current_saved_key = self._secret_store.load_api_key().strip()

        if normalized_key:
            if current_saved_key != normalized_key:
                self._secret_store.save_api_key(normalized_key)
            config.api_key_saved = True
        elif not config.api_key_saved:
            if current_saved_key:
                self._secret_store.clear_api_key()
            config.api_key_saved = False
        else:
            config.api_key_saved = bool(current_saved_key)

        self._write_public_config(config)

    def _write_public_config(self, config: AppConfig) -> None:
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(
            json.dumps(config.to_dict(include_api_key=False), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
