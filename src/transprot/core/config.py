from __future__ import annotations

import json
import os
from pathlib import Path

from transprot.core.models import AppConfig

APP_NAME = "TransProt"


def _resolve_windows_dir(env_name: str, fallback: str) -> Path:
    base = os.getenv(env_name)
    if base:
        return Path(base)
    return Path.home() / fallback


def resolve_config_path() -> Path:
    return _resolve_windows_dir("APPDATA", "AppData/Roaming") / APP_NAME / "config.json"


def resolve_log_dir() -> Path:
    return _resolve_windows_dir("LOCALAPPDATA", "AppData/Local") / APP_NAME / "logs"


class AppConfigStore:
    def __init__(self, config_path: Path | None = None) -> None:
        self._config_path = config_path or resolve_config_path()

    @property
    def config_path(self) -> Path:
        return self._config_path

    def load(self) -> AppConfig:
        if not self._config_path.exists():
            return AppConfig()
        raw = json.loads(self._config_path.read_text(encoding="utf-8"))
        return AppConfig.from_dict(raw)

    def save(self, config: AppConfig) -> None:
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(
            json.dumps(config.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

