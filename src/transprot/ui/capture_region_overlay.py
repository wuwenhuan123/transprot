from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from transprot.core.layout import MIN_CAPTURE_SIZE, clamp_capture_region
from transprot.core.models import CaptureRegion

logger = logging.getLogger(__name__)

_RESIZE_MARGIN = 12
_BUTTON_GAP = 10
_BUTTON_ROW_SPACING = 8
_RECOGNIZE_BUTTON_MIN_SIZE = QSize(92, 36)
_CLOSE_BUTTON_MIN_SIZE = QSize(34, 34)
_RECOGNIZE_TEXT = "翻译"
_CLOSE_TEXT = "×"
_CLEAR_RESULT_TEXT = "清除译文"
_RESULT_PLACEHOLDER = "译文会显示在这里"
_FRAME_INSET = 4
_CAPTURE_INSET = 4
_WDA_NONE = 0x0
_WDA_EXCLUDEFROMCAPTURE = 0x11
_STATUS_BORDER_COLORS = {
    "ready": (94, 224, 162),
    "capturing": (117, 197, 255),
    "recognizing": (255, 205, 95),
    "translating": (135, 177, 255),
    "completed": (94, 224, 162),
    "error": (255, 126, 126),
}
_STATUS_BUTTON_TEXT = {
    "ready": _RECOGNIZE_TEXT,
    "capturing": "截图中...",
    "recognizing": "识别中...",
    "translating": "翻译中...",
    "completed": _RECOGNIZE_TEXT,
    "error": _RECOGNIZE_TEXT,
}

if sys.platform == "win32":
    _USER32 = ctypes.WinDLL("user32", use_last_error=True)
    _USER32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
    _USER32.SetWindowDisplayAffinity.restype = wintypes.BOOL
else:
    _USER32 = None


class _FloatingActionButton(QPushButton):
    def __init__(self, text: str, kind: str = "primary") -> None:
        super().__init__(text, None)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setCursor(Qt.PointingHandCursor)
        if kind == "close":
            self.setStyleSheet(
                "QPushButton {"
                " background-color: rgba(16, 20, 26, 220); color: rgb(242, 246, 249); border: 1px solid rgba(255, 255, 255, 22);"
                " border-radius: 11px; font-family: 'Segoe UI Variable Text', 'Microsoft YaHei UI'; font-size: 18px; font-weight: 600; }"
                "QPushButton:hover { background-color: rgba(180, 66, 66, 232); }"
                "QPushButton:pressed { background-color: rgba(154, 52, 52, 236); }"
            )
            shadow_offset = 8
        else:
            self.setStyleSheet(
                "QPushButton {"
                " background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 rgb(96, 228, 164), stop:1 rgb(53, 186, 121));"
                " color: rgb(10, 18, 14); border: none; border-radius: 12px; padding: 0 14px;"
                " font-family: 'Segoe UI Variable Text', 'Microsoft YaHei UI'; font-size: 13px; font-weight: 700; }"
                "QPushButton:hover { background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 rgb(110, 235, 176), stop:1 rgb(66, 198, 133)); }"
                "QPushButton:pressed { background-color: rgb(58, 182, 120); }"
                "QPushButton:disabled { background-color: rgba(118, 128, 138, 175); color: rgba(237, 241, 244, 205); }"
            )
            shadow_offset = 10
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(22)
        shadow.setOffset(0, shadow_offset)
        shadow.setColor(QColor(6, 10, 14, 90))
        self.setGraphicsEffect(shadow)


