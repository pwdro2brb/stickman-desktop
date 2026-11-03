import pytest

from stickman_desktop.gestures import PointerVelocity


@pytest.mark.parametrize("fps", [30, 60, 144, 240])
def test_velocity_uses_real_event_time_not_animation_frame_time(fps):
    tracker = PointerVelocity()
    for index in range(1 + round(0.1 * fps)):
        t = index / fps
        tracker.record(1000 + t, -500 + 1800 * t, 100 - 600 * t)
    assert tracker.velocity(1000 + t) == pytest.approx((1800, -600))


def test_pause_before_release_discards_previous_flick():
    tracker = PointerVelocity()
    tracker.record(10, 0, 0)
    tracker.record(10.02, 200, 50)
    assert tracker.velocity(10.03)[0] > 1000
    assert tracker.velocity(10.2) == (0, 0)
    tracker.record(10.2, 200, 50)
    assert tracker.velocity(10.2) == (0, 0)


def test_recent_flick_is_not_diluted_by_old_slow_drag():
    tracker = PointerVelocity()
    tracker.record(0, 0, 0)
    tracker.record(1, 20, 0)
    tracker.record(1.02, 60, 0)
    tracker.record(1.04, 100, 0)
    assert tracker.velocity(1.04) == pytest.approx((2000, 0))


def test_duplicate_and_invalid_events_do_not_generate_nonfinite_velocity():
    tracker = PointerVelocity()
    tracker.record(1, 10, 10)
    tracker.record(1, 20, 20)
    tracker.record(float("nan"), 100, 100)
    assert tracker.velocity(1) == (0, 0)
    assert len(tracker.samples) == 1
