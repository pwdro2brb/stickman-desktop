from __future__ import annotations

import ctypes
from ctypes import wintypes
import subprocess
import sys
from dataclasses import dataclass

SW_MINIMIZE = 6
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
PM_REMOVE = 0x0001
VK_F2, VK_F3, VK_F4 = 0x71, 0x72, 0x73
GA_ROOT = 2
DWMWA_CLOAKED = 14
MONITORINFOF_PRIMARY = 1
HWND_TOPMOST = -1
SWP_NOACTIVATE = 0x0010
SWP_NOOWNERZORDER = 0x0200
HMONITOR = getattr(wintypes, "HMONITOR", wintypes.HANDLE)
WNDENUMPROC = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)(
    wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
)
MONITORENUMPROC = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)(
    wintypes.BOOL, HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM
)


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


def _configure_user32(api) -> None:
    # ctypes otherwise assumes an int result, which truncates HWNDs on 64-bit Windows.
    signatures = {
        "EnumWindows": ([WNDENUMPROC, wintypes.LPARAM], wintypes.BOOL),
        "EnumDisplayMonitors": ([wintypes.HDC, ctypes.POINTER(wintypes.RECT),
                                 MONITORENUMPROC, wintypes.LPARAM], wintypes.BOOL),
        "GetMonitorInfoW": ([HMONITOR, ctypes.POINTER(MONITORINFO)], wintypes.BOOL),
        "GetCursorPos": ([ctypes.POINTER(wintypes.POINT)], wintypes.BOOL),
        "SetWindowPos": ([wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                          ctypes.c_int, ctypes.c_int, wintypes.UINT], wintypes.BOOL),
        "GetAncestor": ([wintypes.HWND, wintypes.UINT], wintypes.HWND),
        "GetForegroundWindow": ([], wintypes.HWND),
        "GetDesktopWindow": ([], wintypes.HWND),
        "GetShellWindow": ([], wintypes.HWND),
        "IsWindow": ([wintypes.HWND], wintypes.BOOL),
        "IsWindowVisible": ([wintypes.HWND], wintypes.BOOL),
        "IsIconic": ([wintypes.HWND], wintypes.BOOL),
        "GetWindowTextLengthW": ([wintypes.HWND], ctypes.c_int),
        "GetWindowTextW": ([wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
        "GetWindowRect": ([wintypes.HWND, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL),
        "ShowWindow": ([wintypes.HWND, ctypes.c_int], wintypes.BOOL),
        "GetWindowLongW": ([wintypes.HWND, ctypes.c_int], wintypes.LONG),
        "SetWindowLongW": ([wintypes.HWND, ctypes.c_int, wintypes.LONG], wintypes.LONG),
        "RegisterHotKey": ([wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT], wintypes.BOOL),
        "UnregisterHotKey": ([wintypes.HWND, ctypes.c_int], wintypes.BOOL),
        "PeekMessageW": ([ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                          wintypes.UINT, wintypes.UINT, wintypes.UINT], wintypes.BOOL),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(api, name)
        function.argtypes, function.restype = arguments, result


if sys.platform == "win32":
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    _configure_user32(user32)
    try:
        dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
        dwmapi.DwmGetWindowAttribute.argtypes = [
            wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD
        ]
        dwmapi.DwmGetWindowAttribute.restype = wintypes.LONG
    except (OSError, AttributeError):
        dwmapi = None
else:
    user32 = None
    dwmapi = None


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    rect: tuple[int, int, int, int]


@dataclass(frozen=True)
class MonitorInfo:
    rect: tuple[int, int, int, int]
    work_rect: tuple[int, int, int, int]
    primary: bool


def require_windows() -> None:
    if user32 is None:
        raise RuntimeError("Stickman Desktop requer Windows 10 ou 11.")


def _api_error(message: str) -> OSError:
    code = ctypes.get_last_error() if hasattr(ctypes, "get_last_error") else 0
    if code and hasattr(ctypes, "WinError"):
        return ctypes.WinError(code)
    return OSError(message)


def enumerate_monitors() -> list[MonitorInfo]:
    """Read monitor bounds and taskbar-aware work areas in screen coordinates."""
    require_windows()
    monitors: list[MonitorInfo] = []
    errors: list[Exception] = []

    @MONITORENUMPROC
    def collect(handle, _dc, _rect, _parameter):
        try:
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(info)
            if not user32.GetMonitorInfoW(handle, ctypes.byref(info)):
                raise _api_error("Não foi possível consultar um monitor.")
            rect = (info.rcMonitor.left, info.rcMonitor.top,
                    info.rcMonitor.right, info.rcMonitor.bottom)
            work = (info.rcWork.left, info.rcWork.top,
                    info.rcWork.right, info.rcWork.bottom)
            if rect[2] <= rect[0] or rect[3] <= rect[1]:
                raise OSError("O Windows retornou um monitor sem área utilizável.")
            if (work[2] <= work[0] or work[3] <= work[1]
                    or work[0] < rect[0] or work[1] < rect[1]
                    or work[2] > rect[2] or work[3] > rect[3]):
                raise OSError("O Windows retornou uma área de trabalho inválida.")
            monitors.append(MonitorInfo(rect, work, bool(info.dwFlags & MONITORINFOF_PRIMARY)))
            return True
        except Exception as error:
            # Never let ctypes swallow errors raised inside a native callback.
            errors.append(error)
            return False

    if hasattr(ctypes, "set_last_error"):
        ctypes.set_last_error(0)
    completed = user32.EnumDisplayMonitors(None, None, collect, 0)
    if errors:
        raise OSError("Não foi possível ler os monitores.") from errors[0]
    if not completed:
        raise _api_error("Não foi possível enumerar os monitores.")
    if not monitors:
        raise OSError("Nenhum monitor disponível.")
    return monitors


def cursor_position() -> tuple[int, int]:
    """Return the current cursor position without moving it or changing focus."""
    require_windows()
    point = wintypes.POINT()
    if hasattr(ctypes, "set_last_error"):
        ctypes.set_last_error(0)
    if not user32.GetCursorPos(ctypes.byref(point)):
        raise _api_error("Não foi possível consultar a posição do cursor.")
    return point.x, point.y


def position_overlay(hwnd: int, rect: tuple[int, int, int, int]) -> None:
    """Position the supplied overlay in global coordinates without taking focus."""
    require_windows()
    left, top, right, bottom = rect
    if not hwnd or right <= left or bottom <= top:
        raise ValueError("A janela e a área do overlay devem ser válidas.")
    if hasattr(ctypes, "set_last_error"):
        ctypes.set_last_error(0)
    if not user32.SetWindowPos(top_level_window(hwnd), HWND_TOPMOST, left, top,
                              right - left, bottom - top,
                              SWP_NOACTIVATE | SWP_NOOWNERZORDER):
        raise _api_error("Não foi possível posicionar o overlay.")


def window_title(hwnd: int) -> str:
    require_windows()
    length = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value.strip()


def window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    require_windows()
    rect = wintypes.RECT()
    if hwnd and user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        if rect.right > rect.left and rect.bottom > rect.top:
            return rect.left, rect.top, rect.right, rect.bottom
    return None


def top_level_window(hwnd: int) -> int:
    """Resolve Tk child handles to their top-level wrapper; retain stale handles."""
    require_windows()
    if not hwnd:
        return 0
    return int(user32.GetAncestor(hwnd, GA_ROOT) or hwnd)


def _window_exclusions(excluded: set[int] | None) -> set[int]:
    handles = {int(hwnd) for hwnd in (excluded or set()) if hwnd}
    handles.update(top_level_window(hwnd) for hwnd in tuple(handles))
    handles.update(int(hwnd) for hwnd in (user32.GetShellWindow(), user32.GetDesktopWindow()) if hwnd)
    return handles


def _window_info(hwnd: int, excluded: set[int]) -> WindowInfo | None:
    if not hwnd or hwnd in excluded or not user32.IsWindow(hwnd):
        return None
    if top_level_window(hwnd) in excluded:
        return None
    if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
        return None
    if dwmapi is not None:
        cloaked = wintypes.DWORD()
        result = dwmapi.DwmGetWindowAttribute(
            hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked)
        )
        if result == 0 and cloaked.value:
            return None
    title = window_title(hwnd)
    rect = window_rect(hwnd)
    if not title or rect is None or not user32.IsWindow(hwnd):
        return None
    return WindowInfo(hwnd, title, rect)


def foreground_window(excluded: set[int] | None = None) -> WindowInfo | None:
    require_windows()
    return _window_info(int(user32.GetForegroundWindow() or 0), _window_exclusions(excluded))


def enumerate_visible_windows(excluded: set[int] | None = None) -> list[WindowInfo]:
    """Read a fresh snapshot of visible application windows in desktop Z order."""
    require_windows()
    excluded_handles = _window_exclusions(excluded)
    windows: list[WindowInfo] = []
    errors: list[Exception] = []

    @WNDENUMPROC
    def collect(hwnd, _parameter):
        try:
            info = _window_info(int(hwnd or 0), excluded_handles)
            if info is not None:
                windows.append(info)
            return True
        except Exception as error:
            # Exceptions must not escape a ctypes callback: ctypes would discard them.
            errors.append(error)
            return False

    if hasattr(ctypes, "set_last_error"):
        ctypes.set_last_error(0)
    completed = user32.EnumWindows(collect, 0)
    if errors:
        raise OSError("Não foi possível ler as janelas visíveis.") from errors[0]
    if not completed:
        code = ctypes.get_last_error() if hasattr(ctypes, "get_last_error") else 0
        if code and hasattr(ctypes, "WinError"):
            raise ctypes.WinError(code)
        raise OSError("Não foi possível enumerar as janelas visíveis.")
    return windows


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
