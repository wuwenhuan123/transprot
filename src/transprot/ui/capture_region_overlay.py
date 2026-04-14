from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QContextMenuEvent, QFont, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QApplication, QMenu, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from transprot.core.layout import MIN_CAPTURE_SIZE, clamp_capture_region
from transprot.core.models import CaptureRegion

logger = logging.getLogger(__name__)

_RESIZE_MARGIN = 10
_BUTTON_GAP = 10
_BUTTON_MIN_SIZE = QSize(96, 36)
_TRANSLATE_TEXT = "\u7ffb\u8bd1"
_TRANSLATING_TEXT = "\u7ffb\u8bd1\u4e2d..."
_RESULT_PLACEHOLDER = "\u7ffb\u8bd1\u7ed3\u679c"
_CLEAR_TRANSLATION_TEXT = "\u6e05\u9664\u8bd1\u6587"
_HIDE_OVERLAY_TEXT = "\u9690\u85cf\u7ffb\u8bd1\u6846"
_OPEN_SETTINGS_TEXT = "\u8bbe\u7f6e"
_OVERLAY_TITLE = "TransProt \u7ffb\u8bd1\u533a\u57df"
_WDA_NONE = 0x0
_WDA_EXCLUDEFROMCAPTURE = 0x11
_MIN_RESULT_FONT = 9.5
_MAX_RESULT_FONT = 16.0


class _FloatingTranslateButton(QPushButton):
    def __init__(self, text: str) -> None:
        super().__init__(text, None)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_NativeWindow, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            "QPushButton { background-color: rgba(61, 214, 140, 235); color: rgb(18, 22, 28); border: none; border-radius: 12px; padding: 6px 14px; font-weight: 600; }"
            "QPushButton:disabled { background-color: rgba(120, 130, 145, 180); color: rgba(240, 240, 240, 200); }"
        )


