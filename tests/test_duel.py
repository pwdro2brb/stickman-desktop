import math

import pytest

from stickman_desktop.duel import TabDuel


def test_duel_crossing_several_beats_emits_each_impact_once():
    duel = TabDuel(6, 120, 780, (0, 0, 1280, 800))
    assert not duel.advance(0).impacts
    first = duel.advance(2)
    assert [(hit.owner, hit.fragments) for hit in first.impacts] == [(0, 6)]

    end = duel.advance(20)
    assert [(hit.owner, hit.fragments) for hit in end.impacts] == [(1, 12), (0, 24)]
    assert end.finished and end.tab is None
    assert (end.player.x, end.player.y) == (120, 780)
    assert duel.advance(1).impacts == ()


@pytest.mark.parametrize("pieces", [2, 24])
def test_even_a_short_duel_can_use_fragment_count_limits(pieces):
    frame = TabDuel(0.2, 50, 500, (0, 0, 900, 560), fragments=pieces).advance(1)
    assert frame.finished
    assert len(frame.impacts) == 1
    assert frame.impacts[0].fragments == pieces


def test_duel_pulls_the_tab_into_a_windup_then_knocks_the_target_back():
    duel = TabDuel(6, 120, 780, (0, 0, 1280, 800), source=(420, 110))
    frame = duel.advance(0.33)
    assert frame.tab.phase == "pull"
    assert (frame.tab.x, frame.tab.y) == pytest.approx((420, 110))

    frame = duel.advance(0.54)
    assert frame.player.mode == "windup" and frame.tab.phase == "held"
    frame = duel.advance(0.4)
    assert frame.player.mode == "throw" and frame.tab.phase == "flight"
    initial_target = frame.opponent
    first_angle = frame.tab.angle
    next_frame = duel.advance(0.1)
    assert next_frame.tab.angle > first_angle

    frame = duel.advance(0.3)
    assert len(frame.impacts) == 1 and frame.tab is None
    assert frame.impacts[0].vx > 0 and frame.impacts[0].vy > 0
    assert frame.opponent.mode == "recoil"
    assert frame.opponent.x > initial_target.x and frame.opponent.y < initial_target.y


def test_stage_stays_inside_a_compact_work_area_with_negative_origin():
    area = (-630, -270, -450, -40)
    left, top, right, bottom = area
    duel = TabDuel(6, -500, -49, area, source=(5000, -5000))
    for _ in range(300):
        frame = duel.advance(0.02)
        for pose in (frame.player, frame.opponent, frame.tab, *frame.impacts):
            if pose is not None:
                assert left <= pose.x <= right
                assert top <= pose.y <= bottom
        for hit in frame.impacts:
            direction = frame.player.direction if hit.owner == 0 else frame.opponent.direction
            assert math.isfinite(hit.vx) and hit.vx * direction >= 0


@pytest.mark.parametrize("pieces", [1, 25, True, 2.5])
def test_rejects_invalid_fragment_counts(pieces):
    with pytest.raises(ValueError):
        TabDuel(6, 200, 700, (0, 0, 1280, 800), fragments=pieces)
