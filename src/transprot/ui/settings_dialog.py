from __future__ import annotations

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
    def __init__(self, config: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self.setWindowTitle("TransProt 设置")
        self.resize(520, 340)

        self._provider_combo = QComboBox()
        self._provider_combo.addItem("OpenAI 兼容接口", TranslationProvider.OPENAI_COMPATIBLE)
        self._provider_combo.addItem("通用翻译接口", TranslationProvider.BASIC_HTTP)
        self._provider_combo.currentIndexChanged.connect(self._update_form_state)

        self._hotkey_edit = QLineEdit()
        self._hotkey_edit.setEnabled(False)
        self._hotkey_edit.setToolTip("当前 OCR 区域模式下不使用热键。")
        self._base_url_edit = QLineEdit()
        self._api_key_edit = QLineEdit()
        self._api_key_edit.setEchoMode(QLineEdit.Password)
        self._model_edit = QLineEdit()
        self._timeout_spin = QSpinBox()
        self._timeout_spin.setRange(5, 180)
        self._timeout_spin.setSuffix(" 秒")

        self._hint_label = QLabel(
            "当前版本只做 OCR 识别。下面这些翻译配置会继续保存，但不会参与主流程。"
        )
        self._hint_label.setWordWrap(True)
        self._hotkey_hint = QLabel("当前版本不通过热键触发框选。")
        self._hotkey_hint.setWordWrap(True)
        self._ocr_only_button = QPushButton("OCR 版本暂不测试翻译连接")
        self._ocr_only_button.setEnabled(False)
        self._ocr_only_button.setToolTip("当前主流程只做截图和 OCR 识别，不调用翻译接口。")

        form_layout = QFormLayout()
        form_layout.addRow("服务类型", self._provider_combo)
        form_layout.addRow("热键", self._hotkey_edit)
        form_layout.addRow("接口地址", self._base_url_edit)
        form_layout.addRow("API Key", self._api_key_edit)
        form_layout.addRow("模型", self._model_edit)
        form_layout.addRow("超时", self._timeout_spin)

        button_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        button_box.button(QDialogButtonBox.Save).setText("保存")
        button_box.button(QDialogButtonBox.Cancel).setText("取消")
        button_box.accepted.connect(self._accept_with_validation)
        button_box.rejected.connect(self.reject)

        footer_layout = QHBoxLayout()
        footer_layout.addWidget(self._ocr_only_button)
        footer_layout.addStretch(1)
        footer_layout.addWidget(button_box)

        main_layout = QVBoxLayout(self)
        main_layout.addLayout(form_layout)
        main_layout.addWidget(self._hint_label)
        main_layout.addWidget(self._hotkey_hint)
        main_layout.addStretch(1)
        main_layout.addLayout(footer_layout)

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
