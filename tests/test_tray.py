import ctypes
from ctypes import wintypes
import struct
import sys
from types import SimpleNamespace

import pytest

from stickman_desktop import tray


class FakeBackend:
    def __init__(self, callback):
        self.callback = callback
        self.hwnd = 0
        self.taskbar_message = 0xC001
        self.notifications = []
        self.menu_calls = []
        self.closed = 0
        self.fail_create = self.fail_add = self.fail_version = self.fail_modify = False
        self.selected = 0
        self.menu_error = None

    def create(self):
        self.hwnd = (1 << 40) + 42
        if self.fail_create:
            raise OSError("create failed")

    def notify(self, action, tooltip="Stickman Desktop"):
        self.notifications.append((action, tooltip))
        return not ((action == tray.NIM_ADD and self.fail_add)
                    or (action == tray.NIM_SETVERSION and self.fail_version)
                    or (action == tray.NIM_MODIFY and self.fail_modify))

    def menu(self, entries):
        self.menu_calls.append(entries)
        if self.menu_error:
            raise self.menu_error
        return self.selected

    def close(self):
        self.closed += 1
        self.hwnd = 0


@pytest.fixture
def native(monkeypatch):
    backend = FakeBackend(None)
    def factory(callback):
        backend.callback = callback
        return backend
    monkeypatch.setattr(tray, "_Win32Backend", factory)
    icon = tray.TrayIcon()
    return icon, backend


def test_start_adds_icon_and_sets_v4_once_and_close_is_idempotent(native):
    icon, backend = native
    assert not icon.available
    icon.start()
    assert icon.available
    assert icon.hwnd == (1 << 40) + 42
    icon.start()
    assert [action for action, _ in backend.notifications] == [tray.NIM_ADD, tray.NIM_SETVERSION]
    icon.close()
    icon.close()
    assert backend.closed == 1
    assert backend.notifications[-1][0] == tray.NIM_DELETE
    assert icon.hwnd == 0 and not icon.available
    assert icon.poll() == []


@pytest.mark.parametrize("failure", ["fail_create", "fail_add", "fail_version"])
def test_start_failure_releases_window_and_icon_without_staying_available(native, failure):
    icon, backend = native
    setattr(backend, failure, True)
    with pytest.raises(OSError):
        icon.start()
    assert backend.closed == 1
    assert not icon.available and icon.hwnd == 0
    icon.close()
    assert backend.closed == 1


@pytest.mark.parametrize("event", [tray.WM_LBUTTONDBLCLK, tray.NIN_SELECT, tray.NIN_KEYSELECT])
def test_mouse_and_keyboard_activation_restore_on_poll(native, event):
    icon, backend = native
    icon.start()
    assert backend.callback(tray.WM_TRAY, 0, (1 << 16) | event)
    assert icon.poll() == ["restore"]
    assert icon.poll() == []


def test_popup_runs_outside_native_callback_and_coalesces_duplicate_menu_notifications(native):
    icon, backend = native
    icon.start()
    backend.selected = 5
    backend.callback(tray.WM_TRAY, 0, tray.WM_CONTEXTMENU)
    backend.callback(tray.WM_TRAY, 0, tray.WM_RBUTTONUP)
    assert backend.menu_calls == []
    assert icon.poll() == ["explore"]
    assert len(backend.menu_calls) == 1


def test_menu_labels_reflect_hidden_and_click_through_state(native):
    icon, backend = native
    icon.start()
    icon.set_state(True, True)
    backend.callback(tray.WM_TRAY, 0, tray.WM_CONTEXTMENU)
    icon.poll()
    labels = dict(backend.menu_calls[-1])
    assert labels[2] == "Mostrar personagem"
    assert labels[8] == "Ativar cliques (F3)"
    assert "oculto" in backend.notifications[-1][1]
    previous = len(backend.notifications)
    icon.set_state(True, True)
    assert len(backend.notifications) == previous
    icon.set_state(False, False)
    backend.callback(tray.WM_TRAY, 0, tray.WM_CONTEXTMENU)
    icon.poll()
    labels = dict(backend.menu_calls[-1])
    assert labels[2] == "Ocultar personagem"
    assert labels[8] == "Liberar cliques (F3)"


@pytest.mark.parametrize("identifier, action", list(tray.TrayIcon.ACTIONS.items()))
def test_all_native_menu_commands_map_to_allowlisted_intent(native, identifier, action):
    icon, backend = native
    icon.start()
    backend.selected = identifier
    backend.callback(tray.WM_TRAY, 0, tray.WM_CONTEXTMENU)
    assert icon.poll() == [action]


def test_cancelled_or_unknown_menu_command_does_nothing(native):
    icon, backend = native
    icon.start()
    for selected in (0, 999):
        backend.selected = selected
        backend.callback(tray.WM_TRAY, 0, tray.WM_CONTEXTMENU)
        assert icon.poll() == []


