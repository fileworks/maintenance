"""Deterministic export: the same sources always produce the same bytes.

Every asset is generated from `tokens` and `directions`, never hand-edited. That
is what makes the manifest meaningful — a checksum only proves something if the
thing it covers can be regenerated and compared.

Determinism is not incidental here. Paths are formatted to two decimals, keys
are emitted in a fixed order, and nothing carries a timestamp, so re-running the
export on an unchanged source produces byte-identical files and a clean diff.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from maintenance.identity.directions import DIRECTION_BY_KEY, Direction, Glyph
from maintenance.identity.tokens import (
    CANVAS,
    EXPORT_SIZES,
    GEOMETRY,
    MINIMUM_SIZE,
    ORANGE_CANDIDATES,
    PADDING,
    Colour,
    Palette,
    palettes,
    usable_on,
)

SIMPLIFY_BELOW = 20


@dataclass(frozen=True)
class Asset:
    """One exported file and the checksum that proves it was not hand-edited."""

    path: str
    kind: str
    direction: str
    product: str
    mode: str
    size: int | None
    sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "kind": self.kind,
            "direction": self.direction,
            "product": self.product,
            "mode": self.mode,
            "size": self.size,
            "sha256": self.sha256,
        }


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def render_svg(
    glyph: Glyph,
    palette: Palette,
    *,
    size: int | None = None,
    with_background: bool = True,
) -> str:
    """One glyph, one palette, one size — as a deterministic SVG string.

    Below 20 px the simplified paths are used where a glyph has them: keeping
    the detailed form at 16 px does not preserve detail, it preserves noise.
    """
    simplified = size is not None and size < SIMPLIFY_BELOW and glyph.has_simplification
    strokes = glyph.simplified if simplified else glyph.strokes
    accents = () if simplified else glyph.accents

    dimension = f'width="{size}" height="{size}" ' if size else ""
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" {dimension}'
        f'viewBox="0 0 {CANVAS:g} {CANVAS:g}" role="img" '
        f'aria-label="{glyph.product}">',
        f"  <title>{glyph.product} — {glyph.idea}</title>",
    ]
    if with_background:
        lines.append(
            f'  <rect width="{CANVAS:g}" height="{CANVAS:g}" rx="{GEOMETRY.radius + 2:g}" '
            f'fill="{palette.background.hex}"/>'
        )
    lines.append(
        f'  <g fill="none" stroke-width="{GEOMETRY.stroke:g}" '
        'stroke-linecap="round" stroke-linejoin="round">'
    )
    for path in strokes:
        lines.append(f'    <path d="{path}" stroke="{palette.foreground.hex}"/>')
    for path in accents:
        lines.append(f'    <path d="{path}" stroke="{palette.accent.hex}"/>')
    lines.append("  </g>")
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# Proofs                                                                       #
# --------------------------------------------------------------------------- #


def repository_card(direction: Direction, palette: Palette) -> str:
    """The 1280×640 preview GitHub shows. Five glyphs on one surface."""
    width, height = 1280, 640
    cell = 200
    gap = 40
    total = cell * 5 + gap * 4
    start_x = (width - total) / 2
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="fileworks icon family">',
        f"  <title>fileworks — {direction.name} ({palette.mode})</title>",
        f'  <rect width="{width}" height="{height}" fill="{palette.background.hex}"/>',
    ]
    for index, product in enumerate(direction.glyphs):
        x = start_x + index * (cell + gap)
        y = (height - cell) / 2
        scale = cell / CANVAS
        lines.append(f'  <g transform="translate({x:.1f},{y:.1f}) scale({scale:.4f})">')
        glyph = direction.glyph(product)
        lines.append(
            f'    <g fill="none" stroke-width="{GEOMETRY.stroke:g}" '
            'stroke-linecap="round" stroke-linejoin="round">'
        )
        for path in glyph.strokes:
            lines.append(f'      <path d="{path}" stroke="{palette.foreground.hex}"/>')
        for path in glyph.accents:
            lines.append(f'      <path d="{path}" stroke="{palette.accent.hex}"/>')
        lines.append("    </g>")
        lines.append("  </g>")
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def size_proof(glyph: Glyph, palette: Palette) -> str:
    """The same glyph at every shipped size, on one row, for eyeballing."""
    gap = 16
    width = sum(EXPORT_SIZES[:6]) + gap * 6
    height = max(EXPORT_SIZES[:6]) + gap * 2
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{glyph.product} at every size">',
        f"  <title>{glyph.product} — size proof ({palette.mode})</title>",
        f'  <rect width="{width}" height="{height}" fill="{palette.background.hex}"/>',
    ]
    x = float(gap)
    for size in EXPORT_SIZES[:6]:
        scale = size / CANVAS
        y = (height - size) / 2
        simplified = size < SIMPLIFY_BELOW and glyph.has_simplification
        strokes = glyph.simplified if simplified else glyph.strokes
        accents = () if simplified else glyph.accents
        lines.append(f'  <g transform="translate({x:.1f},{y:.1f}) scale({scale:.4f})">')
        lines.append(
            f'    <g fill="none" stroke-width="{GEOMETRY.stroke:g}" '
            'stroke-linecap="round" stroke-linejoin="round">'
        )
        for path in strokes:
            lines.append(f'      <path d="{path}" stroke="{palette.foreground.hex}"/>')
        for path in accents:
            lines.append(f'      <path d="{path}" stroke="{palette.accent.hex}"/>')
        lines.append("    </g>")
        lines.append("  </g>")
        x += size + gap
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


#: The contexts every candidate family must be proofed in before approval.
PROOF_CONTEXTS = (
    "repository-card",
    "desktop",
    "installer",
    "taskbar",
    "size-proof",
)

#: Nominal sizes each context is judged at.
CONTEXT_SIZES: dict[str, int] = {
    "desktop": 512,
    "installer": 256,
    "taskbar": 32,
}


# --------------------------------------------------------------------------- #
# Export                                                                       #
# --------------------------------------------------------------------------- #


def export_direction(direction: Direction, orange: Colour, out: Path) -> list[Asset]:
    """Write every asset for one direction, and return the manifest entries."""
    assets: list[Asset] = []
    root = out / direction.key
    for palette in palettes(orange):
        if not palette.accessible:
            # A palette whose accent cannot be seen on its own surface is not
            # exported at all — shipping it would be shipping an invisible icon.
            continue
        for product, glyph in direction.glyphs.items():
            for size in EXPORT_SIZES:
                content = render_svg(glyph, palette, size=size)
                path = root / palette.mode / product / f"{product}-{size}.svg"
                assets.append(
                    _write(
                        path,
                        out,
                        content,
                        "icon",
                        direction.key,
                        product,
                        palette.mode,
                        size,
                    )
                )
            master = render_svg(glyph, palette, with_background=False)
            assets.append(
                _write(
                    root / palette.mode / product / f"{product}-master.svg",
                    out,
                    master,
                    "master",
                    direction.key,
                    product,
                    palette.mode,
                    None,
                )
            )
            assets.append(
                _write(
                    root / palette.mode / product / f"{product}-size-proof.svg",
                    out,
                    size_proof(glyph, palette),
                    "proof",
                    direction.key,
                    product,
                    palette.mode,
                    None,
                )
            )
        assets.append(
            _write(
                root / palette.mode / "repository-card.svg",
                out,
                repository_card(direction, palette),
                "proof",
                direction.key,
                "family",
                palette.mode,
                None,
            )
        )
    return assets


def _write(
    path: Path,
    root: Path,
    content: str,
    kind: str,
    direction: str,
    product: str,
    mode: str,
    size: int | None,
) -> Asset:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return Asset(
        # POSIX separators, always. `str()` on a Path yields `\` on Windows, and
        # every lookup against this manifest builds its key with `/`, so a native
        # separator here made all 1,260 assets read as stale on Windows while
        # nothing had actually changed.
        path=path.relative_to(root).as_posix(),
        kind=kind,
        direction=direction,
        product=product,
        mode=mode,
        size=size,
        sha256=_digest(content),
    )


MANIFEST_VERSION = 1


def export_all(out: Path, orange_name: str = "ember") -> dict[str, object]:
    """Export every direction and write the manifest.

    The orange is a *parameter* rather than a constant: choosing it is the
    user's decision, and the export exists so all three can be looked at.
    """
    orange = next(colour for colour in ORANGE_CANDIDATES if colour.name == orange_name)
    if not usable_on(orange, palettes(orange)[0].background):
        raise ValueError(
            f"{orange.name} does not meet 3:1 against the light surface and cannot be exported"
        )
    assets: list[Asset] = []
    for direction in DIRECTION_BY_KEY.values():
        assets.extend(export_direction(direction, orange, out))

    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "orange": {"name": orange.name, "hex": orange.hex},
        "geometry": {
            "canvas": CANVAS,
            "padding": PADDING,
            "stroke": GEOMETRY.stroke,
            "radius": GEOMETRY.radius,
            "minimum_size": MINIMUM_SIZE,
            "simplify_below": SIMPLIFY_BELOW,
        },
        "directions": [
            {
                "key": direction.key,
                "name": direction.name,
                "rule": direction.rule,
                "tradeoff": direction.tradeoff,
            }
            for direction in DIRECTION_BY_KEY.values()
        ],
        "assets": [asset.to_dict() for asset in sorted(assets, key=lambda item: item.path)],
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    return manifest


# --------------------------------------------------------------------------- #
# Validation                                                                   #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class AssetIssue:
    path: str
    kind: str
    detail: str


def validate(out: Path) -> list[AssetIssue]:
    """Check the exported assets against their manifest.

    Three failures matter: an asset that is gone, one whose bytes changed since
    it was exported (which means it was hand-edited), and one the manifest does
    not mention at all (which means it will rot unnoticed).
    """
    manifest_path = out / "manifest.json"
    if not manifest_path.is_file():
        return [AssetIssue("manifest.json", "missing", "no manifest has been exported")]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    issues: list[AssetIssue] = []
    recorded: set[str] = set()
    for entry in manifest.get("assets", []):
        relative = str(entry["path"])
        recorded.add(relative)
        path = out / relative
        if not path.is_file():
            issues.append(AssetIssue(relative, "missing", "listed in the manifest but not present"))
            continue
        actual = _digest(path.read_text(encoding="utf-8"))
        if actual != entry["sha256"]:
            issues.append(
                AssetIssue(relative, "modified", "hand-edited; regenerate it from the sources")
            )

    for path in sorted(out.rglob("*.svg")):
        # Manifest keys are POSIX, so the path found on disk has to be normalised
        # the same way before it is looked up. `str()` here reported every asset
        # on Windows as "present but not in the manifest".
        relative = path.relative_to(out).as_posix()
        if relative not in recorded:
            issues.append(AssetIssue(relative, "unlisted", "present but not in the manifest"))

    return issues


def stale_against_sources(out: Path, orange_name: str = "ember") -> list[AssetIssue]:
    """Whether the exported assets still match what the sources would produce."""
    manifest_path = out / "manifest.json"
    if not manifest_path.is_file():
        return [AssetIssue("manifest.json", "missing", "no manifest has been exported")]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    orange = next(colour for colour in ORANGE_CANDIDATES if colour.name == orange_name)

    expected: dict[str, str] = {}
    for direction in DIRECTION_BY_KEY.values():
        for palette in palettes(orange):
            if not palette.accessible:
                continue
            for product, glyph in direction.glyphs.items():
                for size in EXPORT_SIZES:
                    relative = f"{direction.key}/{palette.mode}/{product}/{product}-{size}.svg"
                    expected[relative] = _digest(render_svg(glyph, palette, size=size))

    issues: list[AssetIssue] = []
    recorded = {str(entry["path"]): str(entry["sha256"]) for entry in manifest.get("assets", [])}
    for relative, digest in expected.items():
        if recorded.get(relative) != digest:
            issues.append(
                AssetIssue(
                    relative,
                    "stale",
                    "the sources have changed since this was exported",
                )
            )
    return issues
