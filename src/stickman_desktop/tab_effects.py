"""Rotating browser-tab props and physical fragments drawn on the overlay."""

from __future__ import annotations

import math
import random
import unicodedata
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .duel import TabImpact, TabPose


Point = tuple[float, float]
Polygon = tuple[Point, ...]

TAB_WIDTH = 132
TAB_HEIGHT = 58
_MAX_SHARDS = 48
_GRAVITY = 900.0
_FONT = ("Consolas", -10, "bold")
_TITLE_LEFT = -45.0
_TITLE_Y = -20.0
_CELL_WIDTH = 6.0

_BODY: Polygon = ((-61, -29), (61, -29), (66, -24), (66, 24),
                  (61, 29), (-61, 29), (-66, 24), (-66, -24))


def _rect(left: float, top: float, right: float, bottom: float) -> Polygon:
    return ((left, top), (right, top), (right, bottom), (left, bottom))


def _edges(points: Polygon):
    return zip(points, points[1:] + points[:1])


def _area(points: Polygon) -> float:
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in _edges(points))) / 2


def _centroid(points: Polygon) -> Point:
    weighted = [(x1 + x2, y1 + y2, x1 * y2 - x2 * y1)
                for (x1, y1), (x2, y2) in _edges(points)]
    scale = 3 * sum(cross for _, _, cross in weighted)
    return (sum(x * cross for x, _, cross in weighted) / scale,
            sum(y * cross for _, y, cross in weighted) / scale)


def _half_plane(points: Polygon, nx: float, ny: float, cut: float) -> Polygon:
    result = []
    for start, end in _edges(points):
        a = nx * start[0] + ny * start[1] - cut
        b = nx * end[0] + ny * end[1] - cut
        if a <= 0:
            result.append(start)
        if (a < 0 < b) or (b < 0 < a):
            ratio = a / (a - b)
            result.append((start[0] + (end[0] - start[0]) * ratio,
                           start[1] + (end[1] - start[1]) * ratio))
    return tuple(result)


def _clip(points: Polygon, boundary: Polygon) -> Polygon:
    for (x1, y1), (x2, y2) in _edges(boundary):
        nx, ny = y2 - y1, x1 - x2
        points = _half_plane(points, nx, ny, nx * x1 + ny * y1)
        if len(points) < 3:
            return ()
    return points


def _fragment_polygons(count: int) -> tuple[Polygon, ...]:
    """Partition the actual bevelled outline with balanced, angled cuts."""
    if type(count) is not int or not 2 <= count <= 24:
        raise ValueError("A aba deve quebrar em 2 a 24 fragmentos.")
    pieces = [_BODY]
    for step in range(count - 1):
        index = max(range(len(pieces)), key=lambda i: _area(pieces[i]))
        piece = pieces.pop(index)
        xs, ys = zip(*piece)
        axis = 0 if max(xs) - min(xs) >= max(ys) - min(ys) else math.pi / 2
        angle = axis + math.sin(0.9 + step * 2.4) * 0.46
        nx, ny = math.cos(angle), math.sin(angle)
        projections = [nx * x + ny * y for x, y in piece]
        cut = (min(projections) + max(projections)) / 2
        pieces.extend((_half_plane(piece, nx, ny, cut), _half_plane(piece, -nx, -ny, -cut)))
    return tuple(pieces)


def _title_cells(title: str) -> tuple[tuple[str, float, float], ...]:
    # Strip control characters from desktop window titles and fit the label in chrome.
    clean = " ".join("".join(c if c.isprintable() else " " for c in title[:256]).split()) or "Aba ativa"
    widths = [2 if unicodedata.east_asian_width(char) in {"F", "W"} else 1 for char in clean]
    remaining = 15
    x = _TITLE_LEFT
    cells = []
    for char, width in zip(clean, widths):
        if width > remaining:
            break
        right = x + width * _CELL_WIDTH
        cells.append((char, x, right))
        remaining -= width
        x = right
    if len(cells) < len(clean) and cells:
        _, left, _ = cells[-1]
        cells[-1] = ("…", left, left + _CELL_WIDTH)
    return tuple(cells)


def _label_in_piece(title: str, boundary: Polygon) -> tuple[str, Point]:
    best: list[tuple[str, float, float]] = []
    run: list[tuple[str, float, float]] = []
    for cell in _title_cells(title):
        _, left, right = cell
        box = _rect(left, _TITLE_Y - 6, right, _TITLE_Y + 6)
        if math.isclose(_area(_clip(box, boundary)), _area(box), abs_tol=1e-6):
            run.append(cell)
            if len(run) > len(best):
                best = run.copy()
        else:
            run.clear()
    if not best:
        return "", (0, 0)
    return "".join(char for char, _, _ in best), (best[0][1], _TITLE_Y)


