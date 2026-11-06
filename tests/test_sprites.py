import json
import shutil
import tkinter as tk

import pytest

from stickman_desktop.sprites import BUILTIN_SPRITE_DIR, SPRITE_STATES, SpritePack, SpriteRenderer


@pytest.mark.parametrize("field,value,match", [
    ("image", "../sprites.png", "na pasta do pacote"),
    ("anchor", [85, 100], "âncora"),
    ("frame_size", [300, 104], "frame_size"),
    ("states", {"idle": {"fps": 1, "loop": True, "frames": [[0, 0]]}}, "definir idle"),
])
def test_invalid_manifest_never_needs_a_tk_interpreter(tmp_path, field, value, match):
    metadata = json.loads((BUILTIN_SPRITE_DIR / "manifest.json").read_text(encoding="utf-8"))
    metadata[field] = value
    (tmp_path / "manifest.json").write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(ValueError, match=match):
        SpritePack.load(None, tmp_path)


def test_frames_outside_png_are_rejected_before_decode(tmp_path):
    metadata = json.loads((BUILTIN_SPRITE_DIR / "manifest.json").read_text(encoding="utf-8"))
    metadata["states"]["idle"]["frames"] = [[650, 0]]
    (tmp_path / "manifest.json").write_text(json.dumps(metadata), encoding="utf-8")
    shutil.copyfile(BUILTIN_SPRITE_DIR / "sprites.png", tmp_path / "sprites.png")
    with pytest.raises(ValueError, match="Quadro fora"):
        SpritePack.load(None, tmp_path)


def test_real_tk_reuses_frames_for_renderers_mirrors_and_cleans_canvas_items():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk não está disponível neste ambiente.")
    root.withdraw()
    try:
        pack = SpritePack.load(root)
        canvas = tk.Canvas(root)
        first = SpriteRenderer(canvas, pack, tag="first")
        second = SpriteRenderer(canvas, pack, tag="second")
        initial = canvas.find_all()
        assert pack.name == "Circuito"
        assert set(pack._animations) == SPRITE_STATES

        for mode in SPRITE_STATES:
            first.render(200, 300, 1, mode, 12, state_elapsed=0.1)
            second.render(300, 400, 1, mode, 12, state_elapsed=0.1)
            assert canvas.itemcget(first.item, "image") == canvas.itemcget(second.item, "image")
            assert canvas.find_all() == initial
            assert canvas.coords(first.item) == [158.0, 200.0]

        right = pack._frame("idle", 0, 1)
        left = pack._frame("idle", 0, -1)
        assert right.get(33, 6) == (255, 193, 102)  # Amber antenna, offset to one side.
        assert left.get(50, 6) == right.get(33, 6)
        assert left.transparency_get(0, 0)

        first.render(200, 300, -1, "walk", 13, state_elapsed=0)
        first_frame = canvas.itemcget(first.item, "image")
        first.set_visible(False)
        first.render(200, 300, -1, "walk", 13, state_elapsed=0.1)
        assert canvas.itemcget(first.item, "image") != first_frame
        assert canvas.itemcget(first.item, "state") == "hidden"
        assert canvas.gettags(first.item) == ("first",)
        first.close()
        first.close()
        assert canvas.find_all() == (second.item,)
        second.close()
        assert not canvas.find_all()
    finally:
        root.destroy()
