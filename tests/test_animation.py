import math

import pytest

from stickman_desktop.animation import CharacterRenderer, Particles, solve_two_bone


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


def _endpoint(canvas, renderer, name):
    return canvas.coords(renderer.parts[name])[-2:]


def _center(canvas, renderer, name):
    left, top, right, bottom = canvas.coords(renderer.parts[name])
    return (left + right) / 2, (top + bottom) / 2


def test_limb_lengths_remain_fixed_through_transitions():
    canvas = FakeCanvas()
    character = CharacterRenderer(canvas, "orange")
    for frame in range(240):
        mode = ("idle", "walk", "jump", "fall", "drag", "wave", "fight")[frame // 35 % 7]
        character.render(200 + frame * 0.5, 300, 1, mode, frame / 60,
                         dt=1 / 60, vx=30 if mode == "walk" else 0)
        for name, expected in (("leg1", 21), ("leg2", 21), ("arm1", 18), ("arm2", 18)):
            x0, y0, x1, y1, x2, y2 = canvas.coords(character.parts[name])
            assert math.hypot(x1 - x0, y1 - y0) == pytest.approx(expected, abs=1e-6)
            assert math.hypot(x2 - x1, y2 - y1) == pytest.approx(expected, abs=1e-6)


def test_steady_walk_plants_feet_and_lifts_swinging_foot():
    canvas = FakeCanvas()
    character = CharacterRenderer(canvas, "orange")
    previous = {}
    planted_samples = 0
    lifted_samples = 0
    for frame in range(240):
        t = frame / 60
        character.render(200 + 140 * t, 300, 1, "walk", t, dt=1 / 60, vx=140)
        for name in ("leg1", "leg2"):
            foot = _endpoint(canvas, character, name)
            if frame > 30 and abs(foot[1] - 300) < 1e-6:
                if name in previous and abs(previous[name][1] - 300) < 1e-6:
                    assert foot[0] == pytest.approx(previous[name][0], abs=1e-6)
                    planted_samples += 1
            if foot[1] < 296.5:
                lifted_samples += 1
            assert foot[1] <= 300 + 1e-6
            previous[name] = foot
    assert planted_samples > 100
    assert lifted_samples > 50


def test_walking_phase_depends_on_travel_not_absolute_clock():
    first_canvas, second_canvas = FakeCanvas(), FakeCanvas()
    first, second = CharacterRenderer(first_canvas, "orange"), CharacterRenderer(second_canvas, "orange")
    for frame in range(180):
        t = frame / 60
        first.render(200 + 140 * t, 300, 1, "walk", t, dt=1 / 60, vx=140)
        second.render(200 + 140 * t, 300, 1, "walk", t + 1000, dt=1 / 60, vx=140)
    for name in ("leg1", "leg2"):
        assert _endpoint(first_canvas, first, name) == pytest.approx(_endpoint(second_canvas, second, name), abs=1e-6)


def test_walk_contact_is_consistent_at_different_frame_rates():
    results = []
    for fps in (30, 120):
        canvas = FakeCanvas()
        renderer = CharacterRenderer(canvas, "orange")
        renderer.render(200, 300, 1, "walk", 0, dt=0, vx=140)
        for frame in range(1, fps * 2 + 1):
            t = frame / fps
            renderer.render(200 + 140 * t, 300, 1, "walk", t, dt=1 / fps, vx=140)
        results.append([_endpoint(canvas, renderer, name) for name in ("leg1", "leg2")])
    for first, second in zip(*results):
        assert first == pytest.approx(second, abs=0.03)


def test_stopping_and_turning_do_not_teleport_feet():
    canvas = FakeCanvas()
    renderer = CharacterRenderer(canvas, "orange")
    for frame in range(90):
        renderer.render(200 + frame * 140 / 60, 300, 1, "walk", frame / 60, dt=1 / 60, vx=140)
    previous = [_endpoint(canvas, renderer, name) for name in ("leg1", "leg2")]
    x = 200 + 89 * 140 / 60
    renderer.render(x, 300, -1, "idle", 1.5, dt=1 / 60, vx=0)
    for name, old in zip(("leg1", "leg2"), previous):
        assert math.dist(_endpoint(canvas, renderer, name), old) < 6
    for frame in range(1, 120):
        renderer.render(x, 300, -1, "idle", 1.5 + frame / 60, dt=1 / 60, vx=0)
    assert _endpoint(canvas, renderer, "leg1")[1] == pytest.approx(300, abs=1e-6)
    assert _endpoint(canvas, renderer, "leg2")[1] == pytest.approx(300, abs=1e-6)


def test_gaze_moves_head_and_eyes_on_both_axes_without_turning_body():
    canvas = FakeCanvas()
    renderer = CharacterRenderer(canvas, "orange")
    samples = []
    for gaze in ((-1000, -1000), (1000, 1000)):
        for frame in range(120):
            renderer.render(200, 300, 1, "idle", frame / 60, gaze=gaze, dt=1 / 60, vx=0)
        head = _center(canvas, renderer, "head")
        eye = _center(canvas, renderer, "eye1")
        samples.append((head, (eye[0] - head[0], eye[1] - head[1])))
    assert samples[0][0][0] < samples[1][0][0]
    assert samples[0][0][1] < samples[1][0][1]
    assert samples[0][1][0] < samples[1][1][0]
    assert samples[0][1][1] < samples[1][1][1]
    assert renderer._facing == 1


def test_gaze_filters_sudden_cursor_jump_and_returns_to_neutral():
    canvas = FakeCanvas()
    renderer = CharacterRenderer(canvas, "orange")
    for frame in range(60):
        renderer.render(200, 300, 1, "idle", frame / 60, gaze=(1200, 220), dt=1 / 60)
    before = renderer._look[0]
    renderer.render(200, 300, 1, "idle", 1, gaze=(-1200, 220), dt=1 / 60)
    assert 0 < renderer._look[0] < before
    for frame in range(120):
        renderer.render(200, 300, 1, "idle", 1 + frame / 60, gaze=None, dt=1 / 60)
    assert renderer._look[0] == pytest.approx(0.4, abs=0.001)
    assert renderer._look[1] == pytest.approx(0, abs=0.001)


@pytest.mark.parametrize("kwargs", [{"gaze": (float("nan"), 0)}, {"dt": -1}, {"vx": float("inf")}])
def test_invalid_tracking_inputs_leave_canvas_unchanged(kwargs):
    canvas = FakeCanvas()
    renderer = CharacterRenderer(canvas, "orange")
    initial = {key: item["coordinates"] for key, item in canvas.items.items()}
    with pytest.raises(ValueError):
        renderer.render(200, 300, 1, "idle", 1, **kwargs)
    assert {key: item["coordinates"] for key, item in canvas.items.items()} == initial


@pytest.mark.parametrize("target", [(0, 0), (12, 18), (1000, 1000), (-1000, 0)])
def test_two_bone_solver_handles_coincident_and_unreachable_targets(target):
    joint, endpoint = solve_two_bone((0, 0), target, 21, 21)
    assert all(math.isfinite(value) for point in (joint, endpoint) for value in point)
    assert math.hypot(*joint) == pytest.approx(21, abs=1e-6)
    assert math.dist(joint, endpoint) == pytest.approx(21, abs=1e-6)
    if math.hypot(*target) <= 42:
        assert endpoint == pytest.approx(target, abs=1e-5)
    else:
        assert math.hypot(*endpoint) <= 42
