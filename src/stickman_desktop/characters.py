from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .animation_state import AnimationStateMachine
from .core import normalize

if TYPE_CHECKING:
    from .animation import CharacterRenderer
    from .motion import Motion
    from .sprites import SpriteRenderer


@dataclass(frozen=True)
class CharacterSpec:
    id: str
    name: str
    color: str
    appearance: str = "strokes"


COMPANIONS = (
    CharacterSpec("faisca", "Faísca", "#39cdd6", "circuito"),
    CharacterSpec("iris", "Íris", "#a58cff"),
    CharacterSpec("nimbo", "Nimbo", "#59da93"),
)


@dataclass
class DesktopCharacter:
    id: str
    name: str
    color: str
    motion: Motion
    renderer: CharacterRenderer | SpriteRenderer
    appearance: str = "strokes"
    behavior: str = "manual"
    next_decision: float = 0.0
    pose: str | None = None
    pose_until: float = 0.0
    hurt_level: int = 0
    hurt_cooldown: float = 0.0
    animation: AnimationStateMachine = field(default_factory=AnimationStateMachine)

    @property
    def tag(self) -> str:
        return f"actor:{self.id}"


def find_character(
    characters: dict[str, DesktopCharacter], query: str
) -> DesktopCharacter | None:
    """Find an actor by stable ID, or by an unambiguous display name."""
    character = characters.get(query.strip().casefold())
    if character is not None:
        return character
    name = normalize(query)
    if not name:
        return None
    matches = [character for character in characters.values() if normalize(character.name) == name]
    return matches[0] if len(matches) == 1 else None


def spawn_x(left: float, right: float, anchor: float, occupied: Iterable[float]) -> float:
    """Choose a nearby position with room for the new character."""
    if left > right:
        raise ValueError("Invalid character placement interval")
    anchor = max(left, min(right, anchor))
    neighbors = sorted(occupied)
    if not neighbors:
        return anchor

    def clearance(point: float) -> float:
        return min(abs(point - neighbor) for neighbor in neighbors)

    spacing = 100.0
    candidates = [left, anchor, right]
    for neighbor in neighbors:
        candidates.extend(point for point in (neighbor - spacing, neighbor + spacing)
                          if left <= point <= right)
    available = [point for point in candidates if clearance(point) >= spacing]
    if available:
        return min(available, key=lambda point: (abs(point - anchor), -point))

    # In a crowded area the safest spot is a boundary or the middle of a gap.
    gaps = [(a + b) / 2 for a, b in zip(neighbors, neighbors[1:])]
    candidates = [left, right, *(point for point in gaps if left <= point <= right)]
    return max(candidates, key=lambda point: (clearance(point), -abs(point - anchor), point))
