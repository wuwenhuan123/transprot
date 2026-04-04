from __future__ import annotations

import importlib.util
import unittest

_PYSIDE6_AVAILABLE = importlib.util.find_spec("PySide6") is not None
if _PYSIDE6_AVAILABLE:
    from PySide6.QtWidgets import QApplication

    from transprot.core.models import AppConfig, TranslationProvider
    from transprot.services.translation import DEFAULT_BAILIAN_BASE_URL, DEFAULT_BAILIAN_MODEL
    from transprot.ui.settings_dialog import SettingsDialog
else:
    QApplication = None
    AppConfig = None
    TranslationProvider = None
    SettingsDialog = None
    DEFAULT_BAILIAN_BASE_URL = None
    DEFAULT_BAILIAN_MODEL = None


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

    def test_build_config_uses_bailian_defaults(self) -> None:
        dialog = SettingsDialog(AppConfig(api_base_url="", model=""))
        dialog._base_url_edit.setText("")
        dialog._model_combo.setCurrentText("")
        dialog._target_lang_combo.setCurrentIndex(0)

        config = dialog.build_config()

        self.assertEqual(config.api_base_url, DEFAULT_BAILIAN_BASE_URL)
        self.assertEqual(config.model, DEFAULT_BAILIAN_MODEL)
        self.assertEqual(config.target_lang, "zh-CN")

    def test_build_config_uses_selected_target_language(self) -> None:
        dialog = SettingsDialog(AppConfig())
        dialog._target_lang_combo.setCurrentIndex(dialog._target_lang_combo.findData("en"))

        config = dialog.build_config()

        self.assertEqual(config.target_lang, "en")

    def test_handle_model_payload_keeps_custom_model_text(self) -> None:
        dialog = SettingsDialog(AppConfig())
        dialog._model_combo.setCurrentText("custom-model")

        dialog._handle_model_payload(
            {
                "models": ["qwen3.5-flash", "qwen-max"],
                "status": "已加载 2 个推荐模型。",
                "error": None,
                "show_warning": False,
            }
        )

        self.assertEqual(dialog._model_combo.currentText(), "custom-model")
        self.assertEqual(dialog._model_combo.itemText(0), "qwen3.5-flash")
        self.assertEqual(dialog._model_status_label.text(), "已加载 2 个推荐模型。")

    def test_advanced_section_is_collapsed_by_default(self) -> None:
        dialog = SettingsDialog(AppConfig())

        self.assertFalse(dialog._advanced_toggle.isChecked())
        self.assertFalse(dialog._advanced_panel.isVisible())
        self.assertEqual(dialog._advanced_toggle.text(), "展开高级设置")

    def test_dialog_height_shrinks_when_advanced_panel_collapses(self) -> None:
        dialog = SettingsDialog(AppConfig())
        dialog.show()
        self._app.processEvents()

        collapsed_height = dialog.height()
        dialog._advanced_toggle.click()
        self._app.processEvents()
        expanded_height = dialog.height()
        dialog._advanced_toggle.click()
        self._app.processEvents()
        collapsed_again_height = dialog.height()

        self.assertGreater(expanded_height, collapsed_height)
        self.assertLess(collapsed_again_height, expanded_height)

    def test_saved_api_key_is_not_backfilled_into_input(self) -> None:
        dialog = SettingsDialog(AppConfig())
        dialog._initial_models_requested = True
        dialog.apply_config(AppConfig(api_key="saved-secret", api_key_saved=True))

        self.assertEqual(dialog._api_key_edit.text(), "")
        self.assertEqual(dialog._api_key_edit.placeholderText(), "已保存，留空表示保持不变")
        self.assertEqual(dialog._api_key_status_label.text(), "已保存，留空表示保持不变。")
        self.assertTrue(dialog._clear_api_key_button.isEnabled())

    def test_build_config_preserves_saved_api_key_when_input_blank(self) -> None:
        dialog = SettingsDialog(AppConfig())
        dialog._initial_models_requested = True
        dialog.apply_config(AppConfig(api_key="saved-secret", api_key_saved=True))

        config = dialog.build_config()

        self.assertEqual(config.api_key, "")
        self.assertTrue(config.api_key_saved)

    def test_clear_saved_api_key_updates_dialog_state(self) -> None:
        dialog = SettingsDialog(AppConfig())
        dialog._initial_models_requested = True
        dialog.apply_config(AppConfig(api_key="saved-secret", api_key_saved=True))

        dialog._clear_saved_api_key()
        config = dialog.build_config()

        self.assertFalse(dialog._clear_api_key_button.isEnabled())
        self.assertEqual(dialog._api_key_status_label.text(), "已清除已保存密钥，保存后生效。")
        self.assertEqual(config.api_key, "")
        self.assertFalse(config.api_key_saved)

    def test_refresh_uses_saved_runtime_api_key_when_input_blank(self) -> None:
        dialog = SettingsDialog(AppConfig())
        dialog._initial_models_requested = True
        dialog.apply_config(AppConfig(api_key="saved-secret", api_key_saved=True))

        self.assertEqual(dialog._effective_api_key(), "saved-secret")

    def test_provider_linkage_updates_field_states_for_basic_http(self) -> None:
        dialog = SettingsDialog(AppConfig())
        index = dialog._provider_combo.findData(TranslationProvider.BASIC_HTTP)
        dialog._provider_combo.setCurrentIndex(index)

        self.assertFalse(dialog._model_combo.isEnabled())
        self.assertTrue(dialog._refresh_models_button.isHidden())
        self.assertEqual(dialog._api_key_label.text(), "接口密钥")
        self.assertEqual(dialog._base_url_label.text(), "通用接口地址")
        self.assertEqual(dialog._api_key_edit.placeholderText(), "如接口需要，可填写接口密钥")
        self.assertEqual(dialog._base_url_edit.placeholderText(), "填写通用翻译接口地址")
        self.assertIn("不使用模型", dialog._model_status_label.text())

    def test_provider_linkage_restores_openai_fields(self) -> None:
        dialog = SettingsDialog(AppConfig(translation_provider=TranslationProvider.BASIC_HTTP))
        index = dialog._provider_combo.findData(TranslationProvider.OPENAI_COMPATIBLE)
        dialog._provider_combo.setCurrentIndex(index)

        self.assertTrue(dialog._model_combo.isEnabled())
        self.assertFalse(dialog._refresh_models_button.isHidden())
        self.assertEqual(dialog._api_key_label.text(), "API 密钥")
        self.assertEqual(dialog._base_url_label.text(), "OpenAI 接口地址")
        self.assertEqual(dialog._base_url_edit.placeholderText(), DEFAULT_BAILIAN_BASE_URL)


if __name__ == "__main__":
    unittest.main()

