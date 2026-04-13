from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
)

from transprot.core.models import AppConfig, TranslationProvider


class SettingsDialog(QDialog):
    def __init__(self, config: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self.setWindowTitle("TransProt 设置")
        self.resize(520, 320)

        self._provider_combo = QComboBox()
        self._provider_combo.addItem("OpenAI 兼容接口", TranslationProvider.OPENAI_COMPATIBLE)
        self._provider_combo.addItem("通用翻译接口", TranslationProvider.BASIC_HTTP)
        self._provider_combo.currentIndexChanged.connect(self._update_form_state)

        self._auto_mode_checkbox = QCheckBox("自动检测区域变化并翻译")
        self._hotkey_edit = QLineEdit()
        self._hotkey_edit.setEnabled(False)
        self._hotkey_edit.setToolTip("当前区域模式下不使用热键。")
        self._base_url_edit = QLineEdit()
        self._api_key_edit = QLineEdit()
        self._api_key_edit.setEchoMode(QLineEdit.Password)
        self._model_edit = QLineEdit()
        self._timeout_spin = QSpinBox()
        self._timeout_spin.setRange(5, 180)
        self._timeout_spin.setSuffix(" 秒")

        self._hotkey_hint = QLabel("当前版本不通过热键触发框选。")
        self._hotkey_hint.setWordWrap(True)
        self._auto_mode_hint = QLabel("开启后会自动检测当前区域画面变化，并在稳定后自动翻译。")
        self._auto_mode_hint.setWordWrap(True)

        form_layout = QFormLayout()
        form_layout.addRow("服务类型", self._provider_combo)
        form_layout.addRow("自动模式", self._auto_mode_checkbox)
        form_layout.addRow("热键", self._hotkey_edit)
        form_layout.addRow("接口地址", self._base_url_edit)
        form_layout.addRow("API 密钥", self._api_key_edit)
        form_layout.addRow("模型", self._model_edit)
        form_layout.addRow("超时", self._timeout_spin)

        button_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        button_box.button(QDialogButtonBox.Save).setText("保存")
        button_box.button(QDialogButtonBox.Cancel).setText("取消")
        button_box.accepted.connect(self._accept_with_validation)
        button_box.rejected.connect(self.reject)

        footer_layout = QHBoxLayout()
        footer_layout.addStretch(1)
        footer_layout.addWidget(button_box)

        main_layout = QVBoxLayout(self)
        main_layout.addLayout(form_layout)
        main_layout.addWidget(self._auto_mode_hint)
        main_layout.addWidget(self._hotkey_hint)
        main_layout.addStretch(1)
        main_layout.addLayout(footer_layout)

        self.apply_config(config)

    def apply_config(self, config: AppConfig) -> None:
        self._config = config
        index = self._provider_combo.findData(config.translation_provider)
        self._provider_combo.setCurrentIndex(max(index, 0))
        self._auto_mode_checkbox.setChecked(config.auto_mode_enabled)
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
            auto_mode_enabled=self._auto_mode_checkbox.isChecked(),
            capture_region=self._config.capture_region,
        )

    def _update_form_state(self) -> None:
        provider = self._provider_combo.currentData()
        self._model_edit.setEnabled(provider == TranslationProvider.OPENAI_COMPATIBLE)

    def _accept_with_validation(self) -> None:
        try:
            self._validated_config()
        except ValueError as exc:
            QMessageBox.warning(self, "配置无效", str(exc))
            return
        self.accept()

    def _validated_config(self) -> AppConfig:
        config = self.build_config()
        if config.timeout_sec < 5:
            raise ValueError("超时时间不能小于 5 秒。")
        return config