class CaptureRegionOverlay(QWidget):
    recognize_requested = Signal(object)
    region_committed = Signal(object)
    clear_requested = Signal()
    hide_requested = Signal()
    settings_requested = Signal()

    def __init__(self, initial_region: CaptureRegion) -> None:
        super().__init__(None)
        self._screen_name = initial_region.screen_name
        self._active_handle: str | None = None
        self._press_pos = QPoint()
        self._press_geometry = QRect()
        self._interaction_screen_name = initial_region.screen_name
        self._interaction_screen_rect = initial_region.rect

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NativeWindow, True)
        self.setMouseTracking(True)
        self.setMinimumSize(*MIN_CAPTURE_SIZE)
        self.setWindowTitle(_OVERLAY_TITLE)

        self._translate_button = _FloatingTranslateButton(_TRANSLATE_TEXT)
        self._translate_button.clicked.connect(self._emit_recognize_requested)

        self._result_view = QPlainTextEdit()
        self._result_view.setReadOnly(True)
        self._result_view.setPlaceholderText(_RESULT_PLACEHOLDER)
        self._result_view.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self._result_view.hide()
        self._result_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self._result_view.customContextMenuRequested.connect(self._show_result_context_menu)
        self._result_view.setStyleSheet(
            "QPlainTextEdit { background-color: rgba(12, 17, 24, 168); color: white; border: 1px solid rgba(255, 255, 255, 36); border-radius: 10px; padding: 8px; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self._result_view, 1)

        self.apply_region(initial_region)
        self._update_result_font()
        logger.info("CaptureRegionOverlay initialized. region=%s", initial_region)

    def apply_region(self, region: CaptureRegion) -> None:
        self._screen_name = region.screen_name
        self.setGeometry(region.x, region.y, region.width, region.height)
        self._sync_button_geometry()
        self._update_result_font()
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
        self._apply_capture_exclusion()
        logger.info(
            "CaptureRegionOverlay shown. visible=%s geometry=%s button_geometry=%s",
            self.isVisible(),
            self.geometry().getRect(),
            self._translate_button.geometry().getRect(),
        )

    def show_result(self, text: str, is_error: bool = False, streaming: bool = False) -> None:
        logger.info(
            "CaptureRegionOverlay showing result. is_error=%s text_length=%s streaming=%s",
            is_error,
            len(text),
            streaming,
        )
        self._result_view.setPlainText(text)
        self._result_view.setStyleSheet(
            "QPlainTextEdit { background-color: rgba(12, 17, 24, 168); color: %s; border: 1px solid rgba(255, 255, 255, 36); border-radius: 10px; padding: 8px; }"
            % ("rgb(255, 130, 130)" if is_error else "white")
        )
        self._update_result_font()
        self._result_view.show()
        if not streaming:
            self._result_view.verticalScrollBar().setValue(0)

    def clear_result(self) -> None:
        logger.info("CaptureRegionOverlay clearing result")
        self._result_view.clear()
        self._result_view.hide()

    def reset_to_idle(self) -> None:
        self.clear_result()
        self.set_busy(False)

    def set_busy(self, busy: bool) -> None:
        logger.info("CaptureRegionOverlay busy state changed: %s", busy)
        self._translate_button.setEnabled(not busy)
        self._translate_button.setText(_TRANSLATING_TEXT if busy else _TRANSLATE_TEXT)
        self._sync_button_geometry()

    def is_busy(self) -> bool:
        return not self._translate_button.isEnabled()

    def has_result_text(self) -> bool:
        return bool(self._result_view.toPlainText().strip())

    def hideEvent(self, event) -> None:
        self._translate_button.hide()
        super().hideEvent(event)

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self._sync_button_geometry()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_button_geometry()
        self._update_result_font()

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        self._show_overlay_menu(event.globalPos())

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.setBrush(QColor(31, 36, 46, 56))
        painter.setPen(QPen(QColor(61, 214, 140, 228), 1.5))
        painter.drawRoundedRect(rect, 12, 12)

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
        event.accept()

    def leaveEvent(self, event) -> None:
        self.unsetCursor()
        super().leaveEvent(event)

    def _emit_recognize_requested(self) -> None:
        region = self.current_region()
        logger.info("CaptureRegionOverlay translate requested. region=%s", region)
        self.recognize_requested.emit(region)

    def _sync_button_geometry(self) -> None:
        if not self.geometry().isValid():
            return
        button_size = self._translate_button.sizeHint().expandedTo(_BUTTON_MIN_SIZE)
        self._translate_button.resize(button_size)
        self._translate_button.move(self._resolve_button_top_left(button_size))
        if self._translate_button.isVisible():
            self._apply_capture_exclusion()

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

    def _show_result_context_menu(self, point: QPoint) -> None:
        self._show_overlay_menu(self._result_view.mapToGlobal(point))

    def _show_overlay_menu(self, global_pos: QPoint) -> None:
        menu, actions = self._create_overlay_menu()
        selected_action = self._exec_overlay_menu(menu, global_pos)
        if selected_action == actions["clear"]:
            self.clear_requested.emit()
        elif selected_action == actions["hide"]:
            self.hide_requested.emit()
        elif selected_action == actions["settings"]:
            self.settings_requested.emit()

    def _create_overlay_menu(self) -> tuple[QMenu, dict[str, object]]:
        menu = QMenu(self)
        clear_action = menu.addAction(_CLEAR_TRANSLATION_TEXT)
        clear_action.setEnabled(self.has_result_text())
        menu.addSeparator()
        hide_action = menu.addAction(_HIDE_OVERLAY_TEXT)
        settings_action = menu.addAction(_OPEN_SETTINGS_TEXT)
        return menu, {
            "clear": clear_action,
            "hide": hide_action,
            "settings": settings_action,
        }

    def _exec_overlay_menu(self, menu: QMenu, global_pos: QPoint):
        return menu.exec(global_pos)

    def _apply_capture_exclusion(self) -> None:
        self._set_exclude_from_capture(self, enabled=True)
        self._set_exclude_from_capture(self._translate_button, enabled=True)

    def _update_result_font(self) -> None:
        font = QFont(self._result_view.font())
        font.setPointSizeF(self._compute_result_font_point_size())
        self._result_view.setFont(font)

    def _compute_result_font_point_size(self) -> float:
        available_width = max(self._result_view.viewport().width(), self.width() - 32, 1)
        available_height = max(self._result_view.viewport().height(), self.height() - 32, 1)
        proposed = min(available_width / 80.0, available_height / 12.0)
        return max(_MIN_RESULT_FONT, min(proposed, _MAX_RESULT_FONT))

    @staticmethod
    def _set_exclude_from_capture(widget: QWidget, enabled: bool) -> None:
        if sys.platform != "win32":
            return
        try:
            hwnd = int(widget.winId())
            affinity = _WDA_EXCLUDEFROMCAPTURE if enabled else _WDA_NONE
            ctypes.windll.user32.SetWindowDisplayAffinity(wintypes.HWND(hwnd), affinity)
        except Exception:
            logger.exception("Failed to update capture exclusion for widget=%s", widget)
