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
}

#: Install commands each class is expected to document, as regular expressions.
INSTALL_PATTERNS: dict[RepoClass, tuple[tuple[str, str], ...]] = {
    "python_cli": (
        (r"pipx install\s+\S+", "a pipx install line"),
        (r"brew install\s+\S+", "a Homebrew install line"),
    ),
    "desktop_application": ((r"\.dmg|\.msi|\.exe|Releases", "a link to the installers"),),
    "homebrew_tap": ((r"brew tap\s+\S+", "a `brew tap` line"),),
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
