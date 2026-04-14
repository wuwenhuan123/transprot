from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any

from transprot.core.errors import ConfigurationError, TranslationError
from transprot.core.models import AppConfig, TranslationProvider, TranslationResult
from transprot.core.text import normalize_translation_text

ProgressCallback = Callable[[str], None]

_REQUEST_FAILED = "翻译请求失败。"
_NO_TRANSLATED_TEXT = "翻译接口没有返回可用的译文。"
_OPENAI_BASE_URL_ERROR = "请先填写阿里云兼容接口地址。"
_OPENAI_API_KEY_ERROR = "请先填写 API 密钥。"
_OPENAI_MODEL_ERROR = "请先填写模型名称。"
_BASIC_HTTP_BASE_URL_ERROR = "请先填写通用翻译接口地址。"
_BASIC_HTTP_NO_TEXT_ERROR = "通用翻译接口没有返回可用的译文。"


def build_translation_prompt(text: str, target_lang: str) -> list[dict[str, str]]:
    user_prompt = (
        "你是屏幕翻译助手。\n"
        f"请自动识别原文语言，并把内容翻译成 {target_lang}。\n"
        "可以纠正少量 OCR 造成的空格、断句和换行噪声。\n"
        "只返回译文，不要解释，并尽量保留段落、列表和换行。\n\n"
        "原文：\n"
        f"{text}"
    )
    return [{"role": "user", "content": user_prompt}]


def _post_json(
    url: str,
    payload: Mapping[str, Any],
    timeout_sec: int,
    headers: Mapping[str, str] | None = None,
    retry_once: bool = True,
) -> dict[str, Any]:
    final_headers = {"Content-Type": "application/json", **(headers or {})}
    request = urllib.request.Request(
        url=url,
        data=json.dumps(payload).encode("utf-8"),
        headers=final_headers,
        method="POST",
    )

    attempts = 2 if retry_once else 1
    last_error: Exception | None = None
    for index in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=timeout_sec) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last_error = TranslationError(_http_error_message(exc))
            if index == attempts - 1 or exc.code < 500:
                break
        except urllib.error.URLError as exc:
            last_error = TranslationError(f"翻译请求失败：{exc.reason}")
            if index == attempts - 1:
                break
        time.sleep(0.8)

    raise TranslationError(str(last_error or _REQUEST_FAILED))


def _stream_json_events(
    url: str,
    payload: Mapping[str, Any],
    timeout_sec: int,
    headers: Mapping[str, str] | None = None,
    retry_once: bool = True,
):
    final_headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        **(headers or {}),
    }
    request = urllib.request.Request(
        url=url,
        data=json.dumps(payload).encode("utf-8"),
        headers=final_headers,
        method="POST",
    )

    attempts = 2 if retry_once else 1
    last_error: Exception | None = None
    for index in range(attempts):
        yielded_any = False
        try:
            with urllib.request.urlopen(request, timeout=timeout_sec) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data:
                        continue
                    if data == "[DONE]":
                        return
                    payload_item = json.loads(data)
                    error_message = _payload_error_message(payload_item)
                    if error_message:
                        raise TranslationError(error_message)
                    yielded_any = True
                    yield payload_item
                return
        except urllib.error.HTTPError as exc:
            last_error = TranslationError(_http_error_message(exc))
            if yielded_any or index == attempts - 1 or exc.code < 500:
                break
        except urllib.error.URLError as exc:
            last_error = TranslationError(f"翻译请求失败：{exc.reason}")
            if yielded_any or index == attempts - 1:
                break
        except TranslationError as exc:
            last_error = exc
            break
        time.sleep(0.8)

    raise TranslationError(str(last_error or _REQUEST_FAILED))


