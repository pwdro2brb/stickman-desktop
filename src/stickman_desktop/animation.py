from __future__ import annotations

import math
import random
from dataclasses import dataclass


class CharacterRenderer:
    """A small, original articulated figure anchored at its feet on a Tk canvas."""

    def __init__(self, canvas, color: str, tag: str = "character") -> None:
        self.canvas = canvas
        self.color = color
        self.tag = tag
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

    def set_visible(self, visible: bool) -> None:
        state = "normal" if visible else "hidden"
        for item in self.parts.values():
            self.canvas.itemconfigure(item, state=state)

    def render(self, x: float, y: float, direction: int, mode: str,
               phase: float, vy: float = 0) -> None:
        """Update poses without creating items; phase is a clock in seconds."""
        if not all(math.isfinite(value) for value in (x, y, direction, phase, vy)):
            raise ValueError("Character coordinates and animation time must be finite.")
        facing = 1 if direction >= 0 else -1
        bob = math.sin(phase * 2.4) * 1.3
        lean = math.sin(phase * 1.2) * 0.6
        shoulder_y, hip_y = y - 55 + bob, y - 24 + bob
        arm1 = (x + facing * 14, y - 42 + bob, x + facing * 20, y - 29 + bob)
        arm2 = (x - facing * 12, y - 42 + bob, x - facing * 17, y - 30 + bob)
        leg1 = (x + facing * 9, y - 13, x + facing * 16, y)
        leg2 = (x - facing * 8, y - 12, x - facing * 15, y)

        if mode == "walk":
            stride = math.sin(phase * 10)
            bob = -abs(math.cos(phase * 10)) * 2
            lean = facing * 3
            shoulder_y, hip_y = y - 55 + bob, y - 24 + bob
            arm1 = (x + facing * (10 - stride * 7), y - 43,
                    x - facing * stride * 22, y - 31)
            arm2 = (x - facing * (10 - stride * 7), y - 43,
                    x + facing * stride * 22, y - 32)
            leg1 = (x + facing * (8 + stride * 5), y - 13,
                    x + facing * stride * 20, y - max(0, stride) * 7)
            leg2 = (x - facing * (8 - stride * 5), y - 13,
                    x - facing * stride * 20, y - max(0, -stride) * 7)
        elif mode in {"jump", "fall"}:
            rising = mode == "jump" and vy <= 0
            lean = facing * (3 if rising else -2)
            shoulder_y, hip_y = y - 57, y - 24
            arm1 = (x + facing * 20, y - 66, x + facing * 30, y - (80 if rising else 59))
            arm2 = (x - facing * 19, y - 62, x - facing * 29, y - (72 if rising else 52))
            leg1 = (x + facing * 16, y - 15, x + facing * 10, y - (10 if rising else 0))
            leg2 = (x - facing * 14, y - 12, x - facing * 22, y - (6 if rising else 1))
        elif mode == "drag":
            sway = math.sin(phase * 8) * 6
            lean = sway * 0.4
            shoulder_y, hip_y = y - 56, y - 23
            arm1 = (x + 18, y - 67, x + 11, y - 78)
            arm2 = (x - 18, y - 64, x - 12, y - 76)
            leg1 = (x + 8 + sway, y - 13, x + 12 + sway, y)
            leg2 = (x - 8 - sway, y - 12, x - 12 - sway, y - 3)
        elif mode == "wave":
            arm1 = (x + facing * 23, y - 67,
                    x + facing * (25 + math.sin(phase * 12) * 7), y - 88)
        elif mode == "fight":
            punch = (math.sin(phase * 13) + 1) * 0.5
            lean = facing * 7
            shoulder_y, hip_y = y - 51, y - 21
            arm1 = (x + facing * 25, y - 57, x + facing * (28 + punch * 25), y - 54)
            arm2 = (x + facing * 5, y - 43, x + facing * (12 + (1 - punch) * 20), y - 56)
            leg1 = (x + facing * 17, y - 13, x + facing * 27, y)
            leg2 = (x - facing * 13, y - 10, x - facing * 22, y)

        neck_x = x + lean
        head_x, head_y = x + lean * 1.3, shoulder_y - 24
        coordinates = {
            "body": (neck_x, shoulder_y - 5, x + lean * 0.4, shoulder_y + 14, x, hip_y),
            "arm1": (neck_x, shoulder_y, *arm1),
            "arm2": (neck_x, shoulder_y + 1, *arm2),
            "leg1": (x, hip_y, *leg1),
            "leg2": (x, hip_y, *leg2),
            "head": (head_x - 14.5, head_y - 14.5, head_x + 14.5, head_y + 14.5),
        }
        blink = 0.6 if phase % 4.7 < 0.12 else 2.1
        for index, name in enumerate(("eye1", "eye2")):
            eye_x = head_x + facing * (3 + index * 6)
            coordinates[name] = (eye_x - 1.4, head_y - blink, eye_x + 1.4, head_y + blink)
        for name, values in coordinates.items():
            self.canvas.coords(self.parts[name], *values)


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
    """Short-lived sparks with a hard limit on live canvas objects."""

    def __init__(self, canvas, max_count: int = 120) -> None:
        if max_count < 0:
            raise ValueError("Particle limit must be non-negative.")
        self.canvas = canvas
        self.max_count = max_count
        self.particles: list[_Particle] = []

    def burst(self, x: float, y: float, color: str = "#ffe600", count: int = 12) -> None:
        if not all(math.isfinite(value) for value in (x, y)):
            raise ValueError("Particle coordinates must be finite.")
        for _ in range(max(0, min(count, self.max_count - len(self.particles)))):
            vx, vy = random.uniform(-130, 130), random.uniform(-180, 25)
            lifetime = random.uniform(0.25, 0.6)
            item = self.canvas.create_line(
                x, y, x + vx * 0.025, y + vy * 0.025,
                fill=color, width=2.2, capstyle="round", tags=("particle",),
            )
            self.particles.append(_Particle(item, x, y, vx, vy, lifetime, lifetime))

    def step(self, dt: float) -> None:
        if not math.isfinite(dt) or dt < 0:
            raise ValueError("Particle time step must be finite and non-negative.")
        if dt == 0:
            return
        alive = []
        for particle in self.particles:
            particle.ttl -= dt
            if particle.ttl <= 0:
                self.canvas.delete(particle.item)
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
        for particle in self.particles:
            self.canvas.delete(particle.item)
        self.particles.clear()
