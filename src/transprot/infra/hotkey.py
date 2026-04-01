from __future__ import annotations

import ctypes
import ctypes.wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication, QObject, Signal

from transprot.core.errors import HotkeyError

user32 = ctypes.windll.user32

WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008

VK_CODES = {chr(code): code for code in range(ord("A"), ord("Z") + 1)}
VK_CODES.update({str(number): ord(str(number)) for number in range(10)})
VK_CODES.update({f"F{index}": 0x6F + index for index in range(1, 13)})


def _parse_hotkey(hotkey: str) -> tuple[int, int]:
    parts = [part.strip().upper() for part in hotkey.split("+") if part.strip()]
    modifiers = 0
    key_code = 0
    for part in parts:
        if part in {"CTRL", "CONTROL"}:
            modifiers |= MOD_CONTROL
        elif part == "ALT":
            modifiers |= MOD_ALT
        elif part == "SHIFT":
            modifiers |= MOD_SHIFT
        elif part in {"WIN", "META"}:
            modifiers |= MOD_WIN
        elif part in VK_CODES:
            key_code = VK_CODES[part]
        else:
            raise HotkeyError(f"Unsupported hotkey part: {part}")

    if not modifiers or not key_code:
        raise HotkeyError("Hotkey must contain at least one modifier and one key.")
    return modifiers, key_code


class GlobalHotkeyManager(QObject, QAbstractNativeEventFilter):
    activated = Signal()

    HOTKEY_ID = 0xB001

    def __init__(self) -> None:
        QObject.__init__(self)
        QAbstractNativeEventFilter.__init__(self)
        self._registered = False
        self._filter_installed = False

    def register_hotkey(self, hotkey: str) -> None:
        modifiers, key_code = _parse_hotkey(hotkey)
        self.unregister_hotkey()
        if not user32.RegisterHotKey(None, self.HOTKEY_ID, modifiers, key_code):
            raise HotkeyError(f"Failed to register hotkey: {hotkey}")
        app = QCoreApplication.instance()
        if app is None:
            raise HotkeyError("QCoreApplication is not initialized.")
        if not self._filter_installed:
            app.installNativeEventFilter(self)
            self._filter_installed = True
        self._registered = True

    def unregister_hotkey(self) -> None:
        if self._registered:
            user32.UnregisterHotKey(None, self.HOTKEY_ID)
            self._registered = False

    def nativeEventFilter(self, eventType, message):
        event_name = eventType.decode() if isinstance(eventType, (bytes, bytearray, memoryview)) else eventType
        if event_name != "windows_generic_MSG":
            return False, 0

        msg = ctypes.wintypes.MSG.from_address(int(message))
        if msg.message == WM_HOTKEY and msg.wParam == self.HOTKEY_ID:
            self.activated.emit()
            return True, 0
        return False, 0
