import math

import pytest

from stickman_desktop.motion import Motion, Surface


FLOOR = Surface("monitor:primary", 0, 1000, 650, "floor")
WINDOW = Surface("window:10", 200, 600, 350)


def advance(motion, seconds=1, fps=60):
    for _ in range(round(seconds * fps)):
        motion.step(1 / fps)


def on_floor():
    motion = Motion(1000, 720, 120, 650)
    motion.set_surfaces([FLOOR, WINDOW])
    return motion


def on_window():
    motion = on_floor()
    assert motion.leap_to(WINDOW.key)
    advance(motion)
    assert motion.support_key == WINDOW.key
    return motion


def test_initial_floor_placement_and_walking_reaches_destination():
    motion = on_floor()
    assert motion.grounded
    motion.walk_to(300)
    advance(motion)
    assert motion.x == 300
    assert motion.y == FLOOR.y
    assert motion.mode == "idle"
    assert motion.target_x is None


def test_walking_on_window_stops_with_body_inside_edge():
    motion = on_window()
    motion.walk_to(900)
    advance(motion, 2)
    assert motion.x == WINDOW.right - motion.EDGE
    assert motion.support_key == WINDOW.key
    assert motion.y == WINDOW.y


def test_jump_leaves_floor_and_lands_again():
    motion = on_floor()
    assert motion.jump()
    assert not motion.jump()
    motion.step(0.15)
    assert motion.y < FLOOR.y
    assert motion.mode == "jump"
    advance(motion)
    assert motion.grounded
    assert motion.y == FLOOR.y
    assert motion.vy == 0


def test_falling_catches_first_window_and_does_not_tunnel():
    motion = Motion(1000, 720, 300, 150)
    lower = Surface("window:20", 200, 600, 450)
    motion.set_surfaces([FLOOR, lower, WINDOW])
    motion.release(0, 900)
    motion.step(0.5)
    assert motion.support_key == WINDOW.key
    assert motion.y == WINDOW.y


def test_moved_window_translates_rider_and_walk_target():
    motion = on_window()
    motion.walk_to(500)
    moved = Surface(WINDOW.key, 260, 660, 380)
    motion.set_surfaces([FLOOR, moved])
    assert motion.x == 460
    assert motion.y == 380
    assert motion.target_x == 560
    assert motion.support_key == WINDOW.key


def test_resize_keeps_world_position_instead_of_teleporting():
    motion = on_window()
    resized = Surface(WINDOW.key, 250, 700, 380)
    motion.set_surfaces([FLOOR, resized])
    assert motion.x == 400
    assert motion.y == 380
    assert motion.grounded


def test_shrunk_window_releases_character_when_support_disappears():
    motion = on_window()
    motion.set_surfaces([FLOOR, Surface(WINDOW.key, 200, 350, 350)])
    assert not motion.grounded
    assert motion.x == 400
    assert motion.mode == "fall"
    advance(motion)
    assert motion.support_key == FLOOR.key


def test_closed_or_minimized_support_falls_to_floor():
    motion = on_window()
    motion.set_surfaces([FLOOR])
    assert not motion.grounded
    advance(motion)
    assert motion.support_key == FLOOR.key
    assert motion.y == FLOOR.y


def test_drop_ignores_origin_window_and_lands_on_lower_window():
    motion = on_window()
    lower = Surface("window:20", 200, 600, 480)
    motion.set_surfaces([FLOOR, WINDOW, lower])
    assert motion.drop()
    advance(motion)
    assert motion.support_key == lower.key
    assert motion.y == lower.y


def test_floor_cannot_be_dropped_through():
    motion = on_floor()
    assert motion.drop() is False
    assert motion.grounded


def test_leap_tracks_moved_target_and_keeps_head_in_viewport():
    motion = on_floor()
    high = Surface(WINDOW.key, 200, 600, 105)
    motion.set_surfaces([FLOOR, high])
    assert motion.leap_to(high.key)
    advance(motion, 0.3)
    moved = Surface(high.key, 400, 800, 110)
    motion.set_surfaces([FLOOR, moved])
    heights = []
    for _ in range(60):
        motion.step(1 / 60)
        heights.append(motion.y)
    assert min(heights) >= motion.HEAD_ROOM
    assert motion.support_key == moved.key
    assert motion.x == 600
    assert motion.y == 110


def test_disappearing_leap_target_cancels_transition_and_falls():
    motion = on_floor()
    motion.leap_to(WINDOW.key)
    advance(motion, 0.3)
    motion.set_surfaces([FLOOR])
    assert motion.mode == "fall"
    advance(motion, 2)
    assert motion.support_key == FLOOR.key


