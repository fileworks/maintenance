"""Regenerate the release ledger from captured, read-only observations.

Observation and mutation are deliberately separate. This canonical generator
contains the identifiers, timestamps, and evidence already gathered from public
channels; it never contacts or changes a publication service. Refresh the
captured facts through review, then run this script and commit its exact output.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from maintenance.ledger import (
    LEDGER_VERSION,
    Channel,
    HistoricalDisposition,
    HistoricalWorkflowOutcome,
    ReleaseLedger,
    record,
    record_historical,
    scaffold,
)

ROOT = Path(__file__).resolve().parent
LEDGER = ROOT / "release-ledger.json"
OBSERVED_AT = datetime(2026, 8, 24, 0, 0, tzinfo=UTC)

# Reviewed channel observations are generator input. The generated ledger is
# deliberately never read as input: otherwise an unreviewed hand edit to its
# owner, product, or untouched channel fields would silently become canonical.
CAPTURED_CHANNELS: tuple[tuple[str, Channel, str | None, str, datetime], ...] = (
    (
        "media-sorter",
        "github_release",
        "1.4.4",
        "observed on github_release",
        datetime(2026, 8, 13, 18, 57, 4, 231472, tzinfo=UTC),
    ),
    (
        "immich-export",
        "github_release",
        "1.0.1",
        "observed on github_release",
        datetime(2026, 8, 13, 18, 7, 39, 913094, tzinfo=UTC),
    ),
    (
        "immich-export",
        "homebrew",
        "1.0.1",
        "observed on homebrew",
        datetime(2026, 8, 13, 18, 7, 39, 913106, tzinfo=UTC),
    ),
    (
        "immich-export",
        "pypi",
        "1.0.1",
        "observed on pypi",
        datetime(2026, 8, 13, 18, 7, 39, 913111, tzinfo=UTC),
    ),
    (
        "paperless-export",
        "github_release",
        "2.0.1",
        "observed on github_release",
        datetime(2026, 8, 13, 18, 7, 39, 913117, tzinfo=UTC),
    ),
    (
        "paperless-export",
        "homebrew",
        "2.0.1",
        "observed on homebrew",
        datetime(2026, 8, 13, 18, 7, 39, 913122, tzinfo=UTC),
    ),
    (
        "paperless-export",
        "pypi",
        "2.0.1",
        "observed on pypi",
        datetime(2026, 8, 13, 18, 7, 39, 913125, tzinfo=UTC),
    ),
    (
        "unpacksort",
        "github_release",
        "1.1.6",
        (
            "GitHub Releases API release 373890356: tag v1.1.6; draft=false; "
            "prerelease=false; SHA256SUMS, wheel, Windows x64 ZIP, and sdist assets"
        ),
        OBSERVED_AT,
    ),
    (
        "unpacksort",
        "pypi",
        "1.1.6",
        "PyPI JSON info.version=1.1.6; wheel and sdist files present",
        OBSERVED_AT,
    ),
    (
        "unpacksort",
        "homebrew",
        "1.1.6",
        (
            "HEAD Formula/unpacksort.rb uses unpacksort-1.1.6.tar.gz with sha256 "
            "eeb355e9665bc8e4807a8d0ee18d5a3a973757092cdff5bb3865ab47e7361c85"
        ),
        OBSERVED_AT,
    ),
    (
        "homebrew-tap",
        "homebrew",
        "unversioned",
        "the live tap is unversioned; all three formulas are audited",
        datetime(2026, 8, 1, 12, 52, 23, 818086, tzinfo=UTC),
    ),
)

# Tag SHA, exact tag-triggered Release run, and outcome. These came from the
# read-only GitHub Actions/tag inventory on 2026-08-21. The successful v1.1.7
# run is intentionally not normalized into the failed rows: its missing release
# has a different and currently unknowable cause.
MEDIA_SORTER_UNRELEASED: dict[str, tuple[str, int, HistoricalWorkflowOutcome]] = {
    "v1.0.0": ("3e26477d8b27a12b199149d71fc32ba3c67e3632", 29208406731, "cancelled"),
    "v1.0.5": ("943d473c235fb9be78ecba8e8b832cf466d790e8", 30027294290, "failure"),
    "v1.1.0": ("79688b7176f768d43152667297987efd6db5cd66", 30563182505, "failure"),
    "v1.1.1": ("b4f76085b6dc800540f616753785171f31e58a31", 30565751987, "failure"),
    "v1.1.2": ("15a5d62f7e16b6c27e38749897e55b4d26637a57", 30577553311, "failure"),
    "v1.1.3": ("16189060d89b7618c252504c94c1ee7729a02e8b", 30579828010, "failure"),
    "v1.1.4": ("c99d51e085e00aa834b1ce2a39b302f2db4063bb", 30581744596, "failure"),
    "v1.1.5": ("ace26751e0ef0db60734b37e8b34b31b1d2f767d", 30583199231, "failure"),
    "v1.1.6": ("b32c73bb9764f565fdcb8134431d7f7a30f2fd33", 30585853759, "failure"),
    "v1.1.7": ("d3c08c3133c3c2417fb4a181d8242ab9f2b733c9", 30588254277, "success"),
    "v1.2.0": ("3d4885b3462794dabd4bf932cecce754f32eefc2", 30696543449, "failure"),
    "v1.2.1": ("ba75c87deb61724cea2d8a13131a2f016aa09ee0", 30698119234, "cancelled"),
    "v1.2.3": ("0ce77cd351c026366a5892a6e4589414c05e7492", 30711692081, "failure"),
    "v1.2.4": ("17ca8106cd42404f5d6eee708355eb953dc8339a", 30722368852, "failure"),
}

EMPTY_EXPORTER_RELEASES = {
    "immich-export": ("ee7b84b27812e24920452773464ac28e3a1ffcf8", 352933988),
    "paperless-export": ("d9c5730909588777c5f83d8527d68fb53b25a122", 352933990),
}

MEDIA_SORTER_ABSENT_TAGS = frozenset(MEDIA_SORTER_UNRELEASED) - {"v1.0.0"}


def regenerate() -> ReleaseLedger:
    """Apply the captured observations and exact historical inventory."""
    ledger = scaffold()
    ledger.ledger_version = LEDGER_VERSION
    for product, channel, version, detail, observed_at in CAPTURED_CHANNELS:
        record(
            ledger,
            product,
            channel,
            version=version,
            detail=detail,
            observed_at=observed_at,
        )
    record(
        ledger,
        "unpacksort",
        "winget",
        version=None,
        state="unverified",
        detail=(
            "Official catalog unavailable: bootstrap PR 410897 closed unmerged with "
            "Needs-CLA; no version inferred"
        ),
        observed_at=OBSERVED_AT,
    )

    # This list is canonical rather than additive. An unusual object is either
    # represented here with evidence or absent from the generated ledger.
    ledger.historical_dispositions = []
    for tag, (commit_sha, run_id, outcome) in MEDIA_SORTER_UNRELEASED.items():
        absent_tag = tag in MEDIA_SORTER_ABSENT_TAGS
        if outcome == "success":
            reason = (
                "The Release run concluded success but neither its tag nor a release is "
                "present; deletion audit history is unavailable, so the cause is unknown."
            )
        elif absent_tag:
            reason = (
                f"The Release run concluded {outcome}; neither its tag nor a release is "
                "present. The retained run does not establish when or why the tag disappeared."
            )
        else:
            reason = (
                f"The tag-triggered Release run concluded {outcome}; no release object is "
                "present. The exact failed or cancelled boundary remains in the run evidence."
            )
        record_historical(
            ledger,
            HistoricalDisposition(
                repository="media-sorter",
                product="media-sorter",
                kind="absent_tag" if absent_tag else "tag_without_release",
                identifier=tag,
                commit_sha=commit_sha,
                release_id=None,
                asset_count=None,
                workflow_run_id=run_id,
                workflow_outcome=outcome,
                intended_asset_state=(
                    "A GitHub Release was intended by the historical Release workflow; the "
                    "exact historical asset set is unproven."
                ),
                observed_at=OBSERVED_AT.isoformat(),
                evidence=(
                    (
                        f"Git refs API and Releases API both omitted {tag} on 2026-08-24; "
                        f"the retained workflow names commit {commit_sha}; "
                    )
                    if absent_tag
                    else (f"Tag resolves to {commit_sha}; GitHub Releases API omitted {tag}; ")
                )
                + (
                    f"Release run https://github.com/fileworks/media-sorter/actions/runs/"
                    f"{run_id} concluded {outcome}."
                ),
                disposition=(
                    "Preserve the observed absence; do not recreate the tag or release."
                    if absent_tag
                    else "Preserve the immutable tag; make no metadata mutation."
                ),
                reason=reason,
                recovery_path=(
                    "With object-specific authorization, review the historical commit and "
                    "captured run before considering any tag or release recreation."
                    if absent_tag
                    else "With object-specific authorization, review the tag commit and "
                    "captured run before considering a metadata-only release; preserve the tag."
                ),
            ),
        )

    for repository, (commit_sha, release_id) in EMPTY_EXPORTER_RELEASES.items():
        record_historical(
            ledger,
            HistoricalDisposition(
                repository=repository,
                product=repository,
                kind="empty_release",
                identifier="v0.0.2",
                commit_sha=commit_sha,
                release_id=release_id,
                asset_count=0,
                workflow_run_id=None,
                workflow_outcome="unobserved",
                intended_asset_state=(
                    "The release object exists with zero assets; whether assets were "
                    "originally intended is unproven."
                ),
                observed_at=OBSERVED_AT.isoformat(),
                evidence=(
                    f"GitHub release API object {release_id} for v0.0.2 reported assets=0; "
                    f"tag resolves to {commit_sha}; retained Actions history exposed no "
                    "associated run."
                ),
                disposition="Preserve the empty historical release; do not synthesize assets.",
                reason=(
                    "The API currently reports an empty release; retained workflow history "
                    "does not establish why, so the cause remains unknown."
                ),
                recovery_path=(
                    "With object-specific authorization, publish a new corrected version if "
                    "needed; never replace this immutable release."
                ),
            ),
        )

    ledger.generated_at = OBSERVED_AT.isoformat()
    return ledger


def rendered() -> str:
    ledger = regenerate()
    return json.dumps(ledger.to_dict(), indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if the ledger is stale.")
    args = parser.parse_args(argv)
    expected = rendered()
    if args.check:
        if LEDGER.read_text(encoding="utf-8") != expected:
            print("release-ledger.json is stale; run refresh_release_ledger.py")
            return 1
        print("release-ledger.json matches captured observations")
        return 0
    LEDGER.write_text(expected, encoding="utf-8")
    print(f"wrote {LEDGER}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
