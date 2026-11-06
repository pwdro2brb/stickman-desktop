import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from stickman_desktop.scenes import (
    BUILTIN_SCENES_DIR, MAX_SCENE_BYTES, load_scene, load_scenes,
)


def scene_data(**updates):
    result = {"id": "example", "name": "Cena original", "duration": 10,
              "steps": [{"at": 0, "action": "say", "text": "Olá!"}]}
    result.update(updates)
    return result


def write_scene(directory, data, filename="example.json"):
    path = directory / filename
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_shipped_scenes_are_valid_original_visual_sequences():
    catalog = load_scenes(BUILTIN_SCENES_DIR)
    assert catalog.errors == ()
    assert {scene.id for scene in catalog.scenes} == {"echo_duel", "boas_vindas"}
    duel = next(scene for scene in catalog.scenes if scene.id == "echo_duel")
    assert duel.duration == 16
    assert [step.action for step in duel.steps] == ["say", "walk", "fight", "portal"]


def test_actions_are_sorted_stably_and_optional_durations_have_defaults(tmp_path):
    path = write_scene(tmp_path, scene_data(steps=[
        {"at": 2, "action": "portal"},
        {"at": 1, "action": "wave"},
        {"at": 1, "action": "fight"},
        {"at": 0, "action": "walk", "fraction": 0.25},
        {"at": 4, "action": "jump"},
        {"at": 5, "action": "climb"},
    ]))
    result = load_scene(path)
    assert [step.action for step in result.steps] == ["walk", "wave", "fight", "portal", "jump", "climb"]
    assert [step.args for step in result.steps] == [
        {"fraction": 0.25}, {"duration": 2.8}, {"duration": 5}, {"duration": 6}, {}, {},
    ]


@pytest.mark.parametrize("action", ["open", "minimize", "exec", "shell", "python", "delete", "unknown", [], True])
def test_scenes_cannot_invoke_tools_or_arbitrary_actions(tmp_path, action):
    path = write_scene(tmp_path, scene_data(steps=[{"at": 0, "action": action}]))
    with pytest.raises(ValueError, match="não permitida"):
        load_scene(path)


@pytest.mark.parametrize("updates", [
    {"extra": "ignored?"}, {"name": ""}, {"name": "x" * 81}, {"name": "bad\x00name"},
    {"id": "../shell"}, {"id": "Uppercase"}, {"id": "x" * 49}, {"id": ""},
    {"duration": True}, {"duration": 0}, {"duration": 91}, {"duration": "10"},
    {"duration": 10 ** 400},
    {"steps": []}, {"steps": {}}, {"steps": [None]},
    {"steps": [{"at": 0, "action": "jump"}] * 65},
])
def test_invalid_scene_structure_is_rejected(tmp_path, updates):
    with pytest.raises(ValueError):
        load_scene(write_scene(tmp_path, scene_data(**updates)))


@pytest.mark.parametrize("step", [
    {"at": -1, "action": "jump"}, {"at": 11, "action": "jump"},
    {"at": True, "action": "jump"}, {"action": "jump"},
    {"at": 0, "action": "jump", "command": "calc.exe"},
    {"at": 0, "action": "jump", "duration": 2},
    {"at": 0, "action": "walk"}, {"at": 0, "action": "walk", "fraction": True},
    {"at": 0, "action": "walk", "fraction": 1.1},
    {"at": 0, "action": "walk", "fraction": -0.1},
    {"at": 0, "action": "say", "text": " "},
    {"at": 0, "action": "say", "text": "x" * 241},
    {"at": 0, "action": "say", "text": 123},
    {"at": 0, "action": "wave", "duration": 0.1},
    {"at": 0, "action": "fight", "duration": 7},
    {"at": 0, "action": "portal", "duration": 11},
    {"at": 0, "action": "portal", "duration": False},
])
def test_invalid_step_arguments_are_rejected(tmp_path, step):
    with pytest.raises(ValueError):
        load_scene(write_scene(tmp_path, scene_data(steps=[step])))


@pytest.mark.parametrize("payload", [
    b"not json", b"\xff", b"[]", b"null", b"{", b'{"id":"a","id":"b"}',
    json.dumps(scene_data(duration=float("nan"))).encode(),
    json.dumps(scene_data(duration=float("inf"))).encode(),
    json.dumps(scene_data(steps=[{"at": float("-inf"), "action": "jump"}])).encode(),
    b"[" * 2000 + b"]" * 2000,
])
def test_malformed_or_nonfinite_json_is_rejected(tmp_path, payload):
    path = tmp_path / "bad.json"
    path.write_bytes(payload)
    with pytest.raises(ValueError):
        load_scene(path)


def test_file_size_is_bounded_and_bom_utf8_is_supported(tmp_path):
    path = tmp_path / "test.json"
    path.write_bytes(b" " * (MAX_SCENE_BYTES + 1))
    with pytest.raises(ValueError, match="64 KiB"):
        load_scene(path)
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps(scene_data()).encode())
    assert load_scene(path).id == "example"


def test_bad_files_are_isolated_and_non_json_files_are_ignored(tmp_path):
    write_scene(tmp_path, scene_data())
    (tmp_path / "bad.json").write_text("broken", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("not a scene", encoding="utf-8")
    (tmp_path / "folder.json").mkdir()
    catalog = load_scenes(tmp_path)
    assert [scene.id for scene in catalog.scenes] == ["example"]
    assert len(catalog.errors) == 2
    assert any("bad.json" in error for error in catalog.errors)
    assert all("notes.txt" not in error for error in catalog.errors)


def test_all_duplicate_ids_are_removed_instead_of_picking_a_winner(tmp_path):
    for filename in ("a.json", "b.json", "c.json"):
        write_scene(tmp_path, scene_data(), filename)
    write_scene(tmp_path, scene_data(id="independent"), "d.json")
    catalog = load_scenes(tmp_path)
    assert [scene.id for scene in catalog.scenes] == ["independent"]
    assert len(catalog.errors) == 2
    assert all("repetido" in error for error in catalog.errors)


def test_catalog_handles_missing_and_empty_directories(tmp_path):
    assert load_scenes(tmp_path).scenes == ()
    assert load_scenes(tmp_path).errors == ()
    assert load_scenes(tmp_path / "missing").errors
    with pytest.raises(ValueError):
        load_scene(tmp_path / "missing.json")


def test_symlinks_do_not_read_outside_catalog(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    scene = write_scene(outside, scene_data())
    folder = tmp_path / "catalog"
    folder.mkdir()
    linked = folder / "linked.json"
    try:
        linked.symlink_to(scene)
    except (OSError, NotImplementedError):
        pytest.skip("Symbolic links are not available for this Windows account")
    assert load_scenes(folder).scenes == ()
    assert load_scenes(folder).errors
    with pytest.raises(ValueError):
        load_scene(linked)


def test_windows_reparse_points_are_rejected_on_older_python(tmp_path, monkeypatch):
    path = write_scene(tmp_path, scene_data())
    monkeypatch.setattr(Path, "lstat", lambda _path: SimpleNamespace(st_mode=0, st_file_attributes=0x400))
    with pytest.raises(ValueError):
        load_scene(path)
    assert load_scenes(tmp_path).scenes == ()
    assert load_scenes(tmp_path).errors


def test_catalog_access_error_is_a_diagnostic_instead_of_a_crash(tmp_path, monkeypatch):
    def denied(_path):
        raise PermissionError("access denied")
    monkeypatch.setattr(Path, "iterdir", denied)
    result = load_scenes(tmp_path)
    assert result.scenes == ()
    assert result.errors
