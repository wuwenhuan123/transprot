from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from transprot.core.errors import ConfigurationError, TranslationError
from transprot.core.models import AppConfig, TranslationProvider, TranslationResult
from transprot.core.text import normalize_translation_text

DEFAULT_BAILIAN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_BAILIAN_MODEL = "qwen-mt-flash"
MIN_TRANSLATION_TIMEOUT_SEC = 60
MIN_MODEL_LIST_TIMEOUT_SEC = 20
TIMEOUT_ERROR_MESSAGE = "请求超时，请稍后重试，或在设置中调大超时时间。"
RECOMMENDED_TEXT_MODELS: tuple[str, ...] = (
    DEFAULT_BAILIAN_MODEL,
    "qwen-mt-plus",
    "qwen-mt-turbo",
    "qwen3.5-flash",
    "qwen3.5-plus",
    "qwen3-max",
    "qwen-flash",
    "qwen-plus",
    "qwen-max",
    "qwen-turbo",
)


def build_translation_prompt(text: str, target_lang: str) -> list[dict[str, str]]:
    system_prompt = (
        "你是一名屏幕翻译助手。"
        "用户输入来自 OCR，可能包含少量识别错误。"
        f"请自动判断原文语言，并将内容翻译成 {target_lang}。"
        "尽量保留段落、换行、项目符号和列表顺序。"
        "只返回译文，不要解释，不要补充说明。"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": text},
    ]


def _build_qwen_mt_user_message(text: str, target_lang: str) -> str:
    return (
        f"请将下面这段 OCR 文本翻译成 {target_lang}。"
        "原文可能存在少量 OCR 识别误差，请在不改变原意的前提下适当修正。"
        "尽量保留段落、换行、项目符号和列表顺序。"
        "只返回译文，不要解释，不要补充说明。\n\n"
        f"{text}"
    )


def _build_openai_messages(text: str, target_lang: str, model: str) -> list[dict[str, str]]:
    normalized_model = model.strip().lower()
    if normalized_model.startswith("qwen-mt"):
        return [{"role": "user", "content": _build_qwen_mt_user_message(text, target_lang)}]
    return build_translation_prompt(text, target_lang)


def _build_request(
    url: str,
    method: str,
    payload: Mapping[str, Any] | None,
    headers: Mapping[str, str] | None,
) -> urllib.request.Request:
    final_headers = {"Content-Type": "application/json", **(headers or {})}
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    return urllib.request.Request(
        url=url,
        data=data,
        headers=final_headers,
        method=method,
    )


def _extract_remote_error_detail(detail: str) -> str:
    cleaned = detail.strip()
    if not cleaned:
        return "请求失败。"
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        return _localize_error_message(cleaned)
    error_message = _extract_openai_error_message(payload)
    if error_message:
        return error_message
    return _localize_error_message(cleaned)


def _request_json(
    url: str,
    timeout_sec: int,
    method: str = "POST",
    payload: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
    retry_once: bool = True,
) -> dict[str, Any]:
    request = _build_request(url, method, payload, headers)

    attempts = 2 if retry_once else 1
    last_error: Exception | None = None
    for index in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=timeout_sec) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore").strip()
            last_error = TranslationError(_extract_remote_error_detail(detail or str(exc)))
            if index == attempts - 1 or exc.code < 500:
                break
        except (TimeoutError, socket.timeout):
            last_error = TranslationError(TIMEOUT_ERROR_MESSAGE)
            if index == attempts - 1:
                break
        except urllib.error.URLError as exc:
            if _is_timeout_error(exc):
                last_error = TranslationError(TIMEOUT_ERROR_MESSAGE)
            else:
                last_error = exc
            if index == attempts - 1:
                break
        time.sleep(0.8)

    if isinstance(last_error, TranslationError):
        raise last_error
    raise TranslationError(f"请求失败：{_localize_error_message(str(last_error))}")


