from __future__ import annotations

import importlib.util
import unittest
from unittest.mock import patch

from transprot.core.models import (
    AppConfig,
    DEFAULT_CLEAR_HOTKEY,
    DEFAULT_OPENAI_BASE_URL,
    DEFAULT_OPENAI_MODEL,
    TranslationProvider,
)

_PYSIDE6_AVAILABLE = importlib.util.find_spec("PySide6") is not None
if _PYSIDE6_AVAILABLE:
    from PySide6.QtGui import QKeySequence
    from PySide6.QtWidgets import QApplication

    from transprot.ui.settings_dialog import SettingsDialog
else:
    QApplication = None
    QKeySequence = None
    SettingsDialog = None


@unittest.skipUnless(_PYSIDE6_AVAILABLE, "PySide6 is required for settings dialog tests.")
class SettingsDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def tearDown(self) -> None:
        for widget in self._app.topLevelWidgets():
            widget.hide()
            widget.deleteLater()
        self._app.processEvents()

    def test_apply_and_build_preserves_api_key_target_language_and_shortcuts(self) -> None:
        dialog = SettingsDialog(
            AppConfig(
                translation_provider=TranslationProvider.OPENAI_COMPATIBLE,
                api_base_url=DEFAULT_OPENAI_BASE_URL,
                api_key="secret-key",
                model="qwen-mt-flash",
                target_lang="en",
                hotkey="Ctrl+Shift+T",
                clear_hotkey="Ctrl+Shift+C",
            )
        )

        rebuilt = dialog.build_config()

        self.assertEqual(dialog._api_key_edit.text(), "secret-key")
        self.assertEqual(rebuilt.api_key, "secret-key")
        self.assertEqual(rebuilt.target_lang, "en")
        self.assertEqual(rebuilt.hotkey, "Ctrl+Shift+T")
        self.assertEqual(rebuilt.clear_hotkey, "Ctrl+Shift+C")

    def test_openai_provider_autofills_default_base_url_and_model(self) -> None:
        dialog = SettingsDialog(
            AppConfig(
                translation_provider=TranslationProvider.OPENAI_COMPATIBLE,
                api_base_url="",
                model="",
            )
        )

        dialog._base_url_edit.clear()
        dialog._model_edit.clear()
        dialog._update_form_state()

        self.assertEqual(dialog._base_url_edit.text(), DEFAULT_OPENAI_BASE_URL)
        self.assertEqual(dialog._model_edit.text(), DEFAULT_OPENAI_MODEL)

    def test_build_config_normalizes_provider_to_enum(self) -> None:
        dialog = SettingsDialog(AppConfig())
        dialog._provider_combo.setCurrentIndex(dialog._provider_combo.findData(TranslationProvider.OPENAI_COMPATIBLE))

        rebuilt = dialog.build_config()

        self.assertEqual(rebuilt.translation_provider, TranslationProvider.OPENAI_COMPATIBLE)

    def test_build_config_falls_back_to_default_clear_shortcut(self) -> None:
        dialog = SettingsDialog(AppConfig())
        dialog._clear_shortcut_edit.setKeySequence(QKeySequence())

        rebuilt = dialog.build_config()

        self.assertEqual(rebuilt.clear_hotkey, DEFAULT_CLEAR_HOTKEY)

    def test_validation_rejects_duplicate_shortcuts(self) -> None:
        dialog = SettingsDialog(AppConfig())
        dialog._translate_shortcut_edit.setKeySequence(QKeySequence("Ctrl+Alt+T"))
        dialog._clear_shortcut_edit.setKeySequence(QKeySequence("Ctrl+Alt+T"))

        with self.assertRaisesRegex(ValueError, "\u4e0d\u80fd\u76f8\u540c"):
            dialog._validated_config()

    def test_validation_rejects_missing_api_key_for_openai_provider(self) -> None:
        dialog = SettingsDialog(
            AppConfig(
                translation_provider=TranslationProvider.OPENAI_COMPATIBLE,
                api_base_url=DEFAULT_OPENAI_BASE_URL,
                api_key="",
                model=DEFAULT_OPENAI_MODEL,
            )
        )

        with self.assertRaisesRegex(ValueError, "API \u5bc6\u94a5"):
            dialog._validated_config()

    def test_apply_config_shows_available_ocr_models(self) -> None:
        with patch(
            "transprot.ui.settings_dialog.describe_available_ocr_models",
            return_value="ppocr-v5-server（内置离线模型）",
        ):
            dialog = SettingsDialog(AppConfig())
            dialog.apply_config(AppConfig())

        self.assertEqual(
            dialog._ocr_models_value.text(),
            "ppocr-v5-server（内置离线模型）",
        )


if __name__ == "__main__":
    unittest.main()
