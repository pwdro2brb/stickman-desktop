"""A visual-only duel staged on the overlay, independent of desktop physics."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, pi, sin


@dataclass(frozen=True)
class FighterPose:
    x: float
    y: float
    direction: int
    mode: str
    elapsed: float


@dataclass(frozen=True)
class TabPose:
    x: float
    y: float
    angle: float
    owner: int
    phase: str


@dataclass(frozen=True)
class TabImpact:
    x: float
    y: float
    angle: float
    vx: float
    vy: float
    fragments: int
    owner: int


@dataclass(frozen=True)
class DuelFrame:
    player: FighterPose
    opponent: FighterPose
    tab: TabPose | None
    impacts: tuple[TabImpact, ...]
    finished: bool


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _ease(progress: float) -> float:
    return progress * progress * (3 - 2 * progress)


def _lerp(start: float, end: float, progress: float) -> float:
    return start + (end - start) * progress


class TabDuel:
    """Sample the choreography by elapsed time, emitting each impact once."""

    _WINDUP = 0.25
    _RELEASE = 0.44
    _CONTACT = 0.65
    _LANDING = 0.82

    def __init__(
        self,
        duration: float,
        player_x: float,
        player_y: float,
        work_area: tuple[float, float, float, float],
        fragments: int | None = None,
        source: tuple[float, float] | None = None,
    ) -> None:
        left, top, right, bottom = work_area
        if (not all(isfinite(value) for value in (duration, player_x, player_y, *work_area))
                or not 0.2 <= duration <= 6 or left >= right or top >= bottom):
            raise ValueError("Duel duration and stage bounds must be valid")
        if fragments is not None and (type(fragments) is not int or not 2 <= fragments <= 24):
            raise ValueError("A tab can break into 2 to 24 fragments")
        if source is not None and not all(isfinite(value) for value in source):
            raise ValueError("Tab source coordinates must be finite")

        self.duration = duration
        self._elapsed = 0.0
        self._impacted = 0
        self._entrance = duration * 0.055
        self._exit = duration * 0.94
        count = 3 if duration >= 4.5 else 2 if duration >= 2.8 else 1
        self._beat_length = (self._exit - self._entrance) / count
        self._fragments = (fragments,) * count if fragments is not None else (6, 12, 24)[:count]

        width, height = right - left, bottom - top
        side_margin = min(26.0, width / 4)
        self._x_bounds = (left + side_margin, right - side_margin)
        self._y_bounds = (top + min(104.0, height * 0.8), bottom - min(3.0, height * 0.05))
        self._player_start = _clamp(player_x, *self._x_bounds)
        self._floor = _clamp(player_y, *self._y_bounds)
        low, high = self._x_bounds
        self._side = 1 if high - self._player_start >= self._player_start - low else -1
        gap = self._gap = min(224.0, (high - low) * 0.55)
        clearance = min(84.0, (high - low - gap) / 2)
        stage_low = low + clearance + (gap if self._side < 0 else 0)
        stage_high = high - clearance - (gap if self._side > 0 else 0)
        player_home = _clamp(self._player_start, stage_low, stage_high)
        self._homes = (player_home, player_home + self._side * gap)
        self._opponent_outer = _clamp(self._homes[1] + self._side * 48, low, high)

        # Keep the centre of a rotated 132 × 58 tab clear of the monitor edge.
        tab_margin_x = min(76.0, width / 2)
        tab_margin_y = min(76.0, height / 2)
        self._tab_x_bounds = (left + tab_margin_x, right - tab_margin_x)
        self._tab_y_bounds = (top + tab_margin_y, bottom - tab_margin_y)
        self._source = self._tab_position(*source) if source is not None else None

    def _tab_position(self, x: float, y: float) -> tuple[float, float]:
        return _clamp(x, *self._tab_x_bounds), _clamp(y, *self._tab_y_bounds)

    def _pose(self, x: float, y: float, owner: int, mode: str, elapsed: float) -> FighterPose:
        return FighterPose(_clamp(x, *self._x_bounds), _clamp(y, *self._y_bounds),
                           self._side if owner == 0 else -self._side, mode, elapsed)

    def _flight(self, beat: int, progress: float) -> tuple[TabPose, float, float]:
        owner = beat % 2
        direction = self._side if owner == 0 else -self._side
        release_reach = min(52.0, self._gap * 0.24)
        contact_reach = min(34.0, self._gap * 0.15)
        origin_x, origin_y = self._tab_position(self._homes[owner] + direction * release_reach, self._floor - 68)
        hit_x, hit_y = self._tab_position(self._homes[1 - owner] - direction * contact_reach, self._floor - 59)
        dx, dy = hit_x - origin_x, hit_y - origin_y
        arc = min(24.0 + beat * 11.0, max(0.0, min(origin_y, hit_y) - self._tab_y_bounds[0]))
        x = origin_x + dx * (0.25 * progress + 0.75 * progress**2)
        y = origin_y + dy * progress - 4 * arc * progress * (1 - progress)
        angle = direction * (-0.24 + (1.45 + beat * 0.65) * progress)
        flight_seconds = (self._CONTACT - self._RELEASE) * self._beat_length
        vx = dx * (0.25 + 1.5 * progress) / flight_seconds
        vy = (dy + 4 * arc * (2 * progress - 1)) / flight_seconds
        return TabPose(x, y, angle, owner, "flight"), vx, vy

    def _impact(self, beat: int) -> TabImpact:
        tab, vx, vy = self._flight(beat, 1.0)
        return TabImpact(tab.x, tab.y, tab.angle, vx, vy, self._fragments[beat], tab.owner)

    def _exchange(self, beat: int, progress: float) -> tuple[FighterPose, FighterPose, TabPose | None]:
        owner = beat % 2
        direction = self._side if owner == 0 else -self._side
        thrower_x = self._homes[owner]
        target_x = self._homes[1 - owner]
        elapsed = progress * self._beat_length
        hold_reach = min(78.0, self._gap * 0.35)
        pull_x, pull_y = self._tab_position(thrower_x + direction * hold_reach, self._floor - 66)
        tab = None
        if progress < self._WINDUP:
            pull = _ease(progress / self._WINDUP)
            source = self._source if beat == 0 and self._source is not None else self._tab_position(
                thrower_x - direction * 52, self._floor - 175
            )
            tab = TabPose(_lerp(source[0], pull_x, pull), _lerp(source[1], pull_y, pull),
                          direction * 0.36 * (1 - pull), owner, "pull")
            thrower = self._pose(thrower_x, self._floor, owner, "windup", elapsed)
        elif progress < self._RELEASE:
            windup = _ease((progress - self._WINDUP) / (self._RELEASE - self._WINDUP))
            release, _, _ = self._flight(beat, 0.0)
            tab = TabPose(_lerp(pull_x, release.x, windup), _lerp(pull_y, release.y, windup),
                          release.angle * windup, owner, "held")
            thrower = self._pose(thrower_x - direction * 16 * windup, self._floor, owner, "windup", elapsed)
        elif progress < self._CONTACT:
            flight = (progress - self._RELEASE) / (self._CONTACT - self._RELEASE)
            tab, _, _ = self._flight(beat, flight)
            lunge = _lerp(-16, 22, _ease(min(1.0, flight / 0.45)))
            thrower = self._pose(thrower_x + direction * lunge, self._floor, owner, "throw",
                                 flight * (self._CONTACT - self._RELEASE) * self._beat_length)
        else:
            recover = _ease((progress - self._CONTACT) / (1 - self._CONTACT))
            thrower = self._pose(thrower_x + direction * 22 * (1 - recover), self._floor,
                                 owner, "recover", elapsed - self._CONTACT * self._beat_length)

        if progress < self._CONTACT:
            target = self._pose(target_x, self._floor, 1 - owner, "idle", elapsed)
        else:
            room = self._x_bounds[1] - target_x if direction > 0 else target_x - self._x_bounds[0]
            kick = min(52.0 + beat * 19.0, room)
            if progress < self._LANDING:
                recoil = (progress - self._CONTACT) / (self._LANDING - self._CONTACT)
                height = min(21.0 + beat * 8.0, self._floor - self._y_bounds[0])
                target = self._pose(target_x + direction * kick * (1 - (1 - recoil)**2),
                                    self._floor - height * sin(pi * recoil), 1 - owner, "recoil",
                                    elapsed - self._CONTACT * self._beat_length)
            else:
                recover = _ease((progress - self._LANDING) / (1 - self._LANDING))
                target = self._pose(target_x + direction * kick * (1 - recover), self._floor,
                                    1 - owner, "recover", elapsed - self._LANDING * self._beat_length)

        return (thrower, target, tab) if owner == 0 else (target, thrower, tab)

    def advance(self, dt: float) -> DuelFrame:
        if not isfinite(dt) or dt < 0:
            raise ValueError("Duel dt must be finite and non-negative")
        self._elapsed = min(self.duration, self._elapsed + dt)
        now = self._elapsed
        impacts = []
        for beat in range(self._impacted, len(self._fragments)):
            hit_time = self._entrance + (beat + self._CONTACT) * self._beat_length
            if hit_time > now:
                break
            impacts.append(self._impact(beat))
            self._impacted += 1

        tab = None
        if now < self._entrance:
            blend = _ease(now / self._entrance)
            player_mode = "idle" if self._player_start == self._homes[0] else "walk"
            player = self._pose(_lerp(self._player_start, self._homes[0], blend), self._floor,
                                0, player_mode, now)
            opponent = self._pose(_lerp(self._opponent_outer, self._homes[1], blend), self._floor,
                                  1, "walk", now)
        elif now < self._exit:
            phase = (now - self._entrance) / self._beat_length
            beat = min(int(phase), len(self._fragments) - 1)
            player, opponent, tab = self._exchange(beat, phase - beat)
        else:
            blend = _ease((now - self._exit) / (self.duration - self._exit))
            player_mode = "idle" if now >= self.duration else "recover"
            player = self._pose(_lerp(self._homes[0], self._player_start, blend), self._floor,
                                0, player_mode, now - self._exit)
            opponent = self._pose(_lerp(self._homes[1], self._opponent_outer, blend), self._floor,
                                  1, player_mode, now - self._exit)
        return DuelFrame(player, opponent, tab, tuple(impacts), now >= self.duration)
