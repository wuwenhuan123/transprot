from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum


class TranslationProvider(str, Enum):
    OPENAI_COMPATIBLE = "openai_compatible"
    BASIC_HTTP = "basic_http"


DEFAULT_HOTKEY = "Ctrl+Alt+T"
DEFAULT_CLEAR_HOTKEY = "Ctrl+Alt+C"
DEFAULT_OPENAI_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_OPENAI_MODEL = "qwen-mt-flash"
DEFAULT_TIMEOUT_SEC = 60
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_SOURCE_LANG = "auto"
DEFAULT_TARGET_LANG = "zh-CN"


def coerce_translation_provider(value: object) -> TranslationProvider:
    if isinstance(value, TranslationProvider):
        return value
    try:
        return TranslationProvider(str(value).strip())
    except ValueError:
        return TranslationProvider.OPENAI_COMPATIBLE


@dataclass(slots=True)
class CaptureRegion:
    screen_name: str
    x: int
    y: int
    width: int
    height: int

    @property
    def rect(self) -> tuple[int, int, int, int]:
        return self.x, self.y, self.width, self.height

    def to_dict(self) -> dict[str, object]:
        return {
            "screen_name": self.screen_name,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "CaptureRegion":
        return cls(
            screen_name=str(payload.get("screen_name", "")),
            x=int(payload.get("x", 0)),
            y=int(payload.get("y", 0)),
            width=int(payload.get("width", 0)),
            height=int(payload.get("height", 0)),
        )


@dataclass(slots=True)
class AppConfig:
    hotkey: str = DEFAULT_HOTKEY
    clear_hotkey: str = DEFAULT_CLEAR_HOTKEY
    translation_provider: TranslationProvider = TranslationProvider.OPENAI_COMPATIBLE
    api_base_url: str = DEFAULT_OPENAI_BASE_URL
    api_key: str = ""
    model: str = DEFAULT_OPENAI_MODEL
    timeout_sec: int = DEFAULT_TIMEOUT_SEC
    log_level: str = DEFAULT_LOG_LEVEL
    source_lang: str = DEFAULT_SOURCE_LANG
    target_lang: str = DEFAULT_TARGET_LANG
    capture_region: CaptureRegion | None = None

    def __post_init__(self) -> None:
        self.translation_provider = coerce_translation_provider(self.translation_provider)

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        provider = coerce_translation_provider(self.translation_provider)
        payload["translation_provider"] = provider.value
        payload["capture_region"] = (
            self.capture_region.to_dict() if self.capture_region is not None else None
        )
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "AppConfig":
        provider = payload.get("translation_provider", TranslationProvider.OPENAI_COMPATIBLE.value)
        capture_region_payload = payload.get("capture_region")
        translation_provider = coerce_translation_provider(provider)
        return cls(
            hotkey=_sanitize_saved_string(payload.get("hotkey"), DEFAULT_HOTKEY),
            clear_hotkey=_sanitize_saved_string(payload.get("clear_hotkey"), DEFAULT_CLEAR_HOTKEY),
            translation_provider=translation_provider,
            api_base_url=_sanitize_saved_string(
                payload.get("api_base_url"),
                DEFAULT_OPENAI_BASE_URL,
            ),
            api_key=_sanitize_saved_string(payload.get("api_key"), ""),
            model=_sanitize_saved_string(payload.get("model"), DEFAULT_OPENAI_MODEL),
            timeout_sec=_coerce_int(payload.get("timeout_sec"), DEFAULT_TIMEOUT_SEC),
            log_level=_sanitize_saved_string(payload.get("log_level"), DEFAULT_LOG_LEVEL),
            source_lang=_sanitize_saved_string(payload.get("source_lang"), DEFAULT_SOURCE_LANG),
            target_lang=_sanitize_saved_string(payload.get("target_lang"), DEFAULT_TARGET_LANG),
            capture_region=(
                CaptureRegion.from_dict(capture_region_payload)
                if isinstance(capture_region_payload, dict)
                else None
            ),
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


def _sanitize_saved_string(value: object, default: str) -> str:
    if value is None:
        return default
    text = str(value).strip()
    if not text or text.startswith("<member '"):
        return default
    return text


def _coerce_int(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
