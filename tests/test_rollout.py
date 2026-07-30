"""Rolling one approved family out: recorded, derived, and never faked."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from maintenance.identity.rollout import (
    Decision,
    ensure_readme_icon,
    has_rasterizer,
    readme_badge,
    record,
    roll_out,
    targets,
)

WHEN = datetime(2026, 7, 28, tzinfo=UTC)


class TestDecision:
    def test_an_approval_is_recorded_as_data(self, tmp_path: Path) -> None:
        decision = record("literal", "ember", approved_by="someone", when=WHEN)
        decision.save(tmp_path)

        reloaded = Decision.load(tmp_path)

        assert reloaded == decision
        assert reloaded is not None and reloaded.approved_on == "2026-07-28"

    def test_an_unknown_family_is_refused(self) -> None:
        with pytest.raises(KeyError, match="family"):
            record("not-a-family", "ember", approved_by="someone")

    def test_an_unknown_colour_is_refused(self) -> None:
        with pytest.raises(KeyError, match="orange"):
            record("literal", "chartreuse", approved_by="someone")

    def test_no_decision_reads_as_none_rather_than_a_default(self, tmp_path: Path) -> None:
        assert Decision.load(tmp_path) is None

    def test_the_recorded_colour_resolves_to_a_real_one(self) -> None:
        assert record("literal", "ember", approved_by="x").colour().hex == "#C2410C"

    def test_the_shipped_decision_is_the_family_that_was_approved(self) -> None:
        decision = Decision.load(Path("maintenance/identity"))

        assert decision is not None
        assert decision.family == "literal"
        assert decision.orange == "ember"


class TestTargets:
    def test_every_repository_gets_a_preview_icon(self) -> None:
        previews = {
            target.repository for target in targets() if target.relative_path.startswith(".github")
        }

        assert previews == {
            "media-sorter",
            "immich-export",
            "paperless-export",
            "unpacksort",
            "homebrew-tap",
        }

    def test_only_the_desktop_product_needs_rasters(self) -> None:
        rasters = {target.repository for target in targets() if target.raster}

        assert rasters == {"media-sorter"}

    def test_every_raster_target_declares_its_size(self) -> None:
        assert all(target.size for target in targets() if target.raster)

    def test_every_target_says_what_it_is_for(self) -> None:
        # A path with no explanation is a path nobody will dare change later.
        assert all(target.note or target.raster for target in targets())


class TestRollout:
    def test_a_dry_run_writes_nothing(self, tmp_path: Path) -> None:
        (tmp_path / "media-sorter").mkdir()
        decision = record("literal", "ember", approved_by="x")

        result = roll_out(decision, tmp_path, dry_run=True)

        assert result.written
        assert not any(tmp_path.rglob("*.svg"))

    def test_a_missing_repository_is_skipped_not_failed(self, tmp_path: Path) -> None:
        result = roll_out(record("literal", "ember", approved_by="x"), tmp_path)

        assert result.written == []
        assert result.skipped
        assert result.clean

    def test_the_written_svg_carries_the_approved_colour(self, tmp_path: Path) -> None:
        (tmp_path / "immich-export").mkdir()

        roll_out(record("literal", "ember", approved_by="x"), tmp_path)

        svg = (tmp_path / "immich-export" / ".github" / "icon.svg").read_text(encoding="utf-8")
        assert "#C2410C" in svg
        assert 'aria-label="immich-export"' in svg

    def test_rolling_out_twice_produces_identical_bytes(self, tmp_path: Path) -> None:
        (tmp_path / "unpacksort").mkdir()
        decision = record("literal", "ember", approved_by="x")

        roll_out(decision, tmp_path)
        first = (tmp_path / "unpacksort" / ".github" / "icon.svg").read_bytes()
        roll_out(decision, tmp_path)

        assert (tmp_path / "unpacksort" / ".github" / "icon.svg").read_bytes() == first

    @pytest.mark.skipif(not has_rasterizer(), reason="rsvg-convert is not installed")
    def test_the_rasters_are_real_images_with_the_accent_in_them(self, tmp_path: Path) -> None:
        # Reading the raster back needs Pillow as much as making it needs
        # rsvg-convert. Guarding only the renderer turned a missing optional
        # dependency into a failure instead of a skip.
        pytest.importorskip("PIL")
        from PIL import Image

        (tmp_path / "media-sorter").mkdir()
        roll_out(record("literal", "ember", approved_by="x"), tmp_path)

        # The canonical source is the only raster the rollout writes; every
        # bundle icon is generated from it by the repository's own pipeline.
        path = tmp_path / "media-sorter" / "branding" / "app-icon.png"
        with Image.open(path) as image:
            assert image.size == (1024, 1024)
            # Pillow types this loosely across modes; an RGB image always
            # yields 3-tuples, which is why it is converted first.
            flat = cast(
                "tuple[tuple[int, int, int], ...]",
                image.convert("RGB").get_flattened_data(),
            )
        ember = sum(
            1 for r, g, b in flat if abs(r - 194) < 24 and abs(g - 65) < 24 and abs(b - 12) < 24
        )
        # A blank square is a valid PNG; the accent has to actually be in it.
        assert ember > 100

    def test_a_missing_rasterizer_is_reported_rather_than_faked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "media-sorter").mkdir()
        # Patched by path rather than through `rollout.shutil`: the module
        # imports shutil for its own use and does not re-export it.
        monkeypatch.setattr("maintenance.identity.rollout.shutil.which", lambda _name: None)

        result = roll_out(record("literal", "ember", approved_by="x"), tmp_path)

        assert result.failed
        assert all("rsvg-convert is unavailable" in item for item in result.failed)
        assert not list((tmp_path / "media-sorter").rglob("*.png"))


class TestReadme:
    def test_the_icon_is_added_above_the_title(self, tmp_path: Path) -> None:
        readme = tmp_path / "README.md"
        readme.write_text("# demo\n\nSome prose.\n", encoding="utf-8")

        assert ensure_readme_icon(tmp_path) is True
        lines = readme.read_text(encoding="utf-8").splitlines()
        assert ".github/icon.svg" in lines[0]
        assert lines[2] == "# demo"

    def test_adding_it_twice_changes_nothing(self, tmp_path: Path) -> None:
        readme = tmp_path / "README.md"
        readme.write_text("# demo\n", encoding="utf-8")
        ensure_readme_icon(tmp_path)
        once = readme.read_text(encoding="utf-8")

        assert ensure_readme_icon(tmp_path) is False
        assert readme.read_text(encoding="utf-8") == once

    def test_a_readme_without_a_title_is_left_alone(self, tmp_path: Path) -> None:
        readme = tmp_path / "README.md"
        readme.write_text("no heading here\n", encoding="utf-8")

        assert ensure_readme_icon(tmp_path) is False

    def test_the_alt_text_is_empty_because_the_title_follows(self, tmp_path: Path) -> None:
        readme = tmp_path / "README.md"
        readme.write_text("# demo\n", encoding="utf-8")
        ensure_readme_icon(tmp_path)

        # A decorative icon immediately above the heading it decorates should
        # not be announced twice by a screen reader.
        assert 'alt=""' in readme.read_text(encoding="utf-8")

    def test_a_readme_without_the_icon_is_reported_as_drift(self) -> None:
        # This replaced a loop that asserted every sibling repository's README
        # already showed the icon. It passed only because the local working tree
        # had uncommitted README edits; against `main` it failed, because the
        # rollout has not landed there yet. Whether another repository adopted
        # the icon is drift to report, not an invariant this suite can hold.
        from maintenance.docs import check_icon

        assert check_icon("demo", "# demo\n") != ()
        assert check_icon("demo", readme_badge() + "\n\n# demo\n") == ()


class TestBrandingPipeline:
    """MediaSorter generates every bundle asset from one pinned source.

    Writing individual derivatives would bypass that contract and its freshness
    test, so the rollout writes the canonical source and lets the repository's
    own generator produce the rest.
    """

    def test_no_derivative_is_written_directly(self) -> None:
        derivative_shapes = (
            "icons/32x32",
            "icons/128x128",
            "Square",
            "StoreLogo",
            "installer/",
        )

        for target in targets():
            assert not any(shape in target.relative_path for shape in derivative_shapes), (
                f"{target.relative_path} is a generated derivative and must not be written directly"
            )

    def test_only_the_canonical_source_is_rasterised(self) -> None:
        rasters = [target for target in targets() if target.raster]

        assert [target.relative_path for target in rasters] == ["branding/app-icon.png"]
        assert rasters[0].size == 1024

    def test_a_repository_without_a_generator_says_so(self, tmp_path: Path) -> None:
        from maintenance.identity.rollout import regenerate_branding

        ok, detail = regenerate_branding(tmp_path)

        assert ok is False
        assert "no branding generator" in detail

    def test_rerunning_when_the_digest_is_already_correct_succeeds(self, tmp_path: Path) -> None:
        from maintenance.identity.rollout import regenerate_branding

        script = Path("media-sorter/scripts/generate_branding.py")
        canonical = Path("media-sorter/branding/app-icon.png")
        if not script.is_file() or not canonical.is_file():
            pytest.skip("media-sorter is not present in this checkout")
        # The generator runs under this interpreter and imports Pillow, so a
        # missing optional dependency is a skip rather than a generator failure.
        pytest.importorskip("PIL")

        # Run against a copy, never the real tree. `regenerate_branding` rewrites
        # the generator's pinned digest and the generator writes every derivative
        # into its own parent directory, so pointing this at `media-sorter` edits
        # the working tree as a side effect of asserting a return value. The
        # generator derives its root from `__file__`, so a copy relocates cleanly.
        for source in (script, canonical):
            target = tmp_path / source.relative_to("media-sorter")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())

        # The normal case on a second run: the pin already matches, which is not
        # a failure to find it.
        ok, detail = regenerate_branding(tmp_path)

        assert ok is True, detail

    def test_the_shipped_canonical_source_matches_the_pin(self) -> None:
        import hashlib
        import re

        script = Path("media-sorter/scripts/generate_branding.py")
        canonical = Path("media-sorter/branding/app-icon.png")
        if not script.is_file() or not canonical.is_file():
            pytest.skip("media-sorter is not present in this checkout")

        pinned = re.search(r'"([0-9a-f]{64})"', script.read_text(encoding="utf-8"))
        assert pinned is not None
        assert hashlib.sha256(canonical.read_bytes()).hexdigest() == pinned.group(1)
