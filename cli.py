"""One command that says whether the fileworks repositories are in policy.

    python -m maintenance.cli            # evaluate and print the report
    python -m maintenance.cli --json out.json
    python -m maintenance.cli --matrix   # the compliance table
    python -m maintenance.cli --offline  # contact no publication channel

It never writes to a repository and never touches a remote setting. Remote
controls are reported `unverifiable` until an authenticated run supplies their
observed values, which is a deliberately separate step.

It does read the public publication channels, because a recorded version nobody
re-checked is a claim rather than a fact. That read is comparison only: nothing
here amends the ledger it audits. A channel it cannot reach is `unverifiable`,
so an offline run degrades instead of certifying what it did not see.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from maintenance.channels import (
    Readers,
    compare_ledger_to_channels,
    live_readers,
    unreadable,
)
from maintenance.channels import findings as channel_findings
from maintenance.docs import check_readme
from maintenance.drift import DriftReport, PlannedChange, compliance_matrix, plan_settings
from maintenance.ledger import ReleaseLedger, scaffold
from maintenance.policy import (
    LEDGER_CHANNEL_CONTROL,
    Finding,
    Repository,
    evaluate,
    evaluate_python_support,
    load_exceptions,
    release_controls,
    repositories,
)
from maintenance.reconcile import gh_client, observe, pull_request_checks
from maintenance.worktree import inspect as inspect_tree

LEDGER_PATH = Path(__file__).parent / "release-ledger.json"
EXCEPTIONS_PATH = Path(__file__).parent / "exceptions.json"


def observe_settings(
    repos: Sequence[Repository], owner: str = "fileworks"
) -> dict[str, dict[str, object]]:
    """Read every repository's remote settings. Read-only, and never fatal.

    A repository that cannot be reached is left out of the mapping entirely, so
    it is reported `unverifiable` — the one honest answer for "we could not
    look". Filling in a default here is how a fetch failure would come back as
    a clean bill of health.
    """
    client = gh_client()
    observed: dict[str, dict[str, object]] = {}
    for repo in repos:
        try:
            observed[repo.name] = dict(observe(repo, owner, client))
        except OSError:
            continue
    return observed


def verify_channels(
    repos: Sequence[Repository],
    ledger: ReleaseLedger,
    readers: Readers,
) -> list[Finding]:
    """Compare the recorded release state to the channels that serve it.

    Applicability is per class, so the tap and this governance package are not
    asked about a version they do not publish. Nothing here writes to the
    ledger: detection and amendment stay separate acts.
    """
    applicable = {control.control_id: control.applies_to for control in release_controls()}.get(
        LEDGER_CHANNEL_CONTROL, ()
    )
    classes = {repo.name: repo.repo_class for repo in repos if repo.repo_class in applicable}
    comparisons = compare_ledger_to_channels(ledger, readers, products=tuple(classes))
    return list(channel_findings(comparisons, classes))


def build_report(
    root: Path,
    *,
    authenticated: bool = False,
    readers: Readers | None = None,
) -> DriftReport:
    repos = repositories(root)
    ledger = ReleaseLedger.read(LEDGER_PATH) if LEDGER_PATH.is_file() else scaffold()
    observations = observe_settings(repos) if authenticated else None
    policy = evaluate(
        repos,
        exceptions=load_exceptions(EXCEPTIONS_PATH),
        authenticated=authenticated,
        observations=observations,
    )
    # Runs without `--authenticated`: PyPI and the tap are public, and a reader
    # that cannot reach its channel answers `unverifiable` rather than failing
    # the run. That is the point — an offline audit degrades, it does not lie.
    policy.findings += verify_channels(repos, ledger, readers or live_readers(gh_client()))
    policy.findings += evaluate_python_support(repos)
    documentation = [
        issue
        for repo in repos
        if repo.path.is_dir()
        for issue in check_readme(repo.name, repo.repo_class, repo.path, ledger)
    ]
    trees = [state for repo in repos if (state := inspect_tree(repo.name, repo.path)) is not None]

    # Only with a session: the plan for branch protection is meaningless without
    # the check names a pull request actually reports, and those have to be read.
    planned: list[PlannedChange] = []
    if authenticated and observations is not None:
        client = gh_client()
        for repo in repos:
            planned += plan_settings(
                repo,
                dict(observations.get(repo.name, {})),
                policy,
                checks=pull_request_checks(repo.name, "fileworks", client),
            )

    return DriftReport(policy=policy, documentation=documentation, trees=trees, planned=planned)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate fileworks repository policy.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--json", type=Path, help="Write the machine-readable report here.")
    parser.add_argument("--matrix", action="store_true", help="Print the compliance matrix.")
    parser.add_argument(
        "--authenticated",
        action="store_true",
        help="Read remote settings through `gh`; without it they are unverifiable.",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Contact no publication channel; release-state controls report unverifiable.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when anything is out of policy.",
    )
    args = parser.parse_args(argv)

    report = build_report(
        args.root,
        authenticated=args.authenticated,
        readers=unreadable() if args.offline else None,
    )
    print(report.markdown())
    if args.matrix:
        print()
        print(compliance_matrix(report.policy, repositories(args.root)))
    if args.json:
        report.write(args.json)
    return 1 if args.strict and not report.clean else 0


if __name__ == "__main__":
    sys.exit(main())
