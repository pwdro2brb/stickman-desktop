import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from stickman_desktop import windows


@dataclass
class FakeWindow:
    title: str = "Editor"
    rect: tuple[int, int, int, int] | None = (10, 20, 610, 420)
    visible: bool = True
    minimized: bool = False
    valid: bool = True


class FakeUser32:
    def __init__(self):
        self.windows = {}
        self.roots = {}
        self.foreground = 0
        self.enum_ok = True

    def GetAncestor(self, hwnd, flag):
        assert flag == windows.GA_ROOT
        return self.roots.get(hwnd, hwnd)

    def GetShellWindow(self):
        return 1

    def GetDesktopWindow(self):
        return 2

    def GetForegroundWindow(self):
        return self.foreground

    def IsWindow(self, hwnd):
        return hwnd in self.windows and self.windows[hwnd].valid

    def IsWindowVisible(self, hwnd):
        return self.windows[hwnd].visible

    def IsIconic(self, hwnd):
        return self.windows[hwnd].minimized

    def GetWindowTextLengthW(self, hwnd):
        return len(self.windows[hwnd].title)

    def GetWindowTextW(self, hwnd, buffer, length):
        buffer.value = self.windows[hwnd].title[:length - 1]
        return len(buffer.value)

    def GetWindowRect(self, hwnd, pointer):
        rect = self.windows[hwnd].rect
        if rect is None:
            return False
        target = ctypes.cast(pointer, ctypes.POINTER(wintypes.RECT)).contents
        target.left, target.top, target.right, target.bottom = rect
        return True

    def EnumWindows(self, callback, parameter):
        if not self.enum_ok:
            return False
        for hwnd in tuple(self.windows):
            if not callback(hwnd, parameter):
                return False
        return True


class FakeDwm:
    def __init__(self, cloaked=(), failed=()):
        self.cloaked = set(cloaked)
        self.failed = set(failed)

    def DwmGetWindowAttribute(self, hwnd, attribute, pointer, size):
        assert attribute == windows.DWMWA_CLOAKED
        assert size == ctypes.sizeof(wintypes.DWORD)
        if hwnd in self.failed:
            return -1
        ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD)).contents.value = int(hwnd in self.cloaked)
        return 0


@pytest.fixture
def api(monkeypatch):
    fake = FakeUser32()
    monkeypatch.setattr(windows, "user32", fake)
    monkeypatch.setattr(windows, "dwmapi", None)
    return fake


def test_enumerate_filters_non_application_windows(api, monkeypatch):
    api.windows = {
        1: FakeWindow("Shell"),
        2: FakeWindow("Desktop"),
        10: FakeWindow("Editor"),
        11: FakeWindow(visible=False),
        12: FakeWindow(minimized=True),
        13: FakeWindow(title=""),
        14: FakeWindow(rect=(10, 20, 10, 420)),
        15: FakeWindow(valid=False),
        16: FakeWindow("Other virtual desktop"),
        17: FakeWindow(title="   "),
        18: FakeWindow(rect=None),
        19: FakeWindow("Left monitor", (-900, -200, -100, 400)),
        20: FakeWindow(rect=(10, 20, 610, 19)),
    }
    monkeypatch.setattr(windows, "dwmapi", FakeDwm(cloaked={16}))

    assert windows.enumerate_visible_windows() == [
        windows.WindowInfo(10, "Editor", (10, 20, 610, 420)),
        windows.WindowInfo(19, "Left monitor", (-900, -200, -100, 400)),
    ]


def test_exclusions_resolve_tk_wrapper_and_preserve_large_handles(api):
    if ctypes.sizeof(wintypes.HWND) < 8:
        pytest.skip("64-bit HWND coverage requires a 64-bit interpreter")
    external = (1 << 40) + 10
    wrapper = (1 << 40) + 20
    child = wrapper + 1
    api.windows = {external: FakeWindow(), wrapper: FakeWindow("Overlay")}
    api.roots[child] = wrapper
    excluded = {child}

    assert windows.top_level_window(child) == wrapper
    assert [info.hwnd for info in windows.enumerate_visible_windows(excluded)] == [external]
    assert excluded == {child}
    api.foreground = wrapper
    assert windows.foreground_window(excluded) is None


