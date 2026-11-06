from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from stickman_desktop import app as app_module
from stickman_desktop.app import StickmanDesktop
from stickman_desktop.characters import DesktopCharacter
from stickman_desktop.motion import Motion
from stickman_desktop.windows import MonitorInfo, WindowInfo


@pytest.fixture
def desktop():
    desktop = StickmanDesktop.__new__(StickmanDesktop)
    desktop.root = Mock()
    desktop.root.winfo_id.return_value = 10
    desktop.canvas = Mock()
    desktop.control = Mock()
    desktop.particles = Mock()
    desktop.monitors = [MonitorInfo((0, 0, 1200, 900), (0, 0, 1200, 850), True)]
    desktop.origin_x = desktop.origin_y = 0
    desktop.sw, desktop.sh = 1200, 900
    desktop.ground_offset = 0
    desktop.active_character = DesktopCharacter("pixel", "Pixel", "#ff7a00", Motion(1200, 900, 200, 847), Mock())
    desktop.characters = {"pixel": desktop.active_character}
    desktop.character_picker = None
    desktop._gaze = None
    desktop.active_character.hurt_level = 0
    desktop.active_character.hurt_cooldown = 0
    desktop.visible_windows = []
    desktop.last_external_window = None
    desktop.active_character.behavior = "manual"
    desktop.active_character.pose = None
    desktop.active_character.pose_until = 0
    desktop.story_running = False
    desktop._story_jobs = set()
    desktop._scene_jobs = set()
    desktop._scene_items = set()
    desktop._echo_visible = False
    desktop.active_character.next_decision = 0
    desktop._next_monitor_scan = 0
    desktop.command_open = False
    desktop.hidden = False
    desktop._closing = False
    desktop.tray = None
    desktop.command_panel = None
    desktop._story_generation = 0
    desktop.scenes = ()
    desktop.scene_errors = ()
    desktop.selected_scene_id = ""
    desktop.scene_picker = desktop.scene_status = desktop.scene_play_button = None
    desktop.click_through = False
    desktop._drag_anchor = None
    desktop._dragging = False
    desktop._drag_sample = None
    desktop._drag_velocity = (0, 0)
    desktop.say = Mock()
    desktop._sync_surfaces()
    desktop._refresh_windows = Mock(side_effect=desktop._sync_surfaces)
    return desktop


def finish_leap(desktop):
    for _ in range(40):
        desktop.motion.step(0.02)


def test_climb_targets_external_window_and_lands_on_its_edge(desktop):
    target = WindowInfo(100, "Editor", (100, 200, 800, 600))
    desktop.visible_windows = [target]
    desktop.last_external_window = target

    desktop.climb_window()
    finish_leap(desktop)

    desktop._refresh_windows.assert_called_once_with()
    assert desktop.motion.support_key == "window:100"
    assert (desktop.x, desktop.y) == pytest.approx((450, 197))
    assert desktop.active_character.behavior == "manual"


def test_climb_refuses_an_edge_without_headroom_and_keeps_existing_floor(desktop):
    target = WindowInfo(100, "Maximized", (0, 0, 1200, 850))
    desktop.visible_windows = [target]
    desktop.last_external_window = target
    support = desktop.motion.support_key

    desktop.climb_window()

    assert desktop.motion.support_key == support
    assert desktop.motion.grounded
    assert "borda livre" in desktop.say.call_args.args[0]


def test_climb_without_external_target_requests_one(desktop):
    desktop.climb_window()

    assert desktop.motion.grounded
    assert "Selecione uma janela externa" in desktop.say.call_args.args[0]


def test_follow_converts_global_cursor_x_into_canvas_coordinates(desktop, monkeypatch):
    desktop.origin_x = -1000
    monkeypatch.setattr(app_module, "cursor_position", Mock(return_value=(-200, 400)))
    desktop.follow_mouse()

    desktop._update_behavior(1)

    assert desktop.motion.target_x == 800
    assert desktop.active_character.behavior == "follow"