def _http_error_message(exc: urllib.error.HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8")
    except Exception:
        body = ""
    if body:
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            message = _payload_error_message(payload)
            if message:
                return message
    return f"翻译请求失败：HTTP {exc.code}"


def _payload_error_message(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message.strip():
            return f"翻译请求失败：{message.strip()}"
    return None


def _normalize_openai_url(base_url: str) -> str:
    cleaned = base_url.strip().rstrip("/")
    if not cleaned:
        raise ConfigurationError(_OPENAI_BASE_URL_ERROR)
    if cleaned.endswith("/chat/completions"):
        return cleaned
    if cleaned.endswith("/v1"):
        return f"{cleaned}/chat/completions"
    return f"{cleaned}/chat/completions"


def _extract_openai_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message", {})
        if isinstance(message, dict):
            return normalize_translation_text(_coerce_content_to_text(message.get("content", "")))

    output_text = payload.get("output_text")
    if isinstance(output_text, str):
        return normalize_translation_text(output_text)

    raise TranslationError(_NO_TRANSLATED_TEXT)


def _extract_openai_stream_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        choice = choices[0]
        if isinstance(choice, dict):
            delta = choice.get("delta") or choice.get("message") or {}
            if isinstance(delta, dict):
                return _coerce_content_to_text(delta.get("content", ""))
    return ""


def _coerce_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    chunks.append(text)
        return "".join(chunks)
    if content is None:
        return ""
    return str(content)


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


class BaseTranslator:
    provider_name = "base"

    def translate(
        self,
        text: str,
        config: AppConfig,
        progress_callback: ProgressCallback | None = None,
    ) -> TranslationResult:
        raise NotImplementedError


class OpenAICompatibleTranslator(BaseTranslator):
    provider_name = TranslationProvider.OPENAI_COMPATIBLE.value

    def translate(
        self,
        text: str,
        config: AppConfig,
        progress_callback: ProgressCallback | None = None,
    ) -> TranslationResult:
        if not config.model.strip():
            raise ConfigurationError(_OPENAI_MODEL_ERROR)
        if not config.api_key.strip():
            raise ConfigurationError(_OPENAI_API_KEY_ERROR)

        start = time.perf_counter()
        headers = {"Authorization": f"Bearer {config.api_key.strip()}"}
        url = _normalize_openai_url(config.api_base_url)
        payload = {
            "model": config.model.strip(),
            "messages": build_translation_prompt(text, config.target_lang),
            "temperature": 0,
            "stream": bool(progress_callback),
        }

        if progress_callback is None:
            response = _post_json(
                url=url,
                payload=payload,
                timeout_sec=config.timeout_sec,
                headers=headers,
                retry_once=True,
            )
            translated = _extract_openai_text(response)
        else:
            parts: list[str] = []
            for event in _stream_json_events(
                url=url,
                payload=payload,
                timeout_sec=config.timeout_sec,
                headers=headers,
                retry_once=True,
            ):
                chunk = _extract_openai_stream_text(event)
                if not chunk:
                    continue
                parts.append(chunk)
                progress_callback(normalize_translation_text("".join(parts)))
            translated = normalize_translation_text("".join(parts))
            if not translated:
                raise TranslationError(_NO_TRANSLATED_TEXT)

        elapsed = int((time.perf_counter() - start) * 1000)
        return TranslationResult(
            source_text=text,
            translated_text=translated,
            provider=self.provider_name,
            latency_ms=elapsed,
        )


class BasicHttpTranslator(BaseTranslator):
    provider_name = TranslationProvider.BASIC_HTTP.value

    def translate(
        self,
        text: str,
        config: AppConfig,
        progress_callback: ProgressCallback | None = None,
    ) -> TranslationResult:
        if not config.api_base_url.strip():
            raise ConfigurationError(_BASIC_HTTP_BASE_URL_ERROR)

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
            raise TranslationError(_BASIC_HTTP_NO_TEXT_ERROR)
        translated = normalize_translation_text(translated)
        if progress_callback is not None:
            progress_callback(translated)
        elapsed = int((time.perf_counter() - start) * 1000)
        return TranslationResult(
            source_text=text,
            translated_text=translated,
            provider=self.provider_name,
            latency_ms=elapsed,
        )


class TranslatorRouter:
    def __init__(self) -> None:
        self._translators = {
            TranslationProvider.OPENAI_COMPATIBLE: OpenAICompatibleTranslator(),
            TranslationProvider.BASIC_HTTP: BasicHttpTranslator(),
        }

    def translate(
        self,
        text: str,
        config: AppConfig,
        progress_callback: ProgressCallback | None = None,
    ) -> TranslationResult:
        translator = self._translators[config.translation_provider]
        return translator.translate(text, config, progress_callback=progress_callback)

    def smoke_test(self, config: AppConfig) -> TranslationResult:
        return self.translate("Hello world", config)
