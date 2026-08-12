"""Generate the public GitHub social previews from one semantic template.

The preview copy is product communication, not design-process metadata.  It
therefore states what a repository does, how it is used, and one meaningful
operating property.  Internal direction names and artificial artwork versions
never appear in generated cards.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from html import escape
from pathlib import Path

from PIL import Image

WIDTH = 1280
HEIGHT = 640
BACKGROUND = "#FAF7F2"
SURFACE = "#FFFFFF"
BORDER = "#E6E3E0"
INK = "#14110F"
BODY = "#221E1C"
MUTED = "#655D58"
ACCENT = "#C2410C"
SANS = "Geist Sans,system-ui,sans-serif"
MONO = "Geist Mono,ui-monospace,monospace"

BANNED_PUBLIC_COPY = ("kontur", "version 01", "01 kontur")


@dataclass(frozen=True)
class Fact:
    """One concise, useful property shown in the preview footer."""

    label: str
    value: str
    monospace: bool = False


@dataclass(frozen=True)
class SocialPreview:
    """Public copy for one repository card."""

    repository: str
    product: str
    summary: str
    facts: tuple[Fact, Fact, Fact]


PREVIEWS = (
    SocialPreview(
        repository="media-sorter",
        product="MediaSorter",
        summary="Review duplicates. Organize photos and videos with confidence.",
        facts=(
            Fact("TYPE", "Desktop app"),
            Fact("PLATFORMS", "macOS + Windows"),
            Fact("PRIVACY", "Local-first"),
        ),
    ),
    SocialPreview(
        repository="immich-export",
        product="immich-export",
        summary="Export Immich originals and metadata to a readable local library.",
        facts=(
            Fact("TYPE", "Command-line tool"),
            Fact("INSTALL", "pipx · Homebrew", monospace=True),
            Fact("SOURCE", "Read-only"),
        ),
    ),
    SocialPreview(
        repository="paperless-export",
        product="paperless-export",
        summary="Run reliable Paperless exports and build yearly tax views.",
        facts=(
            Fact("TYPE", "Command-line tool"),
            Fact("INSTALL", "pipx · Homebrew", monospace=True),
            Fact("OUTPUT", "Export + tax view"),
        ),
    ),
    SocialPreview(
        repository="unpacksort",
        product="unpacksort",
        summary="Recover, deduplicate, and sort nested mail and archive content.",
        facts=(
            Fact("TYPE", "Command-line tool"),
            Fact("INSTALL", "pipx · Homebrew", monospace=True),
            Fact("RESULT", "Manifest + report"),
        ),
    ),
    SocialPreview(
        repository="homebrew-tap",
        product="homebrew-tap",
        summary="Official Homebrew formulas for Fileworks command-line tools.",
        facts=(
            Fact("TYPE", "Package repository"),
            Fact("COMMAND", "brew tap fileworks/tap", monospace=True),
            Fact("CONTENT", "3 maintained formulas"),
        ),
    ),
    SocialPreview(
        repository="maintenance",
        product="maintenance",
        summary="Audit repository policy, releases, dependencies, and drift.",
        facts=(
            Fact("TYPE", "Governance tooling"),
            Fact("MODE", "Read-only checks"),
            Fact("SCOPE", "6 repositories"),
        ),
    ),
)


def _icon_body(icon_svg: str) -> str:
    """Return visual icon nodes without its repository-page title metadata."""
    match = re.fullmatch(r"\s*<svg\b[^>]*>(.*)</svg>\s*", icon_svg, flags=re.DOTALL)
    if match is None:
        raise ValueError("repository icon is not a complete SVG")
    return re.sub(r"<title\b[^>]*>.*?</title>", "", match.group(1), flags=re.DOTALL).strip()


def _text(
    x: int,
    y: int,
    value: str,
    *,
    colour: str,
    size: int,
    weight: int,
    family: str = SANS,
    letter_spacing: str | None = None,
) -> str:
    """Build one escaped text node while keeping layout declarations readable."""
    tracking = f' letter-spacing="{letter_spacing}"' if letter_spacing else ""
    return (
        f'  <text x="{x}" y="{y}" fill="{colour}" font-family="{family}" '
        f'font-size="{size}" font-weight="{weight}"{tracking}>{escape(value)}</text>'
    )


def render_preview(preview: SocialPreview, icon_svg: str) -> str:
    """Render one deterministic, self-contained 1280×640 SVG card."""
    public_copy = " ".join(
        [preview.product, preview.summary, *(item.value for item in preview.facts)]
    ).lower()
    if any(term in public_copy for term in BANNED_PUBLIC_COPY):
        raise ValueError(f"{preview.repository} contains internal design metadata")

    icon = _icon_body(icon_svg)
    fact_x = (112, 456, 800)
    fact_nodes: list[str] = []
    for x, fact in zip(fact_x, preview.facts, strict=True):
        family = MONO if fact.monospace else SANS
        fact_nodes.extend(
            (
                "  "
                + _text(
                    x,
                    461,
                    fact.label,
                    colour=ACCENT,
                    size=14,
                    weight=700,
                    letter_spacing="1.8",
                ),
                "  "
                + _text(
                    x,
                    500,
                    fact.value,
                    colour=MUTED,
                    size=22,
                    weight=500,
                    family=family,
                ),
            )
        )

    lines = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
            f'viewBox="0 0 {WIDTH} {HEIGHT}" role="img" '
            'aria-labelledby="title description">'
        ),
        f'  <title id="title">{escape(preview.product)} · Fileworks</title>',
        f'  <desc id="description">{escape(preview.summary)}</desc>',
        f'  <rect width="{WIDTH}" height="{HEIGHT}" fill="{BACKGROUND}"/>',
        (
            f'  <rect x="72" y="72" width="1136" height="496" rx="32" fill="{SURFACE}" '
            f'stroke="{BORDER}" stroke-width="2"/>'
        ),
        ('  <svg x="112" y="108" width="128" height="128" viewBox="0 0 32 32" aria-hidden="true">'),
        f"    {icon}",
        "  </svg>",
        _text(
            274,
            159,
            "FILEWORKS",
            colour=ACCENT,
            size=24,
            weight=700,
            letter_spacing="2",
        ),
        _text(274, 220, preview.product, colour=INK, size=52, weight=650),
        _text(112, 354, preview.summary, colour=BODY, size=31, weight=500),
        f'  <path d="M112 410H1168" stroke="{BORDER}" stroke-width="2"/>',
        "  <g>",
        *fact_nodes,
        "  </g>",
        "</svg>",
    ]
    return "\n".join(lines) + "\n"


def _render_png(svg_path: Path, png_path: Path) -> None:
    executable = shutil.which("rsvg-convert")
    if executable is None:
        raise RuntimeError("rsvg-convert is required to render social preview PNGs")
    with tempfile.NamedTemporaryFile(suffix=".png", dir=png_path.parent, delete=False) as handle:
        temporary = Path(handle.name)
    try:
        completed = subprocess.run(
            [executable, "-w", str(WIDTH), "-h", str(HEIGHT), "-o", str(temporary), str(svg_path)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "rsvg-convert failed")
        with Image.open(temporary) as image:
            if image.size != (WIDTH, HEIGHT) or image.format != "PNG":
                raise RuntimeError(f"invalid rendered preview: {image.format} {image.size}")
            if image.mode != "RGB":
                image.convert("RGB").save(temporary, format="PNG", optimize=True)
        if temporary.stat().st_size >= 1_000_000:
            raise RuntimeError(f"GitHub preview exceeds 1 MB: {temporary.stat().st_size} bytes")
        temporary.replace(png_path)
    finally:
        temporary.unlink(missing_ok=True)


def generate(root: Path) -> tuple[Path, ...]:
    """Write every SVG and PNG into its repository's `.github` directory."""
    written: list[Path] = []
    for preview in PREVIEWS:
        github = root / preview.repository / ".github"
        icon = github / "icon.svg"
        if not icon.is_file():
            raise FileNotFoundError(f"missing repository icon: {icon}")
        github.mkdir(parents=True, exist_ok=True)
        svg = github / "social-preview.svg"
        png = github / "social-preview.png"
        svg.write_text(render_preview(preview, icon.read_text(encoding="utf-8")), encoding="utf-8")
        _render_png(svg, png)
        written.extend((svg, png))
    return tuple(written)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="directory containing the six repository checkouts",
    )
    args = parser.parse_args()
    written = generate(args.root.resolve())
    print(f"Generated {len(written)} social-preview assets across {len(PREVIEWS)} repositories")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
