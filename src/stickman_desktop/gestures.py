"""Estimate a throw from recent pointer motion, independently of frame rate."""
from __future__ import annotations

import math
from collections import deque


class PointerVelocity:
    WINDOW = 0.08
    STALE = 0.12

    def __init__(self) -> None:
        self.samples: deque[tuple[float, float, float]] = deque(maxlen=32)

    def record(self, now: float, x: float, y: float) -> None:
        if not all(math.isfinite(value) for value in (now, x, y)):
            return
        if self.samples and now < self.samples[-1][0]:
            self.samples.clear()
        if self.samples and now == self.samples[-1][0]:
            self.samples[-1] = (now, x, y)
        else:
            self.samples.append((now, x, y))

    def velocity(self, now: float) -> tuple[float, float]:
        if not self.samples or now - self.samples[-1][0] > self.STALE:
            return 0.0, 0.0
        recent = [sample for sample in self.samples if sample[0] >= now - self.WINDOW]
        if len(recent) < 2:
            return 0.0, 0.0
        # Least-squares slope reduces noisy individual motion events. Center time
        # on the first sample to retain precision with long monotonic clocks.
        start = recent[0][0]
        times = [sample[0] - start for sample in recent]
        mean_t = sum(times) / len(times)
        variance = sum((t - mean_t) ** 2 for t in times)
        if variance < 1e-10:
            return 0.0, 0.0
        return tuple(
            sum((t - mean_t) * sample[axis] for t, sample in zip(times, recent)) / variance
            for axis in (1, 2)
        )
