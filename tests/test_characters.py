from unittest.mock import Mock

import pytest

from stickman_desktop.characters import DesktopCharacter, find_character, spawn_x
from stickman_desktop.motion import Motion


def make_character(id: str, name: str) -> DesktopCharacter:
    return DesktopCharacter(id, name, "#ff7a00", Motion(1000, 800, 200, 747), Mock())


def test_character_animation_is_independent():
    first = make_character("pixel", "Pixel")
    second = make_character("faisca", "Faísca")
    first.animation.update("walk", 0.0, 0.0)
    first.animation.update("walk", 0.2, 0.2)
    frame = second.animation.update("walk", 0.2, 0.2)
    assert frame.elapsed == 0.0
    assert first.tag != second.tag


def test_selection_resolves_id_before_normalized_name():
    pixel = make_character("pixel", "Faísca")
    spark = make_character("faisca", "Faísca")
    characters = {"pixel": pixel, "faisca": spark}
    assert find_character(characters, " FAISCA ") is spark
    assert find_character(characters, "Faísca") is None
    assert find_character({"pixel": pixel}, "faisca") is pixel
    assert find_character(characters, "desconhecido") is None


@pytest.mark.parametrize("left, right, anchor, occupied, expected", [
    (0, 500, 200, [200], 300),
    (0, 250, 220, [220], 120),
    (0, 180, 50, [0, 180], 90),
    (-600, -100, -700, [], -600),
])
def test_spawn_respects_available_room(left, right, anchor, occupied, expected):
    assert spawn_x(left, right, anchor, occupied) == expected
