"""Measuring whether five glyphs actually look different from each other.

"More distinct silhouettes" is the kind of claim a design review can argue about
forever. This turns it into a number: each glyph's strokes are sampled onto a
coarse grid, and the families are compared on how much their five occupancy
patterns differ pairwise.

It is deliberately coarse. A fine grid would measure detail, and detail is not
what tells icons apart in a taskbar — the overall distribution of ink is. The
grid is therefore about the resolution of a squint, which is the test that
matters.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import combinations

from maintenance.identity.directions import Direction, Glyph
from maintenance.identity.tokens import CANVAS

#: Cells per side. Six is roughly what survives being scaled to 16 px.
GRID = 6

#: Points sampled along each straight segment, so a long edge contributes along
#: its length rather than only at its endpoints.
SAMPLES = 12

_COMMAND = re.compile(r"([MLHVAZ])([^MLHVAZ]*)", re.IGNORECASE)
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def _points(path: str) -> list[tuple[float, float]]:
    """Approximate a path as points. Arcs contribute their endpoint only.

    Curvature is ignored on purpose: at the resolution this measures, an arc and
    the chord across it occupy the same cells.
    """
    points: list[tuple[float, float]] = []
    x = y = 0.0
    start = (0.0, 0.0)

    for command, raw in _COMMAND.findall(path):
        numbers = [float(value) for value in _NUMBER.findall(raw)]
        letter = command.upper()

        if letter == "M" and len(numbers) >= 2:
            x, y = numbers[0], numbers[1]
            start = (x, y)
            points.append((x, y))
        elif letter == "L":
            for index in range(0, len(numbers) - 1, 2):
                points.extend(_interpolate((x, y), (numbers[index], numbers[index + 1])))
                x, y = numbers[index], numbers[index + 1]
        elif letter == "H":
            for value in numbers:
                points.extend(_interpolate((x, y), (value, y)))
                x = value
        elif letter == "V":
            for value in numbers:
                points.extend(_interpolate((x, y), (x, value)))
                y = value
        elif letter == "A" and len(numbers) >= 7:
            for index in range(0, len(numbers) - 6, 7):
                target = (numbers[index + 5], numbers[index + 6])
                points.extend(_interpolate((x, y), target))
                x, y = target
        elif letter == "Z":
            points.extend(_interpolate((x, y), start))
            x, y = start

    return points


def _interpolate(
    origin: tuple[float, float], target: tuple[float, float]
) -> list[tuple[float, float]]:
    return [
        (
            origin[0] + (target[0] - origin[0]) * step / SAMPLES,
            origin[1] + (target[1] - origin[1]) * step / SAMPLES,
        )
        for step in range(SAMPLES + 1)
    ]


def occupancy(
    glyph: Glyph, *, include_accents: bool = True, grid: int = GRID
) -> frozenset[tuple[int, int]]:
    """Which grid cells this glyph puts ink in."""
    cells: set[tuple[int, int]] = set()
    paths = list(glyph.strokes) + (list(glyph.accents) if include_accents else [])
    for path in paths:
        for x, y in _points(path):
            column = min(grid - 1, max(0, int(x / CANVAS * grid)))
            row = min(grid - 1, max(0, int(y / CANVAS * grid)))
            cells.add((column, row))
    return frozenset(cells)


def difference(
    left: Glyph, right: Glyph, *, include_accents: bool = True, grid: int = GRID
) -> float:
    """Jaccard distance between two glyphs' ink. 0 is identical, 1 is disjoint.

    Binary occupancy saturates on detailed glyphs: once a family fills most
    cells, two visually different marks overlap heavily and the number falls
    even though a person tells them apart easily. That is why the caller can ask
    for a finer grid — and why :func:`density_difference` exists.
    """
    a = occupancy(left, include_accents=include_accents, grid=grid)
    b = occupancy(right, include_accents=include_accents, grid=grid)
    union = a | b
    if not union:
        return 0.0
    return 1.0 - len(a & b) / len(union)


def density(
    glyph: Glyph, *, include_accents: bool = True, grid: int = GRID
) -> dict[tuple[int, int], float]:
    """How much ink lands in each cell, normalised to sum to one.

    Occupancy asks *whether* a cell has ink; this asks *how much*. For a dense
    family that is the difference between "both glyphs touch this cell" and
    "one glyph barely clips it while the other fills it".
    """
    counts: dict[tuple[int, int], float] = {}
    paths = list(glyph.strokes) + (list(glyph.accents) if include_accents else [])
    total = 0
    for path in paths:
        for x, y in _points(path):
            column = min(grid - 1, max(0, int(x / CANVAS * grid)))
            row = min(grid - 1, max(0, int(y / CANVAS * grid)))
            counts[(column, row)] = counts.get((column, row), 0.0) + 1.0
            total += 1
    if total == 0:
        return {}
    return {cell: value / total for cell, value in counts.items()}


def density_difference(
    left: Glyph, right: Glyph, *, include_accents: bool = True, grid: int = GRID
) -> float:
    """Half the total-variation distance between two glyphs' ink distributions.

    Zero means the ink is spread identically; one means they share no ink at
    all. Unlike occupancy it does not saturate, so it stays meaningful for the
    detailed families.
    """
    a = density(left, include_accents=include_accents, grid=grid)
    b = density(right, include_accents=include_accents, grid=grid)
    if not a and not b:
        return 0.0
    cells = set(a) | set(b)
    return sum(abs(a.get(cell, 0.0) - b.get(cell, 0.0)) for cell in cells) / 2


@dataclass(frozen=True)
class Distinctness:
    """How far apart one family's glyphs are, by two independent measures."""

    direction: str
    silhouette_mean: float
    silhouette_worst: float
    with_accents_mean: float
    closest_pair: tuple[str, str]
    #: Ink-distribution distance, which does not saturate on detailed families.
    density_mean: float = 0.0
    density_worst: float = 0.0

    @property
    def summary(self) -> str:
        return (
            f"{self.direction}: silhouettes differ by {self.silhouette_mean:.0%} on average "
            f"({self.silhouette_worst:.0%} for the closest pair, "
            f"{self.closest_pair[0]} and {self.closest_pair[1]}); "
            f"{self.with_accents_mean:.0%} once accents are drawn; "
            f"ink distribution differs by {self.density_mean:.0%}"
        )