@pytest.mark.parametrize("handle", [0, 1, 2, 11, 12, 13, 14, 15, 16])
def test_foreground_uses_same_visibility_filters(api, monkeypatch, handle):
    api.windows = {
        1: FakeWindow("Shell"),
        2: FakeWindow("Desktop"),
        11: FakeWindow(visible=False),
        12: FakeWindow(minimized=True),
        13: FakeWindow(title=""),
        14: FakeWindow(rect=(0, 0, 0, 10)),
        15: FakeWindow(valid=False),
        16: FakeWindow(),
    }
    api.foreground = handle
    monkeypatch.setattr(windows, "dwmapi", FakeDwm(cloaked={16}))
    assert windows.foreground_window() is None


def test_snapshots_refresh_titles_rectangles_and_closed_windows(api):
    api.windows[10] = FakeWindow("Before")
    api.foreground = 10
    first = windows.enumerate_visible_windows()
    api.windows[10].title = "After"
    api.windows[10].rect = (-500, 50, 100, 500)
    updated = windows.enumerate_visible_windows()

    assert first == [windows.WindowInfo(10, "Before", (10, 20, 610, 420))]
    assert updated == [windows.WindowInfo(10, "After", (-500, 50, 100, 500))]
    assert windows.foreground_window() == updated[0]
    del api.windows[10]
    assert windows.enumerate_visible_windows() == []
    assert windows.foreground_window() is None


def test_dwm_unavailable_or_failed_does_not_hide_valid_windows(api, monkeypatch):
    api.windows[10] = FakeWindow()
    assert len(windows.enumerate_visible_windows()) == 1
    monkeypatch.setattr(windows, "dwmapi", FakeDwm(failed={10}))
    assert len(windows.enumerate_visible_windows()) == 1


def test_enumeration_failure_raises_instead_of_returning_partial_snapshot(api):
    api.enum_ok = False
    with pytest.raises(OSError):
        windows.enumerate_visible_windows()


def test_callback_errors_are_propagated_with_their_cause(api, monkeypatch):
    api.windows = {10: FakeWindow(), 11: FakeWindow()}
    original = api.GetWindowTextLengthW

    def read_title(hwnd):
        if hwnd == 11:
            raise ValueError("simulated metadata error")
        return original(hwnd)

    monkeypatch.setattr(api, "GetWindowTextLengthW", read_title)
    with pytest.raises(OSError) as error:
        windows.enumerate_visible_windows()
    assert isinstance(error.value.__cause__, ValueError)


def test_top_level_window_retains_handle_when_ancestor_is_unavailable(api):
    api.roots[10] = 0
    assert windows.top_level_window(10) == 10
    assert windows.top_level_window(0) == 0


def test_native_signatures_use_pointer_sized_window_handles():
    class Signatures:
        def __getattr__(self, name):
            function = SimpleNamespace()
            setattr(self, name, function)
            return function

    api = Signatures()
    windows._configure_user32(api)
    assert api.GetForegroundWindow.restype is wintypes.HWND
    assert api.GetAncestor.restype is wintypes.HWND
    assert api.GetWindowRect.argtypes[0] is wintypes.HWND
    assert api.EnumWindows.argtypes == [windows.WNDENUMPROC, wintypes.LPARAM]


def test_window_collection_requires_windows(monkeypatch):
    monkeypatch.setattr(windows, "user32", None)
    with pytest.raises(RuntimeError, match="Windows"):
        windows.enumerate_visible_windows()
    with pytest.raises(RuntimeError, match="Windows"):
        windows.foreground_window()


class FakeDisplayUser32(FakeUser32):
    def __init__(self):
        super().__init__()
        self.monitors = {}
        self.monitor_enum_ok = True
        self.monitor_info_failures = set()
        self.cursor = (0, 0)
        self.cursor_ok = True
        self.position_ok = True
        self.positions = []

    def EnumDisplayMonitors(self, dc, clip, callback, parameter):
        assert dc is None and clip is None
        if not self.monitor_enum_ok:
            return False
        for handle, (rect, _work, _primary) in self.monitors.items():
            native_rect = wintypes.RECT(*rect)
            if not callback(handle, None, ctypes.byref(native_rect), parameter):
                return False
        return True

    def GetMonitorInfoW(self, handle, pointer):
        if handle in self.monitor_info_failures:
            return False
        info = ctypes.cast(pointer, ctypes.POINTER(windows.MONITORINFO)).contents
        assert info.cbSize == ctypes.sizeof(windows.MONITORINFO)
        rect, work, primary = self.monitors[handle]
        info.rcMonitor = wintypes.RECT(*rect)
        info.rcWork = wintypes.RECT(*work)
        info.dwFlags = windows.MONITORINFOF_PRIMARY if primary else 0
        return True

    def GetCursorPos(self, pointer):
        if not self.cursor_ok:
            return False
        point = ctypes.cast(pointer, ctypes.POINTER(wintypes.POINT)).contents
        point.x, point.y = self.cursor
        return True

    def SetWindowPos(self, *arguments):
        self.positions.append(arguments)
        return self.position_ok


