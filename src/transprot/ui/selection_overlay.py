from __future__ import annotations

from PySide6.QtCore import QObject, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QWidget

from transprot.core.models import SelectionRegion


class SelectionOverlay(QWidget):
    region_selected = Signal(object)
    cancelled = Signal()

    def __init__(self, screen) -> None:
        super().__init__(None)
        self._screen = screen
        self._start: QPoint | None = None
        self._current: QPoint | None = None
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setCursor(Qt.CrossCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setGeometry(screen.geometry())

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.raise_()
        self.activateWindow()
        self.setFocus()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key_Escape:
            self.cancelled.emit()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._start = event.position().toPoint()
            self._current = self._start
            self.update()
            return
        if event.button() == Qt.RightButton:
            self.cancelled.emit()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._start is not None:
            self._current = event.position().toPoint()
            self.update()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.LeftButton or self._start is None:
            super().mouseReleaseEvent(event)
            return
        self._current = event.position().toPoint()
        local_rect = QRect(self._start, self._current).normalized()
        self._start = None
        self._current = None
        self.update()
        if local_rect.width() < 8 or local_rect.height() < 8:
            self.cancelled.emit()
            return
        global_geometry = self.geometry()
        region = SelectionRegion(
            screen_name=self._screen.name(),
            x=global_geometry.x() + local_rect.x(),
            y=global_geometry.y() + local_rect.y(),
            width=local_rect.width(),
            height=local_rect.height(),
            device_pixel_ratio=self._screen.devicePixelRatio(),
        )
        self.region_selected.emit(region)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._start is None or self._current is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(61, 214, 140), 2)
        painter.setPen(pen)
        painter.drawRect(QRect(self._start, self._current).normalized())


class SelectionSession(QObject):
    region_selected = Signal(object)
    cancelled = Signal()

    def __init__(self, screens: list) -> None:
        super().__init__()
        self._screens = screens
        self._overlays: list[SelectionOverlay] = []
        self._active = False

    def start(self) -> None:
        if self._active:
            return
        self._active = True
        for screen in self._screens:
            overlay = SelectionOverlay(screen)
            overlay.region_selected.connect(self._handle_region_selected)
            overlay.cancelled.connect(self._handle_cancelled)
            overlay.show()
            overlay.raise_()
            self._overlays.append(overlay)

    def stop(self) -> None:
        for overlay in self._overlays:
            overlay.close()
            overlay.deleteLater()
        self._overlays.clear()
        self._active = False

    def _handle_region_selected(self, region: SelectionRegion) -> None:
        if not self._active:
            return
        self.stop()
        self.region_selected.emit(region)

    def _handle_cancelled(self) -> None:
        if not self._active:
            return
        self.stop()
        self.cancelled.emit()
