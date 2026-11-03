import math

import pytest

from stickman_desktop.animation import CharacterRenderer, Particles


class FakeCanvas:
    def __init__(self):
        self.items = {}
        self.next_id = 1

    def _create(self, kind, coordinates, options):
        item = self.next_id
        self.next_id += 1
        self.items[item] = {"kind": kind, "coordinates": coordinates, **options}
        return item

    def create_line(self, *coordinates, **options):
        return self._create("line", coordinates, options)

    def create_oval(self, *coordinates, **options):
        return self._create("oval", coordinates, options)

    def coords(self, item, *values):
        if values:
            self.items[item]["coordinates"] = values
        return self.items[item]["coordinates"]

    def itemconfigure(self, item, **options):
        self.items[item].update(options)

    def delete(self, item):
        del self.items[item]


def test_character_has_drag_target_and_uniform_tags():
    canvas = FakeCanvas()
    character = CharacterRenderer(canvas, "#ff7a00", tag="pixel")

    assert len(character.parts) == len(canvas.items) == 8
    assert all(item["tags"] == ("pixel",) for item in canvas.items.values())
    assert canvas.items[character.parts["head"]]["fill"]


def test_character_reuses_articulated_items_across_all_poses():
    canvas = FakeCanvas()
    character = CharacterRenderer(canvas, "#ff7a00")
    identities = set(canvas.items)
    poses = []
    for mode in ("idle", "walk", "jump", "fall", "drag", "wave", "fight"):
        character.render(200, 300, -1, mode, 17.3, vy=-80 if mode == "jump" else 100)
        poses.append(tuple(canvas.coords(character.parts["arm1"])))
        assert set(canvas.items) == identities
        assert all(math.isfinite(coordinate) for item in canvas.items.values()
                   for coordinate in item["coordinates"])
        assert all(len(canvas.coords(character.parts[name])) == 6
                   for name in ("arm1", "arm2", "leg1", "leg2"))
    assert len(set(poses)) >= 6


def test_hidden_companion_stays_hidden_while_animating():
    canvas = FakeCanvas()
    character = CharacterRenderer(canvas, "#9870ff", tag="echo")
    character.set_visible(False)
    character.render(100, 200, 1, "fight", 2)
    assert all(item["state"] == "hidden" for item in canvas.items.values())
    character.set_visible(True)
    assert all(item["state"] == "normal" for item in canvas.items.values())


def test_character_breathes_and_faces_both_directions_without_allocating():
    canvas = FakeCanvas()
    character = CharacterRenderer(canvas, "#ff7a00")
    character.render(100, 200, 1, "idle", 1)
    first_body = canvas.coords(character.parts["body"])
    right_eye = canvas.coords(character.parts["eye1"])
    character.render(100, 200, -1, "idle", 2)
    assert canvas.coords(character.parts["body"]) != first_body
    assert canvas.coords(character.parts["eye1"])[0] < right_eye[0]
    assert len(canvas.items) == 8


def test_character_rejects_invalid_coordinates_before_updating_canvas():
    canvas = FakeCanvas()
    character = CharacterRenderer(canvas, "#ff7a00")
    initial = {key: value["coordinates"] for key, value in canvas.items.items()}
    with pytest.raises(ValueError):
        character.render(float("nan"), 200, 1, "idle", 0)
    assert {key: value["coordinates"] for key, value in canvas.items.items()} == initial


def test_particle_bursts_obey_cap_and_expiration_frees_capacity():
    canvas = FakeCanvas()
    particles = Particles(canvas, max_count=15)
    particles.burst(100, 200, count=12)
    particles.burst(100, 200, count=12)
    assert len(canvas.items) == len(particles.particles) == 15
    particles.step(1)
    assert not canvas.items and not particles.particles
    particles.burst(100, 200, count=12)
    assert len(canvas.items) == len(particles.particles) == 12


def test_particles_move_existing_items_and_clear_is_idempotent():
    canvas = FakeCanvas()
    particles = Particles(canvas)
    particles.burst(100, 200, color="#00cfff", count=3)
    initial = {key: value["coordinates"] for key, value in canvas.items.items()}
    particles.step(0.05)
    assert set(canvas.items) == set(initial)
    assert any(canvas.coords(item) != coordinates for item, coordinates in initial.items())
    assert all(item["fill"] == "#00cfff" for item in canvas.items.values())
    assert all(math.isfinite(coordinate) for item in canvas.items.values()
               for coordinate in item["coordinates"])
    particles.clear()
    particles.clear()
    assert not canvas.items and not particles.particles


def test_repeated_particle_effects_leave_no_canvas_objects():
    canvas = FakeCanvas()
    particles = Particles(canvas, max_count=20)
    for _ in range(100):
        particles.burst(100, 200, count=30)
        assert len(canvas.items) <= 20
        particles.step(0.1)
    particles.step(1)
    assert not canvas.items and not particles.particles


@pytest.mark.parametrize("dt", [-0.1, float("nan"), float("inf")])
def test_particles_reject_invalid_time_steps(dt):
    with pytest.raises(ValueError):
        Particles(FakeCanvas()).step(dt)


def test_zero_particle_limit_disables_effects():
    canvas = FakeCanvas()
    particles = Particles(canvas, max_count=0)
    particles.burst(0, 0)
    particles.step(0)
    assert not canvas.items
