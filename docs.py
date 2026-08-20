"""README structure per repository class, and checks that it stays true.

A README goes wrong in two ways: it loses a section people need, or it keeps a
section that no longer describes reality. The first is caught by requiring an
information architecture per class; the second by checking documented install
commands and versions against the release ledger rather than against memory.

Nothing here rewrites a README. It reports what is missing or contradicted, so
the product-specific prose a human wrote is never replaced by a template.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from maintenance.ledger import ReleaseLedger
from maintenance.policy import RepoClass

#: The sections a reader needs, in the order they need them.
SECTIONS: dict[RepoClass, tuple[str, ...]] = {
    "desktop_application": (
        "Overview",
        "Status",
        "Install",
        "Quick start",
        "Usage",
        "Configuration",
        "Troubleshooting",
        "Development",
        "Security",
        "License",
    ),
    "python_cli": (
        "Overview",
        "Status",
        "Install",
        "Quick start",
        "Usage",
        "Configuration",
        "Troubleshooting",
        "Development",
        "Security",
        "License",
    ),
    "homebrew_tap": ("Overview", "Install", "Formulas", "Development", "License"),
    "governance_tool": (
        "Overview",
        "Usage",
        "Policy",
        "Dependency automation",
        "Gate alignment",
        "Development",
        "Security",
        "License",
    ),
}

#: Install commands each class is expected to document, as regular expressions.
INSTALL_PATTERNS: dict[RepoClass, tuple[tuple[str, str], ...]] = {
    "python_cli": (
        (r"pipx install\s+\S+", "a pipx install line"),
        (r"brew install\s+\S+", "a Homebrew install line"),
    ),
    "desktop_application": ((r"\.dmg|\.msi|\.exe|Releases", "a link to the installers"),),
    "homebrew_tap": ((r"brew tap\s+\S+", "a `brew tap` line"),),
    "governance_tool": ((r"python -m maintenance\.cli", "the maintenance audit command"),),
}

_HEADING = re.compile(r"^#{1,3}\s+(.+?)\s*$", re.MULTILINE)

#: A quoted version, and deliberately not an IP address: `127.0.0.1` matches a
#: naive three-part pattern, and reporting a loopback address as a stale release
#: is exactly the kind of false positive that gets a check switched off.
_VERSION = re.compile(r"(?<![\d.])\d+\.\d+\.\d+(?![\d.])")


@dataclass(frozen=True)
class DocIssue:
    """One thing a README does not say, or says wrongly."""

    repository: str
    kind: str
    detail: str
    remediation: str = ""


def headings(markdown: str) -> tuple[str, ...]:
    return tuple(match.group(1).strip() for match in _HEADING.finditer(markdown))


def check_structure(
    repository: str,
    repo_class: RepoClass,
    markdown: str,
) -> tuple[DocIssue, ...]:
    """Which required sections are absent. Order is advisory, presence is not."""
    present = {heading.lower() for heading in headings(markdown)}
    issues: list[DocIssue] = []
    for section in SECTIONS[repo_class]:
        if not any(section.lower() in heading for heading in present):
            issues.append(
                DocIssue(
                    repository,
                    "missing_section",
                    f"no “{section}” section",
                    f"add a “{section}” heading — every {repo_class.replace('_', ' ')} has one",
                )
            )
    return tuple(issues)


def check_install_commands(
    repository: str,
    repo_class: RepoClass,
    markdown: str,
) -> tuple[DocIssue, ...]:
    """Whether the README actually tells a reader how to install the thing."""
    issues: list[DocIssue] = []
    for pattern, description in INSTALL_PATTERNS.get(repo_class, ()):
        if re.search(pattern, markdown, re.IGNORECASE) is None:
            issues.append(
                DocIssue(
                    repository,
                    "missing_install",
                    f"no {description}",
                    "document the supported install route, or remove the claim that it exists",
                )
            )
    return tuple(issues)


#: Where a version number is a claim about *this* product rather than a mention
#: of something else. A README that says "works with Immich 3.1.0" is not making
#: a release claim, and flagging it would train people to ignore this check.
_CLAIM_MARKERS = ("install", "version", "release", "badge", "shields.io", "pypi.org")

#: …unless the line is plainly about something else. A README that documents
#: "the Immich v3 API (spec version 3.0.1)" is not claiming its own version, and
#: a check that flagged it would be switched off within a week.
_OTHER_SUBJECT = (
    "api",
    "spec",
    "compatib",
    "immich",
    "paperless",
    "python ",
    "requires",
)


def _quoted_versions(repository: str, markdown: str) -> set[str]:
    """Versions this README appears to claim for itself."""
    package = repository.replace("_", "-")
    found: set[str] = set()
    for line in markdown.splitlines():
        lowered = line.lower()
        if any(subject in lowered for subject in _OTHER_SUBJECT):
            continue
        if package not in lowered and not any(marker in lowered for marker in _CLAIM_MARKERS):
            continue
        found.update(_VERSION.findall(line))
    return found


def check_versions(
    repository: str,
    markdown: str,
    ledger: ReleaseLedger,
) -> tuple[DocIssue, ...]:
    """Hard-coded versions that disagree with the ledger.

    A README quoting a version at all is a small liability; quoting a *wrong*
    one is a support ticket. Anything the ledger cannot verify is reported as
    unverifiable rather than as a mismatch.
    """
    product = ledger.product(repository)
    quoted = _quoted_versions(repository, markdown)
    if not quoted:
        return ()
    if product is None:
        return (
            DocIssue(
                repository,
                "unverifiable_version",
                f"quotes {', '.join(sorted(quoted))} but is not in the ledger",
                "add the product to the ledger, or stop quoting a version here",
            ),
        )
    released = product.released_version
    if released is None:
        return (
            DocIssue(
                repository,
                "unverifiable_version",
                f"quotes {', '.join(sorted(quoted))} while no channel is verified",
                "verify a release channel before quoting a version",
            ),
        )
    stale = sorted(version for version in quoted if version != released)
    if not stale:
        return ()
    return (
        DocIssue(
            repository,
            "stale_version",
            f"quotes {', '.join(stale)} but the ledger says {released}",
            "regenerate the status section from the ledger",
        ),
    )


def check_links(repository: str, markdown: str, repo_root: Path) -> tuple[DocIssue, ...]:
    """Relative links that point at files which are not there."""
    issues: list[DocIssue] = []
    for match in re.finditer(r"\[[^\]]*\]\(([^)#]+)\)", markdown):
        target = match.group(1).strip()
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        if not (repo_root / target).exists():
            issues.append(
                DocIssue(
                    repository,
                    "broken_link",
                    f"{target} does not exist",
                    "fix or remove the link",
                )
            )
    return tuple(issues)


def check_icon(repository: str, markdown: str) -> tuple[DocIssue, ...]:
    """Whether the README actually shows the approved mark.

    Reported rather than asserted. Whether another repository has adopted the
    icon is a fact about that repository's `main`, not a property this package
    can hold true, so a repository that has not adopted it yet must show up as
    one line of drift instead of a failing test here.
    """
    if ".github/icon.svg" in markdown:
        return ()
    return (
        DocIssue(
            repository,
            "missing_icon",
            "the README does not show .github/icon.svg",
            "run the branding rollout and commit the README change",
        ),
    )


def check_readme(
    repository: str,
    repo_class: RepoClass,
    repo_root: Path,
    ledger: ReleaseLedger | None = None,
) -> tuple[DocIssue, ...]:
    """Every documentation check for one repository, in one call."""
    path = repo_root / "README.md"
    if not path.is_file():
        return (DocIssue(repository, "missing_readme", "README.md is absent", "add a README"),)
    markdown = path.read_text(encoding="utf-8", errors="replace")
    issues = (
        check_structure(repository, repo_class, markdown)
        + check_install_commands(repository, repo_class, markdown)
        + check_links(repository, markdown, repo_root)
    )
    # The approved Kontur family identifies all six repositories. Governance
    # is a different product class, not an exception to repository identity.
    issues += check_icon(repository, markdown)
    if ledger is not None:
        issues += check_versions(repository, markdown, ledger)
    return issues


def status_section(repository: str, ledger: ReleaseLedger) -> str:
    """The generated Status block — the one part of a README that is not prose."""
    product = ledger.product(repository)
    if product is None:
        return "## Status\n\nNot yet tracked in the release ledger.\n"
    lines = ["## Status", ""]
    for entry in product.channels:
        if entry.state == "not_applicable":
            continue
        lines.append(f"- **{entry.channel.replace('_', ' ')}**: {entry.displayable}")
    if product.channels_disagree:
        lines.append("")
        lines.append("> Channels currently disagree about the version; treat this as unverified.")
    return "\n".join(lines) + "\n"


TEMPLATES: dict[RepoClass, str] = {
    "python_cli": """# {name}