def test_cursor_failure_keeps_follow_mode_available_without_moving(desktop, monkeypatch):
    monkeypatch.setattr(app_module, "cursor_position", Mock(side_effect=OSError("cursor unavailable")))
    desktop.follow_mouse()

    desktop._update_behavior(1)

    assert desktop.motion.target_x is None
    assert desktop.active_character.behavior == "follow"
    assert desktop.active_character.next_decision == pytest.approx(1.1)


def test_exploration_only_leaps_to_current_eligible_window_surfaces(desktop, monkeypatch):
    desktop.visible_windows = [
        WindowInfo(100, "Too high", (1000, 0, 1200, 700)),
        WindowInfo(200, "Eligible", (100, 250, 900, 650)),
    ]
    desktop._sync_surfaces()
    monkeypatch.setattr(app_module.random, "uniform", lambda *_args: 4)
    monkeypatch.setattr(app_module.random, "random", lambda: 0)
    choose = Mock(side_effect=lambda options: options[0])
    monkeypatch.setattr(app_module.random, "choice", choose)
    desktop.explore()

    desktop._update_behavior(1)
    finish_leap(desktop)

    assert [surface.key for surface in choose.call_args.args[0]] == ["window:200"]
    assert desktop.motion.support_key == "window:200"
    assert desktop.active_character.behavior == "explore"


def test_stop_cancels_story_scene_callbacks_and_visual_items(desktop):
    desktop.active_character.behavior = "follow"
    desktop.story_running = True
    desktop.active_character.pose = "fight"
    desktop._echo_visible = True
    desktop._story_jobs = {"story-1", "story-2"}
    desktop._scene_jobs = {"scene-1"}
    desktop._scene_items = {41, 42}
    desktop.motion.walk_to(900)

    desktop.stop()

    assert desktop.active_character.behavior == "manual"
    assert desktop.active_character.pose is None
    assert desktop.story_running is False
    assert desktop._echo_visible is False
    assert desktop._story_jobs == desktop._scene_jobs == desktop._scene_items == set()
    assert {call.args[0] for call in desktop.root.after_cancel.call_args_list} == {
        "story-1", "story-2", "scene-1",
    }
    assert {call.args[0] for call in desktop.canvas.delete.call_args_list} == {41, 42}
    assert desktop.motion.target_x is None
    assert desktop.motion.vx == 0


def test_story_callback_cannot_restart_an_action_after_stop(desktop):
    desktop.root.after.return_value = "story-1"
    desktop.story_running = True
    callback = Mock()
    desktop._schedule_scene(500, callback, story=True)
    scheduled_callback = desktop.root.after.call_args.args[1]

    desktop.stop()
    scheduled_callback()

    callback.assert_not_called()
    desktop.root.after_cancel.assert_called_once_with("story-1")


def test_manual_walk_uses_global_x_and_interrupts_following(desktop):
    desktop.origin_x = -1000
    desktop.active_character.behavior = "follow"

    desktop.walk_to(-200)

    assert desktop.motion.target_x == 800
    assert desktop.active_character.behavior == "manual"


@pytest.mark.parametrize("coordinate", [float("nan"), float("inf"), -float("inf")])
def test_manual_walk_rejects_nonfinite_coordinates_before_changing_activity(desktop, coordinate):
    desktop.active_character.behavior = "follow"

    with pytest.raises(ValueError):
        desktop.walk_to(coordinate)

    assert desktop.active_character.behavior == "follow"
    assert desktop.motion.target_x is None


def test_drag_press_without_pointer_movement_does_not_detach_support(desktop):
    original = (desktop.x, desktop.y, desktop.motion.support_key)
    desktop._begin_drag(SimpleNamespace(x_root=210, y_root=700))
    desktop._end_drag()

    assert (desktop.x, desktop.y, desktop.motion.support_key) == original
    assert desktop.motion.grounded
    assert desktop._drag_anchor is None
    desktop.canvas.grab_set.assert_called_once_with()
    desktop.canvas.grab_release.assert_called_once_with()


