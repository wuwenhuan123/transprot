from __future__ import annotations

import unittest

from transprot.services.translation import (
    _extract_openai_text,
    _normalize_openai_url,
    _walk_for_text,
    build_translation_prompt,
)


class TranslationTests(unittest.TestCase):
    def test_prompt_targets_requested_language(self) -> None:
        prompt = build_translation_prompt("hello", "Simplified Chinese")
        self.assertIn("Simplified Chinese", prompt[0]["content"])
        self.assertEqual(prompt[1]["content"], "hello")

    def test_openai_url_normalization(self) -> None:
        self.assertEqual(
            _normalize_openai_url("https://example.com/v1"),
            "https://example.com/v1/chat/completions",
        )

    def test_extract_openai_text(self) -> None:
        payload = {"choices": [{"message": {"content": "hello"}}]}
        self.assertEqual(_extract_openai_text(payload), "hello")

    def test_walk_for_text_finds_nested_translation(self) -> None:
        payload = {"data": {"translation": "translated"}}
        self.assertEqual(_walk_for_text(payload), "translated")


if __name__ == "__main__":
    unittest.main()
