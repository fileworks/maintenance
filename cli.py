"""One command that says whether the fileworks repositories are in policy.

    python -m maintenance.cli            # evaluate and print the report
    python -m maintenance.cli --json out.json
    python -m maintenance.cli --matrix   # the compliance table

It never writes to a repository and never touches a remote setting. Remote
controls are reported `unverifiable` until an authenticated run supplies their
observed values, which is a deliberately separate step.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from maintenance.docs import check_readme
from maintenance.drift import DriftReport, compliance_matrix
from maintenance.ledger import ReleaseLedger, scaffold
from maintenance.policy import Repository, evaluate, load_exceptions, repositories
from maintenance.reconcile import gh_client, observe

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


def build_report(root: Path, *, authenticated: bool = False) -> DriftReport:
    repos = repositories(root)
    ledger = ReleaseLedger.read(LEDGER_PATH) if LEDGER_PATH.is_file() else scaffold()
    policy = evaluate(
        repos,
        exceptions=load_exceptions(EXCEPTIONS_PATH),
        authenticated=authenticated,
        observations=observe_settings(repos) if authenticated else None,
    )
    documentation = [
        issue
        for repo in repos
        if repo.path.is_dir()
        for issue in check_readme(repo.name, repo.repo_class, repo.path, ledger)
    ]
    return DriftReport(policy=policy, documentation=documentation)


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
        "--strict",
        action="store_true",
        help="Exit non-zero when anything is out of policy.",
    )
    args = parser.parse_args(argv)

    report = build_report(args.root, authenticated=args.authenticated)
    print(report.markdown())
    if args.matrix:
        print()
        print(compliance_matrix(report.policy, repositories(args.root)))
    if args.json:
        report.write(args.json)
    return 1 if args.strict and not report.clean else 0


if __name__ == "__main__":
    sys.exit(main())
