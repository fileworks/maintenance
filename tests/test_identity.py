"""The identity system: measured, deterministic, and never quietly confusable."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from maintenance.identity.directions import (
    DIRECTION_BY_KEY,
    DIRECTIONS,
    check_confusion,
    confusion_failures,
)
from maintenance.identity.distinctness import (
    GRID,
    density,
    density_difference,
    difference,
    occupancy,
    ranked,
)
from maintenance.identity.distinctness import measure as measure_distinctness
from maintenance.identity.export import (
    export_all,
    render_svg,
    repository_card,
    size_proof,
    stale_against_sources,
    validate,
)
from maintenance.identity.tokens import (
    CONFUSABLE,
    EXPORT_SIZES,
    GEOMETRY,
    GLYPHS,
    INK,
    MINIMUM_SIZE,
    ORANGE_CANDIDATES,
    PAPER,
    SLATE,
    measure,
    palettes,
    usable_on,
)


class TestGeometry:
    def test_the_stroke_lands_on_whole_pixels_at_every_shipped_size(self) -> None:
        # 20 px is the one exception and is why the simplified form exists.
        assert set(GEOMETRY.snapping_sizes) == set(EXPORT_SIZES) - {20}

    def test_clear_space_leaves_a_usable_drawing_area(self) -> None:
        assert GEOMETRY.inner == GEOMETRY.canvas - GEOMETRY.padding * 2
        assert GEOMETRY.inner >= GEOMETRY.canvas * 0.75

    def test_a_minimum_size_is_declared(self) -> None:
        assert min(EXPORT_SIZES) == MINIMUM_SIZE


class TestColour:
    def test_every_candidate_orange_is_measured_not_asserted(self) -> None:
        for colour in ORANGE_CANDIDATES:
            results = measure(colour)
            assert len(results) == 2
            assert all(result.ratio > 1 for result in results)

    def test_a_candidate_that_fails_on_light_is_visible_as_failing(self) -> None:
        amber = next(colour for colour in ORANGE_CANDIDATES if colour.name == "amber")

        assert usable_on(amber, PAPER) is False
        assert usable_on(amber, SLATE) is True

    def test_the_default_orange_passes_on_both_surfaces(self) -> None:
        ember = next(colour for colour in ORANGE_CANDIDATES if colour.name == "ember")

        assert usable_on(ember, PAPER)
        assert usable_on(ember, SLATE)

    def test_contrast_is_symmetric(self) -> None:
        assert INK.contrast_with(PAPER) == pytest.approx(PAPER.contrast_with(INK))

    def test_every_exported_palette_is_accessible(self) -> None:
        ember = next(colour for colour in ORANGE_CANDIDATES if colour.name == "ember")

        for palette in palettes(ember):
            assert palette.accessible, palette.mode

    def test_monochrome_modes_exist_for_both_surfaces(self) -> None:
        modes = {palette.mode for palette in palettes(ORANGE_CANDIDATES[0])}

        assert {"monochrome-light", "monochrome-dark"} <= modes


class TestDirections:
    def test_there_are_at_least_three_coherent_directions(self) -> None:
        assert len(DIRECTIONS) >= 3

    def test_each_direction_covers_every_product(self) -> None:
        for direction in DIRECTIONS:
            assert set(direction.glyphs) == set(GLYPHS)

    def test_each_direction_states_its_rule_and_its_cost(self) -> None:
        for direction in DIRECTIONS:
            assert direction.rule
            assert direction.tradeoff

    def test_no_glyph_is_confusable_with_a_harmful_gesture(self) -> None:
        for direction in DIRECTIONS:
            assert confusion_failures(direction) == [], direction.key

    def test_every_glyph_is_checked_against_every_confusable_shape(self) -> None:
        for direction in DIRECTIONS:
            checks = check_confusion(direction)
            assert len(checks) == len(GLYPHS) * len(CONFUSABLE)

    def test_every_glyph_carries_a_simplified_form_for_small_sizes(self) -> None:
        for direction in DIRECTIONS:
            for glyph in direction.glyphs.values():
                assert glyph.has_simplification, f"{direction.key}/{glyph.product}"


class TestRendering:
    def test_rendering_is_deterministic(self) -> None:
        glyph = DIRECTION_BY_KEY["apertures"].glyph("unpacksort")
        palette = palettes(ORANGE_CANDIDATES[0])[0]

        assert render_svg(glyph, palette, size=32) == render_svg(glyph, palette, size=32)

    def test_a_small_size_uses_the_simplified_form(self) -> None:
        glyph = DIRECTION_BY_KEY["flow"].glyph("unpacksort")
        palette = palettes(ORANGE_CANDIDATES[0])[0]

        small = render_svg(glyph, palette, size=16)
        large = render_svg(glyph, palette, size=256)

        assert small != large
        assert large.count("<path") > small.count("<path")

    def test_every_asset_carries_an_accessible_label(self) -> None:
        glyph = DIRECTION_BY_KEY["stacked"].glyph("media-sorter")
        svg = render_svg(glyph, palettes(ORANGE_CANDIDATES[0])[0], size=64)

        assert 'role="img"' in svg
        assert 'aria-label="media-sorter"' in svg
        assert "<title>" in svg

    def test_the_master_has_no_background(self) -> None:
        glyph = DIRECTION_BY_KEY["stacked"].glyph("media-sorter")
        svg = render_svg(glyph, palettes(ORANGE_CANDIDATES[0])[0], with_background=False)

        assert "<rect" not in svg

    def test_the_repository_card_shows_the_whole_family(self) -> None:
        card = repository_card(DIRECTION_BY_KEY["apertures"], palettes(ORANGE_CANDIDATES[0])[0])

        assert card.count("<g transform=") == len(GLYPHS)
        assert 'width="1280"' in card

    def test_the_size_proof_covers_the_small_end(self) -> None:
        proof = size_proof(
            DIRECTION_BY_KEY["flow"].glyph("immich-export"),
            palettes(ORANGE_CANDIDATES[0])[0],
        )

        assert proof.count("<g transform=") == 6


class TestExportAndValidation:
    @pytest.fixture()
    def exported(self, tmp_path: Path) -> Path:
        export_all(tmp_path)
        return tmp_path

    def test_the_export_produces_a_manifest_covering_every_asset(self, exported: Path) -> None:
        manifest = json.loads((exported / "manifest.json").read_text(encoding="utf-8"))

        assert manifest["manifest_version"] == 1
        assert len(manifest["assets"]) == len(list(exported.rglob("*.svg")))

    def test_a_fresh_export_validates_clean(self, exported: Path) -> None:
        assert validate(exported) == []
        assert stale_against_sources(exported) == []

    def test_manifest_paths_are_posix_on_every_platform(self, exported: Path) -> None:
        # `stale_against_sources` builds its lookup keys with `/`. When the
        # manifest recorded `str(Path)` instead, every key missed on Windows and
        # all 1,260 assets reported stale while nothing had changed. Asserted as
        # an invariant so it holds without needing a Windows runner to notice.
        manifest = json.loads((exported / "manifest.json").read_text(encoding="utf-8"))
        paths = [str(entry["path"]) for entry in manifest["assets"]]

        assert paths
        assert not [path for path in paths if "\\" in path]
        assert all("/" in path for path in paths)

    def test_a_hand_edited_asset_is_caught(self, exported: Path) -> None:
        target = next(exported.rglob("*-32.svg"))
        target.write_text(target.read_text(encoding="utf-8") + "<!-- tweak -->", encoding="utf-8")

        issues = validate(exported)

        assert any(issue.kind == "modified" for issue in issues)

    def test_a_deleted_asset_is_caught(self, exported: Path) -> None:
        next(exported.rglob("*-32.svg")).unlink()

        assert any(issue.kind == "missing" for issue in validate(exported))

    def test_an_unlisted_asset_is_caught(self, exported: Path) -> None:
        (exported / "stray.svg").write_text("<svg/>", encoding="utf-8")

        assert any(issue.kind == "unlisted" for issue in validate(exported))

    def test_a_nested_unlisted_asset_is_reported_with_a_posix_path(self, exported: Path) -> None:
        # The flat `stray.svg` above has no separator to get wrong, which is
        # exactly why it passed on Windows while every nested asset was reported
        # unlisted. This one is nested, so the separator is part of the assertion.
        nested = exported / "stray" / "deeper" / "stray.svg"
        nested.parent.mkdir(parents=True)
        nested.write_text("<svg/>", encoding="utf-8")

        unlisted = [issue for issue in validate(exported) if issue.kind == "unlisted"]

        assert [issue.path for issue in unlisted] == ["stray/deeper/stray.svg"]

    def test_exporting_twice_produces_identical_bytes(self, tmp_path: Path) -> None:
        first = tmp_path / "a"
        second = tmp_path / "b"
        export_all(first)
        export_all(second)

        for path in sorted(first.rglob("*.svg")):
            assert path.read_bytes() == (second / path.relative_to(first)).read_bytes()

    def test_an_orange_that_fails_contrast_cannot_be_exported(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="3:1"):
            export_all(tmp_path, orange_name="amber")

    def test_a_missing_manifest_is_reported_rather_than_crashing(self, tmp_path: Path) -> None:
        assert validate(tmp_path)[0].kind == "missing"


class TestNewDirections:
    """The three families added after the Apertures decision."""

    NEW = ("tabbed", "cut", "nested")

    def test_every_family_is_available(self) -> None:
        # Three originals, three built from the Apertures choice, and the
        # literal-contents rework of Apertures itself.
        assert len(DIRECTIONS) == 7
        for key in (*self.NEW, "literal"):
            assert key in DIRECTION_BY_KEY

    def test_each_new_family_is_complete_and_states_its_cost(self) -> None:
        for key in self.NEW:
            direction = DIRECTION_BY_KEY[key]
            assert set(direction.glyphs) == set(GLYPHS)
            assert direction.rule and direction.tradeoff
            assert all(glyph.has_simplification for glyph in direction.glyphs.values())

    def test_no_new_family_is_confusable_with_a_harmful_gesture(self) -> None:
        for key in self.NEW:
            assert confusion_failures(DIRECTION_BY_KEY[key]) == [], key

    def test_the_new_families_keep_the_shared_construction(self) -> None:
        # Same canvas, so every family can be compared and swapped freely.
        for key in self.NEW:
            for glyph in DIRECTION_BY_KEY[key].glyphs.values():
                for path in glyph.strokes + glyph.accents:
                    assert "M" in path


class TestDistinctness:
    def test_no_family_contains_two_identical_silhouettes(self) -> None:
        # A pair measuring zero means two products draw the same shape, which is
        # the one thing an icon family may not do.
        for direction in DIRECTIONS:
            assert measure_distinctness(direction).silhouette_worst > 0.0, direction.key

    def test_a_glyph_is_identical_to_itself(self) -> None:
        glyph = DIRECTION_BY_KEY["nested"].glyph("unpacksort")

        assert difference(glyph, glyph) == 0.0

    def test_two_different_glyphs_differ(self) -> None:
        direction = DIRECTION_BY_KEY["flow"]

        assert difference(direction.glyph("media-sorter"), direction.glyph("unpacksort")) > 0

    def test_the_ranking_is_ordered_by_silhouette_difference(self) -> None:
        order = [item.silhouette_mean for item in ranked(DIRECTIONS)]

        assert order == sorted(order, reverse=True)

    def test_the_summary_names_the_closest_pair(self) -> None:
        summary = measure_distinctness(DIRECTION_BY_KEY["apertures"]).summary

        assert "closest pair" in summary
        assert "%" in summary

    def test_occupancy_is_bounded_by_the_grid(self) -> None:
        cells = occupancy(DIRECTION_BY_KEY["cut"].glyph("media-sorter"))

        assert cells
        assert all(0 <= column < GRID and 0 <= row < GRID for column, row in cells)

    def test_measuring_ignores_accents_when_asked(self) -> None:
        glyph = DIRECTION_BY_KEY["nested"].glyph("unpacksort")

        assert occupancy(glyph, include_accents=False) <= occupancy(glyph)


class TestLiteralContents:
    """The Apertures family with what each tool actually handles drawn inside."""

    def test_the_family_is_complete(self) -> None:
        direction = DIRECTION_BY_KEY["literal"]

        assert set(direction.glyphs) == set(GLYPHS)
        assert confusion_failures(direction) == []

    def test_every_glyph_simplifies_for_the_small_sizes(self) -> None:
        for glyph in DIRECTION_BY_KEY["literal"].glyphs.values():
            assert glyph.has_simplification
            assert len(glyph.simplified) <= len(glyph.strokes) + len(glyph.accents)

    def test_the_exporters_are_twins_but_not_the_same_drawing(self) -> None:
        direction = DIRECTION_BY_KEY["literal"]
        immich = direction.glyph("immich-export")
        paperless = direction.glyph("paperless-export")

        # Sibling tools, so a shared construction is correct — but a landscape
        # picture and a portrait page must still be told apart.
        assert difference(immich, paperless) > 0.0
        assert density_difference(immich, paperless) > 0.15

    def test_literal_contents_beat_the_abstract_ones_on_ink_distribution(self) -> None:
        literal = measure_distinctness(DIRECTION_BY_KEY["literal"])
        abstract = measure_distinctness(DIRECTION_BY_KEY["apertures"])

        # This is the whole point of the rework: the containers are the same, so
        # the gain has to come from the contents.
        assert literal.density_mean > abstract.density_mean * 2

    def test_the_container_is_shared_with_apertures(self) -> None:
        # Same construction rule; only the contents changed.
        literal = DIRECTION_BY_KEY["literal"].glyph("media-sorter")

        assert any("A3.00,3.00" in path or "A" in path for path in literal.strokes)


class TestDensityMeasure:
    def test_a_glyph_matches_itself_exactly(self) -> None:
        glyph = DIRECTION_BY_KEY["literal"].glyph("unpacksort")

        assert density_difference(glyph, glyph) == pytest.approx(0.0, abs=1e-9)

    def test_density_sums_to_one(self) -> None:
        spread = density(DIRECTION_BY_KEY["literal"].glyph("homebrew-tap"))

        assert sum(spread.values()) == pytest.approx(1.0)

    def test_density_does_not_saturate_where_occupancy_does(self) -> None:
        # The detailed family loses on binary occupancy and wins on ink, which
        # is exactly the saturation this second measure exists to see past.
        literal = measure_distinctness(DIRECTION_BY_KEY["literal"])

        assert literal.with_accents_mean < literal.density_mean

    def test_an_empty_glyph_is_handled(self) -> None:
        from maintenance.identity.directions import Glyph

        blank = Glyph("blank", "nothing", ())

        assert density(blank) == {}
        assert density_difference(blank, blank) == 0.0