def test_stale_drag_sample_releases_without_old_throw_velocity(desktop, monkeypatch):
    monkeypatch.setattr(app_module.time, "monotonic", Mock(side_effect=[100, 100.01, 100.5]))
    desktop._begin_drag(SimpleNamespace(x_root=200, y_root=778))
    desktop._drag(SimpleNamespace(x_root=400, y_root=550))
    assert desktop._dragging

    desktop._end_drag()

    assert (desktop.motion.vx, desktop.motion.vy) == (0, 0)
    assert not desktop.motion.grounded
    assert desktop._drag_anchor is desktop._drag_sample is None
    desktop.canvas.grab_release.assert_called_once_with()


def test_click_through_prevents_character_drag(desktop):
    desktop.click_through = True

    desktop._begin_drag(SimpleNamespace(x_root=200, y_root=778))

    assert desktop._drag_anchor is None
    assert desktop.motion.grounded
    desktop.canvas.grab_set.assert_not_called()


def test_manual_command_interrupts_drag_and_releases_pointer_capture(desktop, monkeypatch):
    monkeypatch.setattr(app_module.time, "monotonic", lambda: 100)
    desktop._begin_drag(SimpleNamespace(x_root=200, y_root=778))
    desktop._drag(SimpleNamespace(x_root=400, y_root=550))
    assert desktop._dragging

    desktop.walk_to(900)

    assert desktop._drag_anchor is desktop._drag_sample is None
    assert desktop._dragging is False
    assert desktop.motion.mode != "drag"
    assert desktop.motion.target_x == 900
    desktop.canvas.grab_release.assert_called_once_with()


def test_topology_change_preserves_global_position_target_and_primary_control(desktop, monkeypatch):
    primary = desktop.monitors[0]
    left = MonitorInfo((-1000, -200, 0, 700), (-1000, -200, 0, 660), False)
    monkeypatch.setattr(app_module, "enumerate_monitors", Mock(return_value=[left, primary]))
    position = Mock()
    monkeypatch.setattr(app_module, "position_overlay", position)
    monkeypatch.setattr(app_module.time, "monotonic", lambda: 10)
    desktop.motion.walk_to(900)
    before = (desktop.x + desktop.origin_x, desktop.y + desktop.origin_y)

    desktop._refresh_desktop()

    assert (desktop.x + desktop.origin_x, desktop.y + desktop.origin_y) == before
    assert desktop.motion.target_x + desktop.origin_x == 900
    assert desktop.motion.grounded
    assert (desktop.origin_x, desktop.origin_y, desktop.sw, desktop.sh) == (-1000, -200, 2200, 1100)
    position.assert_called_once_with(10, (-1000, -200, 1200, 900))
    desktop.canvas.configure.assert_called_once_with(width=2200, height=1100)
    desktop.control.place.assert_called_once_with(x=1012, y=212, width=38, height=34)


def test_topology_api_failure_keeps_last_working_layout(desktop, monkeypatch):
    before = (desktop.monitors, desktop.origin_x, desktop.origin_y, desktop.x, desktop.y)
    monkeypatch.setattr(app_module, "enumerate_monitors", Mock(side_effect=OSError("display unavailable")))
    position = Mock()
    monkeypatch.setattr(app_module, "position_overlay", position)
    monkeypatch.setattr(app_module.time, "monotonic", lambda: 10)

    desktop._refresh_desktop()

    assert (desktop.monitors, desktop.origin_x, desktop.origin_y, desktop.x, desktop.y) == before
    position.assert_not_called()
    desktop.canvas.configure.assert_not_called()


