import pytest

from stickman_desktop.animation_state import AnimationFrame, AnimationStateMachine


def test_playback_starts_at_first_frame_after_each_motion_change():
    state = AnimationStateMachine()

    assert state.update("idle", 10.0, 0.1) == AnimationFrame("idle", 0.0)
    assert state.update("idle", 10.2, 0.2) == AnimationFrame("idle", 0.2)
    assert state.update("walk", 10.3, 0.1) == AnimationFrame("walk", 0.0)
    assert state.update("walk", 10.3, 0.0) == AnimationFrame("walk", 0.0)
    assert state.update("walk", 10.4, 0.1) == AnimationFrame("walk", 0.1)


def test_timed_gesture_expires_at_deadline_and_same_gesture_can_restart():
    state = AnimationStateMachine()

    assert state.update("idle", 1.0, 0.1, pose="wave", pose_until=2.0) == AnimationFrame("wave", 0.0)
    assert state.update("walk", 1.3, 0.3, pose="wave", pose_until=2.0) == AnimationFrame("wave", 0.3)
    assert state.update("idle", 1.4, 0.1, pose="wave", pose_until=2.4) == AnimationFrame("wave", 0.0)
    assert state.update("walk", 2.4, 1.0, pose="wave", pose_until=2.4) == AnimationFrame("walk", 0.0)


@pytest.mark.parametrize("mode", ["jump", "fall", "drag"])
def test_physical_modes_take_precedence_over_timed_pose(mode):
    state = AnimationStateMachine()
    state.update("idle", 1.0, 0.1, pose="fight", pose_until=2.0)

    assert state.update(mode, 1.1, 0.1, pose="fight", pose_until=2.0) == AnimationFrame(mode, 0.0)
    assert state.update("idle", 1.2, 0.1, pose="fight", pose_until=2.0) == AnimationFrame("fight", 0.0)


def test_playback_progress_is_independent_for_each_character():
    first = AnimationStateMachine()
    second = AnimationStateMachine()
    first.update("walk", 1.0, 0.1)

    assert first.update("walk", 1.2, 0.2).elapsed == 0.2
    assert second.update("walk", 1.2, 0.2).elapsed == 0.0


def test_unknown_motion_and_pose_fall_back_to_idle():
    state = AnimationStateMachine()

    assert state.update("unknown", 1.0, 0.1, pose="unknown", pose_until=3.0) == AnimationFrame("idle", 0.0)


@pytest.mark.parametrize("dt", [-0.1, float("nan"), float("inf")])
def test_invalid_delta_does_not_change_animation_state(dt):
    state = AnimationStateMachine()
    state.update("walk", 1.0, 0.1)

    with pytest.raises(ValueError, match="dt"):
        state.update("jump", 1.1, dt)

    assert state.update("walk", 1.2, 0.2) == AnimationFrame("walk", 0.2)
