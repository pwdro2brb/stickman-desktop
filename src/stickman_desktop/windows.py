from __future__ import annotations

import ctypes
from ctypes import wintypes
import subprocess
import sys
from dataclasses import dataclass

if sys.platform == "win32":
    user32 = ctypes.windll.user32
else:
    user32 = None

SW_MINIMIZE = 6
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
PM_REMOVE = 0x0001
VK_F2, VK_F3, VK_F4 = 0x71, 0x72, 0x73


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    rect: tuple[int, int, int, int]


def require_windows() -> None:
    if user32 is None:
        raise RuntimeError("Stickman Desktop requer Windows 10 ou 11.")


def window_title(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value.strip()


def window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    rect = wintypes.RECT()
    if hwnd and user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return rect.left, rect.top, rect.right, rect.bottom
    return None


def foreground_window(excluded: set[int] | None = None) -> WindowInfo | None:
    require_windows()
    excluded = excluded or set()
    hwnd = int(user32.GetForegroundWindow())
    if not hwnd or hwnd in excluded:
        return None
    title = window_title(hwnd)
    rect = window_rect(hwnd)
    if not title or rect is None:
        return None
    return WindowInfo(hwnd, title, rect)


def minimize_window(hwnd: int, excluded: set[int] | None = None) -> bool:
    require_windows()
    if not hwnd or hwnd in (excluded or set()):
        return False
    return bool(user32.ShowWindow(hwnd, SW_MINIMIZE))


def set_click_through(hwnd: int, enabled: bool) -> None:
    require_windows()
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    style |= WS_EX_LAYERED | WS_EX_TOOLWINDOW
    style = style | WS_EX_TRANSPARENT if enabled else style & ~WS_EX_TRANSPARENT
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)


def launch(command: list[str]) -> None:
    subprocess.Popen(command, shell=False)


class GlobalHotkeys:
    """Registers F2/F3/F4 through Win32, independent of Tk focus."""

    KEYS = {1: VK_F2, 2: VK_F3, 3: VK_F4}

    def __init__(self):
        require_windows()
        self.registered: list[int] = []

    def register(self) -> None:
        for identifier, key in self.KEYS.items():
            if user32.RegisterHotKey(None, identifier, MOD_NOREPEAT, key):
                self.registered.append(identifier)

    def poll(self) -> list[int]:
        message = wintypes.MSG()
        events: list[int] = []
        while user32.PeekMessageW(ctypes.byref(message), None, WM_HOTKEY, WM_HOTKEY, PM_REMOVE):
            events.append(int(message.wParam))
        return events

    def close(self) -> None:
        for identifier in self.registered:
            user32.UnregisterHotKey(None, identifier)
        self.registered.clear()
