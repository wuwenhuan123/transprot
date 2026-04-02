from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor

from PySide6.QtCore import QObject, Signal
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
from transprot.services.translation import (
    DEFAULT_BAILIAN_BASE_URL,
    DEFAULT_BAILIAN_MODEL,
    RECOMMENDED_TEXT_MODELS,
    load_recommended_model_options,
)


class _SettingsBridge(QObject):
    payload_ready = Signal(object)


class SettingsDialog(QDialog):
    def __init__(self, config: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="transprot-settings")
        self._bridge = _SettingsBridge()
        self._bridge.payload_ready.connect(self._handle_model_payload)
        self._initial_models_requested = False
        self._model_refresh_inflight = False

        self.setWindowTitle("TransProt 设置")
        self.resize(560, 380)

        self._provider_combo = QComboBox()
        self._provider_combo.addItem("阿里云百炼 / OpenAI 兼容接口", TranslationProvider.OPENAI_COMPATIBLE)
        self._provider_combo.addItem("通用翻译接口", TranslationProvider.BASIC_HTTP)
        self._provider_combo.currentIndexChanged.connect(self._update_form_state)

        self._hotkey_edit = QLineEdit()
        self._hotkey_edit.setEnabled(False)
        self._hotkey_edit.setToolTip("当前常驻框选模式下不使用热键。")

        self._base_url_edit = QLineEdit()
        self._base_url_edit.setPlaceholderText(DEFAULT_BAILIAN_BASE_URL)

        self._api_key_edit = QLineEdit()
        self._api_key_edit.setEchoMode(QLineEdit.Password)

        self._model_combo = QComboBox()
        self._model_combo.setEditable(True)
        self._model_combo.setInsertPolicy(QComboBox.NoInsert)
        self._model_combo.addItems(RECOMMENDED_TEXT_MODELS)
        self._model_combo.setCurrentText(DEFAULT_BAILIAN_MODEL)

        self._refresh_models_button = QPushButton("刷新模型")
        self._refresh_models_button.clicked.connect(self._refresh_models_clicked)

        self._target_lang_edit = QLineEdit()
        self._target_lang_edit.setPlaceholderText("zh-CN")
        self._target_lang_edit.setToolTip("例如 zh-CN、en、ja。")

        self._timeout_spin = QSpinBox()
        self._timeout_spin.setRange(5, 180)
        self._timeout_spin.setSuffix(" 秒")

        self._hotkey_hint = QLabel("当前版本不通过热键触发框选。")
        self._hotkey_hint.setWordWrap(True)

        self._model_status_label = QLabel("")
        self._model_status_label.setWordWrap(True)
        self._model_status_label.setStyleSheet("color: rgb(120, 130, 145);")

        form_layout = QFormLayout()
        form_layout.addRow("服务类型", self._provider_combo)
        form_layout.addRow("热键", self._hotkey_edit)
        form_layout.addRow("接口地址", self._base_url_edit)
        form_layout.addRow("API 密钥", self._api_key_edit)

        model_layout = QHBoxLayout()
        model_layout.setContentsMargins(0, 0, 0, 0)
        model_layout.addWidget(self._model_combo, 1)
        model_layout.addWidget(self._refresh_models_button)
        form_layout.addRow("模型", model_layout)
        form_layout.addRow("目标语言", self._target_lang_edit)
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
        main_layout.addWidget(self._model_status_label)
        main_layout.addWidget(self._hotkey_hint)
        main_layout.addStretch(1)
        main_layout.addLayout(footer_layout)

        self.finished.connect(self._shutdown_executor)
        self.apply_config(config)

    def apply_config(self, config: AppConfig) -> None:
        self._config = config
        index = self._provider_combo.findData(config.translation_provider)
        self._provider_combo.setCurrentIndex(max(index, 0))
        self._hotkey_edit.setText(config.hotkey)
        self._base_url_edit.setText(config.api_base_url or DEFAULT_BAILIAN_BASE_URL)
        self._api_key_edit.setText(config.api_key)
        self._set_model_options(RECOMMENDED_TEXT_MODELS, current_text=config.model or DEFAULT_BAILIAN_MODEL)
        self._target_lang_edit.setText(config.target_lang)
        self._timeout_spin.setValue(config.timeout_sec)
        self._update_form_state()
        if not self._initial_models_requested and config.translation_provider == TranslationProvider.OPENAI_COMPATIBLE:
            self._initial_models_requested = True
            self.refresh_model_options(show_warning=False)

    def build_config(self) -> AppConfig:
        provider = self._provider_combo.currentData()
        base_url = self._base_url_edit.text().strip()
        model = self._model_combo.currentText().strip()
        if provider == TranslationProvider.OPENAI_COMPATIBLE:
            base_url = base_url or DEFAULT_BAILIAN_BASE_URL
            model = model or DEFAULT_BAILIAN_MODEL
        return AppConfig(
            hotkey=self._hotkey_edit.text().strip() or "Ctrl+Alt+T",
            translation_provider=provider,
            api_base_url=base_url,
            api_key=self._api_key_edit.text().strip(),
            model=model,
            timeout_sec=int(self._timeout_spin.value()),
            log_level=self._config.log_level,
            source_lang=self._config.source_lang,
            target_lang=self._target_lang_edit.text().strip() or "zh-CN",
            capture_region=self._config.capture_region,
        )

    def refresh_model_options(self, show_warning: bool = True) -> None:
        if self._model_refresh_inflight:
            return
        provider = self._provider_combo.currentData()
        if provider != TranslationProvider.OPENAI_COMPATIBLE:
            self._model_status_label.setText("当前服务类型不支持自动加载模型列表。")
            return

        self._model_refresh_inflight = True
        self._refresh_models_button.setEnabled(False)
        self._model_status_label.setText("正在刷新模型列表...")
        base_url = self._base_url_edit.text().strip() or DEFAULT_BAILIAN_BASE_URL
        api_key = self._api_key_edit.text().strip()
        timeout_sec = int(self._timeout_spin.value())
        future = self._executor.submit(load_recommended_model_options, base_url, api_key, timeout_sec)
        future.add_done_callback(
            lambda item, warning=show_warning: self._bridge.payload_ready.emit(
                self._pack_model_future(item, warning)
            )
        )

    def _update_form_state(self) -> None:
        provider = self._provider_combo.currentData()
        is_openai = provider == TranslationProvider.OPENAI_COMPATIBLE
        self._model_combo.setEnabled(is_openai)
        self._refresh_models_button.setEnabled(is_openai and not self._model_refresh_inflight)
        if not is_openai:
            self._model_status_label.setText("当前服务类型不支持自动加载模型列表。")
        elif not self._model_status_label.text():
            self._model_status_label.setText("支持手动输入模型名，也可以点击刷新模型加载推荐列表。")

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
        if config.translation_provider == TranslationProvider.OPENAI_COMPATIBLE:
            if not config.api_base_url.strip():
                raise ValueError("OpenAI 兼容接口地址不能为空。")
            if not config.model.strip():
                raise ValueError("模型名称不能为空。")
        if not config.target_lang.strip():
            raise ValueError("目标语言不能为空。")
        return config

    def _refresh_models_clicked(self) -> None:
        self.refresh_model_options(show_warning=True)

    def _set_model_options(self, models: list[str] | tuple[str, ...], current_text: str | None = None) -> None:
        selected = (current_text or self._model_combo.currentText() or DEFAULT_BAILIAN_MODEL).strip()
        self._model_combo.blockSignals(True)
        self._model_combo.clear()
        self._model_combo.addItems(list(models))
        self._model_combo.setCurrentText(selected or DEFAULT_BAILIAN_MODEL)
        self._model_combo.blockSignals(False)

    def _pack_model_future(self, future: Future, show_warning: bool) -> dict[str, object]:
        try:
            models, status_text = future.result()
            return {
                "models": models,
                "status": status_text,
                "error": None,
                "show_warning": show_warning,
            }
        except Exception as exc:
            return {
                "models": list(RECOMMENDED_TEXT_MODELS),
                "status": "模型列表刷新失败，已保留默认模型列表。",
                "error": str(exc),
                "show_warning": show_warning,
            }

    def _handle_model_payload(self, payload: dict[str, object]) -> None:
        self._model_refresh_inflight = False
        self._set_model_options(payload["models"])
        self._model_status_label.setText(str(payload["status"]))
        self._update_form_state()

        error = payload.get("error")
        if error and payload.get("show_warning"):
            QMessageBox.warning(self, "模型列表刷新失败", str(error))

    def _shutdown_executor(self, *_args) -> None:
        executor = getattr(self, "_executor", None)
        if executor is None:
            return
        self._executor = None
        try:
            executor.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            executor.shutdown(wait=False)
