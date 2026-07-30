"""The shared geometry, colour, and spacing every fileworks icon is built from.

An icon family is not five drawings that look similar. It is one grid, one
stroke weight, one corner radius, and one palette, from which five glyphs are
constructed — which is why this file exists before any of them.

Two constraints drive every number here. The first is the 16-pixel case: a
stroke that is not an integer number of pixels at 16 px turns into a grey smear,
so the grid is chosen to land on whole pixels at 16, 32, 128, 256, 512, and
1024. The second is contrast: every foreground/background pair is measured
against WCAG, and a candidate that fails is not a candidate.
"""

from __future__ import annotations

from dataclasses import dataclass

#: The canvas everything is drawn on. 24 divides evenly into every shipped size
#: (16 is the exception and is handled by the simplified variant below).
CANVAS = 24.0

#: Clear space around the glyph, in canvas units. Icons are viewed beside other
#: icons; without a margin the family reads as louder than its neighbours.
PADDING = 2.0

#: The one stroke weight. At 16 px this is exactly 1 device pixel at 1×.
STROKE = 1.5

#: The one corner radius. Softer than a rounded-rectangle app icon, sharper than
#: a pill — it survives being scaled to 16 px without turning into a circle.
RADIUS = 2.0

#: Sizes the export tooling produces. Below 20 px the simplified glyph is used.
EXPORT_SIZES = (16, 20, 32, 48, 64, 128, 256, 512, 1024)
SIMPLIFY_BELOW = 20

#: Minimum size the family is allowed to be used at. Below this the glyphs stop
#: being distinguishable from one another, which is worse than no icon.
MINIMUM_SIZE = 16


@dataclass(frozen=True)
class Colour:
    """One colour, with the numbers a reviewer can check rather than trust."""

    name: str
    hex: str
    #: What it is for, so a palette entry cannot quietly become decorative.
    role: str

    @property
    def rgb(self) -> tuple[int, int, int]:
        value = self.hex.lstrip("#")
        return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))

    @property
    def relative_luminance(self) -> float:
        """WCAG 2.1 relative luminance."""

        def channel(component: int) -> float:
            fraction = component / 255
            return fraction / 12.92 if fraction <= 0.04045 else ((fraction + 0.055) / 1.055) ** 2.4

        red, green, blue = (channel(component) for component in self.rgb)
        return 0.2126 * red + 0.7152 * green + 0.0722 * blue

    def contrast_with(self, other: Colour) -> float:
        lighter = max(self.relative_luminance, other.relative_luminance)
        darker = min(self.relative_luminance, other.relative_luminance)
        return (lighter + 0.05) / (darker + 0.05)


#: Neutrals the glyphs sit on. Not pure black or white: pure black beside a warm
#: orange reads as a hole, and pure white blooms on OLED panels.
INK = Colour("ink", "#14110F", "foreground on light surfaces")
PAPER = Colour("paper", "#FAF7F2", "foreground on dark surfaces, light background")
SLATE = Colour("slate", "#1C1917", "dark background")
MUTED = Colour("muted", "#78716C", "secondary strokes, disabled states")

#: Restrained warm oranges. Each is a real candidate, and each carries the
#: measurements that decide whether it may be used as a foreground at all.
ORANGE_CANDIDATES: tuple[Colour, ...] = (
    Colour("ember", "#C2410C", "warm, low-chroma; the most restrained candidate"),
    Colour("amber", "#D97706", "warmer and lighter; reads gold at small sizes"),
    Colour("clay", "#B45309", "earthy and darkest; strongest on light surfaces"),
)

#: CMYK approximations for print, measured rather than converted naively. These
#: are the values a printer should be given; the sRGB hex above is authoritative
#: for screen.
PRINT_VALUES: dict[str, tuple[int, int, int, int]] = {
    "ember": (0, 78, 96, 24),
    "amber": (0, 66, 100, 15),
    "clay": (0, 71, 100, 29),
}


@dataclass(frozen=True)
class ContrastResult:
    """One measured pair, and whether it may be used."""

    foreground: str
    background: str
    ratio: float

    @property
    def passes_ui(self) -> bool:
        """WCAG 2.1 non-text contrast: 3:1 for interface components."""
        return self.ratio >= 3.0

    @property
    def passes_text(self) -> bool:
        return self.ratio >= 4.5

    def describe(self) -> str:
        verdict = "ok" if self.passes_ui else "FAILS"
        return f"{self.foreground} on {self.background}: {self.ratio:.2f}:1 ({verdict})"


def measure(
    colour: Colour, backgrounds: tuple[Colour, ...] = (PAPER, SLATE)
) -> list[ContrastResult]:
    return [
        ContrastResult(colour.name, background.name, colour.contrast_with(background))
        for background in backgrounds
    ]


def usable_on(colour: Colour, background: Colour) -> bool:
    """Whether this colour may carry a glyph on that surface."""
    return colour.contrast_with(background) >= 3.0


@dataclass(frozen=True)
class Palette:
    """One resolved palette: a mode, its surface, and what sits on it."""

    mode: str
    background: Colour
    foreground: Colour
    accent: Colour

    @property
    def accessible(self) -> bool:
        return usable_on(self.foreground, self.background) and usable_on(
            self.accent, self.background
        )


def palettes(orange: Colour) -> tuple[Palette, ...]:
    """The three modes every asset must survive: light, dark, and monochrome.

    Monochrome is not a fallback — taskbars, menu bars, and print all use it, and
    a family that only works in colour is a family that breaks in three places.
    """
    return (
        Palette("light", PAPER, INK, orange),
        Palette("dark", SLATE, PAPER, orange),
        Palette("monochrome-light", PAPER, INK, INK),
        Palette("monochrome-dark", SLATE, PAPER, PAPER),
    )


@dataclass(frozen=True)
class Geometry:
    """The grid every glyph is constructed on."""

    canvas: float = CANVAS
    padding: float = PADDING
    stroke: float = STROKE
    radius: float = RADIUS

    @property
    def inner(self) -> float:
        """The drawable square, once clear space is removed."""
        return self.canvas - self.padding * 2

    def snaps_at(self, size: int) -> bool:
        """Whether the stroke lands on whole device pixels at this size."""
        scaled = self.stroke * size / self.canvas
        return abs(scaled - round(scaled)) < 1e-9

    @property
    def snapping_sizes(self) -> tuple[int, ...]:
        return tuple(size for size in EXPORT_SIZES if self.snaps_at(size))


GEOMETRY = Geometry()

#: The five products, and the idea each glyph has to carry. Naming the *idea*
#: rather than the shape is what keeps three directions comparable.
GLYPHS: dict[str, str] = {
    "media-sorter": "many things becoming ordered",
    "immich-export": "a library opening outward into a tree",
    "paperless-export": "a document leaving a stack",
    "unpacksort": "a container opening into sorted pieces",
    "homebrew-tap": "a tap feeding several outlets",
}

#: Shapes the family must not be mistaken for. Each is a common icon whose
#: meaning would be actively harmful if confused with ours.
CONFUSABLE = ("delete", "upload", "sync", "compression")
