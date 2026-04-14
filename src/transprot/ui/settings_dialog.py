from __future__ import annotations

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QKeySequenceEdit,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
)

from transprot.core.models import (
    AppConfig,
    DEFAULT_CLEAR_HOTKEY,
    DEFAULT_HOTKEY,
    DEFAULT_OPENAI_BASE_URL,
    DEFAULT_OPENAI_MODEL,
    TranslationProvider,
)

_TARGET_LANG_CHOICES = [
    ("\u7b80\u4f53\u4e2d\u6587", "zh-CN"),
    ("\u7e41\u9ad4\u4e2d\u6587", "zh-TW"),
    ("English", "en"),
    ("\u65e5\u672c\u8a9e", "ja"),
    ("\ud55c\uad6d\uc5b4", "ko"),
]
_PROVIDER_OPENAI_TEXT = "\u963f\u91cc\u4e91\u767e\u70bc\uff08OpenAI \u517c\u5bb9\uff09"
_PROVIDER_BASIC_TEXT = "\u901a\u7528\u7ffb\u8bd1\u63a5\u53e3"
_TITLE_TEXT = "TransProt \u8bbe\u7f6e"
_SAVE_TEXT = "\u4fdd\u5b58"
_CANCEL_TEXT = "\u53d6\u6d88"
_INVALID_CONFIG_TITLE = "\u914d\u7f6e\u65e0\u6548"
_PROVIDER_LABEL = "\u670d\u52a1\u7c7b\u578b"
_TARGET_LANG_LABEL = "\u76ee\u6807\u8bed\u8a00"
_TRANSLATE_SHORTCUT_LABEL = "\u7ffb\u8bd1\u5feb\u6377\u952e"
_CLEAR_SHORTCUT_LABEL = "\u6e05\u9664\u5feb\u6377\u952e"
_BASE_URL_LABEL = "\u63a5\u53e3\u5730\u5740"
_API_KEY_LABEL = "API \u5bc6\u94a5"
_MODEL_LABEL = "\u6a21\u578b"
_TIMEOUT_LABEL = "\u8d85\u65f6"
_SECONDS_SUFFIX = " \u79d2"
_TIMEOUT_ERROR = "\u8d85\u65f6\u65f6\u95f4\u4e0d\u80fd\u5c0f\u4e8e 5 \u79d2\u3002"
_TARGET_LANG_ERROR = "\u8bf7\u5148\u586b\u5199\u76ee\u6807\u8bed\u8a00\u3002"
_SHORTCUT_CONFLICT_ERROR = "\u7ffb\u8bd1\u5feb\u6377\u952e\u548c\u6e05\u9664\u5feb\u6377\u952e\u4e0d\u80fd\u76f8\u540c\u3002"
_BASE_URL_ERROR = "\u8bf7\u5148\u586b\u5199\u963f\u91cc\u4e91\u517c\u5bb9\u63a5\u53e3\u5730\u5740\u3002"
_MODEL_ERROR = "\u8bf7\u5148\u586b\u5199\u6a21\u578b\u540d\u79f0\u3002"


