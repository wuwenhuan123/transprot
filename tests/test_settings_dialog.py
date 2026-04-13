from __future__ import annotations

import importlib.util
import unittest

from transprot.core.models import AppConfig

_PYSIDE6_AVAILABLE = importlib.util.find_spec("PySide6") is not None
if _PYSIDE6_AVAILABLE:
    from PySide6.QtWidgets import QApplication
    from transprot.ui.settings_dialog import SettingsDialog
else:
    QApplication = None
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

    def test_auto_mode_checkbox_roundtrips_into_config(self) -> None:
        dialog = SettingsDialog(AppConfig(auto_mode_enabled=True))

        config = dialog.build_config()

        self.assertTrue(dialog._auto_mode_checkbox.isChecked())
        self.assertTrue(config.auto_mode_enabled)


if __name__ == "__main__":
    unittest.main()
