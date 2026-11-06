from itertools import combinations
from math import isfinite
from types import SimpleNamespace

import pytest

from stickman_desktop.tab_effects import TabEffects, _BODY, _area, _clip, _fragment_polygons


class FakeCanvas:
    def __init__(self):
        self.items = {}
        self.next_id = 0

    def _create(self, *coordinates, **options):
        self.next_id += 1
        self.items[self.next_id] = {"coordinates": coordinates, **options}
        return self.next_id

    create_polygon = _create
    create_text = _create

    def coords(self, item, *coordinates):
        self.items[item]["coordinates"] = coordinates

    def itemconfigure(self, item, **options):
        self.items[item].update(options)

    def delete(self, item):
        del self.items[item]


def make_pose(angle=0.2):
    return SimpleNamespace(x=150.0, y=120.0, angle=angle, owner=0, phase="flight")


def make_impact(count=24):
    return SimpleNamespace(x=150.0, y=120.0, angle=0.2, owner=0, vx=800.0, vy=150.0,
                           fragments=count)


@pytest.mark.parametrize("count", [2, 7, 24])
def test_fragments_partition_the_original_outline_without_overlapping(count):
    pieces = _fragment_polygons(count)
    assert len(pieces) == count
    assert all(_area(piece) > 1 for piece in pieces)
    assert sum(map(_area, pieces)) == pytest.approx(_area(_BODY))
    assert all(_area(_clip(a, b)) < 1e-7 for a, b in combinations(pieces, 2))


def test_intact_tab_reuses_its_items_and_sanitizes_its_title():
    canvas = FakeCanvas()
    effects = TabEffects(canvas)
    title = "Abas\n ativas\x00 — conteúdo longo"
    effects.render_tab(make_pose(), title, 0)
    initial = {key: value["coordinates"] for key, value in canvas.items.items()}
    labels = [value["text"] for value in canvas.items.values() if "text" in value]
    assert labels == ["Abas ativas — …"]

    effects.render_tab(make_pose(1.1), title, 0.2)
    assert set(canvas.items) == set(initial)
    assert any(value["coordinates"] != initial[key] for key, value in canvas.items.items())

    effects.render_tab(None, title, 0.3)
    assert all(value["state"] == "hidden" for value in canvas.items.values())


def test_split_hides_the_tab_and_the_pieces_tumble_pulse_and_expire():
    canvas = FakeCanvas()
    effects = TabEffects(canvas)
    effects.render_tab(make_pose(), "Aba ativa", 0)
    whole = set(canvas.items)
    effects.shatter(make_impact(), "Aba ativa")
    assert all(canvas.items[item]["state"] == "hidden" for item in whole)
    fragments = {key: value.copy() for key, value in canvas.items.items() if key not in whole}
    assert len(fragments) > 24

    effects.step(0.31)
    assert set(canvas.items) == whole | fragments.keys()
    assert any(canvas.items[key]["coordinates"] != item["coordinates"] for key, item in fragments.items())
    assert any(canvas.items[key]["fill"] != item["fill"] for key, item in fragments.items())
    assert all(isfinite(value) for item in canvas.items.values() for value in item["coordinates"])

    effects.step(1)
    assert set(canvas.items) == whole
    effects.clear()
    assert not canvas.items


def test_repeated_impacts_bound_live_items_and_close_discards_everything():
    canvas = FakeCanvas()
    effects = TabEffects(canvas)
    for _ in range(20):
        effects.shatter(make_impact(), "Aba ativa")
    assert len(canvas.items) < 700

    effects.close()
    effects.close()
    effects.shatter(make_impact(), "Aba ativa")
    effects.render_tab(make_pose(), "Aba ativa", 0)
    effects.step(0.1)
    assert not canvas.items


def test_fragments_settle_at_scene_floor_and_continue_showing_activity():
    canvas = FakeCanvas()
    effects = TabEffects(canvas)
    floor_y = 173.0
    effects.shatter(make_impact(), "Aba ativa", floor_y=floor_y)

    for _ in range(85):
        effects.step(0.016)
    previous = {key: value.copy() for key, value in canvas.items.items()}
    assert previous
    assert all(y <= floor_y for item in previous.values() for y in item["coordinates"][1::2])

    effects.step(0.1)
    effects.step(0.1)
    resting = [key for key, item in canvas.items.items()
               if item["coordinates"] == previous[key]["coordinates"]]
    assert resting
    assert any(canvas.items[key]["fill"] != previous[key]["fill"] for key in resting)
    effects.step(1)
    assert not canvas.items
