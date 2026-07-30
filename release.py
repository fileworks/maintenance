"""What a release must produce, in what order, and how to recover when it doesn't.

A release that publishes to three channels can fail in three places, and the
interesting failures are the partial ones: the tag exists but PyPI does not have
the wheel, or PyPI has it and the formula still points at the previous version.
Those states are not errors the pipeline reports — they are states the world is
left in, and somebody has to be able to name and repair them.

So this module does three things. It declares what each repository class must
produce (`artifact_manifest`), it declares the order channels must be published
in and why (`SEQUENCE`), and it turns an observed set of channel states into the
specific recovery step that fixes it (`diagnose`).

Nothing here touches a network. It takes observations and returns judgements, so
the same code runs against real `gh` output and against a test fixture.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from maintenance.policy import RepoClass

Channel = Literal["github_release", "pypi", "homebrew", "winget"]
ChannelState = Literal["absent", "published", "mismatched", "unverified"]


# --------------------------------------------------------------------------- #
# Artifact manifests                                                           #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ArtifactSpec:
    """One file a release must produce, and how its presence is proven."""

    name: str
    pattern: str
    #: How a machine confirms the artifact is usable, not merely present.
    verification: str
    required: bool = True

    def matches(self, filename: str) -> bool:
        return re.fullmatch(self.pattern, filename) is not None


#: What each class ships. The verification column is the point: a release that
#: only checks that a file exists has checked nothing worth checking.
ARTIFACTS: dict[RepoClass, tuple[ArtifactSpec, ...]] = {
    "python_cli": (
        ArtifactSpec(
            "sdist",
            r".+-\d+\.\d+\.\d+\.tar\.gz",
            "pip install the sdist in a clean venv and run --version",
        ),
        ArtifactSpec(
            "wheel",
            r".+-\d+\.\d+\.\d+-py3-none-any\.whl",
            "pipx install the wheel and run the console script end to end",
        ),
        ArtifactSpec(
            "checksums",
            r"(SHA256SUMS|checksums\.txt)",
            "recompute every digest and compare",
        ),
    ),
    "desktop_application": (
        ArtifactSpec(
            "macos-arm64-dmg",
            r".+_aarch64\.dmg|.+-arm64\.dmg",
            "mount, copy to /Applications, launch, confirm the backend answers",
        ),
        ArtifactSpec(
            "macos-x64-dmg",
            r".+_x64\.dmg|.+-x64\.dmg",
            "mount, copy to /Applications, launch, confirm the backend answers",
        ),
        ArtifactSpec("windows-msi", r".+\.msi", "install, launch, uninstall, reinstall"),
        ArtifactSpec("windows-nsis", r".+-setup\.exe|.+\.exe", "install, launch, uninstall"),
        ArtifactSpec(
            "portable-zip",
            r".+portable.*\.zip",
            "extract and launch without installing",
        ),
        ArtifactSpec(
            "checksums",
            r"(SHA256SUMS|checksums\.txt)",
            "recompute every digest and compare",
        ),
    ),
    "homebrew_tap": (
        ArtifactSpec(
            "formula",
            r".+\.rb",
            "brew audit --strict --online, then install and run the test block",
            required=True,
        ),
    ),
}


@dataclass(frozen=True)
class ManifestCheck:
    """One artifact spec, against what a release actually produced."""

    spec: ArtifactSpec
    present: bool
    filename: str | None = None

    @property
    def blocking(self) -> bool:
        return self.spec.required and not self.present


def artifact_manifest(repo_class: RepoClass, filenames: list[str]) -> list[ManifestCheck]:
    """Which declared artifacts a release produced, and which it did not."""
    checks: list[ManifestCheck] = []
    for spec in ARTIFACTS.get(repo_class, ()):
        match = next((name for name in filenames if spec.matches(name)), None)
        checks.append(ManifestCheck(spec=spec, present=match is not None, filename=match))
    return checks


def manifest_complete(checks: list[ManifestCheck]) -> bool:
    return not any(check.blocking for check in checks)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def verify_checksums(directory: Path, checksum_file: Path) -> list[str]:
    """Recompute every digest in a checksum file. Returns the mismatches.

    A checksum file nobody recomputes is a text file. This is the recomputation.
    """
    problems: list[str] = []
    for line in checksum_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            problems.append(f"unreadable line: {line}")
            continue
        expected, name = parts[0], parts[-1].lstrip("*")
        target = directory / name
        if not target.is_file():
            problems.append(f"{name}: listed but not present")
            continue
        if sha256_file(target) != expected:
            problems.append(f"{name}: digest does not match")
    return problems


# --------------------------------------------------------------------------- #
# Sequencing                                                                   #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SequenceStep:
    """One channel, when it may be published, and why in that order."""

    channel: Channel
    after: tuple[Channel, ...]
    reason: str


#: The order is not arbitrary. The GitHub Release is the tag's evidence and must
#: exist before anything claims that version. PyPI follows because the formula
#: points at the PyPI sdist and cannot be written before it has a URL and digest.
#: WinGet is last because it references the GitHub asset.
SEQUENCE: tuple[SequenceStep, ...] = (
    SequenceStep("github_release", (), "the tag's evidence; everything else references it"),
    SequenceStep(
        "pypi",
        ("github_release",),
        "the sdist the formula will point at must exist before the formula does",
    ),
    SequenceStep(
        "homebrew",
        ("pypi",),
        "a formula needs the published URL and digest; it cannot be written earlier",
    ),
    SequenceStep(
        "winget",
        ("github_release",),
        "the manifest references the GitHub asset and its digest",
    ),
)


@dataclass(frozen=True)
class SequenceViolation:
    channel: Channel
    missing_prerequisite: Channel
    detail: str


def check_sequence(states: dict[Channel, ChannelState]) -> list[SequenceViolation]:
    """Whether anything was published before what it depends on."""
    violations: list[SequenceViolation] = []
    for step in SEQUENCE:
        if states.get(step.channel) != "published":
            continue
        for prerequisite in step.after:
            if states.get(prerequisite) != "published":
                violations.append(
                    SequenceViolation(
                        channel=step.channel,
                        missing_prerequisite=prerequisite,
                        detail=(
                            f"{step.channel} is published but {prerequisite} is not — {step.reason}"
                        ),
                    )
                )
    return violations


# --------------------------------------------------------------------------- #
# Diagnosis and recovery                                                       #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Playbook:
    """One named failure, what it looks like, and the steps that repair it."""

    key: str
    title: str
    symptom: str
    steps: tuple[str, ...]
    #: What must never be done in response, and why.
    never: str = ""


PLAYBOOKS: tuple[Playbook, ...] = (
    Playbook(
        "partial_publish",
        "Partial publish",
        "The tag and GitHub Release exist, but a later channel does not.",
        (
            "Confirm the release commit is the one CI went green on.",
            "Re-run the publish job for the missing channel only; the workflow is idempotent.",
            "If PyPI rejected the upload as a duplicate, the artifact is already there — verify "
            "its digest against the release asset rather than republishing.",
            "Re-run the formula bump last, once PyPI serves the sdist.",
        ),
        never="Never bump the version to force a fresh publish. A version that was never "
        "released to some channels is repaired, not skipped over.",
    ),
    Playbook(
        "duplicate_trigger",
        "Duplicate trigger",
        "Two release runs started for the same tag.",
        (
            "Let the first run finish; cancel the second.",
            "PyPI rejects the duplicate upload, which is the desired outcome.",
            "Check the tap received exactly one bump — a second would be a no-op commit.",
        ),
        never="Never delete and re-push the tag. Consumers may already have fetched it.",
    ),
    Playbook(
        "failed_formula_update",
        "Formula bump failed",
        "PyPI has the release; the formula still points at the previous version.",
        (
            "Read the queued bump issue in the tap; it records the requested formula and version.",
            "Confirm the PyPI sdist URL and sha256 by fetching them.",
            "Re-dispatch the bump, or edit the formula with those exact values and open a PR.",
            "brew audit --strict --online and brew install --build-from-source before merging.",
        ),
        never="Never hand-edit url or sha256 without fetching them; a wrong digest fails at "
        "install time on somebody else's machine.",
    ),
    Playbook(
        "artifact_mismatch",
        "Artifact mismatch",
        "A published artifact's digest does not match what CI built.",
        (
            "Treat the published artifact as untrusted until it is explained.",
            "Compare the release asset against the CI run's artifact for the same SHA.",
            "If they differ, yank the release, then investigate before republishing.",
            "Record the incident in the release ledger with state `failed`.",
        ),
        never="Never overwrite the artifact in place. The mismatch is evidence.",
    ),
    Playbook(
        "unverified_channel",
        "Channel could not be checked",
        "A channel's state is unknown because the check could not run.",
        (
            "Record it as `unverified` in the ledger — never as published.",
            "Re-run the audit with an authenticated session.",
            "Until then, no documentation may quote a version for that channel.",
        ),
    ),
)

PLAYBOOK_BY_KEY = {playbook.key: playbook for playbook in PLAYBOOKS}


@dataclass(frozen=True)
class Diagnosis:
    """What state a release is in, and which playbook applies."""

    healthy: bool
    playbook: Playbook | None
    detail: str

    @property
    def summary(self) -> str:
        if self.healthy:
            return "Every applicable channel is published and consistent."
        return f"{self.playbook.title if self.playbook else 'Unknown state'}: {self.detail}"


def diagnose(
    states: dict[Channel, ChannelState],
    *,
    applicable: tuple[Channel, ...],
) -> Diagnosis:
    """Turn observed channel states into the one playbook that applies.

    Order matters: a mismatched artifact is reported ahead of a missing one,
    because a wrong artifact is worse than an absent one.
    """
    relevant = {channel: states.get(channel, "unverified") for channel in applicable}

    mismatched = [channel for channel, state in relevant.items() if state == "mismatched"]
    if mismatched:
        return Diagnosis(
            False,
            PLAYBOOK_BY_KEY["artifact_mismatch"],
            f"{', '.join(mismatched)} does not match what was built",
        )

    unverified = [channel for channel, state in relevant.items() if state == "unverified"]
    if unverified:
        return Diagnosis(
            False,
            PLAYBOOK_BY_KEY["unverified_channel"],
            f"{', '.join(unverified)} could not be checked",
        )

    violations = check_sequence(relevant)
    if violations:
        return Diagnosis(
            False,
            PLAYBOOK_BY_KEY["failed_formula_update"]
            if any(v.channel == "homebrew" for v in violations)
            else PLAYBOOK_BY_KEY["partial_publish"],
            violations[0].detail,
        )

    absent = [channel for channel, state in relevant.items() if state == "absent"]
    if absent and len(absent) < len(relevant):
        return Diagnosis(
            False,
            PLAYBOOK_BY_KEY["partial_publish"],
            f"{', '.join(absent)} was never published",
        )
    if absent:
        return Diagnosis(False, None, "nothing has been published for this version")

    return Diagnosis(True, None, "")


# --------------------------------------------------------------------------- #
# Package metadata alignment                                                   #
# --------------------------------------------------------------------------- #


#: Metadata every Python CLI must declare identically in shape, if not in value.
REQUIRED_METADATA = (
    "name",
    "version",
    "description",
    "readme",
    "requires-python",
    "license",
    "authors",
    "classifiers",
)

#: URLs a package must expose so `pip show` and PyPI both lead somewhere useful.
REQUIRED_URLS = ("Homepage", "Issues", "Changelog")


@dataclass(frozen=True)
class MetadataIssue:
    repository: str
    field: str
    detail: str


def check_metadata(repository: str, pyproject: str) -> list[MetadataIssue]:
    """Check one pyproject for the metadata every CLI in the family declares."""
    issues: list[MetadataIssue] = []
    project = _section(pyproject, "project")
    for field_name in REQUIRED_METADATA:
        if not re.search(rf"^{re.escape(field_name)}\s*=", project, re.MULTILINE):
            issues.append(MetadataIssue(repository, field_name, "not declared in [project]"))

    urls = _section(pyproject, "project.urls")
    for url in REQUIRED_URLS:
        if url not in urls:
            issues.append(MetadataIssue(repository, f"urls.{url}", "not declared"))

    scripts = _section(pyproject, "project.scripts")
    if not scripts.strip():
        issues.append(MetadataIssue(repository, "scripts", "no console script is declared"))
    # The script *name* is the left-hand side; matching anywhere in the section
    # would be satisfied by the module path on the right, which is not the same
    # claim at all.
    elif not re.search(rf"^{re.escape(repository)}\s*=", scripts, re.MULTILINE):
        issues.append(
            MetadataIssue(
                repository,
                "scripts",
                f"the console script should be named `{repository}` so the "
                "command matches the package",
            )
        )
    return issues


def _section(pyproject: str, name: str) -> str:
    pattern = re.compile(rf"^\[{re.escape(name)}\]\s*$(.*?)(?=^\[|\Z)", re.MULTILINE | re.DOTALL)
    match = pattern.search(pyproject)
    return match.group(1) if match else ""


# --------------------------------------------------------------------------- #
# Formula verification                                                         #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class FormulaFacts:
    """What a formula claims, extracted without executing any Ruby."""

    name: str
    url: str | None
    sha256: str | None
    version: str | None
    has_test_block: bool
    test_is_meaningful: bool

    @property
    def complete(self) -> bool:
        return bool(self.url and self.sha256 and self.has_test_block)


#: A test block that only runs --version proves the binary exists and nothing
#: else. A meaningful one exercises the thing the tool is for.
_TRIVIAL_TEST = re.compile(r"assert_match.*--version|assert_match.*--help", re.IGNORECASE)


def read_formula(source: str, *, name: str) -> FormulaFacts:
    url = _first(r'url\s+"([^"]+)"', source)
    sha = _first(r'sha256\s+"([0-9a-f]{64})"', source)
    version = None
    if url:
        match = re.search(r"(\d+\.\d+\.\d+)", url)
        version = match.group(1) if match else None
    test_block = _block(source, "test do")
    return FormulaFacts(
        name=name,
        url=url,
        sha256=sha,
        version=version,
        has_test_block=bool(test_block.strip()),
        test_is_meaningful=bool(test_block.strip())
        and not all(
            _TRIVIAL_TEST.search(line) or not line.strip()
            for line in test_block.splitlines()
            if "assert" in line
        ),
    )


def _first(pattern: str, source: str) -> str | None:
    match = re.search(pattern, source)
    return match.group(1) if match else None


def _block(source: str, opener: str) -> str:
    start = source.find(opener)
    if start == -1:
        return ""
    depth = 0
    for index in range(start, len(source)):
        if source.startswith("do", index) or source.startswith(" if ", index):
            depth += 1
        if source.startswith("end", index):
            depth -= 1
            if depth == 0:
                return source[start:index]
    return source[start:]


@dataclass(frozen=True)
class FormulaIssue:
    formula: str
    detail: str


def check_formula(facts: FormulaFacts, expected_version: str | None) -> list[FormulaIssue]:
    """Whether a formula is complete, current, and actually tested."""
    issues: list[FormulaIssue] = []
    if not facts.url:
        issues.append(FormulaIssue(facts.name, "no url"))
    if not facts.sha256:
        issues.append(FormulaIssue(facts.name, "no sha256"))
    if not facts.has_test_block:
        issues.append(FormulaIssue(facts.name, "no test block"))
    elif not facts.test_is_meaningful:
        issues.append(
            FormulaIssue(
                facts.name,
                "the test block only checks --version or --help, which proves the binary "
                "exists and nothing more",
            )
        )
    if expected_version and facts.version and facts.version != expected_version:
        issues.append(
            FormulaIssue(
                facts.name,
                f"points at {facts.version} but the ledger says {expected_version}",
            )
        )
    return issues


# --------------------------------------------------------------------------- #
# Documentation                                                                #
# --------------------------------------------------------------------------- #


def playbook_markdown() -> str:
    """The recovery playbooks, as a document somebody can follow at 2 a.m."""
    lines = [
        "# Release recovery playbooks",
        "",
        "Each section is one state the world can be left in, how to recognise it, and",
        "what to do. The `Never` lines are the actions that turn a recoverable state",
        "into an unrecoverable one.",
        "",
    ]
    for playbook in PLAYBOOKS:
        lines += [
            f"## {playbook.title}",
            "",
            f"**Symptom.** {playbook.symptom}",
            "",
        ]
        lines += [f"{index}. {step}" for index, step in enumerate(playbook.steps, start=1)]
        if playbook.never:
            lines += ["", f"> **Never.** {playbook.never}"]
        lines.append("")
    lines += [
        "## Publication order",
        "",
        "| Channel | Only after | Why |",
        "|---|---|---|",
    ]
    for step in SEQUENCE:
        after = ", ".join(step.after) or "—"
        lines.append(f"| `{step.channel}` | {after} | {step.reason} |")
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Reading what is published, not what is checked out                           #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SourceRead:
    """File content, and which revision it actually came from."""

    content: str
    revision: str
    #: True when the working tree is not on the default branch, so a check
    #: against it would describe somebody's in-progress work rather than what
    #: users receive.
    working_tree_diverged: bool = False


def read_from_default_branch(
    repo_root: Path,
    relative: str,
    *,
    default_branch: str = "main",
    runner: Callable[[list[str]], tuple[int, str]] | None = None,
) -> SourceRead:
    """Read a file as the default branch has it, falling back to the checkout.

    A formula check that reads the working tree answers "what is on this
    machine", which is a different and much less interesting question than "what
    do users install". When the checkout is on a feature branch — as it often is
    mid-change — the two disagree and only one of them matters.
    """
    run = runner or _git_runner(repo_root)
    for reference in (f"origin/{default_branch}", default_branch):
        code, output = run(["show", f"{reference}:{relative}"])
        if code == 0:
            branch_code, branch = run(["rev-parse", "--abbrev-ref", "HEAD"])
            diverged = branch_code == 0 and branch.strip() not in {
                default_branch,
                reference,
            }
            return SourceRead(output, reference, diverged)

    path = repo_root / relative
    return SourceRead(
        path.read_text(encoding="utf-8") if path.is_file() else "",
        "working tree",
        working_tree_diverged=True,
    )


def _git_runner(repo_root: Path) -> Callable[[list[str]], tuple[int, str]]:
    def run(arguments: list[str]) -> tuple[int, str]:
        try:
            completed = subprocess.run(
                ["git", "-C", str(repo_root), *arguments],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return 1, ""
        return completed.returncode, completed.stdout

    return run
