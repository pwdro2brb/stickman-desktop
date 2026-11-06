"""Bounded sprite sheets with the same foot anchor as the articulated renderer."""
from __future__ import annotations

import base64
import json
import math
import re
import struct
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path

BUILTIN_SPRITE_DIR = Path(__file__).with_name("assets") / "sprites" / "circuito"
SPRITE_STATES = frozenset({"idle", "walk", "jump", "fall", "drag", "wave", "fight"})
_MAX_SHEET_BYTES = 4 * 1024 * 1024
_MAX_SHEET_SIDE = 2048
_MAX_FRAME_PIXELS = 2_000_000


def _read_asset(directory: Path, name: str, limit: int) -> bytes:
    path = directory / name
    if path.resolve().parent != directory or not path.is_file():
        raise ValueError(f"Arquivo de sprite inválido: {name}.")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"Arquivo de sprite grande demais: {name}.")
    return data


def _pair(value: object, label: str, minimum: int, maximum: int) -> tuple[int, int]:
    if (not isinstance(value, list) or len(value) != 2
            or any(type(number) is not int or not minimum <= number <= maximum for number in value)):
        raise ValueError(f"{label} deve conter dois inteiros entre {minimum} e {maximum}.")
    return value[0], value[1]


def _png_size(data: bytes) -> tuple[int, int]:
    # Check the mandatory first chunk before asking Tk to allocate an image.
    if len(data) < 33 or data[:16] != b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR":
        raise ValueError("O arquivo de sprites deve ser um PNG válido.")
    width, height = struct.unpack_from(">II", data, 16)
    if not (1 <= width <= _MAX_SHEET_SIDE and 1 <= height <= _MAX_SHEET_SIDE):
        raise ValueError("A folha PNG deve ter até 2048 pixels por lado.")
    return width, height


@dataclass(frozen=True)
class _Animation:
    fps: float
    loop: bool
    frames: tuple[tuple[tk.PhotoImage, tk.PhotoImage], ...]

    def frame(self, elapsed: float, facing: int) -> tk.PhotoImage:
        count = len(self.frames)
        duration = count / self.fps
        position = elapsed % duration if self.loop else min(elapsed, duration)
        index = min(count - 1, int(position * self.fps))
        return self.frames[index][facing < 0]


