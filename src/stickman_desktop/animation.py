from __future__ import annotations

import math
import random
from dataclasses import dataclass


def solve_two_bone(start, target, upper: float, lower: float, bend: int = 1):
    """Solve a two-segment limb analytically, with a consistent bend direction.

    Unreachable targets are projected onto the reach circle, never stretching
    the bones. The solution is derived from the triangle's law of cosines.
    """
    sx, sy = start
    dx, dy = target[0] - sx, target[1] - sy
    distance = math.hypot(dx, dy)
    ux, uy = (dx / distance, dy / distance) if distance > 1e-8 else (0.0, 1.0)
    reach = max(abs(upper - lower) + 1e-6, min(upper + lower - 1e-6, distance))
    along = (upper * upper - lower * lower + reach * reach) / (2 * reach)
    height = math.sqrt(max(0.0, upper * upper - along * along))
    joint = (sx + ux * along - uy * height * bend,
             sy + uy * along + ux * height * bend)
    end = (sx + ux * reach, sy + uy * reach)
    return joint, end


class CharacterRenderer:
    """Original articulated figure with contact-aware feet and a soft gaze."""

    STRIDE = 80.0
    STANCE = 0.48
    FOOT_CENTER = 0.0  # Motion surfaces already include the 3px stroke clearance.
    LEG_LENGTH = 21.0
    ARM_LENGTH = 18.0

    def __init__(self, canvas, color: str, tag: str = "character") -> None:
        self.canvas, self.color, self.tag = canvas, color, tag
        self.parts: dict[str, int] = {}
        for name in ("arm2", "leg2", "body", "arm1", "leg1"):
            self.parts[name] = canvas.create_line(
                0, 0, 1, 1, 2, 2, fill=color, width=5 if name != "body" else 6,
                capstyle="round", joinstyle="round", tags=(tag,),
            )
        self.parts["head"] = canvas.create_oval(
            0, 0, 1, 1, outline=color, fill="#20212a", width=4, tags=(tag,),
        )
        for name in ("eye1", "eye2"):
            self.parts[name] = canvas.create_oval(
                0, 0, 1, 1, outline="", fill="#fff4de", tags=(tag,),
            )
        self._last_x: float | None = None
        self._last_phase: float | None = None
        self._last_mode = "idle"
        self._facing = 1
        self._gait = 0.0
        self._walk_blend = 0.0
        self._look = (0.0, 0.0)
        self._pose: dict[str, tuple[float, float]] | None = None
        self._turn_feet = None
        self._turn_time = 0.16

    def set_visible(self, visible: bool) -> None:
        for item in self.parts.values():
            self.canvas.itemconfigure(item, state="normal" if visible else "hidden")

    def close(self) -> None:
        for item in self.parts.values():
            self.canvas.delete(item)
        self.parts.clear()

    @classmethod
    def _foot(cls, cycle: float) -> tuple[float, float]:
        cycle %= 1.0
        amplitude = cls.STRIDE * cls.STANCE / 2
        if cycle < cls.STANCE:
            # Root moves +stride*phase while the planted foot moves the inverse
            # distance in root space, exactly cancelling foot sliding.
            return amplitude - cls.STRIDE * cycle, cls.FOOT_CENTER
        progress = (cycle - cls.STANCE) / (1 - cls.STANCE)
        eased = progress * progress * (3 - 2 * progress)
        return (-amplitude + 2 * amplitude * eased,
                cls.FOOT_CENTER - 9 * math.sin(math.pi * progress) ** 2)

    def render(self, x: float, y: float, direction: int, mode: str,
               phase: float, vy: float = 0, *, gaze: tuple[float, float] | None = None,
               dt: float | None = None, vx: float | None = None,
               state_elapsed: float | None = None) -> None:
        values = [x, y, direction, phase, vy]
        if gaze is not None:
            values.extend(gaze)
        if dt is not None:
            values.append(dt)
        if vx is not None:
            values.append(vx)
        action_time = phase if state_elapsed is None else state_elapsed
        values.append(action_time)
        if not all(math.isfinite(value) for value in values) or (dt is not None and dt < 0):
            raise ValueError("Character coordinates and elapsed time must be finite and valid.")
        elapsed = dt if dt is not None else (
            max(0.0, phase - self._last_phase) if self._last_phase is not None else 1 / 60
        )
        elapsed = min(0.1, elapsed)
        # Legacy callers can request another pose at the same clock instant.
        if dt is None and elapsed == 0:
            elapsed = 1 / 60
        facing = 1 if direction >= 0 else -1
        if facing != self._facing and self._pose is not None:
            self._turn_feet = (self._pose["foot1"], self._pose["foot2"])
            self._turn_time = 0.0
        self._facing = facing
        self._turn_time += elapsed
        dx = x - self._last_x if self._last_x is not None else 0.0
        speed = abs(vx) if vx is not None else (abs(dx) / elapsed if elapsed > 0 else 0.0)
        if mode == "walk":
            if self._last_x is None:
                distance = speed * elapsed
            elif vx is not None and abs(dx) > max(2.0, speed * elapsed * 2 + 1):
                distance = speed * elapsed  # A window was translated under the rider.
            else:
                distance = abs(dx)
            self._gait = (self._gait + distance / self.STRIDE) % 1.0
        self._walk_blend = max(0.0, min(1.0, self._walk_blend + (
            elapsed / 0.16 if mode == "walk" else -elapsed / 0.16
        )))
        walk = self._walk_blend
        pulse = math.sin(self._gait * math.tau)
        breathing = math.sin(phase * 2.4) * 0.45 * (1 - walk)
        hip = (facing * 0.6 * walk, -37.5 + walk + breathing + walk * math.cos(self._gait * math.tau * 2) * 0.35)
        shoulder = (facing * 2.4 * walk, -62.5 + breathing + walk * 0.4 * math.cos(self._gait * math.tau * 2))
        first, second = self._foot(self._gait), self._foot(self._gait + 0.5)
        foot1 = (12 * (1 - walk) + facing * first[0] * walk,
                 self.FOOT_CENTER * (1 - walk) + first[1] * walk)
        foot2 = (-12 * (1 - walk) + facing * second[0] * walk,
                 self.FOOT_CENTER * (1 - walk) + second[1] * walk)
        hand1 = (facing * (8 - pulse * 15 * walk), -29.0 + walk * 2 * max(0, pulse))
        hand2 = (-facing * (8 - pulse * 15 * walk), -29.0 + walk * 2 * max(0, -pulse))
        if mode in {"jump", "fall"}:
            rising = mode == "jump" and vy <= 0
            hip, shoulder = (facing * 1.0, -37.0), (facing * 3.0, -61.0)
            hand1 = (facing * 25, -80 if rising else -62)
            hand2 = (-facing * 22, -73 if rising else -55)
            foot1 = (facing * 15, -12 if rising else self.FOOT_CENTER)
            foot2 = (-facing * 12, -7 if rising else self.FOOT_CENTER)
        elif mode == "drag":
            sway = math.sin(action_time * 4.2) * 2
            hip, shoulder = (sway * 0.5, -39.0), (sway, -63.0)
            hand1, hand2 = (12, -87), (-12, -85)
            foot1, foot2 = (10 + sway, self.FOOT_CENTER), (-10 + sway, -4.0)
        elif mode == "wave":
            hand1 = (facing * (23 + math.sin(action_time * 8) * 4), -87)
        elif mode == "windup":
            # Sit into the back foot with both hands bracing the tab's weight.
            hip, shoulder = (-facing * 5, -31.0), (-facing * 10, -54.0)
            hand1, hand2 = (facing * 18, -70), (facing * 16, -55)
            foot1, foot2 = (facing * 16, 0), (-facing * 21, 0)
        elif mode == "throw":
            follow_through = min(1.0, action_time * 7)
            hip = (facing * 5, -35.0)
            shoulder = (facing * (10 + 8 * follow_through), -57 + 3 * follow_through)
            hand1, hand2 = (facing * 43, -64), (facing * 30, -53)
            foot1, foot2 = (facing * 22, 0), (-facing * 15, -3)
        elif mode == "recoil":
            hip, shoulder = (-facing * 4, -34.0), (-facing * 18, -56.0)
            hand1, hand2 = (-facing * 33, -73), (facing * 9, -75)
            foot1, foot2 = (facing * 22, -4), (-facing * 10, -13)
        elif mode == "recover":
            rise = min(1.0, action_time * 4)
            hip, shoulder = (0, -25 - 12 * rise), (-facing * (6 - 5 * rise), -47 - 15 * rise)
            hand1, hand2 = (facing * (21 - 12 * rise), -22 - 7 * rise), (-facing * 16, -27)
            foot1, foot2 = (facing * 16, 0), (-facing * 15, 0)
        elif mode == "fight":
            punch = (math.sin(action_time * 10) + 1) * 0.5
            hip, shoulder = (facing * 2, -36.0), (facing * 6, -60.0)
            hand1, hand2 = (facing * (25 + punch * 9), -59), (facing * 14, -68)
            foot1, foot2 = (facing * 18, self.FOOT_CENTER), (-facing * 18, self.FOOT_CENTER)
        if self._turn_feet is not None and self._turn_time < 0.16:
            weight = self._turn_time / 0.16
            weight = weight * weight * (3 - 2 * weight)
            foot1 = tuple(a + (b - a) * weight for a, b in zip(self._turn_feet[0], foot1))
            foot2 = tuple(a + (b - a) * weight for a, b in zip(self._turn_feet[1], foot2))
        targets = {"hip": hip, "shoulder": shoulder, "hand1": hand1,
                   "hand2": hand2, "foot1": foot1, "foot2": foot2}
        alpha = -math.expm1(-20 * elapsed)
        if self._pose is None:
            self._pose = targets
        else:
            self._pose = {name: tuple(a + (b - a) * alpha for a, b in zip(self._pose[name], value))
                          for name, value in targets.items()}
            # Contact positions are constraints, not interpolated joint angles.
            # Blending them after the transition would make the planted feet slide.
            if mode == "walk" and walk >= 1 and self._turn_time >= 0.16:
                self._pose["foot1"], self._pose["foot2"] = foot1, foot2
            elif mode in {"idle", "wave", "fight"}:
                for name in ("foot1", "foot2"):
                    px, py = self._pose[name]
                    self._pose[name] = (px, min(self.FOOT_CENTER, py))
        pose = self._pose
        hip = (x + pose["hip"][0], y + pose["hip"][1])
        shoulder = (x + pose["shoulder"][0], y + pose["shoulder"][1])
        if gaze is None:
            desired = (facing * 0.4, 0.0)
        else:
            gx, gy = (gaze[0] - shoulder[0]) / 100, (gaze[1] - (shoulder[1] - 20)) / 100
            length = max(1.0, math.hypot(gx, gy))
            desired = (gx / length, gy / length)
        look_alpha = -math.expm1(-10 * elapsed)
        self._look = tuple(a + (b - a) * look_alpha for a, b in zip(self._look, desired))
        look_x, look_y = self._look
        head_x = shoulder[0] + look_x * 2.8
        head_y = shoulder[1] - 20 + look_y * 1.8
        coordinates = {
            "body": (head_x, head_y + 14, *shoulder, *hip),
            "head": (head_x - 14.5, head_y - 14.5, head_x + 14.5, head_y + 14.5),
        }
        for name, start, target_name, length, bend in (
            ("leg1", hip, "foot1", self.LEG_LENGTH, -facing),
            ("leg2", hip, "foot2", self.LEG_LENGTH, -facing),
            ("arm1", shoulder, "hand1", self.ARM_LENGTH, -facing),
            ("arm2", shoulder, "hand2", self.ARM_LENGTH, facing),
        ):
            endpoint = (x + pose[target_name][0], y + pose[target_name][1])
            joint, endpoint = solve_two_bone(start, endpoint, length, length, bend)
            coordinates[name] = (*start, *joint, *endpoint)
        blink = 0.45 if phase % 4.7 < 0.12 else 1.8
        for index, name in enumerate(("eye1", "eye2")):
            side = -1 if index == 0 else 1
            eye_x = head_x + side * 4.3 + look_x * 4
            eye_y = head_y + look_y * 3 + side * look_x * 0.65
            coordinates[name] = (eye_x - 1.4, eye_y - blink, eye_x + 1.4, eye_y + blink)
        for name, values in coordinates.items():
            self.canvas.coords(self.parts[name], *values)
        self._last_x, self._last_phase, self._last_mode = x, phase, mode


