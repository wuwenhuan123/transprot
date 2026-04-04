from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum

_DEFAULT_HOTKEY = "Ctrl+Alt+T"
_DEFAULT_BAILIAN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
_DEFAULT_BAILIAN_MODEL = "qwen-mt-flash"
_DEFAULT_TIMEOUT_SEC = 60
_DEFAULT_LOG_LEVEL = "INFO"
_DEFAULT_SOURCE_LANG = "auto"
_DEFAULT_TARGET_LANG = "zh-CN"


class TranslationProvider(str, Enum):
    OPENAI_COMPATIBLE = "openai_compatible"
    BASIC_HTTP = "basic_http"


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
    hotkey: str = _DEFAULT_HOTKEY
    translation_provider: TranslationProvider = TranslationProvider.OPENAI_COMPATIBLE
    api_base_url: str = _DEFAULT_BAILIAN_BASE_URL
    api_key: str = ""
    api_key_saved: bool = False
    model: str = _DEFAULT_BAILIAN_MODEL
    timeout_sec: int = _DEFAULT_TIMEOUT_SEC
    log_level: str = _DEFAULT_LOG_LEVEL
    source_lang: str = _DEFAULT_SOURCE_LANG
    target_lang: str = _DEFAULT_TARGET_LANG
    capture_region: CaptureRegion | None = None

    def to_dict(self, include_api_key: bool = True) -> dict[str, object]:
        payload = asdict(self)
        payload["translation_provider"] = self.translation_provider.value
        payload["capture_region"] = (
            self.capture_region.to_dict() if self.capture_region is not None else None
        )
        if not include_api_key:
            payload.pop("api_key", None)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "AppConfig":
        provider = payload.get("translation_provider", TranslationProvider.OPENAI_COMPATIBLE.value)
        capture_region_payload = payload.get("capture_region")
        return cls(
            hotkey=_coerce_string(payload.get("hotkey"), _DEFAULT_HOTKEY),
            translation_provider=TranslationProvider(str(provider)),
            api_base_url=_coerce_string(payload.get("api_base_url"), _DEFAULT_BAILIAN_BASE_URL),
            api_key=_coerce_string(payload.get("api_key"), ""),
            api_key_saved=_coerce_bool(payload.get("api_key_saved"), False),
            model=_coerce_string(payload.get("model"), _DEFAULT_BAILIAN_MODEL),
            timeout_sec=_coerce_int(payload.get("timeout_sec"), _DEFAULT_TIMEOUT_SEC),
            log_level=_coerce_string(payload.get("log_level"), _DEFAULT_LOG_LEVEL),
            source_lang=_coerce_string(payload.get("source_lang"), _DEFAULT_SOURCE_LANG),
            target_lang=_coerce_string(payload.get("target_lang"), _DEFAULT_TARGET_LANG),
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


def _coerce_string(value: object, default: str) -> str:
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


def _coerce_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
    if value is None:
        return default
    return bool(value)
