"""Release artifacts and protected publication environments stay coherent."""

from __future__ import annotations

from pathlib import Path

from maintenance.deployments import EXPECTED_ENVIRONMENTS, check_release_deployments


def _workflow(tmp_path: Path, jobs: str) -> Path:
    path = tmp_path / "release.yml"
    path.write_text(f"name: release\njobs:\n{jobs}", encoding="utf-8")
    return path


def test_the_four_product_environment_sets_are_explicit() -> None:
    assert {
        "media-sorter": frozenset({"github-release"}),
        "immich-export": frozenset({"github-release", "pypi", "homebrew"}),
        "paperless-export": frozenset({"github-release", "pypi", "homebrew"}),
        "unpacksort": frozenset({"github-release", "pypi", "homebrew", "winget"}),
    } == EXPECTED_ENVIRONMENTS


def test_matching_publication_jobs_are_clean(tmp_path: Path) -> None:
    workflow = _workflow(
        tmp_path,
        """  github-release:
    environment: github-release
    steps:
      - run: gh release create "$TAG"
  pypi:
    environment: pypi
    steps:
      - uses: pypa/gh-action-pypi-publish@release/v1
  homebrew:
    environment: homebrew
    steps:
      - run: gh workflow run bump.yml
""",
    )

    assert check_release_deployments("immich-export", workflow) == []


def test_a_publication_in_the_wrong_environment_is_named(tmp_path: Path) -> None:
    workflow = _workflow(
        tmp_path,
        """  publish:
    environment: pypi
    steps:
      - run: gh release create "$TAG"
      - uses: pypa/gh-action-pypi-publish@release/v1
""",
    )

    findings = check_release_deployments("immich-export", workflow)

    assert any("publishes github-release" in finding for finding in findings)
    assert any(
        "missing release environments: github-release, homebrew" in finding for finding in findings
    )


def test_media_sorter_accepts_the_release_action_marker(tmp_path: Path) -> None:
    workflow = _workflow(
        tmp_path,
        """  publish:
    environment: github-release
    steps:
      - uses: softprops/action-gh-release@v2
""",
    )

    assert check_release_deployments("media-sorter", workflow) == []
