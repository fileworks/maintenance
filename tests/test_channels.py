"""The record is checked against the thing it describes.

Every test here injects its readers, so nothing in this file touches a network.
The one behaviour worth stating up front: an unreachable channel is never
`compliant`. A check that reports green because it could not look is the exact
failure this module was written to remove.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from maintenance.channels import (
    ChannelComparison,
    Readers,
    compare_ledger_to_channels,
    findings,
    github_release_version,
    normalise,
    pypi_version,
    tap_version,
    unreadable,
)
from maintenance.docs import check_versions
from maintenance.drift import DriftReport
from maintenance.formula import sdist_version
from maintenance.ledger import ReleaseLedger, record, scaffold
from maintenance.policy import LEDGER_CHANNEL_CONTROL, PolicyReport, RepoClass, release_controls

NOW = datetime(2026, 8, 4, tzinfo=UTC)

CLASSES: dict[str, RepoClass] = {
    "immich-export": "python_cli",
    "paperless-export": "python_cli",
    "unpacksort": "python_cli",
    "media-sorter": "desktop_application",
}

FORMULA = """\
class ImmichExport < Formula
  include Language::Python::Virtualenv

  desc "demo"
  url "https://files.pythonhosted.org/packages/f5/28/abc/immich_export-0.2.1.tar.gz"
  sha256 "0" * 64

  resource "httpx" do
    url "https://files.pythonhosted.org/packages/aa/bb/httpx-9.9.9.tar.gz"
  end
