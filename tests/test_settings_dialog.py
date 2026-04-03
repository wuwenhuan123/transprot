from __future__ import annotations

import importlib.util
import unittest

_PYSIDE6_AVAILABLE = importlib.util.find_spec("PySide6") is not None
if _PYSIDE6_AVAILABLE:
    from PySide6.QtWidgets import QApplication

    from transprot.core.models import AppConfig
    from transprot.services.translation import DEFAULT_BAILIAN_BASE_URL, DEFAULT_BAILIAN_MODEL
    from transprot.ui.settings_dialog import SettingsDialog
else:
    QApplication = None
    AppConfig = None
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
        dialog._target_lang_edit.setText("")

        config = dialog.build_config()

        self.assertEqual(config.api_base_url, DEFAULT_BAILIAN_BASE_URL)
        self.assertEqual(config.model, DEFAULT_BAILIAN_MODEL)
        self.assertEqual(config.target_lang, "zh-CN")

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


if __name__ == "__main__":
    unittest.main()
