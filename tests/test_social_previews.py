"""Contracts for the public repository preview cards."""

from __future__ import annotations

from maintenance.identity.social_previews import (
    BANNED_PUBLIC_COPY,
    HEIGHT,
    PREVIEWS,
    WIDTH,
    render_preview,
)


def test_every_repository_has_one_preview() -> None:
    assert {preview.repository for preview in PREVIEWS} == {
        "media-sorter",
        "immich-export",
        "paperless-export",
        "unpacksort",
        "homebrew-tap",
        "maintenance",
    }


def test_public_copy_is_useful_and_has_no_internal_design_metadata() -> None:
    for preview in PREVIEWS:
        assert preview.summary.endswith(".")
        assert len(preview.facts) == 3
        assert all(fact.label and fact.value for fact in preview.facts)
        copy = " ".join(
            [preview.product, preview.summary, *(fact.value for fact in preview.facts)]
        ).lower()
        assert not any(term in copy for term in BANNED_PUBLIC_COPY)


def test_render_is_accessible_self_contained_and_deterministic() -> None:
    icon = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
        '<title>internal</title><path d="M1 1h2"/></svg>'
    )
    preview = PREVIEWS[0]

    first = render_preview(preview, icon)
    second = render_preview(preview, icon)

    assert first == second
    assert f'width="{WIDTH}" height="{HEIGHT}"' in first
    assert 'role="img" aria-labelledby="title description"' in first
    assert '<desc id="description">' in first
    assert "internal" not in first
    assert "http" not in first.removeprefix('<svg xmlns="http://www.w3.org/2000/svg"')
