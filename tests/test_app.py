from unittest.mock import Mock

import pytest

from stickman_desktop import app as app_module
from stickman_desktop.app import StickmanDesktop
from stickman_desktop.windows import WindowInfo


@pytest.fixture
def desktop(monkeypatch):
    desktop = StickmanDesktop.__new__(StickmanDesktop)
    desktop.root = Mock()
    desktop._closing = False
    desktop._loop_jobs = {}
    desktop.root.winfo_id.return_value = 10
    desktop.panel_hwnd = 20
    desktop.windows_panel = None
    desktop.windows_tree = None
    desktop.windows_status = None
    desktop.visible_windows = []
    desktop.last_external_window = None
    desktop.window_scan_failed = False
    desktop.config = {"safety": {"allow_window_minimize": True}}
    desktop.say = Mock()
    desktop.walk_to = Mock()
    desktop._sync_surfaces = Mock()
    desktop._refresh_desktop = Mock()
    monkeypatch.setattr(app_module, "top_level_window", lambda hwnd: {10: 11, 20: 21, 30: 31}.get(hwnd, hwnd))
    monkeypatch.setattr(app_module, "enumerate_visible_windows", Mock(return_value=[]))
    monkeypatch.setattr(app_module, "foreground_window", Mock(return_value=None))
    monkeypatch.setattr(app_module, "minimize_window", Mock(return_value=True))
    return desktop


def test_refresh_selects_foreground_from_fresh_catalog(desktop):
    fresh = WindowInfo(100, "Editor atualizado", (20, 30, 820, 630))
    app_module.enumerate_visible_windows.return_value = [fresh]
    app_module.foreground_window.return_value = WindowInfo(100, "Título anterior", (0, 0, 100, 100))

    assert desktop._refresh_windows() is True

    assert desktop.visible_windows == [fresh]
    assert desktop.last_external_window is fresh
    app_module.enumerate_visible_windows.assert_called_once_with({10, 11, 20, 21})


def test_refresh_preserves_external_target_while_panel_has_focus(desktop):
    desktop.last_external_window = WindowInfo(100, "Editor", (0, 0, 100, 100))
    moved = WindowInfo(100, "Editor renomeado", (-300, 40, 400, 540))
    app_module.enumerate_visible_windows.return_value = [moved]

    desktop._refresh_windows()

    assert desktop.last_external_window is moved


def test_new_foreground_missing_from_snapshot_does_not_reuse_previous_target(desktop):
    previous = WindowInfo(100, "Anterior", (0, 0, 100, 100))
    desktop.last_external_window = previous
    app_module.enumerate_visible_windows.return_value = [previous]
    app_module.foreground_window.return_value = WindowInfo(200, "Recém-aberta", (0, 0, 200, 200))

    desktop._refresh_windows()

    assert desktop.last_external_window is None


def test_refresh_removes_missing_target_without_selecting_another_window(desktop):
    desktop.last_external_window = WindowInfo(100, "Janela fechada", (0, 0, 100, 100))
    other = WindowInfo(200, "Outra janela", (0, 0, 200, 200))
    app_module.enumerate_visible_windows.return_value = [other]

    desktop._refresh_windows()

    assert desktop.visible_windows == [other]
    assert desktop.last_external_window is None


def test_scan_failure_clears_stale_target_and_recovers(desktop):
    stale = WindowInfo(100, "Editor", (0, 0, 100, 100))
    desktop.last_external_window = stale
    desktop.visible_windows = [stale]
    app_module.enumerate_visible_windows.side_effect = [OSError("EnumWindows failed"), [stale]]

    assert desktop._refresh_windows() is False
    assert desktop.visible_windows == []
    assert desktop.last_external_window is None
    assert desktop.window_scan_failed is True

    app_module.foreground_window.return_value = stale
    assert desktop._refresh_windows() is True
    assert desktop.last_external_window is stale
    assert desktop.window_scan_failed is False


def test_capture_reschedules_after_scan_failure(desktop):
    app_module.enumerate_visible_windows.side_effect = OSError("EnumWindows failed")

    desktop._capture_external_window()

    desktop.root.after.assert_called_once_with(250, desktop._capture_external_window)


def test_own_handles_include_native_wrappers_and_window_list(desktop):
    desktop.windows_panel = Mock()
    desktop.windows_panel.winfo_id.return_value = 30

    assert desktop.own_hwnds == {10, 11, 20, 21, 30, 31}


def test_inspect_uses_current_window_dimensions_and_position(desktop):
    desktop.last_external_window = WindowInfo(100, "Antigo", (0, 0, 100, 100))
    app_module.enumerate_visible_windows.return_value = [
        WindowInfo(100, "Atual", (200, 40, 1000, 640))
    ]

    desktop.inspect()

    desktop.say.assert_called_once_with("Janela: Atual\nÁrea: 800 × 600 px", 6)
    desktop.walk_to.assert_called_once_with(600)


def test_minimize_does_not_use_target_that_disappeared(desktop):
    desktop.last_external_window = WindowInfo(100, "Fechada", (0, 0, 100, 100))

    desktop.minimize_external()

    app_module.minimize_window.assert_not_called()
    desktop.say.assert_called_once_with("Selecione uma janela externa e tente novamente.", 4)


def test_minimize_uses_refreshed_target_and_excludes_own_handles(desktop):
    desktop.last_external_window = WindowInfo(100, "Antigo", (0, 0, 100, 100))
    app_module.enumerate_visible_windows.return_value = [
        WindowInfo(100, "Atual", (200, 40, 1000, 640))
    ]

    desktop.minimize_external()

    app_module.minimize_window.assert_called_once_with(100, {10, 11, 20, 21})
    desktop.say.assert_called_once_with("Janela minimizada: Atual", 4)


def test_minimize_respects_disabled_policy(desktop):
    desktop.config["safety"]["allow_window_minimize"] = False

    desktop.minimize_external()

    app_module.enumerate_visible_windows.assert_not_called()
    app_module.minimize_window.assert_not_called()


def test_list_command_opens_window_list(desktop):
    desktop.show_window_list = Mock()

    desktop.execute("listar janelas")

    desktop.show_window_list.assert_called_once_with()


def test_window_list_updates_existing_rows_and_removes_closed_windows(desktop):
    desktop.windows_tree = Mock()
    desktop.windows_tree.get_children.return_value = ("100", "200")
    desktop.windows_tree.item.return_value = ("Editor", "100 × 100", "0, 0")
    desktop.windows_status = Mock()
    desktop.visible_windows = [
        WindowInfo(100, "Editor atualizado", (-100, 20, 500, 420)),
        WindowInfo(300, "Nova janela", (0, 0, 300, 200)),
    ]

    desktop._update_window_list()

    desktop.windows_tree.item.assert_any_call("100", values=("Editor atualizado", "600 × 400", "-100, 20"))
    desktop.windows_tree.move.assert_called_once_with("100", "", 0)
    desktop.windows_tree.insert.assert_called_once_with(
        "", 1, iid="300", values=("Nova janela", "300 × 200", "0, 0")
    )
    desktop.windows_tree.delete.assert_called_once_with("200")
    desktop.windows_status.set.assert_called_once_with("2 janelas visíveis.")