end
"""


def ledger_recording(product: str, channel: str, version: str) -> ReleaseLedger:
    """A scaffold with exactly one verified observation on it."""
    return record(scaffold(), product, channel, version=version, observed_at=NOW)  # type: ignore[arg-type]


def readers(**overrides: object) -> Readers:
    """Unreadable everywhere except where a test says otherwise."""
    base = unreadable()
    return Readers(
        pypi=overrides.get("pypi", base.pypi),  # type: ignore[arg-type]
        homebrew=overrides.get("homebrew", base.homebrew),  # type: ignore[arg-type]
        github_release=overrides.get("github_release", base.github_release),  # type: ignore[arg-type]
    )


# --------------------------------------------------------------------------- #
# 1. The gap, before it was closed                                             #
# --------------------------------------------------------------------------- #


class TestTheGapThisChangeCloses:
    def test_a_ledger_the_channel_disagrees_with_is_a_finding(self) -> None:
        """The 2026-08-04 condition: PyPI at 0.2.1, the ledger still at 0.2.0."""
        ledger = ledger_recording("immich-export", "pypi", "0.2.0")

        comparisons = compare_ledger_to_channels(
            ledger, readers(pypi=lambda _name: "0.2.1"), products=("immich-export",)
        )
        results = findings(comparisons, CLASSES)

        stale = [item for item in results if item.outcome == "stale"]
        assert len(stale) == 1
        assert "0.2.0" in stale[0].detail
        assert "0.2.1" in stale[0].detail
        assert "pypi" in stale[0].detail

    def test_check_versions_passes_when_readme_and_ledger_are_stale_together(self) -> None:
        """Why the existing check could not catch it.

        `check_versions` compares a README to the ledger. Both were wrong by the
        same amount, so they agreed, so it passed. It was reading a source
        nobody was checking — which is the gap, not a bug in the check.
        """
        ledger = ledger_recording("immich-export", "pypi", "0.2.0")

        issues = check_versions("immich-export", "Install version `0.2.0` today.", ledger)

        assert issues == ()


# --------------------------------------------------------------------------- #
# 2. The readers                                                               #
# --------------------------------------------------------------------------- #


class TestPyPiReader:
    def test_it_reads_the_served_version(self) -> None:
        payload = json.dumps({"info": {"version": "1.2.2", "name": "paperless-export"}})

        assert pypi_version("paperless-export", fetch=lambda _url: payload) == "1.2.2"

    def test_an_unreachable_index_is_none_not_a_guess(self) -> None:
        assert pypi_version("paperless-export", fetch=lambda _url: None) is None

    def test_malformed_json_is_none(self) -> None:
        assert pypi_version("x", fetch=lambda _url: "{not json") is None

    def test_a_payload_without_a_version_is_none(self) -> None:
        assert pypi_version("x", fetch=lambda _url: json.dumps({"info": {}})) is None


class TestTapReader:
    def test_it_reads_the_version_out_of_the_sdist_url(self) -> None:
        assert tap_version("immich-export", fetch=lambda _url: FORMULA) == "0.2.1"

    def test_it_ignores_a_resource_block_url(self) -> None:
        """A dependency's version is not the formula's, and the depth says so."""
        assert tap_version("x", fetch=lambda _url: FORMULA) != "9.9.9"

    def test_an_absent_formula_is_none(self) -> None:
        assert tap_version("nothing", fetch=lambda _url: None) is None

    def test_a_pending_formula_reports_no_version(self) -> None:
        pending = 'class X < Formula\n  url "PENDING"\n  sha256 "PENDING"\nend\n'

        assert sdist_version(pending) is None


class TestGithubReleaseReader:
    def test_it_reads_the_latest_tag_without_its_v(self) -> None:
        version = github_release_version(
            "fileworks", "unpacksort", fetch_json=lambda _path: {"tag_name": "v1.1.0"}
        )

        assert version == "1.1.0"

    def test_a_prerelease_is_not_a_release(self) -> None:
        version = github_release_version(
            "fileworks",
            "x",
            fetch_json=lambda _path: {"tag_name": "v2.0.0rc1", "prerelease": True},
        )

        assert version is None

    def test_a_draft_is_not_a_release(self) -> None:
        version = github_release_version(
            "fileworks", "x", fetch_json=lambda _path: {"tag_name": "v2.0.0", "draft": True}
        )

        assert version is None

    def test_no_release_at_all_is_none(self) -> None:
        assert github_release_version("fileworks", "x", fetch_json=lambda _path: None) is None

    def test_tag_spellings_normalise_to_one(self) -> None:
        assert normalise("v1.2.3") == normalise("1.2.3") == "1.2.3"
        # A version that merely starts with a letter v is left alone.
        assert normalise("valid") == "valid"


# --------------------------------------------------------------------------- #
# 3. The comparison                                                            #
# --------------------------------------------------------------------------- #


class TestComparison:
    def test_agreement_is_compliant(self) -> None:
        ledger = ledger_recording("unpacksort", "pypi", "1.1.0")

        comparisons = compare_ledger_to_channels(
            ledger, readers(pypi=lambda _name: "1.1.0"), products=("unpacksort",)
        )

        assert [item.outcome for item in comparisons] == ["compliant"]

    def test_an_unreadable_channel_is_unverifiable_never_compliant(self) -> None:
        ledger = ledger_recording("unpacksort", "pypi", "1.1.0")

        comparisons = compare_ledger_to_channels(ledger, unreadable(), products=("unpacksort",))

        assert [item.outcome for item in comparisons] == ["unverifiable"]

    def test_a_not_applicable_channel_is_skipped(self) -> None:
        """media-sorter ships installers; asking PyPI about it is meaningless."""
        ledger = ledger_recording("media-sorter", "github_release", "1.2.5")

        comparisons = compare_ledger_to_channels(
            ledger,
            readers(github_release=lambda _owner, _repo: "1.2.5"),
            products=("media-sorter",),
        )

        assert [item.channel for item in comparisons] == ["github_release"]

    def test_the_unversioned_tap_is_never_compared(self) -> None:
        ledger = record(scaffold(), "homebrew-tap", "homebrew", version="unversioned")

        comparisons = compare_ledger_to_channels(ledger, unreadable())

        assert all(item.product != "homebrew-tap" for item in comparisons)

    def test_a_channel_with_nothing_recorded_is_not_compared(self) -> None:
        """`unverified` is `ledger.unverified`'s report, not this control's."""
        comparisons = compare_ledger_to_channels(scaffold(), unreadable())

        assert comparisons == ()

    def test_the_homebrew_identifier_resolves_to_a_formula_name(self) -> None:
        seen: list[str] = []
        ledger = ledger_recording("immich-export", "homebrew", "0.2.1")

        compare_ledger_to_channels(
            ledger,
            readers(homebrew=lambda formula: seen.append(formula) or "0.2.1"),  # type: ignore[func-returns-value]
            products=("immich-export",),
        )

        assert seen == ["immich-export"]

    def test_the_release_identifier_resolves_to_an_owner_and_a_repository(self) -> None:
        seen: list[tuple[str, str]] = []
        ledger = ledger_recording("immich-export", "github_release", "0.2.1")

        compare_ledger_to_channels(
            ledger,
            readers(
                github_release=lambda owner, repo: seen.append((owner, repo)) or "0.2.1"  # type: ignore[func-returns-value]
            ),
            products=("immich-export",),
        )

        assert seen == [("fileworks", "immich-export")]


# --------------------------------------------------------------------------- #
# 4. How it reports                                                            #
# --------------------------------------------------------------------------- #


class TestReporting:
    def test_the_control_applies_to_published_products_only(self) -> None:
        control = next(
            item for item in release_controls() if item.control_id == LEDGER_CHANNEL_CONTROL
        )

        assert "homebrew_tap" not in control.applies_to
        assert "governance_tool" not in control.applies_to
        assert control.needs_network is True

    def test_the_drift_report_names_product_channel_and_both_versions(self) -> None:
        comparison = ChannelComparison(
            product="immich-export",
            channel="pypi",
            identifier="immich-export",
            recorded="0.2.0",
            observed="0.2.1",
        )
        report = DriftReport(policy=PolicyReport(findings=list(findings((comparison,), CLASSES))))

        text = report.markdown()

        assert "immich-export" in text
        assert "pypi" in text
        assert "0.2.0" in text
        assert "0.2.1" in text
        assert report.stale_ledger

    def test_an_unverifiable_channel_produces_no_stale_finding(self) -> None:
        comparison = ChannelComparison(
            "unpacksort", "winget", "fileworks.unpacksort", "1.1.0", None
        )
        report = DriftReport(policy=PolicyReport(findings=list(findings((comparison,), CLASSES))))

        assert report.stale_ledger == ()
        assert report.blocking == ()

    def test_the_audit_leaves_the_ledger_byte_identical(self, tmp_path: Path) -> None:
        """Detection never amends. A tool that edits what it audits is trusted for neither."""
        path = ledger_recording("immich-export", "pypi", "0.2.0").write(tmp_path / "ledger.json")
        before = path.read_bytes()

        ledger = ReleaseLedger.read(path)
        results = findings(
            compare_ledger_to_channels(
                ledger, readers(pypi=lambda _name: "0.2.1"), products=("immich-export",)
            ),
            CLASSES,
        )

        assert any(item.outcome == "stale" for item in results)
        assert path.read_bytes() == before