class SettingsDialog(QDialog):
    def __init__(self, config: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self.setWindowTitle(_TITLE_TEXT)
        self.resize(560, 360)

        self._provider_combo = QComboBox()
        self._provider_combo.addItem(_PROVIDER_OPENAI_TEXT, TranslationProvider.OPENAI_COMPATIBLE)
        self._provider_combo.addItem(_PROVIDER_BASIC_TEXT, TranslationProvider.BASIC_HTTP)
        self._provider_combo.currentIndexChanged.connect(self._update_form_state)

        self._target_lang_combo = QComboBox()
        self._target_lang_combo.setEditable(True)
        for label, value in _TARGET_LANG_CHOICES:
            self._target_lang_combo.addItem(label, value)

        self._translate_shortcut_edit = QKeySequenceEdit()
        self._clear_shortcut_edit = QKeySequenceEdit()

        self._base_url_edit = QLineEdit()
        self._base_url_edit.setPlaceholderText(DEFAULT_OPENAI_BASE_URL)
        self._api_key_edit = QLineEdit()
        self._api_key_edit.setEchoMode(QLineEdit.Password)
        self._model_edit = QLineEdit()
        self._model_edit.setPlaceholderText(DEFAULT_OPENAI_MODEL)
        self._timeout_spin = QSpinBox()
        self._timeout_spin.setRange(5, 180)
        self._timeout_spin.setSuffix(_SECONDS_SUFFIX)

        form_layout = QFormLayout()
        form_layout.addRow(_PROVIDER_LABEL, self._provider_combo)
        form_layout.addRow(_TARGET_LANG_LABEL, self._target_lang_combo)
        form_layout.addRow(_TRANSLATE_SHORTCUT_LABEL, self._translate_shortcut_edit)
        form_layout.addRow(_CLEAR_SHORTCUT_LABEL, self._clear_shortcut_edit)
        form_layout.addRow(_BASE_URL_LABEL, self._base_url_edit)
        form_layout.addRow(_API_KEY_LABEL, self._api_key_edit)
        form_layout.addRow(_MODEL_LABEL, self._model_edit)
        form_layout.addRow(_TIMEOUT_LABEL, self._timeout_spin)

        button_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        button_box.button(QDialogButtonBox.Save).setText(_SAVE_TEXT)
        button_box.button(QDialogButtonBox.Cancel).setText(_CANCEL_TEXT)
        button_box.accepted.connect(self._accept_with_validation)
        button_box.rejected.connect(self.reject)

        footer_layout = QHBoxLayout()
        footer_layout.addStretch(1)
        footer_layout.addWidget(button_box)

        main_layout = QVBoxLayout(self)
        main_layout.addLayout(form_layout)
        main_layout.addStretch(1)
        main_layout.addLayout(footer_layout)

        self.apply_config(config)

    def apply_config(self, config: AppConfig) -> None:
        self._config = config
        index = self._provider_combo.findData(config.translation_provider)
        self._provider_combo.setCurrentIndex(max(index, 0))
        self._set_target_language_value(config.target_lang)
        self._translate_shortcut_edit.setKeySequence(QKeySequence(config.hotkey))
        self._clear_shortcut_edit.setKeySequence(QKeySequence(config.clear_hotkey))
        self._base_url_edit.setText(config.api_base_url)
        self._api_key_edit.setText(config.api_key)
        self._model_edit.setText(config.model)
        self._timeout_spin.setValue(config.timeout_sec)
        self._update_form_state()

    def build_config(self) -> AppConfig:
        provider = self._provider_combo.currentData()
        model_text = self._model_edit.text().strip()
        return AppConfig(
            hotkey=_shortcut_text(self._translate_shortcut_edit, DEFAULT_HOTKEY),
            clear_hotkey=_shortcut_text(self._clear_shortcut_edit, DEFAULT_CLEAR_HOTKEY),
            translation_provider=provider,
            api_base_url=self._base_url_edit.text().strip(),
            api_key=self._api_key_edit.text().strip(),
            model=_current_model_value(provider, model_text),
            timeout_sec=int(self._timeout_spin.value()),
            log_level=self._config.log_level,
            source_lang=self._config.source_lang,
            target_lang=self._current_target_language_value(),
            capture_region=self._config.capture_region,
        )

    def _update_form_state(self) -> None:
        provider = self._provider_combo.currentData()
        is_openai = provider == TranslationProvider.OPENAI_COMPATIBLE
        self._model_edit.setEnabled(is_openai)
        if is_openai and not self._base_url_edit.text().strip():
            self._base_url_edit.setText(DEFAULT_OPENAI_BASE_URL)
        if is_openai and not self._model_edit.text().strip():
            self._model_edit.setText(DEFAULT_OPENAI_MODEL)

    def _current_target_language_value(self) -> str:
        current_text = self._target_lang_combo.currentText().strip()
        for index in range(self._target_lang_combo.count()):
            if self._target_lang_combo.itemText(index) == current_text:
                data = self._target_lang_combo.itemData(index)
                if isinstance(data, str) and data.strip():
                    return data
        return current_text or self._config.target_lang

    def _set_target_language_value(self, value: str) -> None:
        index = self._target_lang_combo.findData(value)
        if index >= 0:
            self._target_lang_combo.setCurrentIndex(index)
            return
        self._target_lang_combo.setEditText(value)

    def _accept_with_validation(self) -> None:
        try:
            self._validated_config()
        except ValueError as exc:
            QMessageBox.warning(self, _INVALID_CONFIG_TITLE, str(exc))
            return
        self.accept()

    def _validated_config(self) -> AppConfig:
        config = self.build_config()
        if config.timeout_sec < 5:
            raise ValueError(_TIMEOUT_ERROR)
        if not config.target_lang.strip():
            raise ValueError(_TARGET_LANG_ERROR)
        if config.hotkey == config.clear_hotkey:
            raise ValueError(_SHORTCUT_CONFLICT_ERROR)
        if config.translation_provider == TranslationProvider.OPENAI_COMPATIBLE:
            if not config.api_base_url.strip():
                raise ValueError(_BASE_URL_ERROR)
            if not config.model.strip():
                raise ValueError(_MODEL_ERROR)
        return config


def _shortcut_text(edit: QKeySequenceEdit, fallback: str) -> str:
    text = edit.keySequence().toString(QKeySequence.PortableText).strip()
    return text or fallback


def _current_model_value(provider: TranslationProvider, model_text: str) -> str:
    if model_text:
        return model_text
    if provider == TranslationProvider.OPENAI_COMPATIBLE:
        return DEFAULT_OPENAI_MODEL
    return ""
