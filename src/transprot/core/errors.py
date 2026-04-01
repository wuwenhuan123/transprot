from __future__ import annotations


class TransProtError(RuntimeError):
    """Base application error."""


class ConfigurationError(TransProtError):
    """Raised when config is invalid."""


class OCRUnavailableError(TransProtError):
    """Raised when OCR dependencies are unavailable."""


class TranslationError(TransProtError):
    """Raised when translation fails."""


class HotkeyError(TransProtError):
    """Raised when hotkey registration fails."""
