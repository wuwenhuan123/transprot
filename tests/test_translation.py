from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from transprot.core.errors import TranslationError
from transprot.core.models import AppConfig
from transprot.services.translation import (
    DEFAULT_BAILIAN_BASE_URL,
    DEFAULT_BAILIAN_MODEL,
    MIN_MODEL_LIST_TIMEOUT_SEC,
    MIN_TRANSLATION_TIMEOUT_SEC,
    RECOMMENDED_TEXT_MODELS,
    TIMEOUT_ERROR_MESSAGE,
    _extract_openai_text,
    _extract_stream_delta_text,
    _normalize_models_url,
    _normalize_openai_url,
    _request_json,
    _walk_for_text,
    build_translation_prompt,
    fetch_openai_compatible_model_ids,
    filter_recommended_text_models,
    load_recommended_model_options,
    OpenAICompatibleTranslator,
)


class TranslationTests(unittest.TestCase):
    def test_prompt_targets_requested_language(self) -> None:
        prompt = build_translation_prompt("hello", "简体中文")
        self.assertIn("简体中文", prompt[0]["content"])
        self.assertIn("屏幕翻译助手", prompt[0]["content"])
        self.assertIn("只返回译文", prompt[0]["content"])
        self.assertEqual(prompt[1]["content"], "hello")

    def test_openai_url_normalization(self) -> None:
        self.assertEqual(
            _normalize_openai_url("https://example.com/v1"),
            "https://example.com/v1/chat/completions",
        )
        self.assertEqual(
            _normalize_openai_url(DEFAULT_BAILIAN_BASE_URL),
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        )

    def test_models_url_normalization(self) -> None:
        self.assertEqual(
            _normalize_models_url("https://example.com/v1"),
            "https://example.com/v1/models",
        )
        self.assertEqual(
            _normalize_models_url("https://example.com/v1/chat/completions"),
            "https://example.com/v1/models",
        )

    def test_extract_openai_text(self) -> None:
        payload = {"choices": [{"message": {"content": "hello"}}]}
        self.assertEqual(_extract_openai_text(payload), "hello")

    def test_extract_openai_text_surfaces_api_error(self) -> None:
        payload = {"error": {"message": "Role must be in [user, assistant]."}}

        with self.assertRaises(TranslationError) as ctx:
            _extract_openai_text(payload)

        self.assertEqual(str(ctx.exception), "消息角色只支持 user 或 assistant。")

    def test_extract_stream_delta_text(self) -> None:
        payload = {"choices": [{"delta": {"content": "你好"}}]}
        self.assertEqual(_extract_stream_delta_text(payload), "你好")

    def test_extract_stream_delta_text_supports_message_content(self) -> None:
        payload = {"choices": [{"message": {"content": [{"type": "text", "text": "你好"}]}}]}
        self.assertEqual(_extract_stream_delta_text(payload), "你好")

    def test_walk_for_text_finds_nested_translation(self) -> None:
        payload = {"data": {"translation": "translated"}}
        self.assertEqual(_walk_for_text(payload), "translated")

    def test_filter_recommended_models_uses_intersection(self) -> None:
        models = filter_recommended_text_models(["qwen-max", "qwen-mt-flash", "wanx-image"])
        self.assertEqual(models, ["qwen-mt-flash", "qwen-max"])

    def test_filter_recommended_models_falls_back_to_defaults(self) -> None:
        models = filter_recommended_text_models(["wanx-image", "qwen-vl-max"])
        self.assertEqual(models, list(RECOMMENDED_TEXT_MODELS))

    @patch("transprot.services.translation._request_json")
    def test_fetch_openai_compatible_model_ids(self, request_json) -> None:
        request_json.return_value = {
            "object": "list",
            "data": [
                {"id": "qwen-mt-flash"},
                {"id": "qwen3-max"},
                {"id": "qwen-mt-flash"},
            ],
        }

        model_ids = fetch_openai_compatible_model_ids(DEFAULT_BAILIAN_BASE_URL, "sk-test", 5)

        self.assertEqual(model_ids, ["qwen-mt-flash", "qwen3-max"])
        self.assertEqual(request_json.call_args.kwargs["timeout_sec"], MIN_MODEL_LIST_TIMEOUT_SEC)

    @patch("transprot.services.translation.fetch_openai_compatible_model_ids")
    def test_load_recommended_model_options_without_api_key_uses_defaults(self, fetch_model_ids) -> None:
        models, status = load_recommended_model_options(DEFAULT_BAILIAN_BASE_URL, "", 30)

        self.assertEqual(models, list(RECOMMENDED_TEXT_MODELS))
        self.assertIn("默认模型列表", status)
        fetch_model_ids.assert_not_called()

    @patch("transprot.services.translation.time.sleep")
    @patch("transprot.services.translation.urllib.request.urlopen")
    def test_request_json_retries_and_surfaces_friendly_timeout(self, urlopen, sleep) -> None:
        urlopen.side_effect = [TimeoutError("The read operation timed out"), TimeoutError("The read operation timed out")]

        with self.assertRaises(TranslationError) as ctx:
            _request_json("https://example.com/v1/chat/completions", timeout_sec=5, payload={"x": 1})

        self.assertEqual(str(ctx.exception), TIMEOUT_ERROR_MESSAGE)
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once()

    @patch("transprot.services.translation._post_json")
    def test_openai_translator_uses_minimum_translation_timeout(self, post_json) -> None:
        post_json.return_value = {"choices": [{"message": {"content": "你好"}}]}
        translator = OpenAICompatibleTranslator()
        config = AppConfig(api_base_url=DEFAULT_BAILIAN_BASE_URL, model=DEFAULT_BAILIAN_MODEL, timeout_sec=5)

        result = translator.translate("hello", config)

        self.assertEqual(result.translated_text, "你好")
        self.assertEqual(post_json.call_args.kwargs["timeout_sec"], MIN_TRANSLATION_TIMEOUT_SEC)

    @patch("transprot.services.translation._stream_json")
    def test_openai_translator_streams_partial_results(self, stream_json) -> None:
        stream_json.return_value = iter(
            [
                {"choices": [{"delta": {"content": "你"}}]},
                {"choices": [{"delta": {"content": "好"}}]},
                {"choices": []},
            ]
        )
        translator = OpenAICompatibleTranslator()
        config = AppConfig(api_base_url=DEFAULT_BAILIAN_BASE_URL, model=DEFAULT_BAILIAN_MODEL, timeout_sec=5)
        progress: list[str] = []

        result = translator.translate_stream("hello", config, on_progress=progress.append)

        self.assertEqual(progress, ["你", "你好"])
        self.assertEqual(result.translated_text, "你好")
        self.assertEqual(stream_json.call_args.kwargs["timeout_sec"], MIN_TRANSLATION_TIMEOUT_SEC)

    @patch("transprot.services.translation._stream_json")
    def test_openai_translator_stream_surfaces_api_error(self, stream_json) -> None:
        stream_json.return_value = iter([
            {"error": {"message": "Role must be in [user, assistant]."}},
        ])
        translator = OpenAICompatibleTranslator()
        config = AppConfig(api_base_url=DEFAULT_BAILIAN_BASE_URL, model=DEFAULT_BAILIAN_MODEL, timeout_sec=5)

        with self.assertRaises(TranslationError) as ctx:
            translator.translate_stream("hello", config)

        self.assertEqual(str(ctx.exception), "消息角色只支持 user 或 assistant。")

    @patch("transprot.services.translation._stream_json")
    def test_qwen_mt_translator_uses_user_only_message(self, stream_json) -> None:
        stream_json.return_value = iter([
            {"choices": [{"delta": {"content": "你好"}}]},
        ])
        translator = OpenAICompatibleTranslator()
        config = AppConfig(api_base_url=DEFAULT_BAILIAN_BASE_URL, model="qwen-mt-flash", timeout_sec=5)

        translator.translate_stream("hello", config)

        messages = stream_json.call_args.kwargs["payload"]["messages"]
        self.assertEqual([message["role"] for message in messages], ["user"])
        self.assertIn("hello", messages[0]["content"])
        self.assertIn("OCR", messages[0]["content"])


if __name__ == "__main__":
    unittest.main()
