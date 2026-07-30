"""Rolling one approved family into the places that actually display an icon.

Approval is recorded here as data — which family, which orange, when, and by
whom — because "we picked one" is a fact the export tooling and the compliance
audit both need, and a fact that belongs in a file rather than in somebody's
memory of a conversation.

Everything below is derived from that record. The SVGs come from the same
generator as before; the rasters are produced by `rsvg-convert`, and when that
is not installed the PNG step is *skipped and reported* rather than faked — a
missing icon is obvious, a wrong one is not.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from maintenance.identity.directions import DIRECTION_BY_KEY
from maintenance.identity.export import render_svg
from maintenance.identity.tokens import ORANGE_CANDIDATES, Colour, palettes

DECISION_FILE = "decision.json"


@dataclass(frozen=True)
class Decision:
    """The approved family, recorded so nothing has to remember it."""

    family: str
    orange: str
    approved_by: str
    approved_on: str
    note: str = ""

    def colour(self) -> Colour:
        return next(item for item in ORANGE_CANDIDATES if item.name == self.orange)

    @classmethod
    def load(cls, directory: Path) -> Decision | None:
        path = directory / DECISION_FILE
        if not path.is_file():
            return None
        return cls(**json.loads(path.read_text(encoding="utf-8")))

    def save(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / DECISION_FILE
        path.write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")
        return path


def record(
    family: str,
    orange: str,
    *,
    approved_by: str,
    note: str = "",
    when: datetime | None = None,
) -> Decision:
    """Record an approval, refusing a family or colour that does not exist."""
    if family not in DIRECTION_BY_KEY:
        raise KeyError(f"no such family: {family!r}")
    if not any(item.name == orange for item in ORANGE_CANDIDATES):
        raise KeyError(f"no such orange: {orange!r}")
    return Decision(
        family=family,
        orange=orange,
        approved_by=approved_by,
        approved_on=(when or datetime.now(UTC)).date().isoformat(),
        note=note,
    )


# --------------------------------------------------------------------------- #
# Where each product's icon goes                                               #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Target:
    """One place an asset is written, and what shape it needs to be."""

    repository: str
    product: str
    relative_path: str
    mode: str = "light"
    size: int | None = None
    raster: bool = False
    note: str = ""


def targets() -> tuple[Target, ...]:
    """Every location that displays an icon, across the five repositories."""
    common = [
        Target(repo, product, ".github/icon.svg", note="repository preview and README")
        for repo, product in (
            ("media-sorter", "media-sorter"),
            ("immich-export", "immich-export"),
            ("paperless-export", "paperless-export"),
            ("unpacksort", "unpacksort"),
            ("homebrew-tap", "homebrew-tap"),
        )
    ]
    # MediaSorter owns its own branding pipeline: one canonical 1024 px source
    # with an approved digest, from which every icon, installer bitmap and
    # bundle asset is generated. Writing individual derivatives would bypass
    # that contract and its freshness test, so the only raster written here is
    # the canonical source — `make branding` produces the rest.
    desktop = [
        Target(
            "media-sorter",
            "media-sorter",
            "frontend/public/icon.svg",
            note="the window's favicon and the startup splash",
        ),
        Target(
            "media-sorter",
            "media-sorter",
            "branding/app-icon.svg",
            note="the editable source the canonical raster is rendered from",
        ),
        Target(
            "media-sorter",
            "media-sorter",
            "branding/app-icon.png",
            size=1024,
            raster=True,
            note="the canonical source; every bundle asset derives from this",
        ),
    ]
    return tuple(common + desktop)


@dataclass
class RolloutResult:
    written: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.failed

    def summary(self) -> str:
        parts = [f"{len(self.written)} written"]
        if self.skipped:
            parts.append(f"{len(self.skipped)} skipped")
        if self.failed:
            parts.append(f"{len(self.failed)} failed")
        return ", ".join(parts)


def has_rasterizer() -> bool:
    return shutil.which("rsvg-convert") is not None


def _rasterize(svg: str, destination: Path, size: int) -> bool:
    """Render one SVG to PNG. Returns whether it worked.

    `rsvg-convert` is used rather than a Python library because it is the tool
    already present on this machine, and because a raster produced by a
    different renderer than the one that made the shipped SVG would drift.
    """
    if not has_rasterizer():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        completed = subprocess.run(
            ["rsvg-convert", "-w", str(size), "-h", str(size), "-o", str(destination)],
            input=svg.encode("utf-8"),
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0 and destination.is_file()


def roll_out(decision: Decision, root: Path, *, dry_run: bool = False) -> RolloutResult:
    """Write the approved family into every display location."""
    direction = DIRECTION_BY_KEY[decision.family]
    orange = decision.colour()
    by_mode = {palette.mode: palette for palette in palettes(orange)}
    result = RolloutResult()

    for target in targets():
        repo_root = root / target.repository
        if not repo_root.is_dir():
            result.skipped.append(f"{target.repository}: not present in this checkout")
            continue

        glyph = direction.glyph(target.product)
        palette = by_mode[target.mode]
        destination = repo_root / target.relative_path

        if target.raster:
            svg = render_svg(glyph, palette, size=target.size)
            if dry_run:
                result.written.append(f"{target.repository}/{target.relative_path} (dry run)")
                continue
            if _rasterize(svg, destination, target.size or 128):
                result.written.append(f"{target.repository}/{target.relative_path}")
            else:
                result.failed.append(
                    f"{target.repository}/{target.relative_path}: rsvg-convert is unavailable, "
                    "so the PNG was not written"
                )
            continue

        svg = render_svg(glyph, palette, with_background=target.relative_path.endswith("icon.svg"))
        if dry_run:
            result.written.append(f"{target.repository}/{target.relative_path} (dry run)")
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(svg, encoding="utf-8")
        result.written.append(f"{target.repository}/{target.relative_path}")

    return result


def regenerate_branding(repo_root: Path) -> tuple[bool, str]:
    """Re-run MediaSorter's own branding generator and re-approve the source.

    The repository pins its canonical icon by digest so a silently swapped
    source fails its freshness test. Replacing the icon therefore means updating
    that digest deliberately — which is the point of the pin, and is done here
    rather than by editing the constant by hand.
    """
    script = repo_root / "scripts" / "generate_branding.py"
    canonical = repo_root / "branding" / "app-icon.png"
    if not script.is_file() or not canonical.is_file():
        return False, "this repository has no branding generator"

    digest = hashlib.sha256(canonical.read_bytes()).hexdigest()
    source = script.read_text(encoding="utf-8")
    pattern = re.compile(r'APPROVED_SOURCE_SHA256 = \(\s*"[0-9a-f]{64}"\s*\)')
    if pattern.search(source) is None:
        return False, "the approved digest could not be located in the generator"
    # An unchanged file means the digest was already correct — which is the
    # normal case on a re-run, not a failure to find it.
    updated = pattern.sub(f'APPROVED_SOURCE_SHA256 = (\n    "{digest}"\n)', source, count=1)
    if updated != source:
        script.write_text(updated, encoding="utf-8")

    try:
        completed = subprocess.run(
            [sys.executable, str(script.resolve())],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"the generator could not be run: {type(exc).__name__}"
    if completed.returncode != 0:
        return False, (completed.stderr or completed.stdout).strip()[:300]
    return True, f"regenerated from {digest[:12]}…"


def readme_badge() -> str:
    """The line that puts the icon at the top of a README.

    Identical for every repository: the alt text stays empty because the title
    follows immediately, so there is nothing repository-specific to vary.
    """
    return '<img src=".github/icon.svg" alt="" width="72" height="72" align="left">'


def ensure_readme_icon(repo_root: Path) -> bool:
    """Put the icon above the README's title, once.

    Returns whether anything changed. Idempotent: a README that already shows
    the icon is left exactly as it is.
    """
    readme = repo_root / "README.md"
    if not readme.is_file():
        return False
    text = readme.read_text(encoding="utf-8")
    if ".github/icon.svg" in text:
        return False
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("# "):
            lines.insert(index, readme_badge())
            lines.insert(index + 1, "")
            readme.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return True
    return False
