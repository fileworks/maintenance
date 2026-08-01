"""Consistent GitHub Release and Deployment semantics across Fileworks.

A GitHub Release is the user-facing immutable version and its downloadable
artifacts. A GitHub Deployment is the audit record created when a publication
job targets a protected Environment. The concepts are complementary, so every
publication channel owns one explicit environment rather than producing
accidental or misleading deployment labels.
"""

from __future__ import annotations

import re
from pathlib import Path

EXPECTED_ENVIRONMENTS: dict[str, frozenset[str]] = {
    "media-sorter": frozenset({"github-release"}),
    "immich-export": frozenset({"github-release", "pypi", "homebrew"}),
    "paperless-export": frozenset({"github-release", "pypi", "homebrew"}),
    "unpacksort": frozenset({"github-release", "pypi", "homebrew", "winget"}),
}

_CHANNEL_MARKERS: dict[str, tuple[str, ...]] = {
    "github-release": ("gh release create", "softprops/action-gh-release"),
    "pypi": ("pypa/gh-action-pypi-publish",),
    "homebrew": ("gh workflow run bump.yml",),
    "winget": ("wingetcreate",),
}
_JOB = re.compile(
    r"^  (?P<name>[A-Za-z0-9_-]+):\n(?P<body>.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)",
    re.MULTILINE | re.DOTALL,
)
_ENVIRONMENT = re.compile(r"^    environment:\s*([A-Za-z0-9_-]+)\s*$", re.MULTILINE)


def check_release_deployments(repository: str, workflow: Path) -> list[str]:
    """Return precise release/deployment inconsistencies for one workflow."""
    expected = EXPECTED_ENVIRONMENTS.get(repository)
    if expected is None:
        return []
    if not workflow.is_file():
        return [f"{repository}: release workflow is missing"]

    source = workflow.read_text(encoding="utf-8")
    jobs = {match.group("name"): match.group("body") for match in _JOB.finditer(source)}
    observed: set[str] = set()
    findings: list[str] = []

    for job_name, body in jobs.items():
        environment_match = _ENVIRONMENT.search(body)
        environment = environment_match.group(1) if environment_match else None
        if environment is not None:
            observed.add(environment)

        for channel, markers in _CHANNEL_MARKERS.items():
            if not any(marker in body for marker in markers):
                continue
            if environment != channel:
                actual = environment or "none"
                findings.append(
                    f"{repository}: job {job_name!r} publishes {channel} "
                    f"but targets environment {actual!r}"
                )

    missing = sorted(expected - observed)
    extra = sorted(observed - expected)
    if missing:
        findings.append(f"{repository}: missing release environments: {', '.join(missing)}")
    if extra:
        findings.append(f"{repository}: unexpected release environments: {', '.join(extra)}")
    return findings
