"""Small, deterministic desktop physics model; all coordinates describe the feet."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Surface:
    key: str
    left: float
    right: float
    y: float
    kind: str = "window"


@dataclass(frozen=True)
class Impact:
    x: float
    y: float
    speed: float
    count: int
    kind: str


@dataclass
class _Leap:
    key: str
    start_x: float
    start_y: float
    arc: float
    elapsed: float = 0.0


class Motion:
    """Animate a character without moving or controlling any real window."""

    GRAVITY = 1800.0
    WALK_SPEED = 140.0
    JUMP_SPEED = 650.0
    EDGE = 24.0
    BODY_MARGIN = 28.0
    HEAD_ROOM = 100.0
    LEAP_DURATION = 0.7
    MAX_THROW_SPEED = 3000.0
    WALL_RESTITUTION = 0.78
    FLOOR_RESTITUTION = 0.52
    MIN_BOUNCE_SPEED = 180.0
    MAX_PENDING_IMPACTS = 64

    def __init__(self, width: float, height: float, x: float, y: float) -> None:
        if not all(math.isfinite(value) for value in (width, height, x, y)):
            raise ValueError("Motion coordinates must be finite.")
        if width < self.BODY_MARGIN * 2 or height < self.HEAD_ROOM:
            raise ValueError("The desktop is too small for the character.")
        self.width, self.height = float(width), float(height)
        self.x = self._clamp_x(x)
        self.y = float(y)
        self.vx = self.vy = 0.0
        self.target_x: float | None = None
        self.direction = 1
        self.mode = "idle"
        self.support_key: str | None = None
        self._surfaces: dict[str, Surface] = {}
        self._ignored_key: str | None = None
        self._leap: _Leap | None = None
        self._throwing = False
        self.bounce_count = 0
        self._impacts: list[Impact] = []
        self._bounds: list[tuple[float, float, float, float]] = []

    @property
    def support(self) -> Surface | None:
        return self._surfaces.get(self.support_key)

    @property
    def grounded(self) -> bool:
        return self.support is not None

    @property
    def throwing(self) -> bool:
        return self._throwing

    def _reset_throw(self) -> None:
        self._throwing = False
        self.bounce_count = 0
        self._impacts.clear()

    def drain_impacts(self) -> list[Impact]:
        impacts, self._impacts = self._impacts, []
        return impacts

    def _impact(self, speed: float, kind: str) -> None:
        self.bounce_count += 1
        self._impacts.append(Impact(self.x, self.y, abs(speed), self.bounce_count, kind))
        del self._impacts[:-self.MAX_PENDING_IMPACTS]

    def set_bounds(self, bounds: list[tuple[float, float, float, float]]) -> None:
        """Work areas in canvas coordinates; adjacent areas form one open passage."""
        valid = []
        for left, top, right, bottom in bounds:
            if (not all(math.isfinite(v) for v in (left, top, right, bottom))
                    or right <= left or bottom <= top):
                raise ValueError("Monitor bounds must be finite, non-empty rectangles.")
            valid.append((left, top, right, bottom))
        self._bounds = valid

    @staticmethod
    def _merge_intervals(intervals):
        merged = []
        for left, right in sorted(intervals):
            if merged and left <= merged[-1][1] + 1e-8:
                merged[-1] = (merged[-1][0], max(merged[-1][1], right))
            else:
                merged.append((left, right))
        return merged

    def _axis_limits(self, x: float, y: float, horizontal: bool):
        bounds = self._bounds or [(0.0, 0.0, self.width, self.height)]
        # Sweep the union of work areas before adding body margins. This keeps
        # monitor seams open even when the body overlaps two display rectangles.
        if horizontal:
            edges = sorted({value for rect in bounds for value in (rect[0], rect[2])})
            spans = []
            for a, b in zip(edges, edges[1:]):
                midpoint = (a + b) / 2
                coverage = self._merge_intervals([(top, bottom) for left, top, right, bottom in bounds
                                                  if left <= midpoint <= right])
                if any(top - 1e-8 <= y - self.HEAD_ROOM and y <= bottom + 1e-8
                       for top, bottom in coverage):
                    spans.append((a, b))
            intervals = [(a + self.BODY_MARGIN, b - self.BODY_MARGIN)
                         for a, b in self._merge_intervals(spans)
                         if b - a >= 2 * self.BODY_MARGIN]
            position = x
        else:
            edges = sorted({value for rect in bounds for value in (rect[1], rect[3])})
            spans = []
            for a, b in zip(edges, edges[1:]):
                midpoint = (a + b) / 2
                coverage = self._merge_intervals([(left, right) for left, top, right, bottom in bounds
                                                  if top <= midpoint <= bottom])
                if any(left - 1e-8 <= x - self.BODY_MARGIN
                       and x + self.BODY_MARGIN <= right + 1e-8 for left, right in coverage):
                    spans.append((a, b))
            intervals = [(a + self.HEAD_ROOM, b)
                         for a, b in self._merge_intervals(spans)
                         if b - a >= self.HEAD_ROOM]
            position = y
        if not intervals:
            return ((self.BODY_MARGIN, self.width - self.BODY_MARGIN) if horizontal
                    else (self.HEAD_ROOM, self.height))
        return min(intervals, key=lambda ab: abs(position - max(ab[0], min(ab[1], position))))

    def _clamp_x(self, x: float) -> float:
        return max(self.BODY_MARGIN, min(self.width - self.BODY_MARGIN, float(x)))

    def _limits(self, surface: Surface) -> tuple[float, float] | None:
        margin = self.EDGE if surface.kind == "window" else 0.0
        left = max(self.BODY_MARGIN, surface.left + margin)
        right = min(self.width - self.BODY_MARGIN, surface.right - margin)
        return (left, right) if left <= right else None

    def _contains(self, surface: Surface, x: float) -> bool:
        limits = self._limits(surface)
        return limits is not None and limits[0] - 1e-8 <= x <= limits[1] + 1e-8

    def _set_mode(self) -> None:
        if self.grounded:
            self.mode = ("fall" if self._throwing else
                         "walk" if self.target_x is not None else "idle")
        else:
            self.mode = "jump" if self.vy < 0 else "fall"

    def reframe(self, width: float, height: float, dx: float, dy: float) -> None:
        """Change the canvas origin without moving the character on the desktop."""
        if not all(math.isfinite(value) for value in (width, height, dx, dy)):
            raise ValueError("Desktop geometry must be finite.")
        if width < self.BODY_MARGIN * 2 or height < self.HEAD_ROOM:
            raise ValueError("The desktop is too small for the character.")
        self.width, self.height = float(width), float(height)
        self.x = self._clamp_x(self.x + dx)
        self.y += dy
        if self.target_x is not None:
            self.target_x = self._clamp_x(self.target_x + dx)
        self._surfaces = {
            key: Surface(surface.key, surface.left + dx, surface.right + dx,
                         surface.y + dy, surface.kind)
            for key, surface in self._surfaces.items()
        }
        self._bounds = [(left + dx, top + dy, right + dx, bottom + dy)
                        for left, top, right, bottom in self._bounds]
        self._impacts = [Impact(i.x + dx, i.y + dy, i.speed, i.count, i.kind)
                         for i in self._impacts]
        if self._leap is not None:
            self._leap.start_x += dx
            self._leap.start_y += dy

    def set_surfaces(self, surfaces: list[Surface]) -> None:
        previous = self.support
        self._surfaces = {
            surface.key: surface for surface in surfaces
            if all(math.isfinite(value) for value in (surface.left, surface.right, surface.y))
            and surface.right > surface.left
        }
        if self._ignored_key not in self._surfaces:
            self._ignored_key = None

        if self._leap is not None:
            target = self._surfaces.get(self._leap.key)
            if (target is None or self._limits(target) is None
                    or not self.HEAD_ROOM <= target.y <= self.height):
                self._leap = None
                self.vy = 0.0
                self._set_mode()
            return
        if self.mode == "drag":
            return

        if previous is not None:
            current = self.support
            if current is not None:
                # A drag translates the rider; resizing keeps the rider's world x.
                same_width = math.isclose(current.right - current.left,
                                          previous.right - previous.left, abs_tol=0.5)
                dx = current.left - previous.left if same_width else 0.0
                self.x = self._clamp_x(self.x + dx)
                self.y += current.y - previous.y
                if self.target_x is not None:
                    self.target_x = self._clamp_x(self.target_x + dx)
                if self._contains(current, self.x):
                    self.y, self.vy = current.y, 0.0
                    if current.kind == "window" and self.target_x is not None:
                        limits = self._limits(current)
                        self.target_x = max(limits[0], min(limits[1], self.target_x))
                    self._set_mode()
                    return
            self.support_key = None
            self.target_x = None
            self.vy = 0.0
            self._set_mode()
            return

        # Initial placement and monitor changes may put the feet on a floor.
        if self.vy >= 0 and not self._throwing:
            for surface in self._surfaces.values():
                if (surface.kind == "floor" and abs(self.y - surface.y) <= 2
                        and self._contains(surface, self.x)):
                    self.support_key = surface.key
                    self.y, self.vy = surface.y, 0.0
                    self._set_mode()
                    return
        self._set_mode()

    def walk_to(self, x: float) -> None:
        if not math.isfinite(x):
            raise ValueError("The destination must be finite.")
        self._reset_throw()
        self._leap = None
        self.target_x = self._clamp_x(x)
        surface = self.support
        if surface is not None and surface.kind == "window":
            limits = self._limits(surface)
            self.target_x = max(limits[0], min(limits[1], self.target_x))
        self.direction = 1 if self.target_x >= self.x else -1
        self._set_mode()

    def jump(self) -> bool:
        if not self.grounded:
            return False
        self._reset_throw()
        self.support_key = None
        self._ignored_key = None
        self.vy = -self.JUMP_SPEED
        self.mode = "jump"
        return True

    def leap_to(self, key: str) -> bool:
        surface = self._surfaces.get(key)
        if (surface is None or self._limits(surface) is None
                or not self.HEAD_ROOM <= surface.y <= self.height):
            return False
        self._reset_throw()
        start_y = max(self.HEAD_ROOM, self.y)
        arc = min(70.0, max(0.0, min(start_y, surface.y) - self.HEAD_ROOM))
        self._leap = _Leap(key, self.x, start_y, arc)
        self.support_key = None
        self._ignored_key = None
        self.target_x = None
        self.vx = self.vy = 0.0
        self.mode = "jump"
        destination = (surface.left + surface.right) / 2
        self.direction = 1 if destination >= self.x else -1
        return True

    def drop(self) -> bool:
        if self.support is None or self.support.kind != "window":
            return False
        self._reset_throw()
        self._ignored_key = self.support_key
        self.support_key = None
        self.target_x = None
        self.vx = self.vy = 0.0
        self.mode = "fall"
        return True

    def stop(self) -> None:
        self._reset_throw()
        self._leap = None
        self.target_x = None
        self.vx = 0.0
        self._set_mode()

    def drag_to(self, x: float, y: float) -> None:
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError("The drag coordinates must be finite.")
        self._reset_throw()
        self._leap = None
        self.support_key = None
        self._ignored_key = None
        self.target_x = None
        self.x = self._clamp_x(x)
        self.y = max(self.HEAD_ROOM, min(self.height, float(y)))
        self.vx = self.vy = 0.0
        self.mode = "drag"

    def release(self, vx: float = 0, vy: float = 0) -> None:
        if not math.isfinite(vx) or not math.isfinite(vy):
            raise ValueError("The release velocity must be finite.")
        self._reset_throw()
        self._leap = None
        self.support_key = None
        self.target_x = None
        self.vx = max(-self.MAX_THROW_SPEED, min(self.MAX_THROW_SPEED, float(vx)))
        self.vy = max(-self.MAX_THROW_SPEED, min(self.MAX_THROW_SPEED, float(vy)))
        self._throwing = math.hypot(self.vx, self.vy) >= self.MIN_BOUNCE_SPEED
        if self.vx:
            self.direction = 1 if self.vx > 0 else -1
        self._set_mode()

    def step(self, dt: float) -> None:
        if not math.isfinite(dt) or dt < 0:
            raise ValueError("The elapsed time must be finite and non-negative.")
        # Small fixed upper bounds keep fast throws from tunnelling through edges.
        while dt > 1e-10:
            interval = min(dt, 1 / 120)
            self._step(interval)
            dt -= interval

    def _step(self, dt: float) -> None:
        if self.mode == "drag":
            return
        if self._leap is not None:
            self._step_leap(dt)
            return

        old_x = self.x
        if self.target_x is not None:
            distance = self.target_x - self.x
            travel = self.WALK_SPEED * dt
            if abs(distance) <= travel:
                self.x = self.target_x
                self.target_x = None
                self.vx = 0.0
            else:
                self.vx = math.copysign(self.WALK_SPEED, distance)
                self.x += self.vx * dt
                self.direction = 1 if distance >= 0 else -1
        elif self.vx:
            # Exact exponential drag gives consistent throws across frame rates.
            damping = (1.8 if self.grounded else 0.25) if self._throwing else 1.5
            decay = math.exp(-damping * dt)
            self.x += self.vx * (1 - decay) / damping
            self.vx *= decay
        left, right = self._axis_limits(old_x, self.y, horizontal=True)
        if self.x < left or self.x > right:
            self.x = max(left, min(right, self.x))
            speed = abs(self.vx)
            if self._throwing and speed >= self.MIN_BOUNCE_SPEED:
                self.vx = speed * self.WALL_RESTITUTION * (1 if self.x == left else -1)
                self.direction = 1 if self.vx > 0 else -1
                self._impact(speed, "wall")
            else:
                self.vx = 0.0

        surface = self.support
        if surface is not None:
            if self._contains(surface, self.x):
                self.y, self.vy = surface.y, 0.0
                if self._throwing and abs(self.vx) < self.MIN_BOUNCE_SPEED:
                    self._throwing = False
                    self.vx = 0.0
                self._set_mode()
                return
            self.support_key = None
            self.vy = 0.0

        old_y = self.y
        self.y += self.vy * dt + 0.5 * self.GRAVITY * dt * dt
        self.vy += self.GRAVITY * dt
        ceiling, bottom = self._axis_limits(self.x, old_y, horizontal=False)
        if self.y < ceiling:
            self.y = ceiling
            speed = abs(self.vy)
            if self._throwing and speed >= self.MIN_BOUNCE_SPEED:
                self.vy = speed * self.WALL_RESTITUTION
                self._impact(speed, "ceiling")
            else:
                self.vy = max(0.0, self.vy)

        if self.vy >= 0 and self.y >= old_y:
            crossed = [surface for surface in self._surfaces.values()
                       if surface.key != self._ignored_key
                       and old_y - 1e-8 <= surface.y <= self.y + 1e-8
                       and self._contains(surface, self.x)]
            if crossed:
                landed = min(crossed, key=lambda item: item.y)
                speed = self.vy
                self.y = landed.y
                if self._throwing and speed >= self.MIN_BOUNCE_SPEED:
                    self.support_key = None
                    self.vy = -speed * self.FLOOR_RESTITUTION
                    self.vx *= 0.8
                    self._impact(speed, "floor" if landed.kind == "floor" else "window")
                else:
                    self.support_key = landed.key
                    self.vy = 0.0
                    self._throwing = self._throwing and abs(self.vx) >= self.MIN_BOUNCE_SPEED
                    if landed.kind == "window" and self.target_x is not None:
                        limits = self._limits(landed)
                        self.target_x = max(limits[0], min(limits[1], self.target_x))
                    if self.target_x is None and not self._throwing:
                        self.vx = 0.0

        ignored = self._surfaces.get(self._ignored_key)
        if ignored is not None and self.y > ignored.y + 4:
            self._ignored_key = None
        if self.y > self.height + 150:
            self._rescue()
        self._set_mode()

    def _step_leap(self, dt: float) -> None:
        leap = self._leap
        surface = self._surfaces.get(leap.key)
        limits = self._limits(surface) if surface is not None else None
        if limits is None:
            self._leap = None
            self._set_mode()
            return
        leap.elapsed += dt
        progress = min(1.0, leap.elapsed / self.LEAP_DURATION)
        smooth = progress * progress * (3 - 2 * progress)
        destination = max(limits[0], min(limits[1], (surface.left + surface.right) / 2))
        target_y = max(self.HEAD_ROOM, min(self.height, surface.y))
        arc = min(leap.arc, max(0.0, min(leap.start_y, target_y) - self.HEAD_ROOM))
        self.x = self._clamp_x(leap.start_x + (destination - leap.start_x) * smooth)
        self.y = max(self.HEAD_ROOM, leap.start_y + (target_y - leap.start_y) * smooth
                     - arc * 4 * progress * (1 - progress))
        if progress >= 1:
            self.x, self.y = destination, target_y
            self.support_key = surface.key
            self._leap = None
            self.vx = self.vy = 0.0
            self._set_mode()

    def _rescue(self) -> None:
        floors = [surface for surface in self._surfaces.values()
                  if surface.kind == "floor" and self._limits(surface) is not None]
        if floors:
            def distance(surface):
                left, right = self._limits(surface)
                return abs(self.x - max(left, min(right, self.x)))
            floor = min(floors, key=distance)
            left, right = self._limits(floor)
            self.x = max(left, min(right, self.x))
            self.y = floor.y
            self.support_key = floor.key
        else:
            self.y = self.height
        self.vx = self.vy = 0.0
        self.target_x = None