@dataclass(frozen=True)
class _Layer:
    polygon: Polygon
    fill: str
    outline: str = ""
    width: float = 1
    pulse: str = ""


def _layers(boundary: Polygon, owner: int) -> tuple[_Layer, ...]:
    accent, tab = ("#49e2c4", "#24536d") if owner == 0 else ("#dfacff", "#58417d")
    layers = [
        _Layer(tuple((x + 4, y + 5) for x, y in boundary), "#293449", "#17202e"),
        _Layer(boundary, "#e5eef2", "#17202e", 2),
    ]
    details = (
        _Layer(_rect(-65, -28, 65, -10), "#223147"),
        _Layer(((-59, -26), (48, -26), (56, -11), (-59, -11)), tab),
        _Layer(_rect(-55, -24, -48, -17), accent),
        _Layer(_rect(58, -23, 62, -19), "#8191a6"),
        _Layer(_rect(-63, -11, 63, -9), accent),
        _Layer(_rect(-52, -2, 14, 3), "#617c93"),
        _Layer(_rect(-52, 8, 4, 11), "#9eb2c3"),
        _Layer(_rect(-52, 16, -13, 19), "#9eb2c3"),
        _Layer(_rect(23, -3, 52, 20), "#b8cbd8"),
        _Layer(_rect(28, 14, 47, 17), "#558c94", pulse=accent),
        _Layer(_rect(-52, 23, 1, 25), "#7896a6", pulse=accent),
    )
    for detail in details:
        region = _clip(detail.polygon, boundary)
        if _area(region) >= 1:
            layers.append(_Layer(region, detail.fill, pulse=detail.pulse))
    return tuple(layers)


@dataclass
class _Paint:
    item: int
    polygon: Polygon
    fill: str
    pulse: str
    current_fill: str


class _Drawing:
    def __init__(self, canvas, shape: Polygon, origin: Point, owner: int, title: str,
                 tag: str) -> None:
        self.canvas = canvas
        self.layers = []
        ox, oy = origin
        self.outline = tuple((x - ox, y - oy) for x, y in shape)
        tags = ("duel_tab_effect", tag)
        for layer in _layers(shape, owner):
            polygon = tuple((x - ox, y - oy) for x, y in layer.polygon)
            item = canvas.create_polygon(*_flatten(polygon), fill=layer.fill, outline=layer.outline,
                                         width=layer.width, joinstyle="round", tags=tags, state="hidden")
            self.layers.append(_Paint(item, polygon, layer.fill, layer.pulse, layer.fill))
        text, (tx, ty) = _label_in_piece(title, shape)
        self.text_position = (tx - ox, ty - oy)
        self.label = canvas.create_text(0, 0, text=text, fill="#f4fbff", anchor="w",
                                        font=_FONT, tags=tags, state="hidden") if text else None
        self.visible = False

    def draw(self, x: float, y: float, angle: float, activity: float) -> None:
        angle %= math.tau
        cos_angle, sin_angle = math.cos(angle), math.sin(angle)

        def transform(point: Point) -> Point:
            px, py = point
            return x + px * cos_angle - py * sin_angle, y + px * sin_angle + py * cos_angle

        for paint in self.layers:
            self.canvas.coords(paint.item, *_flatten(transform(point) for point in paint.polygon))
        if self.label is not None:
            self.canvas.coords(self.label, *transform(self.text_position))
            self.canvas.itemconfigure(self.label, angle=-math.degrees(angle) % 360)
        self.pulse(activity)
        self.show(True)

    def pulse(self, activity: float) -> None:
        lit = activity % 0.58 < 0.27
        for paint in self.layers:
            fill = paint.pulse if lit and paint.pulse else paint.fill
            if fill != paint.current_fill:
                self.canvas.itemconfigure(paint.item, fill=fill)
                paint.current_fill = fill

    def bottom_offset(self, angle: float) -> float:
        sin_angle, cos_angle = math.sin(angle), math.cos(angle)
        depth = max(0, 4 * sin_angle + 5 * cos_angle)
        return max(x * sin_angle + y * cos_angle for x, y in self.outline) + depth + 1

    def show(self, visible: bool) -> None:
        if visible != self.visible:
            self.visible = visible
            for item in self._items():
                self.canvas.itemconfigure(item, state="disabled" if visible else "hidden")

    def delete(self) -> None:
        for item in self._items():
            self.canvas.delete(item)

    def _items(self):
        yield from (layer.item for layer in self.layers)
        if self.label is not None:
            yield self.label


def _flatten(points):
    return (coordinate for point in points for coordinate in point)