def test_invalid_leap_target_does_not_change_existing_motion():
    motion = on_floor()
    assert not motion.leap_to("missing")
    assert motion.support_key == FLOOR.key
    assert motion.mode == "idle"


def test_drag_cancels_motion_clamps_coordinates_and_release_limits_throw():
    motion = on_window()
    motion.walk_to(550)
    motion.drag_to(-100, -50)
    assert motion.x == 28
    assert motion.y == 100
    assert motion.target_x is None
    assert not motion.grounded
    assert motion.mode == "drag"
    motion.step(1)
    assert motion.y == 100
    motion.release(9999, 9999)
    assert motion.vx == motion.vy == motion.MAX_THROW_SPEED
    advance(motion, 2)
    assert motion.grounded
    assert 28 <= motion.x <= 972


def test_gap_between_monitors_rescues_to_nearest_floor():
    left = Surface("monitor:left", 0, 300, 620, "floor")
    right = Surface("monitor:right", 650, 1000, 650, "floor")
    motion = Motion(1000, 720, 500, 680)
    motion.set_surfaces([left, right])
    motion.release()
    advance(motion)
    assert motion.support_key == right.key
    assert motion.x == right.left
    assert motion.y == right.y


def test_ordinary_jump_hits_viewport_ceiling_instead_of_losing_character():
    motion = on_floor()
    high = Surface(WINDOW.key, 200, 600, 110)
    motion.set_surfaces([FLOOR, high])
    motion.leap_to(high.key)
    advance(motion)
    motion.jump()
    for _ in range(60):
        motion.step(1 / 60)
        assert motion.y >= motion.HEAD_ROOM
    assert motion.support_key == high.key


def test_frame_rates_produce_same_air_position_and_velocity():
    slow, fast = on_floor(), on_floor()
    for motion in (slow, fast):
        motion.drag_to(120, 200)
        motion.release(200, -50)
    advance(slow, 0.3, 30)
    advance(fast, 0.3, 120)
    assert slow.x == pytest.approx(fast.x, abs=1e-8)
    assert slow.y == pytest.approx(fast.y, abs=1e-8)
    assert slow.vy == pytest.approx(fast.vy, abs=1e-8)


def test_stop_cancels_exploration_destination():
    motion = on_floor()
    motion.walk_to(600)
    motion.step(0.2)
    motion.stop()
    stopped_x = motion.x
    advance(motion)
    assert motion.x == stopped_x
    assert motion.mode == "idle"


def test_adjacent_monitor_floors_have_no_artificial_gap():
    left = Surface("monitor:left", 0, 500, 650, "floor")
    right = Surface("monitor:right", 500, 1000, 650, "floor")
    motion = Motion(1000, 720, 450, 650)
    motion.set_surfaces([left, right])
    motion.walk_to(600)
    advance(motion)
    assert motion.x == 600
    assert motion.y == 650
    assert motion.support_key == right.key


def test_reframe_keeps_rider_and_target_global_without_double_translation():
    motion = on_window()
    motion.walk_to(500)
    motion.reframe(1200, 900, 200, 50)
    motion.set_surfaces([
        Surface(FLOOR.key, 200, 1200, 700, "floor"),
        Surface(WINDOW.key, 400, 800, 400),
    ])
    assert motion.x == 600
    assert motion.y == 400
    assert motion.target_x == 700
    assert motion.support_key == WINDOW.key


def test_reframe_preserves_active_leap_trajectory():
    control, shifted = on_floor(), on_floor()
    for motion in (control, shifted):
        motion.leap_to(WINDOW.key)
        motion.step(0.2)
    shifted.reframe(1200, 900, 200, 50)
    shifted.set_surfaces([
        Surface(FLOOR.key, 200, 1200, 700, "floor"),
        Surface(WINDOW.key, 400, 800, 400),
    ])
    control.step(0.1)
    shifted.step(0.1)
    assert shifted.x == pytest.approx(control.x + 200)
    assert shifted.y == pytest.approx(control.y + 50)


@pytest.mark.parametrize("invalid", [math.nan, math.inf, -1])
def test_invalid_elapsed_time_is_rejected(invalid):
    with pytest.raises(ValueError):
        on_floor().step(invalid)


def test_invalid_surfaces_are_ignored():
    motion = on_floor()
    motion.set_surfaces([FLOOR, Surface("invalid", 5, 2, 100),
                         Surface("infinite", 0, math.inf, 300)])
    assert not motion.leap_to("invalid")
    assert not motion.leap_to("infinite")
