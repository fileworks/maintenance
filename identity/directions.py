"""Three coherent icon-family directions, each with all five glyphs.

A direction is a *construction rule*, not a style adjective. Each one below says
how any glyph in the family is built, and the five glyphs are then derived from
that rule rather than drawn independently — which is what makes them read as one
family and what makes comparing the directions meaningful.

Every path is generated from the shared grid in `tokens`, so the three
directions differ in idea and not in stroke weight, padding, or radius.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from maintenance.identity.tokens import CONFUSABLE, GEOMETRY, GLYPHS

#: Convenience: the drawable box, in canvas units.
LEFT = GEOMETRY.padding
RIGHT = GEOMETRY.canvas - GEOMETRY.padding
TOP = GEOMETRY.padding
BOTTOM = GEOMETRY.canvas - GEOMETRY.padding
MID = GEOMETRY.canvas / 2


@dataclass(frozen=True)
class Glyph:
    """One drawn mark: its paths, and what it is meant to say."""

    product: str
    idea: str
    #: SVG path data for the outline strokes.
    strokes: tuple[str, ...]
    #: Path data filled with the accent colour. Kept separate so monochrome
    #: export can render it as an outline instead of dropping it.
    accents: tuple[str, ...] = ()
    #: A reduced form for sizes below 20 px, where detail becomes noise.
    simplified: tuple[str, ...] = ()

    @property
    def has_simplification(self) -> bool:
        return bool(self.simplified)


@dataclass(frozen=True)
class Direction:
    """One construction rule, and the five glyphs derived from it."""

    key: str
    name: str
    rule: str
    #: What this direction is good at, and what it costs.
    tradeoff: str
    glyphs: dict[str, Glyph]

    def glyph(self, product: str) -> Glyph:
        return self.glyphs[product]


def _rounded_rect(x: float, y: float, width: float, height: float, radius: float) -> str:
    r = min(radius, width / 2, height / 2)
    return (
        f"M{x + r:.2f},{y:.2f} H{x + width - r:.2f} A{r:.2f},{r:.2f} 0 0 1 "
        f"{x + width:.2f},{y + r:.2f} V{y + height - r:.2f} A{r:.2f},{r:.2f} 0 0 1 "
        f"{x + width - r:.2f},{y + height:.2f} H{x + r:.2f} A{r:.2f},{r:.2f} 0 0 1 "
        f"{x:.2f},{y + height - r:.2f} V{y + r:.2f} A{r:.2f},{r:.2f} 0 0 1 {x + r:.2f},{y:.2f} Z"
    )


def _line(x1: float, y1: float, x2: float, y2: float) -> str:
    return f"M{x1:.2f},{y1:.2f} L{x2:.2f},{y2:.2f}"


def _arrow(x: float, y: float, length: float) -> str:
    """A short right-pointing arrow — movement, deliberately not upload."""
    head = 1.6
    return (
        f"M{x:.2f},{y:.2f} H{x + length:.2f} "
        f"M{x + length - head:.2f},{y - head:.2f} L{x + length:.2f},{y:.2f} "
        f"L{x + length - head:.2f},{y + head:.2f}"
    )


# --------------------------------------------------------------------------- #
# Direction A — stacked plates                                                 #
# --------------------------------------------------------------------------- #


def _stacked() -> dict[str, Glyph]:
    """Every glyph is two or three offset plates: things, layered."""

    def plate(dy: float, inset: float) -> str:
        return _rounded_rect(
            LEFT + inset,
            TOP + dy + inset,
            (RIGHT - LEFT) - inset * 2,
            6.0,
            GEOMETRY.radius,
        )

    return {
        "media-sorter": Glyph(
            "media-sorter",
            GLYPHS["media-sorter"],
            (plate(0, 2.0), plate(6.0, 1.0), plate(12.0, 0.0)),
            accents=(_line(LEFT + 3, BOTTOM - 1.5, RIGHT - 3, BOTTOM - 1.5),),
            simplified=(plate(2.0, 1.0), plate(10.0, 0.0)),
        ),
        "immich-export": Glyph(
            "immich-export",
            GLYPHS["immich-export"],
            (plate(0, 1.0), plate(7.0, 0.0)),
            accents=(_arrow(MID - 1, BOTTOM - 2.0, 6.0),),
            simplified=(plate(3.0, 0.0),),
        ),
        "paperless-export": Glyph(
            "paperless-export",
            GLYPHS["paperless-export"],
            (
                plate(0, 3.0),
                _rounded_rect(LEFT, TOP + 6.0, 11.0, 12.0, GEOMETRY.radius),
            ),
            accents=(_arrow(LEFT + 12.5, TOP + 12.0, 5.5),),
            simplified=(_rounded_rect(LEFT + 1, TOP + 2, 12.0, 16.0, GEOMETRY.radius),),
        ),
        "unpacksort": Glyph(
            "unpacksort",
            GLYPHS["unpacksort"],
            (
                _rounded_rect(LEFT, TOP + 5.0, RIGHT - LEFT, 13.0, GEOMETRY.radius),
                _line(LEFT, TOP + 9.0, RIGHT, TOP + 9.0),
            ),
            accents=(
                _line(MID - 3, TOP + 4.0, MID - 6, TOP + 1.5),
                _line(MID, TOP + 3.5, MID, TOP + 1.0),
                _line(MID + 3, TOP + 4.0, MID + 6, TOP + 1.5),
            ),
            simplified=(_rounded_rect(LEFT, TOP + 4.0, RIGHT - LEFT, 14.0, GEOMETRY.radius),),
        ),
        "homebrew-tap": Glyph(
            "homebrew-tap",
            GLYPHS["homebrew-tap"],
            (
                _rounded_rect(LEFT + 2.0, TOP, 12.0, 7.0, GEOMETRY.radius),
                _line(MID, TOP + 7.0, MID, TOP + 11.0),
            ),
            accents=(
                _line(MID - 5, TOP + 11.0, MID + 5, TOP + 11.0),
                _line(MID - 5, TOP + 11.0, MID - 5, BOTTOM - 3.0),
                _line(MID, TOP + 11.0, MID, BOTTOM - 3.0),
                _line(MID + 5, TOP + 11.0, MID + 5, BOTTOM - 3.0),
            ),
            simplified=(
                _rounded_rect(LEFT + 2.0, TOP + 1.0, 12.0, 8.0, GEOMETRY.radius),
                _line(MID, TOP + 9.0, MID, BOTTOM - 3.0),
            ),
        ),
    }


# --------------------------------------------------------------------------- #
# Direction B — apertures                                                      #
# --------------------------------------------------------------------------- #


def _apertures() -> dict[str, Glyph]:
    """Every glyph is one container with an opening: things, made reachable."""
    frame = _rounded_rect(LEFT, TOP, RIGHT - LEFT, BOTTOM - TOP, GEOMETRY.radius + 1)
    return {
        "media-sorter": Glyph(
            "media-sorter",
            GLYPHS["media-sorter"],
            (frame, _line(LEFT + 4, MID, RIGHT - 4, MID)),
            accents=(
                _line(LEFT + 4, MID - 4, RIGHT - 8, MID - 4),
                _line(LEFT + 4, MID + 4, RIGHT - 6, MID + 4),
            ),
            simplified=(frame, _line(LEFT + 4, MID, RIGHT - 4, MID)),
        ),
        "immich-export": Glyph(
            "immich-export",
            GLYPHS["immich-export"],
            (frame, _line(LEFT + 4, MID + 3, MID, MID - 3)),
            accents=(_line(MID, MID - 3, RIGHT - 4, MID + 3),),
            simplified=(frame,),
        ),
        "paperless-export": Glyph(
            "paperless-export",
            GLYPHS["paperless-export"],
            (
                frame,
                _line(LEFT + 4, MID - 3, RIGHT - 4, MID - 3),
                _line(LEFT + 4, MID + 1, RIGHT - 6, MID + 1),
            ),
            accents=(_line(LEFT + 4, MID + 5, MID + 1, MID + 5),),
            simplified=(frame, _line(LEFT + 4, MID, RIGHT - 5, MID)),
        ),
        "unpacksort": Glyph(
            "unpacksort",
            GLYPHS["unpacksort"],
            (frame, _line(LEFT, MID - 2, RIGHT, MID - 2)),
            accents=(
                _line(MID - 3, MID + 2, MID - 3, BOTTOM - 3),
                _line(MID + 3, MID + 2, MID + 3, BOTTOM - 3),
            ),
            simplified=(frame, _line(LEFT, MID - 2, RIGHT, MID - 2)),
        ),
        "homebrew-tap": Glyph(
            "homebrew-tap",
            GLYPHS["homebrew-tap"],
            (frame, _line(MID, TOP + 4, MID, MID)),
            accents=(
                _line(MID - 4, MID, MID + 4, MID),
                _line(MID - 4, MID, MID - 4, BOTTOM - 4),
                _line(MID + 4, MID, MID + 4, BOTTOM - 4),
            ),
            simplified=(frame, _line(MID, TOP + 4, MID, BOTTOM - 4)),
        ),
    }


# --------------------------------------------------------------------------- #
# Direction C — flow marks                                                     #
# --------------------------------------------------------------------------- #


def _flow() -> dict[str, Glyph]:
    """Every glyph is a path with a junction: things, going somewhere on purpose."""
    return {
        "media-sorter": Glyph(
            "media-sorter",
            GLYPHS["media-sorter"],
            (
                _line(LEFT + 2, BOTTOM - 2, MID, MID),
                _line(MID, MID, RIGHT - 2, TOP + 3),
            ),
            accents=(_line(MID, MID, RIGHT - 2, MID + 5),),
            simplified=(_line(LEFT + 2, BOTTOM - 2, RIGHT - 2, TOP + 2),),
        ),
        "immich-export": Glyph(
            "immich-export",
            GLYPHS["immich-export"],
            (_rounded_rect(LEFT, TOP + 3, 10.0, 14.0, GEOMETRY.radius),),
            accents=(_arrow(LEFT + 11, MID, 7.0),),
            simplified=(_rounded_rect(LEFT + 1, TOP + 3, 11.0, 14.0, GEOMETRY.radius),),
        ),
        "paperless-export": Glyph(
            "paperless-export",
            GLYPHS["paperless-export"],
            (
                _rounded_rect(LEFT, TOP, 11.0, 15.0, GEOMETRY.radius),
                _line(LEFT + 2.5, TOP + 4, LEFT + 8.5, TOP + 4),
                _line(LEFT + 2.5, TOP + 7.5, LEFT + 7.0, TOP + 7.5),
            ),
            accents=(_arrow(LEFT + 12.5, TOP + 11, 5.5),),
            simplified=(_rounded_rect(LEFT + 1, TOP + 1, 12.0, 16.0, GEOMETRY.radius),),
        ),
        "unpacksort": Glyph(
            "unpacksort",
            GLYPHS["unpacksort"],
            (_rounded_rect(LEFT + 3, MID - 1, 14.0, 9.0, GEOMETRY.radius),),
            accents=(
                _line(LEFT + 5, MID - 3, LEFT + 3, TOP + 2),
                _line(MID, MID - 3, MID, TOP + 1),
                _line(RIGHT - 5, MID - 3, RIGHT - 3, TOP + 2),
            ),
            simplified=(_rounded_rect(LEFT + 2, MID - 2, 16.0, 10.0, GEOMETRY.radius),),
        ),
        "homebrew-tap": Glyph(
            "homebrew-tap",
            GLYPHS["homebrew-tap"],
            (
                _line(LEFT + 3, TOP + 2, RIGHT - 3, TOP + 2),
                _line(MID, TOP + 2, MID, MID + 2),
                _line(LEFT + 4, MID + 2, RIGHT - 4, MID + 2),
            ),
            accents=(
                _line(LEFT + 4, MID + 2, LEFT + 4, BOTTOM - 3),
                _line(RIGHT - 4, MID + 2, RIGHT - 4, BOTTOM - 3),
            ),
            simplified=(
                _line(MID, TOP + 2, MID, MID + 2),
                _line(LEFT + 4, MID + 2, RIGHT - 4, MID + 2),
            ),
        ),
    }


DIRECTIONS: tuple[Direction, ...] = (
    Direction(
        "stacked",
        "Stacked plates",
        "Offset plates on a shared grid; the accent marks what moves.",
        "Reads as 'many files' instantly and survives 16 px, but the plates make "
        "every glyph horizontal, so the family is wide and a little static.",
        _stacked(),
    ),
    Direction(
        "apertures",
        "Apertures",
        "One rounded container per glyph, opened differently by the accent.",
        "The strongest family resemblance and the best monochrome behaviour; the "
        "cost is that the containers look alike at a glance until the accent is seen.",
        _apertures(),
    ),
    Direction(
        "flow",
        "Flow marks",
        "A path with a junction; the accent is the branch that leaves it.",
        "The most distinctive silhouettes and the clearest sense of direction, but "
        "the thin diagonals are the weakest of the three at 16 px.",
        _flow(),
    ),
)

DIRECTION_BY_KEY = {direction.key: direction for direction in DIRECTIONS}


# --------------------------------------------------------------------------- #
# Confusion                                                                    #
# --------------------------------------------------------------------------- #


Risk = Literal["low", "high"]


@dataclass(frozen=True)
class ConfusionCheck:
    """Whether a glyph could be mistaken for something with another meaning."""

    product: str
    confusable_with: str
    risk: Risk = "low"
    reason: str = ""


#: Signatures of the icons ours must not be mistaken for. A glyph that matches
#: one of these predicates is flagged: mistaking "export" for "delete" is not a
#: cosmetic problem.
_CONFUSION_RULES: dict[str, Callable[[Glyph], bool]] = {
    # A downward arrow into a container is the universal delete/trash gesture.
    "delete": lambda glyph: any("L12.00,22" in path for path in glyph.accents),
    # An upward arrow out of a container is upload.
    "upload": lambda glyph: any(
        "L12.00,2.00" in path or "L12.00,1.00" in path for path in glyph.accents
    ),
    # Two opposed curved arrows are sync.
    "sync": lambda glyph: sum("A" in path for path in glyph.accents) >= 2,
    # Arrows pointing inward at each other are compression.
    "compression": lambda glyph: (
        len(glyph.accents) >= 2 and all("H" in path for path in glyph.accents)
    ),
}


def check_confusion(direction: Direction) -> list[ConfusionCheck]:
    """Every glyph against every shape it must not be mistaken for."""
    results: list[ConfusionCheck] = []
    for product, glyph in direction.glyphs.items():
        for other in CONFUSABLE:
            rule = _CONFUSION_RULES[other]
            hit = rule(glyph)
            results.append(
                ConfusionCheck(
                    product=product,
                    confusable_with=other,
                    risk="high" if hit else "low",
                    reason=(
                        f"the accent reads as a {other} gesture"
                        if hit
                        else f"no {other} gesture present"
                    ),
                )
            )
    return results


def confusion_failures(direction: Direction) -> list[ConfusionCheck]:
    return [check for check in check_confusion(direction) if check.risk == "high"]


# --------------------------------------------------------------------------- #
# Direction D — tabbed folders                                                 #
# --------------------------------------------------------------------------- #


def _tab_folder(tab_x: float, tab_width: float) -> str:
    """A folder whose tab position and width carry the product's identity.

    The tab is what breaks the rectangle. Apertures' one real cost is that five
    containers look alike until the accent is read; moving the tab changes the
    *outer* silhouette, so the glyphs differ before any accent is seen.
    """
    top = TOP + 4.0
    return (
        f"M{LEFT:.2f},{top + 2:.2f} A2.00,2.00 0 0 1 {LEFT + 2:.2f},{top:.2f} "
        f"H{tab_x:.2f} L{tab_x + 1.5:.2f},{TOP + 1.2:.2f} "
        f"H{tab_x + tab_width:.2f} A1.20,1.20 0 0 1 {tab_x + tab_width + 1.2:.2f},{TOP + 2.4:.2f} "
        f"L{tab_x + tab_width + 1.2:.2f},{top:.2f} H{RIGHT - 2:.2f} "
        f"A2.00,2.00 0 0 1 {RIGHT:.2f},{top + 2:.2f} V{BOTTOM - 2:.2f} "
        f"A2.00,2.00 0 0 1 {RIGHT - 2:.2f},{BOTTOM:.2f} H{LEFT + 2:.2f} "
        f"A2.00,2.00 0 0 1 {LEFT:.2f},{BOTTOM - 2:.2f} Z"
    )


def _tabbed() -> dict[str, Glyph]:
    """Every glyph is a folder; the tab says which one, before the accent does."""
    return {
        "media-sorter": Glyph(
            "media-sorter",
            GLYPHS["media-sorter"],
            (
                _tab_folder(LEFT + 2, 7.0),
                _line(LEFT + 3, MID + 1, RIGHT - 3, MID + 1),
            ),
            accents=(_line(LEFT + 4, MID + 4.5, RIGHT - 4, MID + 4.5),),
            simplified=(_tab_folder(LEFT + 2, 7.0),),
        ),
        "immich-export": Glyph(
            "immich-export",
            GLYPHS["immich-export"],
            (
                _tab_folder(MID - 1, 4.0),
                _line(LEFT + 3, MID + 5, MID - 1, MID + 5),
            ),
            accents=(_arrow(MID, MID + 1, 7.0),),
            simplified=(_tab_folder(MID - 1, 4.0),),
        ),
        "paperless-export": Glyph(
            "paperless-export",
            GLYPHS["paperless-export"],
            (
                _tab_folder(RIGHT - 7, 5.0),
                _line(LEFT + 3, MID + 1, MID + 1, MID + 1),
                _line(LEFT + 3, MID + 4, LEFT + 8, MID + 4),
            ),
            accents=(_line(MID + 3, MID + 4, RIGHT - 3, MID + 4),),
            simplified=(_tab_folder(RIGHT - 7, 5.0),),
        ),
        "unpacksort": Glyph(
            "unpacksort",
            GLYPHS["unpacksort"],
            (_tab_folder(LEFT + 2, 13.0), _line(LEFT, MID + 2.5, RIGHT, MID + 2.5)),
            accents=(
                _line(MID - 4, MID + 5, MID - 5.5, BOTTOM - 2),
                _line(MID, MID + 5, MID, BOTTOM - 2.5),
                _line(MID + 4, MID + 5, MID + 5.5, BOTTOM - 2),
            ),
            simplified=(_tab_folder(LEFT + 2, 13.0),),
        ),
        "homebrew-tap": Glyph(
            "homebrew-tap",
            GLYPHS["homebrew-tap"],
            (
                _tab_folder(MID + 2, 3.0),
                _line(MID, MID + 1, MID, MID + 4),
                _line(MID - 4.5, MID + 4, MID + 4.5, MID + 4),
            ),
            accents=(
                _line(MID - 4.5, MID + 4, MID - 4.5, BOTTOM - 2.5),
                _line(MID + 4.5, MID + 4, MID + 4.5, BOTTOM - 2.5),
            ),
            simplified=(
                _tab_folder(MID + 2, 3.0),
                _line(MID, MID + 1, MID, BOTTOM - 2.5),
            ),
        ),
    }


# --------------------------------------------------------------------------- #
# Direction E — cut corners                                                    #
# --------------------------------------------------------------------------- #


def _cut_corner(corner: str) -> str:
    """A container with one corner taken off — the dog-ear, generalised.

    Which corner is cut is the product's mark. A cut reads in monochrome and at
    16 px, where an interior accent does not, so the family stays legible in the
    two places apertures is weakest.
    """
    cut = 6.0
    r = GEOMETRY.radius
    if corner == "tr":
        return (
            f"M{LEFT + r:.2f},{TOP:.2f} H{RIGHT - cut:.2f} L{RIGHT:.2f},{TOP + cut:.2f} "
            f"V{BOTTOM - r:.2f} A{r:.2f},{r:.2f} 0 0 1 {RIGHT - r:.2f},{BOTTOM:.2f} "
            f"H{LEFT + r:.2f} A{r:.2f},{r:.2f} 0 0 1 {LEFT:.2f},{BOTTOM - r:.2f} "
            f"V{TOP + r:.2f} A{r:.2f},{r:.2f} 0 0 1 {LEFT + r:.2f},{TOP:.2f} Z"
        )
    if corner == "br":
        return (
            f"M{LEFT + r:.2f},{TOP:.2f} H{RIGHT - r:.2f} A{r:.2f},{r:.2f} 0 0 1 "
            f"{RIGHT:.2f},{TOP + r:.2f} V{BOTTOM - cut:.2f} L{RIGHT - cut:.2f},{BOTTOM:.2f} "
            f"H{LEFT + r:.2f} A{r:.2f},{r:.2f} 0 0 1 {LEFT:.2f},{BOTTOM - r:.2f} "
            f"V{TOP + r:.2f} A{r:.2f},{r:.2f} 0 0 1 {LEFT + r:.2f},{TOP:.2f} Z"
        )
    if corner == "tl":
        return (
            f"M{LEFT + cut:.2f},{TOP:.2f} H{RIGHT - r:.2f} A{r:.2f},{r:.2f} 0 0 1 "
            f"{RIGHT:.2f},{TOP + r:.2f} V{BOTTOM - r:.2f} A{r:.2f},{r:.2f} 0 0 1 "
            f"{RIGHT - r:.2f},{BOTTOM:.2f} H{LEFT + r:.2f} A{r:.2f},{r:.2f} 0 0 1 "
            f"{LEFT:.2f},{BOTTOM - r:.2f} V{TOP + cut:.2f} Z"
        )
    # Both top corners: a box that has been opened.
    return (
        f"M{LEFT + cut:.2f},{TOP:.2f} H{RIGHT - cut:.2f} L{RIGHT:.2f},{TOP + cut:.2f} "
        f"V{BOTTOM - r:.2f} A{r:.2f},{r:.2f} 0 0 1 {RIGHT - r:.2f},{BOTTOM:.2f} "
        f"H{LEFT + r:.2f} A{r:.2f},{r:.2f} 0 0 1 {LEFT:.2f},{BOTTOM - r:.2f} "
        f"V{TOP + cut:.2f} Z"
    )


def _cut() -> dict[str, Glyph]:
    """Every glyph is a container missing one corner; which corner is the mark."""
    return {
        "media-sorter": Glyph(
            "media-sorter",
            GLYPHS["media-sorter"],
            (_cut_corner("tr"),),
            accents=(
                _line(LEFT + 4, MID, RIGHT - 8, MID),
                _line(LEFT + 4, MID + 4, RIGHT - 4, MID + 4),
            ),
            simplified=(_cut_corner("tr"),),
        ),
        "immich-export": Glyph(
            "immich-export",
            GLYPHS["immich-export"],
            (_cut_corner("br"),),
            accents=(_arrow(LEFT + 5, MID + 1, 8.0),),
            simplified=(_cut_corner("br"),),
        ),
        "paperless-export": Glyph(
            "paperless-export",
            GLYPHS["paperless-export"],
            (
                _cut_corner("tr"),
                _line(RIGHT - 6, TOP, RIGHT - 6, TOP + 6),
                _line(RIGHT - 6, TOP + 6, RIGHT, TOP + 6),
            ),
            accents=(_line(LEFT + 4, MID + 3, MID + 3, MID + 3),),
            simplified=(_cut_corner("tr"),),
        ),
        "unpacksort": Glyph(
            "unpacksort",
            GLYPHS["unpacksort"],
            (_cut_corner("both"),),
            accents=(
                _line(MID - 4, MID - 1, MID - 6, MID - 4),
                _line(MID, MID - 1.5, MID, MID - 5),
                _line(MID + 4, MID - 1, MID + 6, MID - 4),
            ),
            simplified=(_cut_corner("both"),),
        ),
        "homebrew-tap": Glyph(
            "homebrew-tap",
            GLYPHS["homebrew-tap"],
            (_cut_corner("tl"),),
            accents=(
                _line(LEFT + 5, MID - 2, MID + 3, MID - 2),
                _line(MID + 3, MID - 2, MID + 3, MID + 3),
                _line(MID - 2, MID + 3, RIGHT - 4, MID + 3),
            ),
            simplified=(_cut_corner("tl"),),
        ),
    }


# --------------------------------------------------------------------------- #
# Direction F — nested pockets                                                 #
# --------------------------------------------------------------------------- #


def _pocket(depth: float = 9.0) -> str:
    """A deep-radius pocket. The generous curve is where the warmth comes from."""
    top = BOTTOM - depth
    return (
        f"M{LEFT:.2f},{top:.2f} V{BOTTOM - 5:.2f} A5.00,5.00 0 0 0 {LEFT + 5:.2f},{BOTTOM:.2f} "
        f"H{RIGHT - 5:.2f} A5.00,5.00 0 0 0 {RIGHT:.2f},{BOTTOM - 5:.2f} V{top:.2f}"
    )


def _nested() -> dict[str, Glyph]:
    """A pocket holding something; the held shape protrudes and identifies it.

    The silhouette differs above the rim, which is exactly where the eye lands
    first — and a thing held in a pocket is a file metaphor without drawing a
    literal document five times.
    """
    return {
        "media-sorter": Glyph(
            "media-sorter",
            GLYPHS["media-sorter"],
            (
                _pocket(),
                _rounded_rect(LEFT + 3, TOP + 1, 8.0, 8.0, GEOMETRY.radius),
                _rounded_rect(LEFT + 7, TOP + 3, 8.0, 8.0, GEOMETRY.radius),
            ),
            accents=(_line(LEFT + 4, BOTTOM - 3.5, RIGHT - 4, BOTTOM - 3.5),),
            simplified=(
                _pocket(),
                _rounded_rect(LEFT + 5, TOP + 2, 9.0, 9.0, GEOMETRY.radius),
            ),
        ),
        "immich-export": Glyph(
            "immich-export",
            GLYPHS["immich-export"],
            (_pocket(), _rounded_rect(LEFT + 2, TOP, 9.0, 10.0, GEOMETRY.radius)),
            accents=(_arrow(LEFT + 12, TOP + 5, 7.0),),
            simplified=(
                _pocket(),
                _rounded_rect(LEFT + 2, TOP + 1, 9.0, 9.0, GEOMETRY.radius),
            ),
        ),
        "paperless-export": Glyph(
            "paperless-export",
            GLYPHS["paperless-export"],
            (
                _pocket(),
                f"M{LEFT + 5:.2f},{TOP + 10:.2f} V{TOP + 1.5:.2f} "
                f"A1.50,1.50 0 0 1 {LEFT + 6.5:.2f},{TOP:.2f} H{RIGHT - 8:.2f} "
                f"L{RIGHT - 5:.2f},{TOP + 3:.2f} V{TOP + 10:.2f}",
                _line(LEFT + 7, TOP + 4, RIGHT - 8, TOP + 4),
            ),
            accents=(_line(LEFT + 7, TOP + 7, RIGHT - 9, TOP + 7),),
            simplified=(
                _pocket(),
                _rounded_rect(LEFT + 5, TOP, 10.0, 10.0, GEOMETRY.radius),
            ),
        ),
        "unpacksort": Glyph(
            "unpacksort",
            GLYPHS["unpacksort"],
            (_pocket(7.0),),
            accents=(
                # Squared rather than rounded: two curved marks either side of a
                # centre read as the paired arrows of a sync icon, which is not
                # what unpacking means.
                f"M{LEFT + 2.5:.2f},{TOP + 8.5:.2f} V{TOP + 3:.2f} "
                f"H{LEFT + 8:.2f} V{TOP + 8.5:.2f}",
                _line(MID, TOP + 1, MID, TOP + 5),
                f"M{RIGHT - 8:.2f},{TOP + 8.5:.2f} V{TOP + 3:.2f} "
                f"H{RIGHT - 2.5:.2f} V{TOP + 8.5:.2f}",
            ),
            simplified=(_pocket(7.0), _rounded_rect(MID - 4, TOP + 2, 8.0, 7.0, 1.5)),
        ),
        "homebrew-tap": Glyph(
            "homebrew-tap",
            GLYPHS["homebrew-tap"],
            (
                _pocket(7.0),
                f"M{LEFT + 4:.2f},{TOP:.2f} H{MID + 2:.2f} "
                f"A2.00,2.00 0 0 1 {MID + 4:.2f},{TOP + 2:.2f} V{TOP + 4:.2f}",
            ),
            accents=(
                _line(MID + 4, TOP + 4, MID + 4, TOP + 7),
                _line(MID - 3, TOP + 8, MID + 4, TOP + 8),
            ),
            simplified=(_pocket(7.0), _line(MID + 4, TOP, MID + 4, TOP + 8)),
        ),
    }


DIRECTIONS = (
    *DIRECTIONS,
    Direction(
        "tabbed",
        "Tabbed folders",
        "A folder whose tab position and width identify the product; the accent is what it holds.",
        "Keeps the aperture idea but moves the difference to the outer silhouette, so the five "
        "read apart before any accent is seen. The strongest file metaphor of the six, and the "
        "warmest — the tab breaks the rectangle. The cost is that a tab needs a little height, so "
        "the interior is tighter than apertures.",
        _tabbed(),
    ),
    Direction(
        "cut",
        "Cut corners",
        "A container with one corner taken off; which corner is the product's mark.",
        "The cut survives monochrome and 16 px, which is exactly where an interior accent stops "
        "working — so this is the most legible of the six at the small end. The cost is that a "
        "dog-eared rectangle is a well-worn shape, so it is the least distinctive as a family.",
        _cut(),
    ),
    Direction(
        "nested",
        "Nested pockets",
        "A deep pocket holding something; the held shape protrudes above the rim and names it.",
        "The most personality of the six: the deep curve and the protruding contents give the "
        "family a warmth the flat containers do not have, and the silhouette differs above the "
        "rim where the eye lands first. The cost is the most ink — it is the busiest at 16 px.",
        _nested(),
    ),
)

DIRECTION_BY_KEY = {direction.key: direction for direction in DIRECTIONS}


# --------------------------------------------------------------------------- #
# Direction G — apertures with literal contents                                #
# --------------------------------------------------------------------------- #
#
# The Apertures construction, kept exactly, with the abstraction taken out of
# the contents. The container still says "a place things live"; what is inside
# now says which things and where they go — a photo, a document, a folder, a
# file lifted out of a stack, a tap.
#
# The two exporters are deliberately parallel. They are sibling tools that do
# the same thing to different media, so making their glyphs siblings is the
# honest answer rather than a failure of imagination.


def _container(gap: str = "whole") -> str:
    """The shared container, optionally opened where its contents leave.

    The opening is part of the outline rather than a mark inside it, so it
    survives monochrome and small sizes — and it is what the accent points at.
    """
    r = GEOMETRY.radius
    if gap == "right":
        return (
            f"M{RIGHT:.2f},{MID - 3.5:.2f} V{TOP + r:.2f} "
            f"A{r:.2f},{r:.2f} 0 0 0 {RIGHT - r:.2f},{TOP:.2f} H{LEFT + r:.2f} "
            f"A{r:.2f},{r:.2f} 0 0 0 {LEFT:.2f},{TOP + r:.2f} V{BOTTOM - r:.2f} "
            f"A{r:.2f},{r:.2f} 0 0 0 {LEFT + r:.2f},{BOTTOM:.2f} H{RIGHT - r:.2f} "
            f"A{r:.2f},{r:.2f} 0 0 0 {RIGHT:.2f},{BOTTOM - r:.2f} V{MID + 3.5:.2f}"
        )
    if gap == "top":
        return (
            f"M{MID - 4:.2f},{TOP:.2f} H{LEFT + r:.2f} "
            f"A{r:.2f},{r:.2f} 0 0 0 {LEFT:.2f},{TOP + r:.2f} V{BOTTOM - r:.2f} "
            f"A{r:.2f},{r:.2f} 0 0 0 {LEFT + r:.2f},{BOTTOM:.2f} H{RIGHT - r:.2f} "
            f"A{r:.2f},{r:.2f} 0 0 0 {RIGHT:.2f},{BOTTOM - r:.2f} V{TOP + r:.2f} "
            f"A{r:.2f},{r:.2f} 0 0 0 {RIGHT - r:.2f},{TOP:.2f} H{MID + 4:.2f}"
        )
    return _rounded_rect(LEFT, TOP, RIGHT - LEFT, BOTTOM - TOP, r + 1)


def _photo(x: float, y: float, width: float, height: float) -> tuple[str, str]:
    """A picture: a frame, a horizon with a peak, and a sun.

    The peak is what makes it read as a photograph rather than a card, and it is
    a diagonal — which is also what tells it apart from the document at 16 px.
    """
    frame = _rounded_rect(x, y, width, height, 1.2)
    inset = 1.6
    base = y + height - inset
    horizon = (
        f"M{x + inset:.2f},{base:.2f} L{x + width * 0.42:.2f},{y + height * 0.42:.2f} "
        f"L{x + width * 0.62:.2f},{base - height * 0.28:.2f} "
        f"L{x + width * 0.78:.2f},{base - height * 0.5:.2f} "
        f"L{x + width - inset:.2f},{base:.2f}"
    )
    return frame, horizon


def _sun(cx: float, cy: float, radius: float = 0.9) -> str:
    return (
        f"M{cx - radius:.2f},{cy:.2f} A{radius:.2f},{radius:.2f} 0 1 0 {cx + radius:.2f},{cy:.2f} "
        f"A{radius:.2f},{radius:.2f} 0 1 0 {cx - radius:.2f},{cy:.2f}"
    )


def _sheet(x: float, y: float, width: float, height: float) -> tuple[str, tuple[str, ...]]:
    """A document: a page with a turned corner and lines of text on it."""
    fold = 2.6
    page = (
        f"M{x:.2f},{y + 1.2:.2f} A1.20,1.20 0 0 1 {x + 1.2:.2f},{y:.2f} "
        f"H{x + width - fold:.2f} L{x + width:.2f},{y + fold:.2f} "
        f"V{y + height - 1.2:.2f} A1.20,1.20 0 0 1 {x + width - 1.2:.2f},{y + height:.2f} "
        f"H{x + 1.2:.2f} A1.20,1.20 0 0 1 {x:.2f},{y + height - 1.2:.2f} Z"
    )
    corner = f"M{x + width - fold:.2f},{y:.2f} V{y + fold:.2f} H{x + width:.2f}"
    lines = tuple(
        _line(
            x + 1.8,
            y + fold + 1.6 + offset,
            x + width - 1.8 - offset * 0.8,
            y + fold + 1.6 + offset,
        )
        for offset in (0.0, 2.4)
    )
    return page, (corner, *lines)


def _folder_shape(x: float, y: float, width: float, height: float) -> str:
    """A directory: the tab is the whole point, so it is not subtle."""
    tab = width * 0.42
    return (
        f"M{x:.2f},{y + height - 1.5:.2f} V{y + 1.5:.2f} "
        f"A1.50,1.50 0 0 1 {x + 1.5:.2f},{y:.2f} H{x + tab:.2f} "
        f"L{x + tab + 1.6:.2f},{y + 1.8:.2f} H{x + width - 1.5:.2f} "
        f"A1.50,1.50 0 0 1 {x + width:.2f},{y + 3.3:.2f} V{y + height - 1.5:.2f} "
        f"A1.50,1.50 0 0 1 {x + width - 1.5:.2f},{y + height:.2f} H{x + 1.5:.2f} "
        f"A1.50,1.50 0 0 1 {x:.2f},{y + height - 1.5:.2f} Z"
    )


def _literal() -> dict[str, Glyph]:
    photo_frame, horizon = _photo(LEFT + 2.5, MID - 3.5, 11.5, 7.5)
    page, page_details = _sheet(LEFT + 4.5, MID - 6, 8.0, 12.0)
    lifted, lifted_details = _sheet(MID - 3.5, TOP - 1.5, 7.0, 7.5)

    return {
        # A directory, with loose items being filed into it.
        "media-sorter": Glyph(
            "media-sorter",
            GLYPHS["media-sorter"],
            (
                _container("whole"),
                _folder_shape(LEFT + 3.5, MID - 1, 13.0, 8.5),
            ),
            accents=(
                # Squared, not rounded: two curved marks side by side read as
                # the paired arrows of a sync icon, which is not filing.
                f"M{LEFT + 4.5:.2f},{TOP + 5.7:.2f} V{TOP + 2.5:.2f} "
                f"H{LEFT + 8.5:.2f} V{TOP + 5.7:.2f} Z",
                f"M{LEFT + 10:.2f},{TOP + 5.7:.2f} V{TOP + 2.5:.2f} "
                f"H{LEFT + 14:.2f} V{TOP + 5.7:.2f} Z",
                _line(MID + 4.5, TOP + 4.1, RIGHT - 3.5, TOP + 4.1),
            ),
            simplified=(
                _container("whole"),
                _folder_shape(LEFT + 3.5, MID - 2, 13.0, 9.5),
            ),
        ),
        # A picture leaving through the opening.
        "immich-export": Glyph(
            "immich-export",
            GLYPHS["immich-export"],
            (_container("right"), photo_frame, horizon),
            accents=(_sun(LEFT + 10.8, MID - 1.4), _arrow(MID + 3.5, MID, 5.5)),
            simplified=(_container("right"), photo_frame),
        ),
        # A document leaving through the opening — deliberately the exporter's twin.
        "paperless-export": Glyph(
            "paperless-export",
            GLYPHS["paperless-export"],
            (_container("right"), page, *page_details),
            accents=(_arrow(MID + 2.5, MID, 6.0),),
            simplified=(_container("right"), page),
        ),
        # One file lifted clear of the stack it was buried in.
        "unpacksort": Glyph(
            "unpacksort",
            GLYPHS["unpacksort"],
            (
                _container("top"),
                _line(LEFT + 3.5, MID + 3.5, RIGHT - 3.5, MID + 3.5),
                _line(LEFT + 3.5, MID + 6.5, RIGHT - 3.5, MID + 6.5),
            ),
            accents=(lifted, *lifted_details),
            simplified=(
                _container("top"),
                _rounded_rect(MID - 3.5, TOP - 1, 7.0, 7.0, 1.2),
            ),
        ),
        # A tap: the spout the other tools come out of, and a drop under it.
        "homebrew-tap": Glyph(
            "homebrew-tap",
            GLYPHS["homebrew-tap"],
            (
                _container("whole"),
                f"M{LEFT + 3:.2f},{TOP + 4.5:.2f} H{MID + 1:.2f} "
                f"A1.80,1.80 0 0 1 {MID + 2.8:.2f},{TOP + 6.3:.2f} V{TOP + 8.5:.2f}",
                _line(LEFT + 5.5, TOP + 2.5, LEFT + 5.5, TOP + 4.5),
            ),
            accents=(
                f"M{MID + 2.8:.2f},{MID:.2f} L{MID + 4.2:.2f},{MID + 2.4:.2f} "
                f"A1.70,1.70 0 1 1 {MID + 1.4:.2f},{MID + 2.4:.2f} Z",
                _line(LEFT + 4, BOTTOM - 3.5, RIGHT - 4, BOTTOM - 3.5),
            ),
            simplified=(
                _container("whole"),
                f"M{LEFT + 3:.2f},{TOP + 4.5:.2f} H{MID + 1:.2f} "
                f"A1.80,1.80 0 0 1 {MID + 2.8:.2f},{TOP + 6.3:.2f} V{MID:.2f}",
            ),
        ),
    }


DIRECTIONS = (
    *DIRECTIONS,
    Direction(
        "literal",
        "Apertures — literal contents",
        "The Apertures container, with what each tool actually handles drawn inside it.",
        "Every glyph now names its own job: a directory being filed into, a photo and a document "
        "each leaving through an opening, a file lifted clear of a stack, a tap with a drop under "
        "it. The two exporters are twins on purpose — they are sibling tools. The cost is ink: "
        "this is the most detailed family, so the simplified 16 px form drops the contents' "
        "interior and keeps only their outline.",
        _literal(),
    ),
)

DIRECTION_BY_KEY = {direction.key: direction for direction in DIRECTIONS}
