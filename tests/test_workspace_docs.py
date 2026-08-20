"""P-03 / P-04 — the workspace documents are checked against one version source.

`CLAUDE.md`, `planning/reference/release-status.md` and `.mex/ROUTER.md` live
above every repository, so no repository's CI reads them. All three drifted:
two named versions that were two releases old, and one called a released tool
unreleased.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from maintenance.docs import (
    VERSION_CHECK_IGNORE,
    WORKSPACE_DOCUMENTS,
    check_workspace_versions,
)
from maintenance.ledger import ReleaseLedger

WORKSPACE = Path(__file__).resolve().parent.parent.parent


def _ledger(tmp_path: Path, **versions: str) -> ReleaseLedger:
    payload = {
        "ledger_version": "1",
        "generated_at": "2026-08-20T00:00:00+00:00",
        "products": [
            {
                "name": name,
                "repository": name,
                "owner": "fileworks",
                # `released_version` is derived from verified channels, not
                # stored, so a fixture has to state the channel to state a version.
                "channels": [
                    {
                        "channel": "pypi",
                        "identifier": name,
                        "version": version,
                        "state": "verified",
                        "verified_at": "2026-08-20T00:00:00+00:00",
                        "detail": "fixture",
                    }
                ],
            }
            for name, version in versions.items()
        ],
    }
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return ReleaseLedger.read(path)


def _workspace(tmp_path: Path, name: str = "workspace", **documents: str) -> Path:
    """A distinct directory per call — two fixtures in one test must not collide."""
    root = tmp_path / name
    for relative in WORKSPACE_DOCUMENTS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(documents.get(relative.split("/")[-1].replace(".md", ""), ""), "utf-8")
    return root


class TestItCatchesDrift:
    def test_a_seeded_wrong_version_fails(self, tmp_path: Path) -> None:
        ledger = _ledger(tmp_path, **{"immich-export": "1.0.1"})
        workspace = _workspace(tmp_path, CLAUDE="`immich-export` is released `0.0.4` today.")

        issues = check_workspace_versions(workspace, ledger)

        assert [issue.kind for issue in issues] == ["stale_version"]
        assert "0.0.4" in issues[0].detail
        assert "1.0.1" in issues[0].detail

    def test_the_corrected_version_passes(self, tmp_path: Path) -> None:
        """The other half of the same claim: it is not simply always failing."""
        ledger = _ledger(tmp_path, **{"immich-export": "1.0.1"})
        workspace = _workspace(tmp_path, CLAUDE="`immich-export` is released `1.0.1` today.")

        assert check_workspace_versions(workspace, ledger) == ()

    def test_a_line_naming_several_products_is_faulted_only_for_orphans(
        self, tmp_path: Path
    ) -> None:
        """A line cannot say which of two versions belongs to which product, so
        it is faulted only for quoting one that is nobody's."""
        ledger = _ledger(tmp_path, **{"immich-export": "1.0.1", "paperless-export": "2.0.1"})
        current = _workspace(
            tmp_path,
            "current",
            CLAUDE="the tap serves `immich-export` `1.0.1` and `paperless-export` `2.0.1`",
        )
        stale = _workspace(
            tmp_path,
            "stale",
            CLAUDE="the tap serves `immich-export` `0.0.4` and `paperless-export` `2.0.1`",
        )

        assert check_workspace_versions(current, ledger) == ()
        assert [issue.kind for issue in check_workspace_versions(stale, ledger)] == [
            "stale_version"
        ]

    def test_a_missing_document_is_reported_rather_than_skipped(self, tmp_path: Path) -> None:
        ledger = _ledger(tmp_path, **{"immich-export": "1.0.1"})
        empty = tmp_path / "not-a-workspace"
        empty.mkdir()

        kinds = {issue.kind for issue in check_workspace_versions(empty, ledger)}

        assert kinds == {"missing_document"}


class TestTheEscapeHatchIsVisible:
    def test_an_ignored_line_is_not_checked(self, tmp_path: Path) -> None:
        ledger = _ledger(tmp_path, **{"media-sorter": "1.4.4"})
        workspace = _workspace(
            tmp_path,
            CLAUDE=f"MediaSorter builds pin `v9.0.0` of the action <!-- {VERSION_CHECK_IGNORE} -->",
        )

        assert check_workspace_versions(workspace, ledger) == ()

    def test_the_same_line_without_the_marker_is_checked(self, tmp_path: Path) -> None:
        """Otherwise the marker would be proving nothing."""
        ledger = _ledger(tmp_path, **{"media-sorter": "1.4.4"})
        workspace = _workspace(tmp_path, CLAUDE="MediaSorter builds pin `v9.0.0` of the action")

        assert [issue.kind for issue in check_workspace_versions(workspace, ledger)] == [
            "stale_version"
        ]


class TestTheRealWorkspace:
    def test_the_documents_beside_this_repository_agree_with_the_ledger(self) -> None:
        """The check that would have caught P-03/P-04 before it was written.

        Skipped where the workspace is not checked out around this repository.
        CI clones `maintenance` on its own, so `WORKSPACE` is the runner's work
        directory and none of the workspace documents exist there — the check
        would report every one of them missing and fail for a reason that has
        nothing to do with the change under test.

        The skip is narrow on purpose: it fires only when *no* workspace
        document is present, which means "there is no workspace here". A
        workspace that exists but is missing one document still fails, because
        that is the drift this check was written to catch.
        """
        present = [name for name in WORKSPACE_DOCUMENTS if (WORKSPACE / name).is_file()]
        if not present:
            pytest.skip(f"no workspace checked out around {WORKSPACE}")

        ledger_path = Path(__file__).resolve().parent.parent / "release-ledger.json"
        issues = check_workspace_versions(WORKSPACE, ReleaseLedger.read(ledger_path))

        assert [f"{issue.repository}: {issue.detail}" for issue in issues] == []