@pytest.fixture
def displays(monkeypatch):
    fake = FakeDisplayUser32()
    monkeypatch.setattr(windows, "user32", fake)
    return fake


def test_enumerate_monitors_preserves_negative_origins_and_work_areas(displays):
    displays.monitors = {
        10: ((-1920, -200, 0, 880), (-1920, -160, 0, 880), False),
        20: ((0, 0, 2560, 1440), (0, 0, 2560, 1392), True),
    }

    assert windows.enumerate_monitors() == [
        windows.MonitorInfo((-1920, -200, 0, 880), (-1920, -160, 0, 880), False),
        windows.MonitorInfo((0, 0, 2560, 1440), (0, 0, 2560, 1392), True),
    ]


def test_monitor_callback_preserves_pointer_sized_handles(displays):
    if ctypes.sizeof(windows.HMONITOR) < 8:
        pytest.skip("64-bit handle coverage requires a 64-bit interpreter")
    displays.monitors[(1 << 40) + 10] = ((0, 0, 800, 600), (0, 0, 800, 560), True)

    assert windows.enumerate_monitors() == [
        windows.MonitorInfo((0, 0, 800, 600), (0, 0, 800, 560), True)
    ]


def test_monitor_enumeration_failure_raises(displays):
    displays.monitor_enum_ok = False
    with pytest.raises(OSError):
        windows.enumerate_monitors()


def test_monitor_info_failure_does_not_return_partial_list(displays):
    displays.monitors = {
        10: ((0, 0, 800, 600), (0, 0, 800, 560), True),
        20: ((800, 0, 1600, 600), (800, 0, 1600, 560), False),
    }
    displays.monitor_info_failures.add(20)
    with pytest.raises(OSError) as error:
        windows.enumerate_monitors()
    assert isinstance(error.value.__cause__, OSError)


@pytest.mark.parametrize("rect,work", [
    ((0, 0, 0, 600), (0, 0, 800, 560)),
    ((0, 0, 800, 600), (0, 0, 800, 0)),
    ((0, 0, 800, 600), (-1, 0, 800, 560)),
    ((0, 0, 800, 600), (0, 0, 801, 560)),
])
def test_monitor_invalid_bounds_raise(displays, rect, work):
    displays.monitors[10] = (rect, work, True)
    with pytest.raises(OSError):
        windows.enumerate_monitors()


def test_no_monitors_raises(displays):
    with pytest.raises(OSError, match="Nenhum monitor"):
        windows.enumerate_monitors()


def test_cursor_position_preserves_signed_screen_coordinates(displays):
    displays.cursor = (-1200, -50)
    assert windows.cursor_position() == (-1200, -50)


def test_cursor_position_failure_raises(displays):
    displays.cursor_ok = False
    with pytest.raises(OSError):
        windows.cursor_position()


def test_position_overlay_uses_native_wrapper_and_negative_origin_without_focus(displays):
    displays.roots[10] = 20

    windows.position_overlay(10, (-1920, -200, 2560, 1440))

    assert displays.positions == [
        (20, windows.HWND_TOPMOST, -1920, -200, 4480, 1640,
         windows.SWP_NOACTIVATE | windows.SWP_NOOWNERZORDER)
    ]


def test_position_overlay_failure_raises(displays):
    displays.position_ok = False
    with pytest.raises(OSError):
        windows.position_overlay(10, (0, 0, 800, 600))


@pytest.mark.parametrize("handle,rect", [
    (0, (0, 0, 800, 600)), (10, (0, 0, 0, 600)), (10, (0, 0, 800, 0)),
])
def test_position_overlay_rejects_invalid_inputs(displays, handle, rect):
    with pytest.raises(ValueError):
        windows.position_overlay(handle, rect)
    assert displays.positions == []


def test_display_apis_require_windows(monkeypatch):
    monkeypatch.setattr(windows, "user32", None)
    for action in (windows.enumerate_monitors, windows.cursor_position,
                   lambda: windows.position_overlay(10, (0, 0, 800, 600))):
        with pytest.raises(RuntimeError, match="Windows"):
            action()
