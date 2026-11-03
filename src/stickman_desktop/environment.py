"""Convert desktop metadata into the character's local, visual playground."""
from __future__ import annotations

from .motion import Surface
from .windows import MonitorInfo, WindowInfo


def virtual_bounds(monitors: list[MonitorInfo]) -> tuple[int, int, int, int]:
    if not monitors:
        raise ValueError("At least one monitor is required")
    return (
        min(m.rect[0] for m in monitors), min(m.rect[1] for m in monitors),
        max(m.rect[2] for m in monitors), max(m.rect[3] for m in monitors),
    )


def nearest_monitor(monitors: list[MonitorInfo], x: float, y: float) -> MonitorInfo:
    def distance(monitor: MonitorInfo) -> float:
        left, top, right, bottom = monitor.work_rect
        return (x - max(left, min(right, x))) ** 2 + (y - max(top, min(bottom, y))) ** 2
    return min(monitors, key=distance)


def desktop_surfaces(
    monitors: list[MonitorInfo], windows: list[WindowInfo],
    origin: tuple[int, int], ground_offset: float = 72,
    support_key: str | None = None, character_x: float | None = None,
) -> list[Surface]:
    """Use work areas for floors and exposed top edges for window platforms.

    Windows arrive in Z order, so higher windows can cover lower top edges.
    One usable segment per window keeps the platform's identity stable.
    """
    ox, oy = origin
    result = []
    for monitor in monitors:
        left, top, right, bottom = monitor.work_rect
        result.append(Surface(
            f"monitor:{monitor.rect}", left - ox, right - ox,
            max(top + 104, bottom - ground_offset) - oy, "floor",
        ))
    for index, window in enumerate(windows):
        left, top, right, _bottom = window.rect
        key = f"window:{window.hwnd}"
        segments: list[tuple[float, float]] = []
        for monitor in monitors:
            ml, mt, mr, mb = monitor.work_rect
            if not mt + 104 <= top <= mb - ground_offset - 24:
                continue
            start, end = max(left, ml), min(right, mr)
            candidates = [(start, end)] if end - start >= 80 else []
            for higher in windows[:index]:
                hl, ht, hr, hb = higher.rect
                if ht <= top < hb:
                    exposed = []
                    for a, b in candidates:
                        if hr <= a or hl >= b:
                            exposed.append((a, b))
                        else:
                            if hl - a >= 80:
                                exposed.append((a, min(b, hl)))
                            if b - hr >= 80:
                                exposed.append((max(a, hr), b))
                    candidates = exposed
            segments.extend(candidates)
        if not segments:
            continue
        merged: list[tuple[float, float]] = []
        for a, b in sorted(segments):
            if merged and a <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], b))
            else:
                merged.append((a, b))
        segments = merged
        preferred = [segment for segment in segments if (
            key == support_key and character_x is not None
            and segment[0] + 24 <= character_x + ox <= segment[1] - 24
        )]
        a, b = max(preferred or segments, key=lambda segment: segment[1] - segment[0])
        result.append(Surface(key, a - ox, b - ox, top - oy))
    return result