class CaptureRegionOverlay(QWidget):
    recognize_requested = Signal(object)
    region_committed = Signal(object)
    hide_requested = Signal()
    clear_requested = Signal()

    def __init__(self, initial_region: CaptureRegion) -> None:
        super().__init__(None)
        self._screen_name = initial_region.screen_name
        self._active_handle: str | None = None
        self._press_pos = QPoint()
        self._press_geometry = QRect()
        self._interaction_screen_name = initial_region.screen_name
        self._interaction_screen_rect = initial_region.rect
        self._capture_exclusion_logged = False
        self._current_status = "ready"
        self._busy = False

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setMinimumSize(*MIN_CAPTURE_SIZE)
        self.setWindowTitle("TransProt 翻译框")
        app = QApplication.instance()
        if app is not None and not app.windowIcon().isNull():
            self.setWindowIcon(app.windowIcon())

        self._recognize_button = _FloatingActionButton(_RECOGNIZE_TEXT, "primary")
        self._recognize_button.clicked.connect(self._emit_recognize_requested)
        self._close_button = _FloatingActionButton(_CLOSE_TEXT, "close")
        self._close_button.clicked.connect(self._emit_hide_requested)

        self._result_view = QPlainTextEdit()
        self._result_view.setReadOnly(True)
        self._result_view.setPlaceholderText(_RESULT_PLACEHOLDER)
        self._result_view.hide()
        self._result_view.setFrameStyle(QFrame.NoFrame)
        self._result_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self._result_view.customContextMenuRequested.connect(self._show_result_context_menu)
        result_font = QFont("Microsoft YaHei UI", 12)
        result_font.setHintingPreference(QFont.PreferFullHinting)
        self._result_view.setFont(result_font)
        self._result_view.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self._result_view.setStyleSheet(self._result_stylesheet(False))

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 12)
        shadow.setColor(QColor(6, 10, 14, 90))
        self._result_view.setGraphicsEffect(shadow)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(0)
        layout.addWidget(self._result_view, 1)

        self.apply_region(initial_region)
        self.set_status("ready")
        logger.info("CaptureRegionOverlay initialized. region=%s", initial_region)

    def apply_region(self, region: CaptureRegion) -> None:
        self._screen_name = region.screen_name
        self.setGeometry(region.x, region.y, region.width, region.height)
        self._sync_action_buttons()
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

    def current_capture_region(self) -> CaptureRegion:
        frame_region = self.current_region()
        min_width, min_height = MIN_CAPTURE_SIZE
        inset_x = min(_CAPTURE_INSET, max((frame_region.width - min_width) // 2, 0))
        inset_y = min(_CAPTURE_INSET, max((frame_region.height - min_height) // 2, 0))
        capture_region = CaptureRegion(
            screen_name=frame_region.screen_name,
            x=frame_region.x + inset_x,
            y=frame_region.y + inset_y,
            width=frame_region.width - (inset_x * 2),
            height=frame_region.height - (inset_y * 2),
        )
        logger.info("CaptureRegionOverlay effective capture region: frame=%s capture=%s", frame_region, capture_region)
        return capture_region

    def show_region(self) -> None:
        logger.info("CaptureRegionOverlay show requested. current_geometry=%s", self.geometry().getRect())
        self.setWindowState(Qt.WindowNoState)
        self.showNormal()
        self.show()
        self._sync_action_buttons()
        self._recognize_button.show()
        self._close_button.show()
        self._recognize_button.raise_()
        self._close_button.raise_()
        self._apply_capture_exclusion()
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.ActiveWindowFocusReason)
        logger.info(
            "CaptureRegionOverlay shown. visible=%s geometry=%s active=%s recognize_button=%s close_button=%s",
            self.isVisible(),
            self.geometry().getRect(),
            self.isActiveWindow(),
            self._recognize_button.geometry().getRect(),
            self._close_button.geometry().getRect(),
        )

    def show_result(self, text: str, is_error: bool = False) -> None:
        logger.info("CaptureRegionOverlay showing result. is_error=%s text_length=%s", is_error, len(text))
        self._result_view.setPlainText(text)
        self._result_view.setStyleSheet(self._result_stylesheet(is_error))
        self._result_view.show()
        self._result_view.verticalScrollBar().setValue(0)

    def clear_result(self) -> None:
        logger.info("CaptureRegionOverlay clearing result")
        self._result_view.clear()
        self._result_view.hide()

    def reset_to_idle(self) -> None:
        logger.info("CaptureRegionOverlay resetting to idle state")
        self.clear_result()
        self.set_busy(False)
        self.set_status("ready")

    def set_busy(self, busy: bool) -> None:
        logger.info("CaptureRegionOverlay busy state changed: %s", busy)
        self._busy = busy
        self._refresh_button_state()

    def set_status(self, status: str) -> None:
        self._current_status = status if status in _STATUS_BUTTON_TEXT else "ready"
        self._refresh_button_state()
        self.update()

    def hideEvent(self, event) -> None:
        self._recognize_button.hide()
        self._close_button.hide()
        super().hideEvent(event)

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self._sync_action_buttons()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_action_buttons()

    def contextMenuEvent(self, event) -> None:
        if not self._can_clear_result():
            return super().contextMenuEvent(event)
        self._show_clear_menu(event.globalPos())
        event.accept()

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        red, green, blue = _STATUS_BORDER_COLORS.get(self._current_status, _STATUS_BORDER_COLORS["ready"])
        glow_rect = self.rect().adjusted(_FRAME_INSET, _FRAME_INSET, -_FRAME_INSET, -_FRAME_INSET)
        frame_rect = glow_rect.adjusted(4, 4, -4, -4)

        painter.setBrush(QColor(8, 12, 16, 22))
        painter.setPen(QPen(QColor(red, green, blue, 42), 5))
        painter.drawRoundedRect(glow_rect, 18, 18)

        painter.setBrush(QColor(10, 14, 18, 24))
        painter.setPen(QPen(QColor(255, 255, 255, 20), 1))
        painter.drawRoundedRect(frame_rect, 16, 16)

        painter.setPen(QPen(QColor(red, green, blue, 210), 2))
        painter.drawRoundedRect(frame_rect, 16, 16)

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
        region = self.current_capture_region()
        logger.info("CaptureRegionOverlay translate requested. capture_region=%s", region)
        self.recognize_requested.emit(region)

    def _emit_hide_requested(self) -> None:
        logger.info("CaptureRegionOverlay hide requested")
        self.hide_requested.emit()

    def _show_result_context_menu(self, position: QPoint) -> None:
        if not self._can_clear_result():
            return
        self._show_clear_menu(self._result_view.mapToGlobal(position))

    def _show_clear_menu(self, global_pos: QPoint) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background-color: rgba(10, 14, 18, 240); color: rgb(242, 246, 249); border: 1px solid rgba(255, 255, 255, 18); border-radius: 10px; padding: 6px; }"
            "QMenu::item { padding: 8px 18px; border-radius: 8px; }"
            "QMenu::item:selected { background-color: rgba(94, 224, 162, 42); }"
        )
        clear_action = menu.addAction(_CLEAR_RESULT_TEXT)
        selected = menu.exec(global_pos)
        if selected == clear_action:
            self._request_clear_result()

    def _request_clear_result(self) -> None:
        logger.info("CaptureRegionOverlay clear requested")
        self.clear_requested.emit()

    def _can_clear_result(self) -> bool:
        return self._result_view.isVisible() and bool(self._result_view.toPlainText().strip()) and not self._busy

    def _apply_capture_exclusion(self) -> None:
        overlay_excluded = self._set_excluded_from_capture(self, True)
        recognize_excluded = self._set_excluded_from_capture(self._recognize_button, True)
        close_excluded = self._set_excluded_from_capture(self._close_button, True)
        if not self._capture_exclusion_logged:
            logger.info(
                "Capture exclusion applied. overlay=%s recognize_button=%s close_button=%s",
                overlay_excluded,
                recognize_excluded,
                close_excluded,
            )
            self._capture_exclusion_logged = True

    def _sync_action_buttons(self) -> None:
        if not self.geometry().isValid():
            return
        recognize_size = self._recognize_button.sizeHint().expandedTo(_RECOGNIZE_BUTTON_MIN_SIZE)
        close_size = self._close_button.sizeHint().expandedTo(_CLOSE_BUTTON_MIN_SIZE)
        self._recognize_button.resize(recognize_size)
        self._close_button.resize(close_size)
        recognize_top_left, close_top_left = self._resolve_action_button_positions(recognize_size, close_size)
        self._recognize_button.move(recognize_top_left)
        self._close_button.move(close_top_left)

    def _resolve_action_button_positions(self, recognize_size: QSize, close_size: QSize) -> tuple[QPoint, QPoint]:
        geometry = self.geometry()
        screen = QApplication.screenAt(geometry.center())
        total_width = recognize_size.width() + _BUTTON_ROW_SPACING + close_size.width()
        preferred_x = geometry.right() - total_width + 1

        if screen is None:
            row_x = preferred_x
            row_y = geometry.top() - max(recognize_size.height(), close_size.height()) - _BUTTON_GAP
        else:
            screen_rect = screen.availableGeometry()
            row_x = max(screen_rect.left(), min(preferred_x, screen_rect.right() - total_width + 1))
            row_height = max(recognize_size.height(), close_size.height())
            above_y = geometry.top() - row_height - _BUTTON_GAP
            below_y = geometry.bottom() + _BUTTON_GAP + 1
            if above_y >= screen_rect.top():
                row_y = above_y
            else:
                row_y = min(below_y, screen_rect.bottom() - row_height + 1)

        recognize_y = row_y + max(0, (close_size.height() - recognize_size.height()) // 2)
        close_y = row_y + max(0, (recognize_size.height() - close_size.height()) // 2)
        recognize_top_left = QPoint(row_x, recognize_y)
        close_top_left = QPoint(row_x + recognize_size.width() + _BUTTON_ROW_SPACING, close_y)
        return recognize_top_left, close_top_left

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

    def _refresh_button_state(self) -> None:
        self._recognize_button.setEnabled(not self._busy)
        self._recognize_button.setText(_STATUS_BUTTON_TEXT.get(self._current_status, _RECOGNIZE_TEXT))
        self._sync_action_buttons()

    @staticmethod
    def _result_stylesheet(is_error: bool) -> str:
        text_color = "rgb(255, 146, 146)" if is_error else "rgb(246, 249, 251)"
        border_color = "rgba(255, 126, 126, 96)" if is_error else "rgba(255, 255, 255, 20)"
        return (
            "QPlainTextEdit { background-color: rgba(9, 13, 18, 208); color: %s; border: 1px solid %s;"
            " border-radius: 18px; padding: 16px 18px; selection-background-color: rgba(135, 177, 255, 120);"
            " font-family: 'Microsoft YaHei UI', 'Segoe UI Variable Text'; }"
        ) % (text_color, border_color)

    @staticmethod
    def _set_excluded_from_capture(widget: QWidget, excluded: bool) -> bool:
        if _USER32 is None:
            return False
        try:
            hwnd = int(widget.winId())
        except Exception:
            return False
        affinity = _WDA_EXCLUDEFROMCAPTURE if excluded else _WDA_NONE
        return bool(_USER32.SetWindowDisplayAffinity(hwnd, affinity))
