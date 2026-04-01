from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any

from transprot.core.errors import ConfigurationError, TranslationError
from transprot.core.models import AppConfig, TranslationProvider, TranslationResult
from transprot.core.text import normalize_translation_text


def build_translation_prompt(text: str, target_lang: str) -> list[dict[str, str]]:
    system_prompt = (
        "You are a screen translation assistant. "
        f"Detect the source language and translate the content into {target_lang}. "
        "Return translated text only. Do not explain. Preserve paragraph, list, and line breaks when possible."
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": text},
    ]


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
            last_error = exc
            if index == attempts - 1 or exc.code < 500:
                break
        except urllib.error.URLError as exc:
            last_error = exc
            if index == attempts - 1:
                break
        time.sleep(0.8)

    raise TranslationError(f"Translation request failed: {last_error}")


def _normalize_openai_url(base_url: str) -> str:
    cleaned = base_url.strip().rstrip("/")
    if not cleaned:
        raise ConfigurationError("API base URL is required.")
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
            content = message.get("content", "")
            if isinstance(content, list):
                chunks = [item.get("text", "") for item in content if isinstance(item, dict)]
                return normalize_translation_text("".join(chunks))
            return normalize_translation_text(str(content))

    output_text = payload.get("output_text")
    if isinstance(output_text, str):
        return normalize_translation_text(output_text)

    raise TranslationError("No translated text found in OpenAI-compatible response.")


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

    def translate(self, text: str, config: AppConfig) -> TranslationResult:
        raise NotImplementedError


class OpenAICompatibleTranslator(BaseTranslator):
    provider_name = TranslationProvider.OPENAI_COMPATIBLE.value

    def translate(self, text: str, config: AppConfig) -> TranslationResult:
        if not config.model:
            raise ConfigurationError("Model is required for OpenAI-compatible translation.")

        start = time.perf_counter()
        payload = {
            "model": config.model,
            "messages": build_translation_prompt(text, config.target_lang),
            "temperature": 0,
            "stream": False,
        }
        headers = {}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"
        response = _post_json(
            url=_normalize_openai_url(config.api_base_url),
            payload=payload,
            timeout_sec=config.timeout_sec,
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


class BasicHttpTranslator(BaseTranslator):
    provider_name = TranslationProvider.BASIC_HTTP.value

    def translate(self, text: str, config: AppConfig) -> TranslationResult:
        if not config.api_base_url.strip():
            raise ConfigurationError("API endpoint is required for basic translation mode.")

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
            raise TranslationError("No translated text found in basic API response.")
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

    def smoke_test(self, config: AppConfig) -> TranslationResult:
        return self.translate("Hello world", config)
