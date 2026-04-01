from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from transprot.core.layout import compute_overlay_rect
from transprot.core.models import SelectionRegion


class TranslationOverlay(QWidget):
    closed = Signal()

    def __init__(self, screen_rect_provider: Callable[[str], tuple[int, int, int, int]]) -> None:
        super().__init__(None)
        self._screen_rect_provider = screen_rect_provider
        self._filter_installed = False
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setObjectName("translationOverlay")
        self.setStyleSheet(
            "#translationOverlay { background-color: rgba(26, 29, 36, 230); border: 1px solid rgba(61, 214, 140, 220); border-radius: 12px; }"
            "QLabel { color: white; font-size: 14px; }"
            "QPushButton { color: white; border: none; background: transparent; font-size: 16px; }"
            "QPushButton:hover { color: rgb(61, 214, 140); }"
        )

        self._close_button = QPushButton("x")
        self._close_button.setFixedWidth(28)
        self._close_button.clicked.connect(self.hide_overlay)
        self._text_label = QLabel()
        self._text_label.setWordWrap(True)
        self._text_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        title_layout = QHBoxLayout()
        title_layout.addStretch(1)
        title_layout.addWidget(self._close_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 14)
        layout.setSpacing(6)
        layout.addLayout(title_layout)
        layout.addWidget(self._text_label)

    def show_translation(self, region: SelectionRegion, translated_text: str) -> None:
        screen_rect = self._screen_rect_provider(region.screen_name)
        max_width = min(max(region.width + 120, 320), max(360, screen_rect[2] - 24))
        self._text_label.setMaximumWidth(max_width - 28)
        self._text_label.setText(translated_text)
        self.adjustSize()
        preferred = (max(self.sizeHint().width(), 320), self.sizeHint().height())
        geometry = compute_overlay_rect(region.rect, screen_rect, preferred)
        self.setGeometry(*geometry)
        self._install_global_filter()
        self.show()
        self.raise_()
        self.activateWindow()

    def hide_overlay(self) -> None:
        if self._filter_installed:
            app = QApplication.instance()
            if app is not None:
                app.removeEventFilter(self)
            self._filter_installed = False
        self.hide()
        self.closed.emit()

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.MouseButtonPress and self.isVisible():
            if not self.geometry().contains(event.globalPosition().toPoint()):
                self.hide_overlay()
        if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
            self.hide_overlay()
        return super().eventFilter(watched, event)

    def _install_global_filter(self) -> None:
        if self._filter_installed:
            return
        app = QApplication.instance()
        if app is None:
            return
        app.installEventFilter(self)
        self._filter_installed = True