def _stream_json(
    url: str,
    timeout_sec: int,
    payload: Mapping[str, Any],
    headers: Mapping[str, str] | None = None,
    retry_once: bool = True,
) -> Iterable[dict[str, Any]]:
    request_headers = {"Accept": "text/event-stream", **(headers or {})}
    request = _build_request(url, "POST", payload, request_headers)

    attempts = 2 if retry_once else 1
    last_error: Exception | None = None
    for index in range(attempts):
        emitted_chunks = False
        try:
            with urllib.request.urlopen(request, timeout=timeout_sec) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="ignore").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data:
                        continue
                    if data == "[DONE]":
                        return
                    emitted_chunks = True
                    yield json.loads(data)
                return
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore").strip()
            last_error = TranslationError(_extract_remote_error_detail(detail or str(exc)))
            if emitted_chunks or index == attempts - 1 or exc.code < 500:
                break
        except (TimeoutError, socket.timeout):
            last_error = TranslationError(TIMEOUT_ERROR_MESSAGE)
            if emitted_chunks or index == attempts - 1:
                break
        except urllib.error.URLError as exc:
            if _is_timeout_error(exc):
                last_error = TranslationError(TIMEOUT_ERROR_MESSAGE)
            else:
                last_error = exc
            if emitted_chunks or index == attempts - 1:
                break
        time.sleep(0.8)

    if isinstance(last_error, TranslationError):
        raise last_error
    raise TranslationError(f"请求失败：{_localize_error_message(str(last_error))}")


def _post_json(
    url: str,
    payload: Mapping[str, Any],
    timeout_sec: int,
    headers: Mapping[str, str] | None = None,
    retry_once: bool = True,
) -> dict[str, Any]:
    return _request_json(
        url=url,
        timeout_sec=timeout_sec,
        method="POST",
        payload=payload,
        headers=headers,
        retry_once=retry_once,
    )


def _normalize_openai_url(base_url: str) -> str:
    cleaned = base_url.strip().rstrip("/")
    if not cleaned:
        raise ConfigurationError("接口地址不能为空。")
    if cleaned.endswith("/chat/completions"):
        return cleaned
    if cleaned.endswith("/v1"):
        return f"{cleaned}/chat/completions"
    return f"{cleaned}/chat/completions"


def _normalize_models_url(base_url: str) -> str:
    cleaned = base_url.strip().rstrip("/")
    if not cleaned:
        raise ConfigurationError("接口地址不能为空。")
    if cleaned.endswith("/models"):
        return cleaned
    if cleaned.endswith("/chat/completions"):
        prefix = cleaned[: -len("/chat/completions")]
        return f"{prefix}/models"
    if cleaned.endswith("/v1"):
        return f"{cleaned}/models"
    return f"{cleaned}/models"


def _localize_error_message(message: str) -> str:
    cleaned = message.strip()
    if not cleaned:
        return "请求失败。"

    exact_map = {
        "Role must be in [user, assistant].": "消息角色只支持 user 或 assistant。",
        "Required body invalid, please check the request body format.": "请求体格式无效，请检查请求参数。",
        "OpenAI-compatible API returned an error.": "翻译服务返回了错误。",
        "No translated text found in OpenAI-compatible response.": "翻译服务未返回可用译文。",
        "No translated text found in basic API response.": "翻译接口未返回可用译文。",
        "API Key is required to load models.": "请先填写 API 密钥后再加载模型列表。",
        "API base URL is required.": "接口地址不能为空。",
        "Model is required for OpenAI-compatible translation.": "请先填写翻译模型名称。",
        "API endpoint is required for basic translation mode.": "通用翻译接口模式需要填写接口地址。",
        "No model list found in OpenAI-compatible response.": "翻译服务未返回模型列表。",
    }
    if cleaned in exact_map:
        return exact_map[cleaned]

    if cleaned.startswith("Request failed:"):
        return f"请求失败：{cleaned.split(':', 1)[1].strip()}"
    if "timed out" in cleaned.lower():
        return TIMEOUT_ERROR_MESSAGE
    if cleaned.startswith("<urlopen error"):
        return f"网络请求失败：{cleaned.removeprefix('<urlopen error').rstrip('>').strip()}"
    return cleaned


def _extract_openai_error_message(payload: Any) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    error = payload.get("error")
    if isinstance(error, str) and error.strip():
        return _localize_error_message(error.strip())
    if not isinstance(error, Mapping):
        return None
    for key in ("message", "code", "type"):
        value = error.get(key)
        if isinstance(value, str) and value.strip():
            return _localize_error_message(value.strip())
    return "翻译服务返回了错误。"


def _extract_text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, Mapping):
        for key in ("text", "content"):
            extracted = _extract_text_content(content.get(key))
            if extracted:
                return extracted
        return ""
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            piece = _extract_text_content(item)
            if piece:
                parts.append(piece)
        return "".join(parts)
    return ""


