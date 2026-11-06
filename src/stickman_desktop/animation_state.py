"""Animation playback state independent of the renderer and physics clock."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


_MOTION_MODES = frozenset({"idle", "walk", "jump", "fall", "drag"})
_GROUNDED_MODES = frozenset({"idle", "walk"})
_GESTURES = frozenset({"wave", "fight"})


@dataclass(frozen=True)
class AnimationFrame:
    mode: str
    elapsed: float


class AnimationStateMachine:
    """Select a pose and track seconds spent in it for one character."""

    def __init__(self) -> None:
        self._frame: AnimationFrame | None = None
        self._gesture_until: float | None = None

    def update(
        self,
        motion_mode: str,
        now: float,
        dt: float,
        *,
        pose: str | None = None,
        pose_until: float = 0,
    ) -> AnimationFrame:
        """Resolve the current mode and restart playback when it changes."""
        if not isfinite(dt) or dt < 0:
            raise ValueError("Animation dt must be finite and non-negative")
        if not isfinite(now) or not isfinite(pose_until):
            raise ValueError("Animation timestamps must be finite")

        mode = motion_mode if motion_mode in _MOTION_MODES else "idle"
        gesture_until = None
        if mode in _GROUNDED_MODES and pose in _GESTURES and now < pose_until:
            mode = pose
            gesture_until = pose_until

        elapsed = 0.0
        if self._frame is not None and self._frame.mode == mode and self._gesture_until == gesture_until:
            elapsed = self._frame.elapsed + dt
            if not isfinite(elapsed):
                raise ValueError("Animation elapsed time exceeds the supported range")

        self._frame = AnimationFrame(mode, elapsed)
        self._gesture_until = gesture_until
        return self._frame
