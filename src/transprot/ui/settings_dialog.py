from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
)

from transprot.core.models import AppConfig, TranslationProvider
from transprot.services.translation import (
    DEFAULT_BAILIAN_BASE_URL,
    DEFAULT_BAILIAN_MODEL,
    RECOMMENDED_TEXT_MODELS,
    load_recommended_model_options,
)

_MIN_DIALOG_WIDTH = 520
_API_KEY_PLACEHOLDER = "填写百炼 API 密钥"
_GENERIC_API_KEY_PLACEHOLDER = "如接口需要，可填写接口密钥"
_SAVED_API_KEY_PLACEHOLDER = "已保存，留空表示保持不变"
_GENERIC_BASE_URL_PLACEHOLDER = "填写通用翻译接口地址"
_BASIC_HTTP_MODEL_STATUS = "当前服务类型不使用模型，也不支持加载模型列表。"
_TARGET_LANGUAGE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("中文", "zh-CN"),
    ("英文", "en"),
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
        self._api_key_saved_state = False
        self._api_key_clear_requested = False

        self.setWindowTitle("TransProt 设置")
        self.setMinimumWidth(_MIN_DIALOG_WIDTH)
        self.setStyleSheet(
            "QDialog { background-color: rgb(243, 246, 247); }"
            "QFrame#panelCard { background-color: rgb(255, 255, 255); border: 1px solid rgba(17, 24, 39, 18); border-radius: 16px; }"
            "QLabel#panelHint { color: rgb(92, 104, 118); font-size: 12px; }"
            "QLineEdit, QComboBox, QSpinBox {"
            " min-height: 36px; background-color: rgb(255, 255, 255); border: 1px solid rgba(15, 23, 42, 18);"
            " border-radius: 10px; padding: 0 12px; font-size: 13px; }"
            "QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: rgba(94, 224, 162, 170); }"
            "QComboBox::drop-down { border: none; width: 28px; }"
            "QPushButton { min-height: 36px; border-radius: 10px; padding: 0 14px; font-size: 13px; font-weight: 600; }"
            "QToolButton { color: rgb(33, 45, 56); font-size: 13px; font-weight: 700; border: none; padding: 4px 0; }"
        )

        self._provider_combo = QComboBox()
        self._provider_combo.addItem("阿里云百炼 / OpenAI 兼容接口", TranslationProvider.OPENAI_COMPATIBLE)
        self._provider_combo.addItem("通用翻译接口", TranslationProvider.BASIC_HTTP)
        self._provider_combo.currentIndexChanged.connect(self._update_form_state)

        self._hotkey_edit = QLineEdit()
        self._hotkey_edit.setEnabled(False)
        self._hotkey_edit.setToolTip("当前常驻框选模式下不使用热键。")

        self._base_url_edit = QLineEdit()
        self._base_url_edit.setPlaceholderText(DEFAULT_BAILIAN_BASE_URL)
        self._base_url_edit.setClearButtonEnabled(True)

        self._api_key_edit = QLineEdit()
        self._api_key_edit.setEchoMode(QLineEdit.Password)
        self._api_key_edit.setClearButtonEnabled(True)
        self._api_key_edit.setPlaceholderText(_API_KEY_PLACEHOLDER)

        self._clear_api_key_button = QPushButton("清除已保存密钥")
        self._clear_api_key_button.clicked.connect(self._clear_saved_api_key)
        self._clear_api_key_button.setStyleSheet(
            "QPushButton { background-color: rgb(248, 250, 251); color: rgb(30, 41, 53); border: 1px solid rgba(15, 23, 42, 18); }"
            "QPushButton:hover { background-color: rgb(241, 245, 247); }"
        )

        self._api_key_status_label = QLabel("")
        self._api_key_status_label.setObjectName("panelHint")
        self._api_key_status_label.setWordWrap(False)
        self._api_key_status_label.hide()

        self._model_combo = QComboBox()
        self._model_combo.setEditable(True)
        self._model_combo.setInsertPolicy(QComboBox.NoInsert)
        self._model_combo.addItems(RECOMMENDED_TEXT_MODELS)
        self._model_combo.setCurrentText(DEFAULT_BAILIAN_MODEL)

        self._refresh_models_button = QPushButton("刷新模型")
        self._refresh_models_button.clicked.connect(self._refresh_models_clicked)
        self._refresh_models_button.setStyleSheet(
            "QPushButton { background-color: rgb(248, 250, 251); color: rgb(30, 41, 53); border: 1px solid rgba(15, 23, 42, 18); }"
            "QPushButton:hover { background-color: rgb(241, 245, 247); }"
        )

        self._target_lang_combo = QComboBox()
        for label, value in _TARGET_LANGUAGE_OPTIONS:
            self._target_lang_combo.addItem(label, value)

        self._timeout_spin = QSpinBox()
        self._timeout_spin.setRange(5, 180)
        self._timeout_spin.setSuffix(" 秒")

        self._model_status_label = QLabel("")
        self._model_status_label.setObjectName("panelHint")
        self._model_status_label.setWordWrap(False)
        self._model_status_label.hide()

        common_card = QFrame()
        common_card.setObjectName("panelCard")
        common_layout = QVBoxLayout(common_card)
        common_layout.setContentsMargins(16, 16, 16, 16)
        common_layout.setSpacing(12)

        common_form = QFormLayout()
        common_form.setContentsMargins(0, 0, 0, 0)
        common_form.setSpacing(14)
        common_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self._api_key_label = QLabel("API 密钥")
        self._model_label = QLabel("模型")
        self._target_lang_label = QLabel("目标语言")
        self._base_url_label = QLabel("接口地址")

        api_key_row = QHBoxLayout()
        api_key_row.setContentsMargins(0, 0, 0, 0)
        api_key_row.setSpacing(8)
        api_key_row.addWidget(self._api_key_edit, 1)
        api_key_row.addWidget(self._clear_api_key_button)
        common_form.addRow(self._api_key_label, api_key_row)
        common_form.addRow("", self._api_key_status_label)

        model_layout = QHBoxLayout()
        model_layout.setContentsMargins(0, 0, 0, 0)
        model_layout.setSpacing(8)
        model_layout.addWidget(self._model_combo, 1)
        model_layout.addWidget(self._refresh_models_button)
        common_form.addRow(self._model_label, model_layout)
        common_form.addRow("", self._model_status_label)
        common_form.addRow(self._target_lang_label, self._target_lang_combo)
        common_form.addRow("超时", self._timeout_spin)
        common_layout.addLayout(common_form)

        self._advanced_toggle = QToolButton()
        self._advanced_toggle.setCheckable(True)
        self._advanced_toggle.setChecked(False)
        self._advanced_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._advanced_toggle.toggled.connect(self._set_advanced_visible)

        self._advanced_panel = QFrame()
        self._advanced_panel.setObjectName("panelCard")
        advanced_panel_layout = QVBoxLayout(self._advanced_panel)
        advanced_panel_layout.setContentsMargins(16, 16, 16, 16)
        advanced_panel_layout.setSpacing(0)

        advanced_form = QFormLayout()
        advanced_form.setContentsMargins(0, 0, 0, 0)
        advanced_form.setSpacing(14)
        advanced_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        advanced_form.addRow("服务类型", self._provider_combo)
        advanced_form.addRow(self._base_url_label, self._base_url_edit)
        advanced_form.addRow("热键", self._hotkey_edit)
        advanced_panel_layout.addLayout(advanced_form)

        button_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        save_button = button_box.button(QDialogButtonBox.Save)
        cancel_button = button_box.button(QDialogButtonBox.Cancel)
        save_button.setText("保存")
        cancel_button.setText("取消")
        save_button.setMinimumWidth(112)
        cancel_button.setMinimumWidth(96)
        save_button.setStyleSheet(
            "QPushButton { background-color: rgb(94, 224, 162); color: rgb(14, 20, 16); border: none; }"
            "QPushButton:hover { background-color: rgb(109, 232, 177); }"
        )
        cancel_button.setStyleSheet(
            "QPushButton { background-color: rgb(248, 250, 251); color: rgb(34, 45, 56); border: 1px solid rgba(15, 23, 42, 18); }"
            "QPushButton:hover { background-color: rgb(241, 245, 247); }"
        )
        button_box.accepted.connect(self._accept_with_validation)
        button_box.rejected.connect(self.reject)

        footer_layout = QHBoxLayout()
        footer_layout.addStretch(1)
        footer_layout.addWidget(button_box)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(18, 18, 18, 18)
        main_layout.setSpacing(12)
        main_layout.addWidget(common_card)
        main_layout.addWidget(self._advanced_toggle)
        main_layout.addWidget(self._advanced_panel)
        main_layout.addLayout(footer_layout)

        self.finished.connect(self._shutdown_executor)
        self._set_advanced_visible(False)
        self.apply_config(config)

    def apply_config(self, config: AppConfig) -> None:
        self._config = config
        self._api_key_saved_state = config.api_key_saved
        self._api_key_clear_requested = False
        index = self._provider_combo.findData(config.translation_provider)
        self._provider_combo.setCurrentIndex(max(index, 0))
        self._hotkey_edit.setText(config.hotkey)
        self._base_url_edit.setText(config.api_base_url or DEFAULT_BAILIAN_BASE_URL)
        self._api_key_edit.clear()
        self._sync_api_key_ui()
        self._set_model_options(RECOMMENDED_TEXT_MODELS, current_text=config.model or DEFAULT_BAILIAN_MODEL)
        self._set_target_language(config.target_lang)
        self._timeout_spin.setValue(config.timeout_sec)
        self._update_form_state()

        show_advanced = (
            config.translation_provider != TranslationProvider.OPENAI_COMPATIBLE
            or bool(config.api_base_url.strip() and config.api_base_url.strip() != DEFAULT_BAILIAN_BASE_URL)
        )
        self._advanced_toggle.setChecked(show_advanced)
        self._set_advanced_visible(show_advanced)

        if not self._initial_models_requested and config.translation_provider == TranslationProvider.OPENAI_COMPATIBLE:
            self._initial_models_requested = True
            self.refresh_model_options(show_warning=False)

    def build_config(self) -> AppConfig:
        provider = self._provider_combo.currentData()
        base_url = self._base_url_edit.text().strip()
        model = self._model_combo.currentText().strip()
        api_key = self._api_key_edit.text().strip()
        api_key_saved = bool(api_key) or self._api_key_saved_state
        target_lang = str(self._target_lang_combo.currentData() or "zh-CN")
        if provider == TranslationProvider.OPENAI_COMPATIBLE:
            base_url = base_url or DEFAULT_BAILIAN_BASE_URL
            model = model or DEFAULT_BAILIAN_MODEL
        return AppConfig(
            hotkey=self._hotkey_edit.text().strip() or "Ctrl+Alt+T",
            translation_provider=provider,
            api_base_url=base_url,
            api_key=api_key,
            api_key_saved=api_key_saved,
            model=model,
            timeout_sec=int(self._timeout_spin.value()),
            log_level=self._config.log_level,
            source_lang=self._config.source_lang,
            target_lang=target_lang,
            capture_region=self._config.capture_region,
        )

    def refresh_model_options(self, show_warning: bool = True) -> None:
        if self._model_refresh_inflight:
            return
        provider = self._provider_combo.currentData()
        if provider != TranslationProvider.OPENAI_COMPATIBLE:
            self._set_model_status(_BASIC_HTTP_MODEL_STATUS)
            return

        self._model_refresh_inflight = True
        self._refresh_models_button.setEnabled(False)
        self._set_model_status("正在刷新模型列表...")
        base_url = self._base_url_edit.text().strip() or DEFAULT_BAILIAN_BASE_URL
        api_key = self._effective_api_key()
        timeout_sec = int(self._timeout_spin.value())
        future = self._executor.submit(load_recommended_model_options, base_url, api_key, timeout_sec)
        future.add_done_callback(
            lambda item, warning=show_warning: self._bridge.payload_ready.emit(
                self._pack_model_future(item, warning)
            )
        )

    def _effective_api_key(self) -> str:
        entered_key = self._api_key_edit.text().strip()
        if entered_key:
            return entered_key
        if self._api_key_saved_state and not self._api_key_clear_requested:
            return self._config.api_key
        return ""

    def _update_form_state(self) -> None:
        provider = self._provider_combo.currentData()
        is_openai = provider == TranslationProvider.OPENAI_COMPATIBLE
        self._base_url_label.setText("OpenAI 接口地址" if is_openai else "通用接口地址")
        self._api_key_label.setText("API 密钥" if is_openai else "接口密钥")
        self._model_label.setText("模型" if is_openai else "模型（不使用）")
        self._model_combo.setEnabled(is_openai)
        self._model_combo.setToolTip("" if is_openai else "当前服务类型不使用模型配置。")
        self._refresh_models_button.setEnabled(is_openai and not self._model_refresh_inflight)
        self._refresh_models_button.setVisible(is_openai)
        self._model_label.setEnabled(is_openai)
        self._clear_api_key_button.setEnabled(self._api_key_saved_state)
        if not self._api_key_saved_state:
            self._api_key_edit.setPlaceholderText(self._default_api_key_placeholder())
        self._base_url_edit.setPlaceholderText(
            DEFAULT_BAILIAN_BASE_URL if is_openai else _GENERIC_BASE_URL_PLACEHOLDER
        )
        if not is_openai:
            self._set_model_status(_BASIC_HTTP_MODEL_STATUS)
        elif self._model_status_label.text() in {"", _BASIC_HTTP_MODEL_STATUS}:
            self._set_model_status("")

    def _sync_api_key_ui(self) -> None:
        if self._api_key_clear_requested:
            self._api_key_edit.setPlaceholderText(self._default_api_key_placeholder())
            self._set_api_key_status("已清除已保存密钥，保存后生效。")
        elif self._api_key_saved_state:
            self._api_key_edit.setPlaceholderText(_SAVED_API_KEY_PLACEHOLDER)
            self._set_api_key_status("已保存，留空表示保持不变。")
        else:
            self._api_key_edit.setPlaceholderText(self._default_api_key_placeholder())
            self._set_api_key_status("")
        self._update_form_state()

    def _clear_saved_api_key(self) -> None:
        self._api_key_edit.clear()
        self._api_key_saved_state = False
        self._api_key_clear_requested = True
        self._config.api_key = ""
        self._config.api_key_saved = False
        self._sync_api_key_ui()

    def _set_advanced_visible(self, visible: bool) -> None:
        self._advanced_panel.setVisible(visible)
        self._advanced_toggle.setArrowType(Qt.DownArrow if visible else Qt.RightArrow)
        self._advanced_toggle.setText("收起高级设置" if visible else "展开高级设置")
        if self.isVisible():
            self._sync_dialog_size()

    def _sync_dialog_size(self) -> None:
        layout = self.layout()
        if layout is None:
            return
        layout.activate()
        target_height = max(self.minimumSizeHint().height(), layout.sizeHint().height() + 12)
        self.resize(max(self.width(), _MIN_DIALOG_WIDTH), target_height)

    def _set_api_key_status(self, text: str) -> None:
        self._api_key_status_label.setText(text)
        self._api_key_status_label.setVisible(bool(text.strip()))

    def _set_model_status(self, text: str) -> None:
        self._model_status_label.setText(text)
        self._model_status_label.setVisible(bool(text.strip()))

    def _default_api_key_placeholder(self) -> str:
        provider = self._provider_combo.currentData()
        if provider == TranslationProvider.BASIC_HTTP:
            return _GENERIC_API_KEY_PLACEHOLDER
        return _API_KEY_PLACEHOLDER

    def _set_target_language(self, target_lang: str) -> None:
        index = self._target_lang_combo.findData(target_lang)
        self._target_lang_combo.setCurrentIndex(index if index >= 0 else 0)

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
        self._set_model_status(str(payload["status"]))
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