def _extract_openai_text(payload: dict[str, Any]) -> str:
    error_message = _extract_openai_error_message(payload)
    if error_message:
        raise TranslationError(error_message)

    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first_choice = choices[0]
        if isinstance(first_choice, Mapping):
            for field in ("message", "delta"):
                container = first_choice.get(field)
                if isinstance(container, Mapping):
                    content = _extract_text_content(container.get("content"))
                    if content:
                        return normalize_translation_text(content)
                    text_value = _extract_text_content(container.get("text"))
                    if text_value:
                        return normalize_translation_text(text_value)
            choice_text = _extract_text_content(first_choice.get("text"))
            if choice_text:
                return normalize_translation_text(choice_text)

    output_text = _extract_text_content(payload.get("output_text"))
    if output_text:
        return normalize_translation_text(output_text)

    translated = _walk_for_text(payload)
    if translated:
        return normalize_translation_text(translated)

    raise TranslationError("翻译服务未返回可用译文。")


def _extract_stream_delta_text(payload: Mapping[str, Any]) -> str:
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first_choice = choices[0]
        if isinstance(first_choice, Mapping):
            for field in ("delta", "message"):
                container = first_choice.get(field)
                if isinstance(container, Mapping):
                    content = _extract_text_content(container.get("content"))
                    if content:
                        return content
                    text_value = _extract_text_content(container.get("text"))
                    if text_value:
                        return text_value
            choice_text = _extract_text_content(first_choice.get("text"))
            if choice_text:
                return choice_text

    output_text = _extract_text_content(payload.get("output_text"))
    if output_text:
        return output_text
    return ""


def _walk_for_text(payload: Any) -> str | None:
    keys = {"translatedText", "translation", "translated_text", "text"}
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value
        for value in payload.values():
            result = _walk_for_text(value)
            if result:
                return result
    if isinstance(payload, list):
        for item in payload:
            result = _walk_for_text(item)
            if result:
                return result
    return None


def _extract_model_ids(payload: Mapping[str, Any]) -> list[str]:
    data = payload.get("data")
    if not isinstance(data, list):
        raise TranslationError("翻译服务未返回模型列表。")

    model_ids: list[str] = []
    for item in data:
        if not isinstance(item, Mapping):
            continue
        model_id = item.get("id")
        if isinstance(model_id, str) and model_id.strip():
            model_ids.append(model_id.strip())
    return _unique_strings(model_ids)