def test_menu_failure_restores_access_instead_of_raising_in_tk_callback(native):
    icon, backend = native
    icon.start()
    backend.menu_error = OSError("popup failed")
    backend.callback(tray.WM_TRAY, 0, tray.WM_CONTEXTMENU)
    assert icon.poll() == ["restore"]
    assert icon.last_error == "popup failed"


def test_explorer_restart_readds_icon_with_version_before_becoming_available(native):
    icon, backend = native
    icon.start()
    backend.notifications.clear()
    backend.callback(backend.taskbar_message, 0, 0)
    assert backend.notifications == []
    assert icon.poll() == []
    assert [action for action, _ in backend.notifications] == [tray.NIM_ADD, tray.NIM_SETVERSION]
    assert icon.available


def test_failed_recovery_restores_character_once_and_retries_with_cooldown(native, monkeypatch):
    icon, backend = native
    icon.start()
    monkeypatch.setattr(tray.time, "monotonic", lambda: 10)
    backend.fail_add = True
    backend.fail_modify = True
    backend.callback(backend.taskbar_message, 0, 0)
    assert icon.poll() == ["restore"]
    assert not icon.available
    attempts = len(backend.notifications)
    assert icon.poll() == []
    assert len(backend.notifications) == attempts
    backend.fail_add = False
    backend.fail_modify = False
    monkeypatch.setattr(tray.time, "monotonic", lambda: 12.1)
    assert icon.poll() == []
    assert icon.available and icon.last_error is None


def test_tooltip_failure_marks_unavailable_and_still_deletes_icon_on_close(native):
    icon, backend = native
    icon.start()
    backend.fail_modify = True
    icon.set_state(True, False)
    assert not icon.available
    assert icon.poll() == ["restore"]
    icon.close()
    assert backend.notifications[-1][0] == tray.NIM_DELETE


def test_recovery_repairs_an_existing_icon_after_duplicate_broadcast(native):
    icon, backend = native
    icon.start()
    backend.notifications.clear()
    backend.fail_add = True
    backend.callback(backend.taskbar_message, 0, 0)
    backend.callback(backend.taskbar_message, 0, 0)
    assert icon.poll() == []
    assert [action for action, _ in backend.notifications] == [
        tray.NIM_ADD, tray.NIM_MODIFY, tray.NIM_SETVERSION,
    ]
    assert icon.available


def test_hidden_native_window_close_requests_app_quit_without_tk_work(native):
    icon, backend = native
    icon.start()
    assert not backend.callback(0x9999, 0, 0)
    assert backend.callback(tray.WM_CLOSE, 0, 0)
    assert backend.closed == 0
    assert icon.poll() == ["quit"]


def test_events_queued_while_popup_is_open_wait_for_next_poll(native):
    icon, backend = native
    icon.start()
    def menu(_entries):
        backend.callback(tray.WM_COMMAND, 7, 0)
        return 0
    backend.menu = menu
    backend.callback(tray.WM_TRAY, 0, tray.WM_CONTEXTMENU)
    assert icon.poll() == []
    assert icon.poll() == ["stop"]


def test_native_backend_requires_windows(monkeypatch):
    monkeypatch.setattr(tray.sys, "platform", "linux")
    with pytest.raises(RuntimeError, match="Windows"):
        tray._Win32Backend(lambda *_: False)


def test_icon_is_original_transparent_rgba_dib_at_multiple_sizes():
    for size in (16, 24, 32):
        data = tray._icon_resource(size)
        header = struct.unpack("<IiiHHIIiiII", data[:40])
        assert header[:5] == (40, size, size * 2, 1, 32)
        pixels = data[40:40 + size * size * 4]
        alpha = pixels[3::4]
        assert 0 in alpha and 255 in alpha
        colored = [pixels[index:index+4] for index in range(0, len(pixels), 4) if pixels[index+3]]
        assert len(colored) > size
        assert set(colored) == {bytes((0, 122, 255, 255))}


def test_native_signatures_preserve_pointer_handles():
    class Library:
        def __getattr__(self, name):
            fn = SimpleNamespace()
            setattr(self, name, fn)
            return fn
    backend = tray._Win32Backend.__new__(tray._Win32Backend)
    backend.user32, backend.kernel32, backend.shell32 = Library(), Library(), Library()
    backend._configure()
    assert backend.user32.CreateWindowExW.restype is wintypes.HWND
    assert backend.user32.DefWindowProcW.restype is ctypes.c_ssize_t
    assert backend.user32.CreateIconFromResourceEx.restype is wintypes.HICON
    assert backend.shell32.Shell_NotifyIconW.argtypes[1]._type_ is tray.NOTIFYICONDATAW
    if sys.platform == "win32" and ctypes.sizeof(ctypes.c_void_p) == 8:
        assert ctypes.sizeof(tray.NOTIFYICONDATAW) == 976
