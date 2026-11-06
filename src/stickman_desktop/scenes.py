"""Load small, declarative visual scenes. Scene files cannot invoke tools."""
from __future__ import annotations

import json
import math
import re
import stat
from dataclasses import dataclass
from pathlib import Path

BUILTIN_SCENES_DIR = Path(__file__).with_name("assets") / "scenes"
MAX_SCENE_BYTES = 64 * 1024
MAX_STEPS = 64
_ACTIONS = {
    "say": {"text"}, "walk": {"fraction"}, "jump": set(),
    "wave": {"duration"}, "climb": set(), "fight": {"duration", "fragments"},
    "portal": {"duration"},
}
_DURATIONS = {"wave": (0.2, 5.0, 2.8), "fight": (0.2, 6.0, 5.0),
              "portal": (1.0, 10.0, 6.0)}


@dataclass(frozen=True)
class SceneStep:
    at: float
    action: str
    args: dict


@dataclass(frozen=True)
class Scene:
    id: str
    name: str
    duration: float
    steps: tuple[SceneStep, ...]


@dataclass(frozen=True)
class SceneCatalog:
    scenes: tuple[Scene, ...]
    errors: tuple[str, ...]


def _number(value: object, label: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} deve ser um número entre {minimum:g} e {maximum:g}.")
    try:
        number = float(value)
    except OverflowError:
        number = math.inf
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError(f"{label} deve ser um número entre {minimum:g} e {maximum:g}.")
    return number


def _text(value: object, label: str, limit: int, multiline: bool = False) -> str:
    if (not isinstance(value, str) or not value.strip() or len(value) > limit
            or any(not char.isprintable() and not (multiline and char in "\n\t")
                   for char in value)):
        raise ValueError(f"{label} deve ser um texto válido de até {limit} caracteres.")
    return value.strip()


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Campo JSON repetido: {key[:60]!r}.")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ValueError(f"Constante JSON inválida: {value}.")


def _validate(data: object) -> Scene:
    fields = {"id", "name", "duration", "steps"}
    if not isinstance(data, dict) or set(data) != fields:
        raise ValueError("A cena deve conter somente id, name, duration e steps.")
    identifier = data["id"]
    if not isinstance(identifier, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,47}", identifier):
        raise ValueError("id deve ter até 48 letras minúsculas, números, _ ou -, iniciando por letra ou número.")
    name = _text(data["name"], "name", 80)
    duration = _number(data["duration"], "duration", 1, 90)
    raw_steps = data["steps"]
    if not isinstance(raw_steps, list) or not 1 <= len(raw_steps) <= MAX_STEPS:
        raise ValueError(f"steps deve conter entre 1 e {MAX_STEPS} passos.")
    steps = []
    for index, raw in enumerate(raw_steps):
        label = f"Passo {index + 1}"
        if not isinstance(raw, dict) or not {"at", "action"} <= set(raw):
            raise ValueError(f"{label}: at e action são obrigatórios.")
        action = raw["action"]
        if not isinstance(action, str) or action not in _ACTIONS:
            raise ValueError(f"{label}: ação visual não permitida.")
        if set(raw) - ({"at", "action"} | _ACTIONS[action]):
            raise ValueError(f"{label}: campo não permitido para {action}.")
        at = _number(raw["at"], f"{label}: at", 0, duration)
        args = {}
        if action == "say":
            args["text"] = _text(raw.get("text"), f"{label}: text", 240, multiline=True)
        elif action == "walk":
            args["fraction"] = _number(raw.get("fraction"), f"{label}: fraction", 0, 1)
        elif action in _DURATIONS:
            low, high, default = _DURATIONS[action]
            args["duration"] = _number(raw.get("duration", default), f"{label}: duration", low, high)
        if action == "fight" and "fragments" in raw:
            fragments = raw["fragments"]
            if type(fragments) is not int or not 2 <= fragments <= 24:
                raise ValueError(f"{label}: fragments deve ser um inteiro entre 2 e 24.")
            args["fragments"] = fragments
        steps.append(SceneStep(at, action, args))
    return Scene(identifier, name, duration, tuple(sorted(steps, key=lambda step: step.at)))


def _is_link(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    # st_file_attributes also detects Windows junctions on Python 3.10/3.11,
    # which do not yet provide Path.is_junction().
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def load_scene(path: Path) -> Scene:
    """Read one bounded UTF-8 JSON file or raise a user-readable ValueError."""
    path = Path(path)
    try:
        if path.suffix.lower() != ".json" or _is_link(path) or not path.is_file():
            raise ValueError("A cena deve ser um arquivo .json regular, sem link simbólico.")
        with path.open("rb") as stream:
            payload = stream.read(MAX_SCENE_BYTES + 1)
        if len(payload) > MAX_SCENE_BYTES:
            raise ValueError("A cena excede o limite de 64 KiB.")
        data = json.loads(payload.decode("utf-8-sig"), object_pairs_hook=_unique_object,
                          parse_constant=_invalid_constant)
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError("Não foi possível ler um JSON UTF-8 válido.") from error
    return _validate(data)


def _filename(path: Path) -> str:
    return "".join(char if char.isprintable() else "?" for char in path.name)[:96]


def load_scenes(directory: Path) -> SceneCatalog:
    """Load direct JSON children, isolating invalid files and ambiguous IDs."""
    directory = Path(directory)
    try:
        if _is_link(directory) or not directory.is_dir():
            return SceneCatalog((), ("Pasta de cenas indisponível ou inválida.",))
        paths = sorted((path for path in directory.iterdir() if path.suffix.lower() == ".json"),
                       key=lambda path: path.name.casefold())
    except OSError:
        return SceneCatalog((), ("Não foi possível listar a pasta de cenas.",))
    loaded: dict[str, Scene] = {}
    conflicts: set[str] = set()
    errors = []
    for path in paths:
        try:
            scene = load_scene(path)
            if scene.id in loaded or scene.id in conflicts:
                loaded.pop(scene.id, None)
                conflicts.add(scene.id)
                raise ValueError(f"id de cena repetido: {scene.id}.")
            loaded[scene.id] = scene
        except ValueError as error:
            errors.append(f"{_filename(path)}: {error}")
    return SceneCatalog(tuple(loaded.values()), tuple(errors))