def _unique_strings(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        cleaned = value.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        ordered.append(cleaned)
    return ordered


def _effective_timeout(timeout_sec: int, minimum_sec: int) -> int:
    return max(int(timeout_sec), minimum_sec)


def _is_timeout_error(exc: urllib.error.URLError) -> bool:
    reason = getattr(exc, "reason", None)
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return True
    if isinstance(reason, str) and "timed out" in reason.lower():
        return True
    if isinstance(exc, TimeoutError):
        return True
    return "timed out" in str(exc).lower()


def filter_recommended_text_models(model_ids: Iterable[str]) -> list[str]:
    available = set(_unique_strings(model_ids))
    filtered = [model_name for model_name in RECOMMENDED_TEXT_MODELS if model_name in available]
    return filtered or list(RECOMMENDED_TEXT_MODELS)


def fetch_openai_compatible_model_ids(base_url: str, api_key: str, timeout_sec: int) -> list[str]:
    if not api_key.strip():
        raise ConfigurationError("请先填写 API 密钥后再加载模型列表。")

    response = _request_json(
        url=_normalize_models_url(base_url),
        timeout_sec=_effective_timeout(timeout_sec, MIN_MODEL_LIST_TIMEOUT_SEC),
        method="GET",
        headers={"Authorization": f"Bearer {api_key.strip()}"},
        retry_once=True,
    )
    return _extract_model_ids(response)


def load_recommended_model_options(base_url: str, api_key: str, timeout_sec: int) -> tuple[list[str], str]:
    if not api_key.strip():
        return list(RECOMMENDED_TEXT_MODELS), "未填写 API 密钥，已使用默认模型列表。"

    model_ids = fetch_openai_compatible_model_ids(base_url, api_key, timeout_sec)
    models = filter_recommended_text_models(model_ids)
    return models, f"已加载 {len(models)} 个推荐模型。"


class BaseTranslator:
    provider_name = "base"

    def translate(self, text: str, config: AppConfig) -> TranslationResult:
        raise NotImplementedError

    def translate_stream(
        self,
        text: str,
        config: AppConfig,
        on_progress: Callable[[str], None] | None = None,
    ) -> TranslationResult:
        result = self.translate(text, config)
        if on_progress is not None:
            on_progress(result.translated_text)
        return result


class OpenAICompatibleTranslator(BaseTranslator):
    provider_name = TranslationProvider.OPENAI_COMPATIBLE.value

    def translate(self, text: str, config: AppConfig) -> TranslationResult:
        if not config.model:
            raise ConfigurationError("请先填写翻译模型名称。")

        start = time.perf_counter()
        payload = {
            "model": config.model,
            "messages": _build_openai_messages(text, config.target_lang, config.model),
            "temperature": 0,
            "stream": False,
        }
        headers = {}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"
        response = _post_json(
            url=_normalize_openai_url(config.api_base_url),
            payload=payload,
            timeout_sec=_effective_timeout(config.timeout_sec, MIN_TRANSLATION_TIMEOUT_SEC),
            headers=headers,
            retry_once=True,
        )
        translated = _extract_openai_text(response)
        elapsed = int((time.perf_counter() - start) * 1000)
        return TranslationResult(
            source_text=text,
            translated_text=translated,
            provider=self.provider_name,
            latency_ms=elapsed,
        )

    def translate_stream(
        self,
        text: str,
        config: AppConfig,
        on_progress: Callable[[str], None] | None = None,
    ) -> TranslationResult:
        if not config.model:
            raise ConfigurationError("请先填写翻译模型名称。")

        start = time.perf_counter()
        payload = {
            "model": config.model,
            "messages": _build_openai_messages(text, config.target_lang, config.model),
            "temperature": 0,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        headers = {}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"

        content_parts: list[str] = []
        for chunk in _stream_json(
            url=_normalize_openai_url(config.api_base_url),
            payload=payload,
            timeout_sec=_effective_timeout(config.timeout_sec, MIN_TRANSLATION_TIMEOUT_SEC),
            headers=headers,
            retry_once=True,
        ):
            error_message = _extract_openai_error_message(chunk)
            if error_message:
                raise TranslationError(error_message)
            delta_text = _extract_stream_delta_text(chunk)
            if not delta_text:
                continue
            content_parts.append(delta_text)
            if on_progress is not None:
                on_progress("".join(content_parts))

        translated = normalize_translation_text("".join(content_parts))
        if not translated:
            raise TranslationError("翻译服务未返回可用译文。")

        elapsed = int((time.perf_counter() - start) * 1000)
        return TranslationResult(
            source_text=text,
            translated_text=translated,
            provider=self.provider_name,
            latency_ms=elapsed,
        )


class BasicHttpTranslator(BaseTranslator):
    provider_name = TranslationProvider.BASIC_HTTP.value

    def translate(self, text: str, config: AppConfig) -> TranslationResult:
        if not config.api_base_url.strip():
            raise ConfigurationError("通用翻译接口模式需要填写接口地址。")

        start = time.perf_counter()
        headers = {}
        payload: dict[str, Any] = {
            "q": text,
            "source": config.source_lang,
            "target": config.target_lang,
        }
        if config.api_key:
            payload["api_key"] = config.api_key
            headers["Authorization"] = f"Bearer {config.api_key}"

        response = _post_json(
            url=config.api_base_url.strip(),
            payload=payload,
            timeout_sec=config.timeout_sec,
            headers=headers,
            retry_once=True,
        )
        translated = _walk_for_text(response)
        if not translated:
            raise TranslationError("翻译接口未返回可用译文。")
        elapsed = int((time.perf_counter() - start) * 1000)
        return TranslationResult(
            source_text=text,
            translated_text=normalize_translation_text(translated),
            provider=self.provider_name,
            latency_ms=elapsed,
        )


class TranslatorRouter:
    def __init__(self) -> None:
        self._translators = {
            TranslationProvider.OPENAI_COMPATIBLE: OpenAICompatibleTranslator(),
            TranslationProvider.BASIC_HTTP: BasicHttpTranslator(),
        }

    def translate(self, text: str, config: AppConfig) -> TranslationResult:
        translator = self._translators[config.translation_provider]
        return translator.translate(text, config)

    def translate_stream(
        self,
        text: str,
        config: AppConfig,
        on_progress: Callable[[str], None] | None = None,
    ) -> TranslationResult:
        translator = self._translators[config.translation_provider]
        return translator.translate_stream(text, config, on_progress=on_progress)

    def smoke_test(self, config: AppConfig) -> TranslationResult:
        return self.translate("你好，世界", config)
