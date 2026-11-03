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
    advance(motion, 2)
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
    motion.vy = 900  # A fast fall is not a user throw.
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
    advance(motion, 8)
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
    advance(motion, 2)
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


def test_fast_throw_reflects_from_wall_with_less_energy():
    motion = Motion(1000, 2000, 900, 1000)
    motion.release(1000, 0)
    motion.step(0.1)
    assert motion.x <= 972
    assert -1000 < motion.vx < 0
    impact, = motion.drain_impacts()
    assert impact.kind == "wall"
    assert impact.count == 1 and impact.speed > 900
    assert motion.drain_impacts() == []


def test_slow_release_does_not_bounce_or_generate_impacts():
    motion = Motion(1000, 2000, 965, 1000)
    motion.release(90, 0)
    motion.step(0.2)
    assert motion.x == 972
    assert motion.vx == 0
    assert not motion.throwing
    assert motion.drain_impacts() == []


def test_fast_floor_impact_bounces_and_snapshots_do_not_pin_character():
    motion = Motion(1000, 720, 120, 400)
    motion.set_surfaces([FLOOR])
    motion.release(0, 600)
    for _ in range(60):
        motion.step(1 / 240)
        motion.set_surfaces([FLOOR])
    # Still descending before impact.
    assert motion.vy > 0
    for _ in range(80):
        motion.step(1 / 240)
        motion.set_surfaces([FLOOR])
    assert motion.bounce_count >= 1
    assert not motion.grounded
    assert motion.y < FLOOR.y
    assert motion.drain_impacts()[0].kind == "floor"
    advance(motion, 8)
    assert motion.grounded and motion.vx == motion.vy == 0
    assert not motion.throwing


def test_faster_throw_creates_more_impacts_before_settling():
    def toss(speed):
        motion = Motion(500, 900, 250, 450)
        motion.set_surfaces([Surface("floor", 0, 500, 850, "floor")])
        motion.release(speed, -500)
        advance(motion, 8)
        return motion
    slow, fast = toss(200), toss(2800)
    assert fast.bounce_count >= 2
    assert fast.bounce_count > slow.bounce_count
    assert fast.grounded and slow.grounded


@pytest.mark.parametrize("action", ["stop", "walk", "drag", "leap"])
def test_manual_motion_resets_throw_sequence_and_pending_impacts(action):
    motion = Motion(1000, 2000, 900, 1000)
    motion.set_surfaces([Surface("window", 100, 500, 600)])
    motion.release(1000, 0)
    motion.step(0.1)
    assert motion.bounce_count
    if action == "walk":
        motion.walk_to(400)
    elif action == "drag":
        motion.drag_to(400, 500)
    elif action == "leap":
        motion.leap_to("window")
    else:
        motion.stop()
    assert not motion.throwing
    assert motion.bounce_count == 0
    assert motion.drain_impacts() == []


def test_workarea_wall_bounces_before_blank_virtual_desktop_gap():
    motion = Motion(1800, 1000, 740, 400)
    motion.set_bounds([(0, 0, 800, 900), (1000, 0, 1800, 900)])
    motion.release(1000, 0)
    motion.step(0.1)
    assert motion.x <= 772 and motion.vx < 0
    assert motion.drain_impacts()[0].kind == "wall"


def test_adjacent_monitors_are_open_even_when_body_straddles_seam():
    motion = Motion(1800, 1000, 760, 400)
    motion.set_bounds([(0, 50, 800, 900), (800, 50, 1800, 900)])
    motion.release(1000, 0)
    motion.step(0.1)
    assert motion.x > 800 and motion.vx > 0
    assert motion.drain_impacts() == []
    # The ceiling remains the work area's top, even right on the seam.
    motion.drag_to(800, 155)
    motion.release(0, -500)
    motion.step(0.05)
    assert motion.y >= 150 and motion.vy > 0
    assert motion.drain_impacts()[0].kind == "ceiling"


def test_vertically_offset_monitor_blocks_body_without_headroom():
    motion = Motion(1800, 1000, 740, 200)
    motion.set_bounds([(0, 0, 800, 900), (800, 250, 1800, 1000)])
    motion.release(1000, 0)
    motion.step(0.1)
    assert motion.x <= 772 and motion.vx < 0
    assert motion.drain_impacts()[0].kind == "wall"


def test_repeated_bounds_updates_preserve_throw_and_pending_impact():
    motion = Motion(1000, 2000, 900, 1000)
    bounds = [(0, 0, 1000, 2000)]
    motion.set_bounds(bounds)
    motion.release(1000, 0)
    motion.step(0.1)
    previous = motion.vx
    motion.set_bounds(bounds)
    assert motion.throwing and motion.vx == previous
    assert motion.bounce_count == 1
    assert len(motion.drain_impacts()) == 1


def test_reframe_translates_workareas_and_queued_impacts():
    motion = Motion(1000, 2000, 900, 1000)
    motion.set_bounds([(0, 0, 1000, 2000)])
    motion.release(1000, 0)
    motion.step(0.1)
    motion.reframe(1200, 2100, 200, 100)
    impact, = motion.drain_impacts()
    assert impact.x == 1172 and impact.y >= 1100
    assert motion._bounds == [(200, 100, 1200, 2100)]


def test_invalid_bounds_are_rejected_without_replacing_previous_bounds():
    motion = on_floor()
    motion.set_bounds([(0, 0, 1000, 720)])
    with pytest.raises(ValueError):
        motion.set_bounds([(0, 0, math.inf, 720)])
    assert motion._bounds == [(0, 0, 1000, 720)]


def test_horizontal_throw_from_floor_keeps_momentum_and_bounces_off_wall():
    motion = Motion(500, 900, 250, 850)
    motion.set_surfaces([Surface("floor", 0, 500, 850, "floor")])
    motion.release(2500, 0)
    motion.step(0.15)
    assert motion.bounce_count >= 1
    assert motion.vx < 0
    assert motion.throwing
    assert any(impact.kind == "wall" for impact in motion.drain_impacts())
    advance(motion, 6)
    assert motion.grounded and motion.vx == motion.vy == 0
    assert not motion.throwing


def test_pending_impact_queue_is_bounded_without_losing_total_count():
    motion = on_floor()
    for _ in range(100):
        motion._impact(500, "wall")
    impacts = motion.drain_impacts()
    assert len(impacts) == motion.MAX_PENDING_IMPACTS
    assert impacts[-1].count == motion.bounce_count == 100
