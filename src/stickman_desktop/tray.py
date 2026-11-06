"""Windows notification-area icon; native callbacks only enqueue messages.

Create, poll and close on the Tk thread. The hidden top-level window deliberately
receives TaskbarCreated broadcasts; it is not a message-only window.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from collections import deque
import math
import os
import struct
import sys
import time

WM_TRAY = 0x8000 + 41
WM_CONTEXTMENU = 0x007B
WM_LBUTTONUP, WM_LBUTTONDBLCLK, WM_RBUTTONUP = 0x0202, 0x0203, 0x0205
WM_COMMAND, WM_CLOSE, WM_NULL = 0x0111, 0x0010, 0
NIN_SELECT, NIN_KEYSELECT = 0x0400, 0x0401
NIM_ADD, NIM_MODIFY, NIM_DELETE, NIM_SETFOCUS, NIM_SETVERSION = range(5)
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_SHOWTIP = 1, 2, 4, 0x80
NOTIFYICON_VERSION_4 = 4
WNDPROC = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)(
    ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
)


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT), ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON), ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256), ("uVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64), ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", GUID), ("hBalloonIcon", wintypes.HICON),
    ]


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT), ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    ]


def _icon_resource(size: int = 32) -> bytes:
    """An original orange stick figure as a 32-bit icon DIB, without image libraries."""
    pixels = bytearray()
    mask_stride = ((size + 31) // 32) * 4
    mask = bytearray(mask_stride * size)
    segments = [(16, 13, 16, 23), (16, 16, 9, 22), (16, 16, 23, 22),
                (16, 23, 10, 30), (16, 23, 22, 30)]

    def line_distance(x, y, a, b, c, d):
        length = (c - a) ** 2 + (d - b) ** 2
        t = max(0.0, min(1.0, ((x - a) * (c - a) + (y - b) * (d - b)) / length))
        return math.hypot(x - a - t * (c - a), y - b - t * (d - b))

    for row, yy in enumerate(reversed(range(size))):
        for xx in range(size):
            x, y = (xx + 0.5) * 32 / size, (yy + 0.5) * 32 / size
            painted = abs(math.hypot(x - 16, y - 7.5) - 5) <= 1.4
            painted = painted or any(line_distance(x, y, *segment) <= 1.3 for segment in segments)
            pixels.extend((0, 122, 255, 255) if painted else (0, 0, 0, 0))
            if not painted:
                mask[row * mask_stride + xx // 8] |= 1 << (7 - xx % 8)
    header = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0,
                         len(pixels) + len(mask), 0, 0, 0, 0)
    return header + pixels + mask


class _Win32Backend:
    def __init__(self, callback) -> None:
        if sys.platform != "win32":
            raise RuntimeError("A bandeja requer Windows 10 ou 11.")
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.hwnd = self.icon = self.instance = 0
        self.taskbar_message = 0
        self._class_registered = self._owned_icon = False
        self._class_name = f"StickmanTray_{os.getpid()}_{id(self)}"
        self.callback_error: str | None = None
        self._configure()

        @WNDPROC
        def window_proc(hwnd, message, wparam, lparam):
            try:
                if callback(message, int(wparam), int(lparam)):
                    return 0
            except Exception as error:
                # Never let ctypes silently discard a callback exception.
                self.callback_error = str(error)
            return self.user32.DefWindowProcW(hwnd, message, wparam, lparam)
        self._window_proc = window_proc

    def _configure(self) -> None:
        signatures = {
            "RegisterClassExW": ([ctypes.POINTER(WNDCLASSEXW)], wintypes.WORD),
            "UnregisterClassW": ([wintypes.LPCWSTR, wintypes.HINSTANCE], wintypes.BOOL),
            "CreateWindowExW": ([wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                 wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                 ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                 wintypes.HINSTANCE, ctypes.c_void_p], wintypes.HWND),
            "DestroyWindow": ([wintypes.HWND], wintypes.BOOL),
            "DefWindowProcW": ([wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                wintypes.LPARAM], ctypes.c_ssize_t),
            "RegisterWindowMessageW": ([wintypes.LPCWSTR], wintypes.UINT),
            "GetSystemMetrics": ([ctypes.c_int], ctypes.c_int),
            "CreateIconFromResourceEx": ([ctypes.c_void_p, wintypes.DWORD, wintypes.BOOL,
                                          wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                          wintypes.UINT], wintypes.HICON),
            "LoadIconW": ([wintypes.HINSTANCE, ctypes.c_void_p], wintypes.HICON),
            "DestroyIcon": ([wintypes.HICON], wintypes.BOOL),
            "CreatePopupMenu": ([], wintypes.HMENU),
            "DestroyMenu": ([wintypes.HMENU], wintypes.BOOL),
            "AppendMenuW": ([wintypes.HMENU, wintypes.UINT, ctypes.c_size_t,
                             wintypes.LPCWSTR], wintypes.BOOL),
            "TrackPopupMenu": ([wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, wintypes.HWND, ctypes.c_void_p], wintypes.UINT),
            "SetForegroundWindow": ([wintypes.HWND], wintypes.BOOL),
            "GetCursorPos": ([ctypes.POINTER(wintypes.POINT)], wintypes.BOOL),
            "PostMessageW": ([wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                              wintypes.LPARAM], wintypes.BOOL),
        }
        for name, (args, result) in signatures.items():
            fn = getattr(self.user32, name)
            fn.argtypes, fn.restype = args, result
        self.kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        self.kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        self.shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
        self.shell32.Shell_NotifyIconW.restype = wintypes.BOOL

    def create(self) -> None:
        self.instance = int(self.kernel32.GetModuleHandleW(None) or 0)
        self.taskbar_message = self.user32.RegisterWindowMessageW("TaskbarCreated")
        if not self.instance or not self.taskbar_message:
            raise OSError("Não foi possível preparar a bandeja do Windows.")
        window_class = WNDCLASSEXW()
        window_class.cbSize = ctypes.sizeof(window_class)
        window_class.lpfnWndProc = self._window_proc
        window_class.hInstance = self.instance
        window_class.lpszClassName = self._class_name
        if not self.user32.RegisterClassExW(ctypes.byref(window_class)):
            raise OSError("Não foi possível registrar a janela da bandeja.")
        self._class_registered = True
        # Parent NULL, style 0: hidden top-level, receiving Explorer broadcasts.
        self.hwnd = int(self.user32.CreateWindowExW(
            0, self._class_name, "Stickman Tray", 0, 0, 0, 0, 0,
            None, None, self.instance, None,
        ) or 0)
        if not self.hwnd:
            raise OSError("Não foi possível criar a janela da bandeja.")
        size = max(16, min(64, self.user32.GetSystemMetrics(49)))  # SM_CXSMICON
        resource = _icon_resource(size)
        buffer = ctypes.create_string_buffer(resource)
        self.icon = int(self.user32.CreateIconFromResourceEx(
            buffer, len(resource), True, 0x00030000, size, size, 0,
        ) or 0)
        self._owned_icon = bool(self.icon)
        if not self.icon:
            self.icon = int(self.user32.LoadIconW(None, ctypes.c_void_p(32512)) or 0)
        if not self.icon:
            raise OSError("Não foi possível criar o ícone da bandeja.")

    def notify(self, action: int, tooltip: str = "Stickman Desktop") -> bool:
        data = NOTIFYICONDATAW()
        data.cbSize = ctypes.sizeof(data)
        data.hWnd, data.uID = self.hwnd, 1
        data.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP | NIF_SHOWTIP
        data.uCallbackMessage, data.hIcon = WM_TRAY, self.icon
        data.szTip = tooltip[:127]
        data.uVersion = NOTIFYICON_VERSION_4
        return bool(self.shell32.Shell_NotifyIconW(action, ctypes.byref(data)))

    def menu(self, entries: list[tuple[int, str]]) -> int:
        menu = self.user32.CreatePopupMenu()
        if not menu:
            raise OSError("Não foi possível abrir o menu da bandeja.")
        try:
            for identifier, label in entries:
                if not self.user32.AppendMenuW(menu, 0, identifier, label):
                    raise OSError("Não foi possível montar o menu da bandeja.")
            point = wintypes.POINT()
            if not self.user32.GetCursorPos(ctypes.byref(point)):
                raise OSError("Não foi possível posicionar o menu da bandeja.")
            self.user32.SetForegroundWindow(self.hwnd)
            command = self.user32.TrackPopupMenu(
                menu, 0x0100 | 0x0080 | 0x0002, point.x, point.y, 0, self.hwnd, None,
            )
            self.user32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
            self.notify(NIM_SETFOCUS)
            return int(command)
        finally:
            self.user32.DestroyMenu(menu)

    def close(self) -> None:
        if self.hwnd:
            self.user32.DestroyWindow(self.hwnd)
            self.hwnd = 0
        if self.icon and self._owned_icon:
            self.user32.DestroyIcon(self.icon)
        self.icon = 0
        if self._class_registered:
            self.user32.UnregisterClassW(self._class_name, self.instance)
            self._class_registered = False


class TrayIcon:
    """Own a tray icon and deliver user intent as strings from ``poll()``."""

    ACTIONS = {
        1: "restore", 2: "toggle_visible", 3: "commands", 4: "windows", 5: "explore",
        6: "story", 7: "stop", 8: "toggle_click_through", 9: "quit",
    }

    def __init__(self) -> None:
        self._backend: _Win32Backend | None = None
        self._events: deque[str] = deque(maxlen=64)
        self._running = self._added = False
        self._hidden = self._click_through = False
        self._retry_at = 0.0
        self.last_error: str | None = None

    @property
    def available(self) -> bool:
        return self._running and self._added

    @property
    def hwnd(self) -> int:
        return self._backend.hwnd if self._backend is not None else 0

    def _tooltip(self) -> str:
        return "Stickman Desktop — " + ("oculto" if self._hidden else "ativo")

    def _add(self) -> bool:
        if not self._backend.notify(NIM_ADD, self._tooltip()):
            # A duplicate broadcast or transient MODIFY failure may leave the
            # icon present. Repair that icon instead of retrying ADD forever.
            if not self._running or not self._backend.notify(NIM_MODIFY, self._tooltip()):
                return False
        if not self._backend.notify(NIM_SETVERSION, self._tooltip()):
            self._backend.notify(NIM_DELETE)
            return False
        return True

    def start(self) -> None:
        if self._running:
            return
        self._events.clear()
        try:
            self._backend = _Win32Backend(self._on_message)
            self._backend.create()
            self._added = self._add()
            if not self._added:
                raise OSError("Não foi possível adicionar o ícone à bandeja.")
            self._running = True
            self.last_error = None
        except Exception:
            self.close()
            raise

    def set_state(self, hidden: bool, click_through: bool) -> None:
        changed = (hidden, click_through) != (self._hidden, self._click_through)
        self._hidden, self._click_through = bool(hidden), bool(click_through)
        if self.available and changed:
            if not self._backend.notify(NIM_MODIFY, self._tooltip()):
                self._lost_icon()

    def _on_message(self, message: int, wparam: int, lparam: int) -> bool:
        if self._backend is not None and message == self._backend.taskbar_message:
            if "_readd" not in self._events:
                self._events.append("_readd")
            return True
        if message == WM_CLOSE:
            self._events.append("quit")
            return True
        if message == WM_TRAY:
            event = lparam & 0xFFFF
            if event in {WM_CONTEXTMENU, WM_RBUTTONUP}:
                if "_menu" not in self._events:
                    self._events.append("_menu")
            elif event in {WM_LBUTTONDBLCLK, NIN_SELECT, NIN_KEYSELECT}:
                self._events.append("restore")
            return True
        if message == WM_COMMAND:
            command = self.ACTIONS.get(wparam & 0xFFFF)
            if command:
                self._events.append(command)
            return True
        return False

    def _menu_entries(self) -> list[tuple[int, str]]:
        return [
            (1, "Restaurar personagem"),
            (2, "Mostrar personagem" if self._hidden else "Ocultar personagem"),
            (3, "Comandos (F2)"), (4, "Janelas visíveis"), (5, "Explorar"),
            (6, "História"), (7, "Parar"),
            (8, "Ativar cliques (F3)" if self._click_through else "Liberar cliques (F3)"),
            (9, "Sair"),
        ]

    def _lost_icon(self) -> None:
        self._added = False
        self._retry_at = time.monotonic() + 2
        self.last_error = "Ícone da bandeja indisponível; mantendo o personagem acessível."
        if "restore" not in self._events:
            self._events.append("restore")

    def poll(self) -> list[str]:
        if not self._running:
            return []
        result = []
        # Native popup messages may enqueue more work while TrackPopupMenu runs;
        # process the current batch only to prevent callback-driven busy loops.
        pending = list(self._events)
        self._events.clear()
        for event in pending:
            if event == "_readd":
                self._added = self._add()
                if not self._added:
                    self._lost_icon()
                else:
                    self.last_error = None
            elif event == "_menu":
                try:
                    action = self.ACTIONS.get(self._backend.menu(self._menu_entries()))
                    if action:
                        result.append(action)
                except OSError as error:
                    self.last_error = str(error)
                    result.append("restore")
            else:
                result.append(event)
        if not self._added and time.monotonic() >= self._retry_at:
            self._added = self._add()
            if not self._added:
                self._retry_at = time.monotonic() + 2
            else:
                self.last_error = None
        # Recovery failures restore on this poll, never strand a hidden overlay.
        if "restore" in self._events:
            self._events.remove("restore")
            if "restore" not in result:
                result.append("restore")
        return result

    def close(self) -> None:
        self._running = False
        if self._backend is not None:
            try:
                if self._backend.hwnd:
                    self._backend.notify(NIM_DELETE)
            finally:
                self._added = False
                self._backend.close()
                self._backend = None
        self._events.clear()
