from itertools import count
from unittest.mock import Mock

import pytest

from stickman_desktop import app as module
from stickman_desktop.app import StickmanDesktop
from stickman_desktop.motion import Motion, Surface
from stickman_desktop.scenes import Scene, SceneCatalog, SceneStep
from stickman_desktop.windows import MonitorInfo


@pytest.fixture
def desktop(monkeypatch):
    app = StickmanDesktop.__new__(StickmanDesktop)
    app.root = Mock()
    app.root.winfo_id.return_value = 10
    sequence = count()
    app.pending = {}
    def schedule(delay, callback):
        token = f"after-{next(sequence)}"
        app.pending[token] = (delay, callback)
        return token
    app.root.after.side_effect = schedule
    app.canvas = Mock()
    app.control = Mock()
    app.particles = Mock()
    app.hotkeys = Mock()
    app.hotkeys.poll.return_value = []
    app.tray = Mock(available=True)
    app.tray.poll.return_value = []
    app.hidden = app._closing = app.click_through = False
    app.command_panel = app.windows_panel = None
    app.windows_tree = app.windows_status = None
    app.scene_picker = app.scene_status = app.scene_play_button = None
    app.command_open = False
    app.panel_hwnd = 0
    app.monitors = [MonitorInfo((0, 0, 1000, 800), (0, 0, 1000, 750), True)]
    app.origin_x = app.origin_y = 0
    app.sw, app.sh, app.ground_offset = 1000, 800, 0
    app.motion = Motion(1000, 800, 200, 747)
    app.motion.set_surfaces([Surface("floor", 0, 1000, 747, "floor")])
    app.behavior = "manual"
    app.pose = None
    app.pose_until = 0
    app.story_running = False
    app._story_generation = 0
    app._story_jobs, app._scene_jobs, app._scene_items = set(), set(), set()
    app._echo_visible = False
    app._drag_anchor = app._drag_sample = None
    app._dragging = False
    app._last_tick = 0
    app.frame = 0
    app.visible_windows = []
    app.last_external_window = None
    app.say = Mock()
    app._update_gaze = Mock()
    app._render = Mock()
    app._refresh_windows = Mock()
    app.scenes = (
        Scene("first", "Primeira", 1, (SceneStep(0, "say", {"text": "primeira"}),)),
        Scene("second", "Segunda", 2, (SceneStep(0, "say", {"text": "segunda"}),)),
    )
    app.scene_errors = ()
    app.selected_scene_id = "first"
    monkeypatch.setattr(module, "position_overlay", Mock())
    monkeypatch.setattr(module, "set_click_through", Mock())
    monkeypatch.setattr(module, "top_level_window", lambda hwnd: hwnd)
    return app


def test_hide_cancels_scene_and_hides_every_app_panel(desktop):
    desktop.start_story()
    desktop.command_panel = Mock()
    panel = desktop.command_panel
    desktop.windows_panel = Mock()
    listing = desktop.windows_panel
    desktop.hide_overlay()
    assert desktop.hidden
    assert not desktop.story_running and not desktop._story_jobs
    assert desktop.behavior == "manual"
    assert desktop.command_panel is desktop.windows_panel is None
    panel.destroy.assert_called_once()
    listing.destroy.assert_called_once()
    desktop.root.withdraw.assert_called_once()
    desktop.tray.set_state.assert_called_with(hidden=True, click_through=False)


@pytest.mark.parametrize("available", [False, None])
def test_missing_tray_does_not_strand_hidden_character(desktop, available):
    if available is None:
        desktop.tray = None
    else:
        desktop.tray.available = False
    desktop.hide_overlay()
    assert not desktop.hidden
    desktop.root.withdraw.assert_not_called()
    assert "permanecer visível" in desktop.say.call_args.args[0]


def test_hidden_ticks_pause_physics_and_drawing(desktop):
    desktop.hide_overlay()
    desktop.motion.vy = 400
    before = (desktop.x, desktop.y, desktop.motion.vy)
    desktop._tick()
    assert (desktop.x, desktop.y, desktop.motion.vy) == before
    desktop._render.assert_not_called()
    desktop.root.after.assert_called_with(16, desktop._tick)