{description}

## Overview

What this tool does, and what it deliberately does not do.

{status}

## Install

```bash
pipx install {package}
# or
brew install fileworks/tap/{package}
```

## Quick start

```bash
{package} --help
```

## Usage

The commands, their options, and what each one writes.

## Configuration

Environment variables and configuration files, with their defaults.

## Troubleshooting

What the common failures look like and what to do about them.

## Development

```bash
uv sync --all-extras --dev
uv run pytest -q
```

## Security

Report vulnerabilities as described in [SECURITY.md](SECURITY.md).

## License

MIT — see [LICENSE](LICENSE).
""",
    "homebrew_tap": """# {name}

{description}

## Overview

The Homebrew tap for the fileworks command-line tools.

## Install

```bash
brew tap fileworks/tap
```

## Formulas

Each formula and what it installs.

## Development

Formulas are bumped automatically by each product's release pipeline.

## License

MIT — see [LICENSE](LICENSE).
""",
}


def render_template(
    repo_class: RepoClass,
    *,
    name: str,
    description: str,
    package: str,
    ledger: ReleaseLedger | None = None,
) -> str:
    """A starting README for a class — a scaffold, never a replacement."""
    template = TEMPLATES.get(repo_class)
    if template is None:
        raise KeyError(f"no template for {repo_class!r}")
    status = status_section(name, ledger) if ledger is not None else "## Status\n\nUnreleased.\n"
    return template.format(
        name=name, description=description, package=package, status=status.rstrip()
    )


#: The workspace documents that quote product versions. They live above every
#: repository, so no repository's CI reads them — which is exactly why they went
#: stale (`P-03`/`P-04`): three of them named versions that were two releases old
#: and one called a released tool unreleased.
WORKSPACE_DOCUMENTS: tuple[str, ...] = (
    "CLAUDE.md",
    "planning/reference/release-status.md",
    ".mex/ROUTER.md",
)


#: An escape hatch a document can use on a line whose version belongs to
#: something else — an action ref, a toolchain, an upstream server. Written into
#: the document rather than guessed at by this module, so the exception is
#: visible to whoever reads the line and wonders why it is not checked.
VERSION_CHECK_IGNORE = "version-check: ignore"


def _subject_key(text: str) -> str:
    """`MediaSorter`, `media-sorter` and `Media Sorter` are one subject."""
    return "".join(character for character in text.lower() if character.isalnum())


def check_workspace_versions(workspace: Path, ledger: ReleaseLedger) -> tuple[DocIssue, ...]:
    """Version claims in the workspace documents, checked against the ledger.

    Deliberately *not* `check_versions`, which a README gets. That one excludes
    any line mentioning `immich` or `paperless` so an exporter's README quoting
    the upstream server's version is not mistaken for its own — and in these
    documents those are precisely the lines that matter. Reusing it here found
    nothing while `CLAUDE.md` was two releases stale.

    So the association is explicit instead of heuristic: a version is compared
    against a product only when that product is the single subject named on the
    line. A line naming several products cannot say which version belongs to
    which, so it is only faulted for quoting a version that is nobody's current
    one — which is still enough to catch the stale tap line.
    """
    issues: list[DocIssue] = []
    current = {
        _subject_key(product.repository): product.released_version for product in ledger.products
    }
    known_versions = {version for version in current.values() if version}

    for relative in WORKSPACE_DOCUMENTS:
        path = workspace / relative
        if not path.is_file():
            issues.append(
                DocIssue(
                    relative,
                    "missing_document",
                    f"{relative} is not present in {workspace}",
                    "point the check at the workspace root, or update the document list",
                )
            )
            continue

        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if VERSION_CHECK_IGNORE in line:
                continue
            quoted = set(_VERSION.findall(line))
            if not quoted:
                continue
            key = _subject_key(line)
            named = [repository for repository in current if repository in key]
            if len(named) == 1:
                expected = current[named[0]]
                wrong = sorted(version for version in quoted if version != expected)
                if wrong and expected:
                    issues.append(
                        DocIssue(
                            relative,
                            "stale_version",
                            f"line {number} says {named[0]} is "
                            f"{', '.join(wrong)} but the ledger says {expected}",
                            f"update the document to {expected}, or correct the ledger",
                        )
                    )
            elif len(named) > 1:
                orphaned = sorted(version for version in quoted if version not in known_versions)
                if orphaned:
                    issues.append(
                        DocIssue(
                            relative,
                            "stale_version",
                            f"line {number} names {', '.join(sorted(named))} and quotes "
                            f"{', '.join(orphaned)}, which is no product's current version",
                            "state one product per line, or update the versions",
                        )
                    )
    return tuple(issues)