@dataclass(frozen=True)
class SpritePack:
    """Decoded frames shared by all renderers using one Tk interpreter."""

    name: str
    width: int
    anchor: tuple[int, int]
    _animations: dict[str, _Animation]

    @classmethod
    def load(cls, master, directory: Path = BUILTIN_SPRITE_DIR) -> SpritePack:
        """Load manifest.json and its local PNG, raising ValueError on invalid assets."""
        try:
            return cls._load(master, Path(directory).resolve())
        except (OSError, UnicodeError, RecursionError, tk.TclError) as error:
            raise ValueError("Não foi possível carregar o pacote de sprites.") from error

    @classmethod
    def _load(cls, master, directory: Path) -> SpritePack:
        metadata = json.loads(_read_asset(directory, "manifest.json", 32_768).decode("utf-8-sig"))
        fields = {"name", "image", "frame_size", "anchor", "states"}
        if not isinstance(metadata, dict) or set(metadata) != fields:
            raise ValueError("Manifesto de sprites inválido.")
        name = metadata["name"]
        if not isinstance(name, str) or not name.strip() or len(name) > 60 or not name.isprintable():
            raise ValueError("Nome de pacote de sprites inválido.")
        image_name = metadata["image"]
        if not isinstance(image_name, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}\.png", image_name):
            raise ValueError("O manifesto deve indicar um arquivo PNG na pasta do pacote.")
        width, height = _pair(metadata["frame_size"], "frame_size", 1, 256)
        anchor_x, anchor_y = _pair(metadata["anchor"], "anchor", 0, 256)
        if anchor_x > width or anchor_y > height:
            raise ValueError("A âncora deve estar dentro do quadro.")
        states = metadata["states"]
        if not isinstance(states, dict) or set(states) != SPRITE_STATES:
            raise ValueError("O pacote deve definir idle, walk, jump, fall, drag, wave e fight.")

        data = _read_asset(directory, image_name, _MAX_SHEET_BYTES)
        sheet_width, sheet_height = _png_size(data)
        definitions = {}
        total_pixels = 0
        for state, definition in states.items():
            if not isinstance(definition, dict) or set(definition) != {"fps", "loop", "frames"}:
                raise ValueError(f"Estado de sprite inválido: {state}.")
            fps, loop, frames = definition["fps"], definition["loop"], definition["frames"]
            if type(fps) not in {int, float} or not 1 <= fps <= 60 or type(loop) is not bool:
                raise ValueError(f"Cadência ou repetição inválida: {state}.")
            if not isinstance(frames, list) or not 1 <= len(frames) <= 16:
                raise ValueError(f"O estado {state} deve ter de 1 a 16 quadros.")
            origins = [_pair(frame, "frame", 0, _MAX_SHEET_SIDE) for frame in frames]
            if any(x + width > sheet_width or y + height > sheet_height for x, y in origins):
                raise ValueError(f"Quadro fora da folha PNG: {state}.")
            total_pixels += len(origins) * width * height
            if total_pixels > _MAX_FRAME_PIXELS:
                raise ValueError("O conjunto de quadros excede o limite do pacote.")
            definitions[state] = (fps, loop, origins)

        sheet = tk.PhotoImage(master=master, data=base64.b64encode(data), format="png")
        if (sheet.width(), sheet.height()) != (sheet_width, sheet_height):
            raise ValueError("Dimensões do PNG não correspondem ao cabeçalho.")
        animations = {}
        for state, (fps, loop, origins) in definitions.items():
            frames = []
            for x, y in origins:
                right = tk.PhotoImage(master=master, width=width, height=height)
                left = tk.PhotoImage(master=master, width=width, height=height)
                region = (str(sheet), "-from", x, y, x + width, y + height)
                right.tk.call(str(right), "copy", *region)
                left.tk.call(str(left), "copy", *region, "-subsample", -1, 1)
                frames.append((right, left))
            animations[state] = _Animation(fps, loop, tuple(frames))
        return cls(name.strip(), width, (anchor_x, anchor_y), animations)

    def _frame(self, mode: str, elapsed: float, facing: int) -> tk.PhotoImage:
        return self._animations.get(mode, self._animations["idle"]).frame(elapsed, facing)


class SpriteRenderer:
    """Draw one shared sprite frame, keeping a stable Canvas hit target."""

    def __init__(self, canvas, pack: SpritePack, tag: str = "character") -> None:
        self.canvas, self.pack, self.tag = canvas, pack, tag
        self._image = pack._frame("idle", 0, 1)
        self.item = canvas.create_image(-512, -512, anchor="nw", image=self._image, tags=(tag,))
        self._mode: str | None = None
        self._started = 0.0

    def render(self, x: float, y: float, direction: int, mode: str, phase: float,
               vy: float = 0, *, gaze: tuple[float, float] | None = None,
               dt: float | None = None, vx: float | None = None,
               state_elapsed: float | None = None) -> None:
        if self.item is None:
            return
        if not all(math.isfinite(value) for value in (x, y, direction, phase)):
            raise ValueError("Coordenadas e tempo do sprite devem ser finitos.")
        if state_elapsed is not None and (not math.isfinite(state_elapsed) or state_elapsed < 0):
            raise ValueError("Tempo do estado deve ser finito e não negativo.")
        if mode != self._mode or phase < self._started:
            self._mode, self._started = mode, phase
        elapsed = phase - self._started if state_elapsed is None else state_elapsed
        image = self.pack._frame(mode, elapsed, direction)
        if image is not self._image:
            self.canvas.itemconfigure(self.item, image=image)
            self._image = image
        anchor_x, anchor_y = self.pack.anchor
        if direction < 0:
            anchor_x = self.pack.width - anchor_x
        self.canvas.coords(self.item, x - anchor_x, y - anchor_y)

    def set_visible(self, visible: bool) -> None:
        if self.item is not None:
            self.canvas.itemconfigure(self.item, state="normal" if visible else "hidden")

    def close(self) -> None:
        if self.item is not None:
            self.canvas.delete(self.item)
            self.item = None
