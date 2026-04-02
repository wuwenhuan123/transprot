from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QApplication, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from transprot.core.layout import MIN_CAPTURE_SIZE, clamp_capture_region
from transprot.core.models import CaptureRegion

logger = logging.getLogger(__name__)

_RESIZE_MARGIN = 10
_BUTTON_GAP = 10
_BUTTON_ROW_SPACING = 8
_RECOGNIZE_BUTTON_MIN_SIZE = QSize(96, 36)
_CLOSE_BUTTON_MIN_SIZE = QSize(36, 36)
_RECOGNIZE_TEXT = "翻译"
_RECOGNIZING_TEXT = "翻译中..."
_CLOSE_TEXT = "×"
_RESULT_PLACEHOLDER = "翻译结果"
_FRAME_INSET = 2
_CAPTURE_INSET = 4
_WDA_NONE = 0x0
_WDA_EXCLUDEFROMCAPTURE = 0x11

if sys.platform == "win32":
    _USER32 = ctypes.WinDLL("user32", use_last_error=True)
    _USER32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
    _USER32.SetWindowDisplayAffinity.restype = wintypes.BOOL
else:
    _USER32 = None


class _FloatingActionButton(QPushButton):
    def __init__(self, text: str, style_type: str) -> None:
        super().__init__(text, None)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setCursor(Qt.PointingHandCursor)
        if style_type == "close":
            self.setStyleSheet(
                "QPushButton { background-color: rgba(28, 32, 40, 220); color: rgb(245, 245, 245); border: 1px solid rgba(255, 255, 255, 35); border-radius: 12px; font-size: 18px; font-weight: 600; }"
                "QPushButton:hover { background-color: rgba(196, 70, 70, 235); }"
            )
        else:
            self.setStyleSheet(
                "QPushButton { background-color: rgba(61, 214, 140, 235); color: rgb(18, 22, 28); border: none; border-radius: 12px; padding: 6px 14px; font-weight: 600; }"
                "QPushButton:disabled { background-color: rgba(120, 130, 145, 180); color: rgba(240, 240, 240, 200); }"
            )


class CaptureRegionOverlay(QWidget):
    recognize_requested = Signal(object)
    region_committed = Signal(object)
    hide_requested = Signal()

    def __init__(self, initial_region: CaptureRegion) -> None:
        super().__init__(None)
        self._screen_name = initial_region.screen_name
        self._active_handle: str | None = None
        self._press_pos = QPoint()
        self._press_geometry = QRect()
        self._interaction_screen_name = initial_region.screen_name
        self._interaction_screen_rect = initial_region.rect
        self._capture_exclusion_logged = False

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
        self._result_view.setStyleSheet(
            "QPlainTextEdit { background-color: rgba(9, 11, 16, 170); color: white; border: 1px solid rgba(255, 255, 255, 35); border-radius: 10px; padding: 8px; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        layout.addWidget(self._result_view, 1)

        self.apply_region(initial_region)
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

    def set_busy(self, busy: bool) -> None:
        logger.info("CaptureRegionOverlay busy state changed: %s", busy)
        self._recognize_button.setEnabled(not busy)
        self._recognize_button.setText(_RECOGNIZING_TEXT if busy else _RECOGNIZE_TEXT)
        self._sync_action_buttons()

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

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(_FRAME_INSET, _FRAME_INSET, -_FRAME_INSET, -_FRAME_INSET)
        painter.setBrush(QColor(18, 25, 33, 92))
        painter.setPen(QPen(QColor(61, 214, 140, 245), 4))
        painter.drawRoundedRect(rect, 14, 14)

        corner_pen = QPen(QColor(245, 255, 249, 235), 3)
        painter.setPen(corner_pen)
        corner = 20
        left = rect.left()
        right = rect.right()
        top = rect.top()
        bottom = rect.bottom()
        painter.drawLine(left + 8, top + 8, left + 8 + corner, top + 8)
        painter.drawLine(left + 8, top + 8, left + 8, top + 8 + corner)
        painter.drawLine(right - 8 - corner, top + 8, right - 8, top + 8)
        painter.drawLine(right - 8, top + 8, right - 8, top + 8 + corner)
        painter.drawLine(left + 8, bottom - 8, left + 8 + corner, bottom - 8)
        painter.drawLine(left + 8, bottom - 8 - corner, left + 8, bottom - 8)
        painter.drawLine(right - 8 - corner, bottom - 8, right - 8, bottom - 8)
        painter.drawLine(right - 8, bottom - 8 - corner, right - 8, bottom - 8)

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