def test_restore_recovers_interaction_and_offscreen_position(desktop):
    desktop.hidden = desktop.click_through = True
    desktop.motion.x = 1200
    desktop.restore_overlay()
    assert not desktop.hidden and not desktop.click_through
    desktop.root.deiconify.assert_called_once()
    module.position_overlay.assert_called_once_with(10, (0, 0, 1000, 800))
    module.set_click_through.assert_called_once_with(10, False)
    assert (desktop.x, desktop.y) == pytest.approx((500, 747))
    desktop._render.assert_called_once_with(0)


def test_quit_event_stops_dispatch_and_disposes_resources_once(desktop):
    tray = desktop.tray
    tray.poll.return_value = ["quit", "commands"]
    desktop.open_command_panel = Mock()
    desktop._poll_hotkeys()
    desktop.close()
    tray.close.assert_called_once()
    desktop.particles.close.assert_called_once()
    desktop.hotkeys.close.assert_called_once()
    desktop.root.destroy.assert_called_once()
    desktop.root.after.assert_not_called()
    desktop.open_command_panel.assert_not_called()


def test_stale_scene_callback_cannot_run_after_another_scene_starts(desktop):
    desktop.start_story("first")
    old = next(callback for delay, callback in desktop.pending.values() if delay == 0)
    desktop.start_story("second")
    assert desktop.story_running
    desktop.say.reset_mock()
    old()
    desktop.say.assert_not_called()
    assert desktop.selected_scene_id == "second"


def test_selected_scene_is_used_by_default_story_shortcut(desktop):
    desktop.selected_scene_id = "second"
    desktop.start_story()
    callbacks = [callback for delay, callback in desktop.pending.values() if delay == 0]
    callbacks[-1]()
    desktop.say.assert_called_with("segunda", 4)
    assert len(desktop._story_jobs) == 1


def test_unknown_scene_id_is_never_a_path_or_tool(desktop, monkeypatch):
    load = Mock()
    monkeypatch.setattr(module, "load_scenes", load)
    desktop.open_allowed_app = Mock()
    desktop.minimize_external = Mock()
    desktop.execute("cena ../../calc.exe")
    assert not desktop.story_running
    load.assert_not_called()
    desktop.open_allowed_app.assert_not_called()
    desktop.minimize_external.assert_not_called()


def test_scene_visual_actions_do_not_interrupt_their_own_story(desktop):
    desktop.start_story()
    generation = desktop._story_generation
    desktop._run_scene_step(SceneStep(0, "walk", {"fraction": 0.5}))
    assert desktop.motion.target_x == 500
    desktop._run_scene_step(SceneStep(0, "wave", {"duration": 0.3}))
    assert desktop.pose == "wave"
    assert desktop.story_running and desktop._story_generation == generation
    clear = next(callback for delay, callback in desktop.pending.values() if delay == 300)
    clear()
    assert desktop.pose is None


def test_reloading_invalid_files_stops_previous_scene_and_keeps_valid_entries(desktop, monkeypatch):
    desktop.start_story()
    catalog = SceneCatalog((desktop.scenes[1],), ("broken.json: ação desconhecida",))
    monkeypatch.setattr(module, "load_scenes", Mock(return_value=catalog))
    desktop.reload_scenes()
    assert not desktop.story_running and not desktop._story_jobs
    assert desktop.selected_scene_id == "second"
    assert desktop.scenes == catalog.scenes and desktop.scene_errors == catalog.errors
    assert "correção" in desktop.say.call_args.args[0]


def test_empty_scene_catalog_does_not_schedule_actions(desktop):
    desktop.scenes = ()
    desktop.selected_scene_id = ""
    desktop.start_story()
    desktop.root.after.assert_not_called()
    assert not desktop.story_running


def test_story_shortcut_restores_even_with_an_empty_scene_catalog(desktop):
    desktop.hidden = True
    desktop.scenes = ()
    desktop.selected_scene_id = ""
    desktop.start_story()
    assert not desktop.hidden
    desktop.root.deiconify.assert_called_once()
    assert not desktop.story_running


@pytest.mark.parametrize("command,method", [
    ("ocultar", "hide_overlay"), ("restaurar", "restore_overlay"),
    ("recarregar cenas", "reload_scenes"),
])
def test_command_routes_to_lifecycle_action(desktop, command, method):
    action = Mock()
    setattr(desktop, method, action)
    desktop.execute(command)
    action.assert_called_once_with()