def test_topology_change_cancels_effects_and_story_jobs_using_old_coordinates(desktop, monkeypatch):
    primary = desktop.monitors[0]
    left = MonitorInfo((-1000, 0, 0, 900), (-1000, 0, 0, 850), False)
    monkeypatch.setattr(app_module, "enumerate_monitors", Mock(return_value=[left, primary]))
    monkeypatch.setattr(app_module, "position_overlay", Mock())
    monkeypatch.setattr(app_module.time, "monotonic", lambda: 10)
    desktop.story_running = True
    desktop.active_character.pose = "fight"
    desktop._story_jobs = {"old-story"}
    desktop._scene_jobs = {"old-portal"}
    desktop._scene_items = {41}
    desktop.motion.walk_to(900)

    desktop._refresh_desktop()

    assert desktop.story_running is False
    assert desktop.active_character.pose is None
    assert desktop._story_jobs == desktop._scene_jobs == desktop._scene_items == set()
    desktop.canvas.delete.assert_called_once_with(41)
    desktop.particles.clear.assert_called_once_with()
    assert desktop.motion.target_x is None


def test_gaze_tracks_global_cursor_without_starting_follow_mode(desktop, monkeypatch):
    desktop.origin_x, desktop.origin_y = -1000, -200
    monkeypatch.setattr(app_module, "cursor_position", lambda: (-300, -50))
    before = (desktop.x, desktop.y, desktop.motion.target_x)

    desktop._update_gaze()

    assert desktop._gaze == (700, 150)
    assert (desktop.x, desktop.y, desktop.motion.target_x) == before
    assert desktop.active_character.behavior == "manual"


def test_cursor_read_failure_returns_gaze_to_neutral(desktop, monkeypatch):
    desktop._gaze = (100, 200)
    monkeypatch.setattr(app_module, "cursor_position", Mock(side_effect=OSError("unavailable")))
    desktop._update_gaze()
    assert desktop._gaze is None


def test_release_includes_final_pointer_event_and_fast_event_intervals(desktop, monkeypatch):
    monkeypatch.setattr(app_module.time, "monotonic", Mock(side_effect=[100, 100.01, 100.02]))
    desktop._begin_drag(SimpleNamespace(x_root=200, y_root=800))
    desktop._drag(SimpleNamespace(x_root=210, y_root=800))
    desktop._end_drag(SimpleNamespace(x_root=230, y_root=800))

    assert desktop.motion.vx == pytest.approx(1500)
    assert desktop._drag_anchor is None
    desktop.canvas.grab_release.assert_called_once_with()


def test_drag_near_taskbar_cannot_release_below_floor(desktop, monkeypatch):
    monkeypatch.setattr(app_module.time, "monotonic", lambda: 100)
    desktop._begin_drag(SimpleNamespace(x_root=200, y_root=desktop.y))
    desktop._drag(SimpleNamespace(x_root=400, y_root=1000))
    assert desktop.y == 847
    desktop._end_drag()
    desktop.motion.step(0.02)
    assert desktop.motion.grounded
    assert desktop.y == 847


def test_repeated_hard_bounces_react_with_cooldown_and_no_bubble_spam(desktop):
    drain = Mock()
    desktop.motion.drain_impacts = drain
    def impact(count, speed=800):
        return SimpleNamespace(x=30, y=300, count=count, speed=speed, kind="wall")
    drain.return_value = [impact(1)]
    desktop._react_to_impacts(1)
    desktop.say.assert_not_called()
    drain.return_value = [impact(2)]
    desktop._react_to_impacts(1.1)
    assert "Ai!" in desktop.say.call_args.args[0]
    assert desktop.say.call_count == 1
    drain.return_value = [impact(3), impact(4)]
    desktop._react_to_impacts(1.2)
    assert desktop.say.call_count == 1
    drain.return_value = [impact(5)]
    desktop._react_to_impacts(3)
    assert "já chega" in desktop.say.call_args.args[0]
    assert desktop.say.call_count == 2
    assert desktop.active_character.hurt_level == 2


def test_weak_bounces_do_not_produce_hurt_reaction(desktop):
    desktop.motion.drain_impacts = Mock(return_value=[
        SimpleNamespace(x=30, y=300, count=3, speed=190, kind="floor"),
    ])
    desktop._react_to_impacts(10)
    desktop.say.assert_not_called()
