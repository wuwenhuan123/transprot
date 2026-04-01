from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum


class TranslationProvider(str, Enum):
    OPENAI_COMPATIBLE = "openai_compatible"
    BASIC_HTTP = "basic_http"


@dataclass(slots=True)
class AppConfig:
    hotkey: str = "Ctrl+Alt+T"
    translation_provider: TranslationProvider = TranslationProvider.OPENAI_COMPATIBLE
    api_base_url: str = ""
    api_key: str = ""
    model: str = ""
    timeout_sec: int = 30
    log_level: str = "INFO"
    source_lang: str = "auto"
    target_lang: str = "zh-CN"

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["translation_provider"] = self.translation_provider.value
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "AppConfig":
        provider = payload.get("translation_provider", TranslationProvider.OPENAI_COMPATIBLE.value)
        return cls(
            hotkey=str(payload.get("hotkey", cls.hotkey)),
            translation_provider=TranslationProvider(str(provider)),
            api_base_url=str(payload.get("api_base_url", "")),
            api_key=str(payload.get("api_key", "")),
            model=str(payload.get("model", "")),
            timeout_sec=int(payload.get("timeout_sec", 30)),
            log_level=str(payload.get("log_level", "INFO")),
            source_lang=str(payload.get("source_lang", "auto")),
            target_lang=str(payload.get("target_lang", "zh-CN")),
        )


@dataclass(slots=True)
class SelectionRegion:
    screen_name: str
    x: int
    y: int
    width: int
    height: int
    device_pixel_ratio: float = 1.0

    @property
    def rect(self) -> tuple[int, int, int, int]:
        return self.x, self.y, self.width, self.height


@dataclass(slots=True)
class OCRLine:
    text: str
    bbox: tuple[int, int, int, int] = (0, 0, 0, 0)


@dataclass(slots=True)
class OCRResult:
    full_text: str
    lines: list[OCRLine] = field(default_factory=list)
    image_size: tuple[int, int] = (0, 0)
    provider: str = "paddleocr"


@dataclass(slots=True)
class TranslationResult:
    source_text: str
    translated_text: str
    provider: str
    latency_ms: int