def measure(direction: Direction) -> Distinctness:
    """Measure one family.

    The silhouette-only figure is the one that matters for the complaint this
    was built to answer: it ignores accents, so it says whether the containers
    themselves are told apart.
    """
    names = list(direction.glyphs)
    silhouette: list[tuple[float, tuple[str, str]]] = []
    accented: list[float] = []

    for left, right in combinations(names, 2):
        pair = (left, right)
        silhouette.append(
            (
                difference(direction.glyph(left), direction.glyph(right), include_accents=False),
                pair,
            )
        )
        accented.append(difference(direction.glyph(left), direction.glyph(right)))

    densities = [
        density_difference(direction.glyph(left), direction.glyph(right))
        for left, right in combinations(names, 2)
    ]
    worst, closest = min(silhouette, key=lambda item: item[0])
    return Distinctness(
        direction=direction.key,
        silhouette_mean=sum(value for value, _pair in silhouette) / len(silhouette),
        silhouette_worst=worst,
        with_accents_mean=sum(accented) / len(accented),
        closest_pair=closest,
        density_mean=sum(densities) / len(densities),
        density_worst=min(densities),
    )


def ranked(directions: tuple[Direction, ...]) -> list[Distinctness]:
    """Every family, most distinct silhouettes first."""
    return sorted(
        (measure(direction) for direction in directions),
        key=lambda item: item.silhouette_mean,
        reverse=True,
    )
