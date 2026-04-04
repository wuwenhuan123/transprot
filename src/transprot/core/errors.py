from __future__ import annotations


class TransProtError(RuntimeError):
    """应用基础异常。"""


class ConfigurationError(TransProtError):
    """配置无效时抛出。"""


class OCRUnavailableError(TransProtError):
    """OCR 依赖或运行环境不可用时抛出。"""


class TranslationError(TransProtError):
    """翻译失败时抛出。"""


class HotkeyError(TransProtError):
    """热键注册失败时抛出。"""


class SecretStoreError(TransProtError):
    """安全存储不可用或读写失败时抛出。"""
