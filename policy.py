"""The desired state of every fileworks repository, and a read-only check of it.

This module answers one question — *does this repository have what its class
requires?* — and answers it without changing anything. Reconciliation is a
separate, explicitly authorized step; an evaluator that could also fix things
would inevitably be run against production settings by accident.

Every outcome is one of six, and the difference between the last two matters:
`missing` means the control is absent, while `unverifiable` means this run could
not tell. Reporting "compliant" for something nobody checked is the failure mode
a compliance tool exists to prevent.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

RepoClass = Literal["desktop_application", "python_cli", "homebrew_tap", "governance_tool"]
Outcome = Literal["compliant", "missing", "mismatched", "excepted", "stale", "unverifiable"]
POLICY_VERSION = "1"


@dataclass(frozen=True)
class FileControl:
    """A file the repository must have, optionally with required content."""

    control_id: str
    path: str
    #: Other paths that satisfy the same control. A quality workflow is a quality
    #: workflow whether it is called `ci.yml` or `quality.yml`; requiring one
    #: exact name would be policy for policy's sake.
    alternatives: tuple[str, ...] = ()
    #: Substrings that must appear. Kept deliberately loose: this checks that a
    #: repository *has* a security policy, not that it uses our exact wording.
    must_contain: tuple[str, ...] = ()
    applies_to: tuple[RepoClass, ...] = (
        "desktop_application",
        "python_cli",
        "homebrew_tap",
        "governance_tool",
    )
    rationale: str = ""


@dataclass(frozen=True)
class SettingControl:
    """A remote repository setting, which only an authenticated run can see."""

    control_id: str
    setting: str
    expected: str | bool
    applies_to: tuple[RepoClass, ...] = (
        "desktop_application",
        "python_cli",
        "homebrew_tap",
        "governance_tool",
    )
    rationale: str = ""
    #: Controls that must be observed green before this one may be applied.
    prerequisites: tuple[str, ...] = ()


@dataclass(frozen=True)
class PolicyException:
    """A documented, dated reason a control does not apply here.

    An exception without an owner and an expiry is just a disabled check, so
    both are required and a passed expiry makes the exception itself stale.
    """

    repository: str
    control_id: str
    reason: str
    owner: str
    expires_on: str

    def expired(self, *, today: datetime | None = None) -> bool:
        now = today or datetime.now(UTC)
        try:
            return datetime.fromisoformat(self.expires_on).replace(tzinfo=UTC) < now
        except ValueError:
            return True


@dataclass(frozen=True)
class Repository:
    """One repository, its class, and where it lives on this machine."""

    name: str
    repo_class: RepoClass
    path: Path
    description: str = ""


# --------------------------------------------------------------------------- #
# The manifest                                                                 #
# --------------------------------------------------------------------------- #


def file_controls() -> tuple[FileControl, ...]:
    return (
        FileControl(
            "readme",
            "README.md",
            must_contain=("## ",),
            rationale="Every repository states what it is and how to install it.",
        ),
        FileControl(
            "license",
            "LICENSE",
            must_contain=("MIT",),
            rationale="Public repositories carry an explicit licence.",
        ),
        FileControl(
            "changelog",
            "CHANGELOG.md",
            applies_to=("desktop_application", "python_cli"),
            rationale="Released products record what changed between versions.",
        ),
        FileControl(
            "security_policy",
            "SECURITY.md",
            rationale="A public repository says where to report a vulnerability.",
        ),
        FileControl(
            "contributing",
            "CONTRIBUTING.md",
            rationale="A public repository says how to propose a change.",
        ),
        FileControl(
            "codeowners",
            ".github/CODEOWNERS",
            rationale="Review routing is explicit rather than implied.",
        ),
        FileControl(
            "renovate",
            "renovate.json",
            must_contain=("extends",),
            rationale="Dependency updates are automated from a shared preset.",
        ),
        FileControl(
            "quality_workflow",
            ".github/workflows/ci.yml",
            alternatives=(".github/workflows/quality.yml",),
            rationale="Every push runs the class's quality gates.",
        ),
        FileControl(
            "release_workflow",
            ".github/workflows/release.yml",
            applies_to=("desktop_application", "python_cli"),
            rationale="Releases are automated, not hand-cut.",
        ),
        FileControl(
            "python_project",
            "pyproject.toml",
            applies_to=("python_cli", "governance_tool"),
            must_contain=("[project]", "requires-python"),
            rationale="Python packages declare their metadata in one place.",
        ),
    )


def setting_controls() -> tuple[SettingControl, ...]:
    """Remote settings. Every one of these needs an authenticated `gh` run."""
    return (
        SettingControl(
            "description",
            "description",
            expected="<non-empty>",
            rationale="The repository card says what the project is.",
        ),
        SettingControl(
            "delete_branch_on_merge",
            "delete_branch_on_merge",
            expected=True,
            rationale="Merged branches do not accumulate.",
        ),
        SettingControl(
            "allow_squash_merge",
            "allow_squash_merge",
            expected=True,
            rationale="One commit per change keeps the history readable.",
        ),
        SettingControl(
            "vulnerability_alerts",
            "security_and_analysis.dependabot_security_updates",
            expected=True,
            rationale="Known-vulnerable dependencies are surfaced automatically.",
        ),
        SettingControl(
            "default_branch_protection",
            "protection.main.required_status_checks",
            expected="<class gates>",
            prerequisites=("quality_workflow",),
            rationale="`main` only takes changes whose gates passed.",
        ),
        SettingControl(
            "actions_permissions",
            "actions.default_workflow_permissions",
            expected="read",
            rationale="Workflows get write access explicitly, never by default.",
        ),
    )


def repositories(root: Path) -> tuple[Repository, ...]:
    """Every in-scope Git repository, including this governance repository.

    The descriptions are the ones that go on the repository cards, so they say
    what the tool does rather than which organisation owns it — the owner is
    already on the page. `unpacksort`'s is the wording already published.
    """
    return (
        Repository(
            "media-sorter",
            "desktop_application",
            root / "media-sorter",
            "Offline desktop app to sort, deduplicate, and tag photos and video before import",
        ),
        Repository(
            "immich-export",
            "python_cli",
            root / "immich-export",
            "Export an Immich library to a plain local tree with albums, "
            "people, tags, and sidecars",
        ),
        Repository(
            "paperless-export",
            "python_cli",
            root / "paperless-export",
            "Export a Paperless-ngx archive and post-process it into a per-year tax view",
        ),
        Repository(
            "unpacksort",
            "python_cli",
            root / "unpacksort",
            "Safely unpack, deduplicate, classify, and sort nested mail and archive content",
        ),
        Repository(
            "homebrew-tap",
            "homebrew_tap",
            root / "homebrew-tap",
            "Homebrew tap for the fileworks command-line tools",
        ),
        Repository(
            "maintenance",
            "governance_tool",
            root / "maintenance",
            "Executable governance, release-evidence, and repository policy for fileworks",
        ),
    )


# --------------------------------------------------------------------------- #
# Evaluation                                                                   #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Finding:
    """One control, one repository, one outcome."""

    repository: str
    repo_class: RepoClass
    control_id: str
    outcome: Outcome
    detail: str = ""
    remediation: str = ""

    @property
    def compliant(self) -> bool:
        return self.outcome in {"compliant", "excepted"}


@dataclass
class PolicyReport:
    """The result of one read-only evaluation."""

    findings: list[Finding] = field(default_factory=list)
    evaluated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    policy_version: str = POLICY_VERSION
    #: True when remote settings could not be read, so their outcomes are
    #: `unverifiable` rather than absent.
    authenticated: bool = False

    @property
    def compliant(self) -> bool:
        return all(finding.compliant for finding in self.findings)

    def for_repository(self, name: str) -> tuple[Finding, ...]:
        return tuple(finding for finding in self.findings if finding.repository == name)

    def by_outcome(self, outcome: Outcome) -> tuple[Finding, ...]:
        return tuple(finding for finding in self.findings if finding.outcome == outcome)

    def to_dict(self) -> dict[str, object]:
        return {
            "policy_version": self.policy_version,
            "evaluated_at": self.evaluated_at,
            "authenticated": self.authenticated,
            "compliant": self.compliant,
            "findings": [
                {
                    "repository": finding.repository,
                    "class": finding.repo_class,
                    "control": finding.control_id,
                    "outcome": finding.outcome,
                    "detail": finding.detail,
                    "remediation": finding.remediation,
                }
                for finding in self.findings
            ],
        }


def evaluate(
    repos: Sequence[Repository],
    *,
    exceptions: Iterable[PolicyException] = (),
    controls: Sequence[FileControl] | None = None,
    settings: Sequence[SettingControl] | None = None,
    authenticated: bool = False,
    observations: Mapping[str, Mapping[str, object]] | None = None,
    today: datetime | None = None,
) -> PolicyReport:
    """Check every applicable control, changing nothing.

    This evaluator never shells out to `gh`, so it stays safe to run anywhere,
    including in a hook. Remote settings are therefore judged only against
    *observations* the caller passes in, and are `unverifiable` without them.

    Being authenticated is not evidence. A session can have every scope and
    still have looked at nothing; treating the credential as the answer is how a
    compliance tool ends up reporting green for checks nobody ran. All
    *authenticated* changes is the remediation wording.
    """
    index = {(item.repository, item.control_id): item for item in exceptions}
    report = PolicyReport(authenticated=authenticated)

    # `is None` rather than a falsy check: an explicitly empty sequence means
    # "evaluate no controls of this kind", not "fall back to all of them".
    active_files = file_controls() if controls is None else controls
    active_settings = setting_controls() if settings is None else settings

    for repo in repos:
        for control in active_files:
            if repo.repo_class not in control.applies_to:
                continue
            report.findings.append(
                _evaluate_file(repo, control, index.get((repo.name, control.control_id)), today)
            )
        for setting in active_settings:
            if repo.repo_class not in setting.applies_to:
                continue
            exception = index.get((repo.name, setting.control_id))
            if exception is not None and not exception.expired(today=today):
                report.findings.append(
                    Finding(
                        repo.name,
                        repo.repo_class,
                        setting.control_id,
                        "excepted",
                        detail=exception.reason,
                    )
                )
                continue
            report.findings.append(
                _evaluate_setting(
                    repo,
                    setting,
                    (observations or {}).get(repo.name),
                    authenticated=authenticated,
                )
            )
    return report


def _evaluate_setting(
    repo: Repository,
    control: SettingControl,
    observed: Mapping[str, object] | None,
    *,
    authenticated: bool,
) -> Finding:
    """Judge one remote setting against what was actually seen."""
    if observed is None or control.setting not in observed:
        return Finding(
            repo.name,
            repo.repo_class,
            control.control_id,
            "unverifiable",
            detail="nothing was observed for this setting",
            remediation=(
                "pass `observations=` from `reconcile.observe()`"
                if authenticated
                else "run `gh auth login`, then re-audit with `--authenticated`"
            ),
        )

    current = observed[control.setting]
    if _satisfies(control.expected, current):
        return Finding(
            repo.name,
            repo.repo_class,
            control.control_id,
            "compliant",
            detail=f"observed {current!r}",
        )
    return Finding(
        repo.name,
        repo.repo_class,
        control.control_id,
        "mismatched",
        detail=f"observed {current!r}, expected {control.expected!r}",
        remediation="plan and apply it with `maintenance.reconcile`",
    )


def _satisfies(expected: str | bool, current: object) -> bool:
    """Whether an observed value meets a control.

    Two controls are relative rather than absolute. A description only has to
    say something — the owner's own wording is theirs to keep, and a policy that
    demanded exact prose would rewrite good descriptions. Required checks are
    per class, and *which* names belong there is the reconciler's business,
    because only it knows how gates map onto job names; here the question is
    whether `main` requires any checks at all.
    """
    if expected == "<non-empty>":
        return bool(current)
    if expected == "<class gates>":
        return isinstance(current, (list, tuple)) and bool(current)
    return current == expected


def _evaluate_file(
    repo: Repository,
    control: FileControl,
    exception: PolicyException | None,
    today: datetime | None,
) -> Finding:
    if exception is not None:
        if exception.expired(today=today):
            return Finding(
                repo.name,
                repo.repo_class,
                control.control_id,
                "stale",
                detail=f"the exception expired on {exception.expires_on}",
                remediation="renew the exception with a new expiry, or satisfy the control",
            )
        return Finding(
            repo.name,
            repo.repo_class,
            control.control_id,
            "excepted",
            detail=exception.reason,
        )

    candidates = [repo.path / control.path] + [
        repo.path / alternative for alternative in control.alternatives
    ]
    try:
        path = next((item for item in candidates if item.is_file()), candidates[0])
        exists = path.is_file()
    except OSError as exc:
        return Finding(
            repo.name,
            repo.repo_class,
            control.control_id,
            "unverifiable",
            detail=f"{type(exc).__name__} while reading {control.path}",
        )
    if not exists:
        return Finding(
            repo.name,
            repo.repo_class,
            control.control_id,
            "missing",
            detail=f"{' or '.join([control.path, *control.alternatives])} is absent",
            remediation=f"add {control.path} — {control.rationale}",
        )
    if not control.must_contain:
        return Finding(repo.name, repo.repo_class, control.control_id, "compliant")

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return Finding(
            repo.name,
            repo.repo_class,
            control.control_id,
            "unverifiable",
            detail=f"{type(exc).__name__} while reading {control.path}",
        )
    absent = [needle for needle in control.must_contain if needle not in content]
    if absent:
        return Finding(
            repo.name,
            repo.repo_class,
            control.control_id,
            "mismatched",
            detail=f"{control.path} is missing: {', '.join(absent)}",
            remediation=f"update {control.path} — {control.rationale}",
        )
    return Finding(repo.name, repo.repo_class, control.control_id, "compliant")


def load_exceptions(path: Path) -> tuple[PolicyException, ...]:
    """Read the exception file, refusing entries that are not fully specified."""
    if not path.is_file():
        return ()
    payload = json.loads(path.read_text(encoding="utf-8"))
    parsed: list[PolicyException] = []
    for entry in payload.get("exceptions", []):
        missing = [
            key
            for key in ("repository", "control_id", "reason", "owner", "expires_on")
            if not entry.get(key)
        ]
        if missing:
            raise ValueError(f"exception is missing {', '.join(missing)}: {entry}")
        parsed.append(
            PolicyException(
                **{
                    key: entry[key]
                    for key in (
                        "repository",
                        "control_id",
                        "reason",
                        "owner",
                        "expires_on",
                    )
                }
            )
        )
    return tuple(parsed)