@dataclass
class _Shard:
    drawing: _Drawing
    x: float
    y: float
    vx: float
    vy: float
    angle: float
    spin: float
    ttl: float
    floor_y: float | None
    age: float = 0
    settled: bool = False

    def advance(self, dt: float) -> None:
        if self.settled:
            self.drawing.pulse(self.age)
            return
        self.x += self.vx * dt
        self.y += self.vy * dt + _GRAVITY * dt * dt / 2
        self.vy += _GRAVITY * dt
        self.angle += self.spin * dt
        if self.floor_y is not None:
            contact_y = self.floor_y - self.drawing.bottom_offset(self.angle)
            if self.y >= contact_y:
                self.y = contact_y
                if self.vy > 85:
                    self.vy *= -0.24
                    self.vx *= 0.52
                    self.spin *= 0.64
                elif self.vy >= 0:
                    self.vy = 0
                    self.vx *= math.exp(-12 * dt)
                    self.spin *= math.exp(-14 * dt)
                    self.settled = abs(self.vx) < 12 and abs(self.spin) < 0.3
        self.drawing.draw(self.x, self.y, self.angle, self.age)


class TabEffects:
    """Own all prop items and release them on scene cancellation or shutdown."""

    def __init__(self, canvas) -> None:
        self.canvas = canvas
        self._tab: _Drawing | None = None
        self._tab_key: tuple[int, str] | None = None
        self._shards: list[_Shard] = []
        self._closed = False

    def render_tab(self, pose: TabPose | None, title: str, activity: float) -> None:
        if self._closed:
            return
        if pose is None:
            if self._tab is not None:
                self._tab.show(False)
            return
        if not all(math.isfinite(value) for value in (pose.x, pose.y, pose.angle, activity)):
            raise ValueError("Posição e tempo da aba devem ser finitos.")
        key = (pose.owner, title)
        if self._tab_key != key:
            if self._tab is not None:
                self._tab.delete()
            self._tab = _Drawing(self.canvas, _BODY, (0, 0), pose.owner, title, "duel_tab_whole")
            self._tab_key = key
        self._tab.draw(pose.x, pose.y, pose.angle, activity)

    def shatter(self, impact: TabImpact, title: str, *, floor_y: float | None = None) -> None:
        if self._closed:
            return
        if not all(math.isfinite(value) for value in (impact.x, impact.y, impact.angle, impact.vx, impact.vy)):
            raise ValueError("Posição e velocidade do impacto devem ser finitas.")
        if floor_y is not None and not math.isfinite(floor_y):
            raise ValueError("A altura do chão da cena deve ser finita.")
        pieces = _fragment_polygons(impact.fragments)
        if self._tab is not None:
            self._tab.show(False)
        excess = len(self._shards) + len(pieces) - _MAX_SHARDS
        if excess > 0:
            for shard in self._shards[:excess]:
                shard.drawing.delete()
            del self._shards[:excess]

        rng = random.Random(f"{impact.owner}:{impact.fragments}:{title}")
        cos_angle, sin_angle = math.cos(impact.angle), math.sin(impact.angle)
        incoming_x = max(-1600, min(1600, impact.vx))
        incoming_y = max(-1000, min(1000, impact.vy))
        for piece in pieces:
            cx, cy = _centroid(piece)
            dx, dy = cx * cos_angle - cy * sin_angle, cx * sin_angle + cy * cos_angle
            size = math.sqrt(_area(piece) / (TAB_WIDTH * TAB_HEIGHT))
            spread = 1.25 - size / 2
            vx = incoming_x * 0.25 + dx * 3.2 * spread + rng.uniform(-80, 80)
            vy = incoming_y * 0.18 + dy * 2.7 * spread - rng.uniform(110, 240)
            spin = rng.choice((-1, 1)) * rng.uniform(2, 8) * spread
            drawing = _Drawing(self.canvas, piece, (cx, cy), impact.owner, title, "duel_tab_shard")
            lifetime = rng.uniform(1.75, 2.25) if floor_y is not None else rng.uniform(0.95, 1.25)
            y = impact.y + dy
            if floor_y is not None:
                y = min(y, floor_y - drawing.bottom_offset(impact.angle))
            shard = _Shard(drawing, impact.x + dx, y, vx, vy, impact.angle, spin, lifetime, floor_y)
            self._shards.append(shard)
            drawing.draw(shard.x, shard.y, shard.angle, 0)

    def step(self, dt: float) -> None:
        if self._closed:
            return
        if not math.isfinite(dt) or dt < 0:
            raise ValueError("Tempo do efeito deve ser finito e não negativo.")
        survivors = []
        for shard in self._shards:
            shard.age += dt
            if shard.age >= shard.ttl:
                shard.drawing.delete()
                continue
            shard.advance(dt)
            survivors.append(shard)
        self._shards = survivors

    def clear(self) -> None:
        if self._tab is not None:
            self._tab.delete()
            self._tab = None
            self._tab_key = None
        for shard in self._shards:
            shard.drawing.delete()
        self._shards.clear()

    def close(self) -> None:
        self.clear()
        self._closed = True