@dataclass
class _Particle:
    item: int
    x: float
    y: float
    vx: float
    vy: float
    ttl: float
    lifetime: float


class Particles:
    """Bounded sparks whose Canvas items are recycled between bursts."""

    def __init__(self, canvas, max_count: int = 120) -> None:
        if not isinstance(max_count, int) or isinstance(max_count, bool) or max_count < 0:
            raise ValueError("Particle limit must be a non-negative integer.")
        self.canvas = canvas
        self.max_count = max_count
        self.particles: list[_Particle] = []
        self._free_items: list[int] = []
        self._allocated: set[int] = set()
        self._closed = False

    @property
    def allocated_count(self) -> int:
        return len(self._allocated)

    def burst(self, x: float, y: float, color: str = "#ffe600", count: int = 12) -> None:
        if not all(math.isfinite(value) for value in (x, y)):
            raise ValueError("Particle coordinates must be finite.")
        if self._closed:
            return
        for _ in range(max(0, min(count, self.max_count - len(self.particles)))):
            vx, vy = random.uniform(-130, 130), random.uniform(-180, 25)
            lifetime = random.uniform(0.25, 0.6)
            coordinates = (x, y, x + vx * 0.025, y + vy * 0.025)
            if self._free_items:
                item = self._free_items[-1]
                self.canvas.itemconfigure(item, fill=color, width=2.2, state="normal")
                self.canvas.coords(item, *coordinates)
                self._free_items.pop()
            else:
                item = self.canvas.create_line(
                    *coordinates, fill=color, width=2.2, state="normal",
                    capstyle="round", tags=("particle",),
                )
                self._allocated.add(item)
            self.particles.append(_Particle(item, x, y, vx, vy, lifetime, lifetime))

    def step(self, dt: float) -> None:
        if not math.isfinite(dt) or dt < 0:
            raise ValueError("Particle time step must be finite and non-negative.")
        if dt == 0 or self._closed:
            return
        alive = []
        for particle in self.particles:
            particle.ttl -= dt
            if particle.ttl <= 0:
                self.canvas.itemconfigure(particle.item, state="hidden")
                self._free_items.append(particle.item)
                continue
            particle.vy += 380 * dt
            particle.x += particle.vx * dt
            particle.y += particle.vy * dt
            self.canvas.coords(particle.item, particle.x, particle.y,
                               particle.x - particle.vx * 0.025,
                               particle.y - particle.vy * 0.025)
            self.canvas.itemconfigure(particle.item, width=max(0.5, 2.2 * particle.ttl / particle.lifetime))
            alive.append(particle)
        self.particles = alive

    def clear(self) -> None:
        """Hide active effects while retaining the bounded pool for reuse."""
        for particle in self.particles:
            self.canvas.itemconfigure(particle.item, state="hidden")
            self._free_items.append(particle.item)
        self.particles.clear()

    def close(self) -> None:
        """Delete all owned Canvas items and permanently close this pool."""
        if self._closed:
            return
        for item in self._allocated:
            self.canvas.delete(item)
        self._allocated.clear()
        self._free_items.clear()
        self.particles.clear()
        self._closed = True
