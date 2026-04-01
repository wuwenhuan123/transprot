from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from transprot.core.config import AppConfigStore, resolve_config_path, resolve_log_dir


def _dependency_state() -> dict[str, bool]:
    modules = ["PySide6", "PIL", "paddleocr"]
    return {name: importlib.util.find_spec(name) is not None for name in modules}


def run_self_check() -> None:
    store = AppConfigStore()
    config_path = resolve_config_path()
    log_dir = resolve_log_dir()
    config_exists = config_path.exists()
    config = store.load()
    payload = {
        "config_path": str(config_path),
        "config_exists": config_exists,
        "log_dir": str(log_dir),
        "dependencies": _dependency_state(),
        "provider": config.translation_provider.value,
        "hotkey": config.hotkey,
        "api_base_url": config.api_base_url,
        "model": config.model,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))

