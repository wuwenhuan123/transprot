from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from transprot.core.models import AppConfig, TranslationProvider


class SettingsDialog(QDialog):
    test_connection_requested = Signal(object)
    test_result_ready = Signal(bool, str)

    def __init__(self, config: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self.setWindowTitle("TransProt Settings")
        self.resize(520, 320)

        self._provider_combo = QComboBox()
        self._provider_combo.addItem("OpenAI-compatible API", TranslationProvider.OPENAI_COMPATIBLE)
        self._provider_combo.addItem("Basic translation API", TranslationProvider.BASIC_HTTP)
        self._provider_combo.currentIndexChanged.connect(self._update_form_state)

        self._hotkey_edit = QLineEdit()
        self._base_url_edit = QLineEdit()
        self._api_key_edit = QLineEdit()
        self._api_key_edit.setEchoMode(QLineEdit.Password)
        self._model_edit = QLineEdit()
        self._timeout_spin = QSpinBox()
        self._timeout_spin.setRange(5, 180)
        self._timeout_spin.setSuffix(" s")
        self._hint_label = QLabel("Basic translation API mode sends q/source/target by default.")
        self._hint_label.setWordWrap(True)
        self._test_status = QLabel("")
        self._test_button = QPushButton("Test connection")
        self._test_button.clicked.connect(self._emit_test_request)

        form_layout = QFormLayout()
        form_layout.addRow("Provider", self._provider_combo)
        form_layout.addRow("Hotkey", self._hotkey_edit)
        form_layout.addRow("Endpoint", self._base_url_edit)
        form_layout.addRow("API key", self._api_key_edit)
        form_layout.addRow("Model", self._model_edit)
        form_layout.addRow("Timeout", self._timeout_spin)

        button_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self._accept_with_validation)
        button_box.rejected.connect(self.reject)

        footer_layout = QHBoxLayout()
        footer_layout.addWidget(self._test_button)
        footer_layout.addStretch(1)
        footer_layout.addWidget(button_box)

        main_layout = QVBoxLayout(self)
        main_layout.addLayout(form_layout)
        main_layout.addWidget(self._hint_label)
        main_layout.addWidget(self._test_status)
        main_layout.addStretch(1)
        main_layout.addLayout(footer_layout)

        self.test_result_ready.connect(self.set_test_result)
        self.apply_config(config)

    def apply_config(self, config: AppConfig) -> None:
        self._config = config
        index = self._provider_combo.findData(config.translation_provider)
        self._provider_combo.setCurrentIndex(max(index, 0))
        self._hotkey_edit.setText(config.hotkey)
        self._base_url_edit.setText(config.api_base_url)
        self._api_key_edit.setText(config.api_key)
        self._model_edit.setText(config.model)
        self._timeout_spin.setValue(config.timeout_sec)
        self._update_form_state()

    def build_config(self) -> AppConfig:
        return AppConfig(
            hotkey=self._hotkey_edit.text().strip() or "Ctrl+Alt+T",
            translation_provider=self._provider_combo.currentData(),
            api_base_url=self._base_url_edit.text().strip(),
            api_key=self._api_key_edit.text().strip(),
            model=self._model_edit.text().strip(),
            timeout_sec=int(self._timeout_spin.value()),
            log_level=self._config.log_level,
            source_lang=self._config.source_lang,
            target_lang=self._config.target_lang,
        )

    def set_testing_state(self, testing: bool) -> None:
        self._test_button.setEnabled(not testing)
        if testing:
            self._test_status.setText("Testing connection...")

    def set_test_result(self, success: bool, message: str) -> None:
        self._test_button.setEnabled(True)
        self._test_status.setText(message)
        self._test_status.setStyleSheet("color: rgb(61, 214, 140);" if success else "color: rgb(240, 91, 91);")

    def _update_form_state(self) -> None:
        provider = self._provider_combo.currentData()
        self._model_edit.setEnabled(provider == TranslationProvider.OPENAI_COMPATIBLE)

    def _emit_test_request(self) -> None:
        try:
            config = self._validated_config()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid configuration", str(exc))
            return
        self.set_testing_state(True)
        self.test_connection_requested.emit(config)

    def _accept_with_validation(self) -> None:
        try:
            self._validated_config()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid configuration", str(exc))
            return
        self.accept()

    def _validated_config(self) -> AppConfig:
        config = self.build_config()
        if not config.api_base_url:
            raise ValueError("Endpoint is required.")
        if config.translation_provider == TranslationProvider.OPENAI_COMPATIBLE and not config.model:
            raise ValueError("Model is required for OpenAI-compatible mode.")
        return config
