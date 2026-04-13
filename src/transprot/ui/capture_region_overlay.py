from __future__ import annotations

import logging

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QContextMenuEvent, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from transprot.core.layout import MIN_CAPTURE_SIZE, clamp_capture_region
from transprot.core.models import CaptureRegion

logger = logging.getLogger(__name__)

_RESIZE_MARGIN = 10
_BUTTON_GAP = 10
_BUTTON_MIN_SIZE = QSize(96, 36)
_HINT_TEXT = "拖动或缩放这个区域，使它覆盖目标文字"
_TRANSLATE_TEXT = "翻译"
_TRANSLATING_TEXT = "翻译中..."
_RESULT_PLACEHOLDER = "翻译结果"
_CLEAR_RESULT_TEXT = "清除译文"


class _FloatingTranslateButton(QPushButton):
    def __init__(self, text: str) -> None:
        super().__init__(text, None)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            "QPushButton { background-color: rgba(61, 214, 140, 235); color: rgb(18, 22, 28); border: none; border-radius: 12px; padding: 6px 14px; font-weight: 600; }"
            "QPushButton:disabled { background-color: rgba(120, 130, 145, 180); color: rgba(240, 240, 240, 200); }"
        )


class CaptureRegionOverlay(QWidget):
    recognize_requested = Signal(object)
    region_committed = Signal(object)
    interaction_started = Signal()
    interaction_finished = Signal(object)
    clear_requested = Signal()

    def __init__(self, initial_region: CaptureRegion) -> None:
        super().__init__(None)
        self._screen_name = initial_region.screen_name
        self._active_handle: str | None = None
        self._press_pos = QPoint()
        self._press_geometry = QRect()
        self._interaction_screen_name = initial_region.screen_name
        self._interaction_screen_rect = initial_region.rect

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setMinimumSize(*MIN_CAPTURE_SIZE)
        self.setWindowTitle("TransProt 翻译区域")

        self._hint_label = QLabel(_HINT_TEXT)
        self._hint_label.setStyleSheet("color: rgba(255, 255, 255, 200); font-size: 12px;")

        self._translate_button = _FloatingTranslateButton(_TRANSLATE_TEXT)
        self._translate_button.clicked.connect(self._emit_recognize_requested)

        self._result_view = QPlainTextEdit()
        self._result_view.setReadOnly(True)
        self._result_view.setPlaceholderText(_RESULT_PLACEHOLDER)
        self._result_view.hide()
        self._result_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self._result_view.customContextMenuRequested.connect(self._show_result_context_menu)
        self._result_view.setStyleSheet(
            "QPlainTextEdit { background-color: rgba(9, 11, 16, 170); color: white; border: 1px solid rgba(255, 255, 255, 35); border-radius: 10px; padding: 8px; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        layout.addWidget(self._hint_label)
        layout.addWidget(self._result_view, 1)

        self.apply_region(initial_region)
        logger.info("CaptureRegionOverlay initialized. region=%s", initial_region)

    def apply_region(self, region: CaptureRegion) -> None:
        self._screen_name = region.screen_name
        self.setGeometry(region.x, region.y, region.width, region.height)
        self._sync_button_geometry()
        logger.info("CaptureRegionOverlay applied region: %s", region)

    def current_region(self) -> CaptureRegion:
        geometry = self.geometry()
        screen = QApplication.screenAt(geometry.center())
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            region = CaptureRegion(
                screen_name=self._screen_name,
                x=geometry.x(),
                y=geometry.y(),
                width=geometry.width(),
                height=geometry.height(),
            )
            logger.info("CaptureRegionOverlay current region without screen: %s", region)
            return region
        screen_rect = self._screen_rect(screen)
        region = clamp_capture_region(
            CaptureRegion(
                screen_name=screen.name(),
                x=geometry.x(),
                y=geometry.y(),
                width=geometry.width(),
                height=geometry.height(),
            ),
            screen_rect,
        )
        if region.rect != (geometry.x(), geometry.y(), geometry.width(), geometry.height()):
            self.setGeometry(region.x, region.y, region.width, region.height)
        self._screen_name = region.screen_name
        return region

    def show_region(self) -> None:
        logger.info("CaptureRegionOverlay show requested. current_geometry=%s", self.geometry().getRect())
        self.setWindowState(Qt.WindowNoState)
        self.showNormal()
        self.show()
        self._sync_button_geometry()
        self._translate_button.show()
        self._translate_button.raise_()
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.ActiveWindowFocusReason)
        logger.info(
            "CaptureRegionOverlay shown. visible=%s geometry=%s active=%s button_geometry=%s",
            self.isVisible(),
            self.geometry().getRect(),
            self.isActiveWindow(),
            self._translate_button.geometry().getRect(),
        )

    def show_result(self, text: str, is_error: bool = False) -> None:
        logger.info("CaptureRegionOverlay showing result. is_error=%s text_length=%s", is_error, len(text))
        self._result_view.setPlainText(text)
        self._result_view.setStyleSheet(
            "QPlainTextEdit { background-color: rgba(9, 11, 16, 170); color: %s; border: 1px solid rgba(255, 255, 255, 35); border-radius: 10px; padding: 8px; }"
            % ("rgb(255, 120, 120)" if is_error else "white")
        )
        self._result_view.show()
        self._result_view.verticalScrollBar().setValue(0)

    def clear_result(self) -> None:
        logger.info("CaptureRegionOverlay clearing result")
        self._result_view.clear()
        self._result_view.hide()

    def is_result_visible(self) -> bool:
        return self._result_view.isVisible()

    def set_busy(self, busy: bool) -> None:
        logger.info("CaptureRegionOverlay busy state changed: %s", busy)
        self._translate_button.setEnabled(not busy)
        self._translate_button.setText(_TRANSLATING_TEXT if busy else _TRANSLATE_TEXT)
        self._sync_button_geometry()

    def hideEvent(self, event) -> None:
        self._translate_button.hide()
        super().hideEvent(event)

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self._sync_button_geometry()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_button_geometry()

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        if self.is_result_visible():
            self._show_clear_menu(event.globalPos())
            event.accept()
            return
        super().contextMenuEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.setBrush(QColor(31, 36, 46, 88))
        painter.setPen(QPen(QColor(61, 214, 140, 220), 2))
        painter.drawRoundedRect(rect, 14, 14)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        self._active_handle = self._hit_test(event.position().toPoint())
        self._press_pos = event.globalPosition().toPoint()
        self._press_geometry = self.geometry()
        self._interaction_screen_name, self._interaction_screen_rect = self._resolve_interaction_screen()
        logger.info(
            "CaptureRegionOverlay mouse press. handle=%s geometry=%s",
            self._active_handle,
            self._press_geometry.getRect(),
        )
        self.interaction_started.emit()
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._active_handle is None:
            self._update_cursor(self._hit_test(event.position().toPoint()))
            return super().mouseMoveEvent(event)

        delta = event.globalPosition().toPoint() - self._press_pos
        geometry = self._geometry_for_handle(self._press_geometry, delta, self._active_handle)
        geometry = self._clamp_geometry(geometry, self._interaction_screen_name, self._interaction_screen_rect)
        self.setGeometry(geometry)
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.LeftButton or self._active_handle is None:
            return super().mouseReleaseEvent(event)
        self._active_handle = None
        self._update_cursor(self._hit_test(event.position().toPoint()))
        region = self.current_region()
        logger.info("CaptureRegionOverlay mouse release. committed_region=%s", region)
        self.region_committed.emit(region)
        self.interaction_finished.emit(region)
        event.accept()

    def leaveEvent(self, event) -> None:
        self.unsetCursor()
        super().leaveEvent(event)

    def _emit_recognize_requested(self) -> None:
        region = self.current_region()
        logger.info("CaptureRegionOverlay translate requested. region=%s", region)
        self.recognize_requested.emit(region)

    def _show_result_context_menu(self, pos: QPoint) -> None:
        if not self.is_result_visible():
            return
        self._show_clear_menu(self._result_view.mapToGlobal(pos))

    def _show_clear_menu(self, global_pos: QPoint) -> None:
        menu = QMenu(self)
        action = menu.addAction(_CLEAR_RESULT_TEXT)
        selected = menu.exec(global_pos)
        if selected == action:
            self.clear_requested.emit()

    def _sync_button_geometry(self) -> None:
        if not self.geometry().isValid():
            return
        button_size = self._translate_button.sizeHint().expandedTo(_BUTTON_MIN_SIZE)
        self._translate_button.resize(button_size)
        self._translate_button.move(self._resolve_button_top_left(button_size))

    def _resolve_button_top_left(self, button_size: QSize) -> QPoint:
        geometry = self.geometry()
        screen = QApplication.screenAt(geometry.center())
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            return QPoint(geometry.right() - button_size.width() + 1, geometry.top())

        screen_rect = screen.availableGeometry()
        preferred_x = geometry.right() - button_size.width() + 1
        x = max(screen_rect.left(), min(preferred_x, screen_rect.right() - button_size.width() + 1))

        above_y = geometry.top() - button_size.height() - _BUTTON_GAP
        below_y = geometry.bottom() + _BUTTON_GAP + 1
        if above_y >= screen_rect.top():
            y = above_y
        else:
            y = min(below_y, screen_rect.bottom() - button_size.height() + 1)

        return QPoint(x, y)

    def _resolve_interaction_screen(self) -> tuple[str, tuple[int, int, int, int]]:
        screen = QApplication.screenAt(self.geometry().center())
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            return self._screen_name, self.current_region().rect
        return screen.name(), self._screen_rect(screen)

    def _screen_rect(self, screen) -> tuple[int, int, int, int]:
        geometry = screen.geometry()
        return geometry.x(), geometry.y(), geometry.width(), geometry.height()

    def _hit_test(self, point: QPoint) -> str:
        rect = self.rect()
        left = point.x() <= _RESIZE_MARGIN
        right = point.x() >= rect.width() - _RESIZE_MARGIN
        top = point.y() <= _RESIZE_MARGIN
        bottom = point.y() >= rect.height() - _RESIZE_MARGIN

        if left and top:
            return "top_left"
        if right and top:
            return "top_right"
        if left and bottom:
            return "bottom_left"
        if right and bottom:
            return "bottom_right"
        if left:
            return "left"
        if right:
            return "right"
        if top:
            return "top"
        if bottom:
            return "bottom"
        return "move"

    def _update_cursor(self, handle: str) -> None:
        cursor_map = {
            "move": Qt.SizeAllCursor,
            "left": Qt.SizeHorCursor,
            "right": Qt.SizeHorCursor,
            "top": Qt.SizeVerCursor,
            "bottom": Qt.SizeVerCursor,
            "top_left": Qt.SizeFDiagCursor,
            "bottom_right": Qt.SizeFDiagCursor,
            "top_right": Qt.SizeBDiagCursor,
            "bottom_left": Qt.SizeBDiagCursor,
        }
        self.setCursor(cursor_map.get(handle, Qt.ArrowCursor))

    def _geometry_for_handle(self, base: QRect, delta: QPoint, handle: str) -> QRect:
        if handle == "move":
            return QRect(base.x() + delta.x(), base.y() + delta.y(), base.width(), base.height())

        left = base.left()
        top = base.top()
        right = base.right() + 1
        bottom = base.bottom() + 1

        if "left" in handle:
            left += delta.x()
        if "right" in handle:
            right += delta.x()
        if "top" in handle:
            top += delta.y()
        if "bottom" in handle:
            bottom += delta.y()

        min_width, min_height = MIN_CAPTURE_SIZE
        if right - left < min_width:
            if "left" in handle:
                left = right - min_width
            else:
                right = left + min_width
        if bottom - top < min_height:
            if "top" in handle:
                top = bottom - min_height
            else:
                bottom = top + min_height

        return QRect(left, top, right - left, bottom - top)

    def _clamp_geometry(
        self,
        geometry: QRect,
        screen_name: str,
        screen_rect: tuple[int, int, int, int],
    ) -> QRect:
        region = clamp_capture_region(
            CaptureRegion(
                screen_name=screen_name,
                x=geometry.x(),
                y=geometry.y(),
                width=geometry.width(),
                height=geometry.height(),
            ),
            screen_rect,
        )
        return QRect(region.x, region.y, region.width, region.height)
