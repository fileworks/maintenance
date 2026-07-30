"""One Renovate preset, and the thin extensions every repository points at it.

The preset is generated rather than hand-copied into five files, because five
hand-copied files are five files that drift. Each repository keeps a two-line
`renovate.json` that extends the shared preset and adds only what is genuinely
local — a Rust toolchain in one place, a formula manager in another.

The automerge allowlist is deliberately narrow. Patch and minor updates to
ordinary dependencies merge themselves once every required check is green;
anything that can change what users receive — publishers, toolchains, codecs,
installers, security-sensitive libraries — always waits for a person.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from maintenance.policy import RepoClass

PRESET_NAME = "fileworks-base"

#: Package patterns that never automerge, whatever their update type. Each entry
#: is here because a bad version of it reaches users directly.
MANUAL_ONLY = (
    "pyinstaller",
    "tauri*",
    "@tauri-apps/**",
    "semantic-release",
    "python-semantic-release",
    "twine",
    "ffmpeg*",
    "pillow",
    "pikepdf",
    "cryptography",
    "certifi",
    "urllib3",
    "requests",
)

#: How long a release must have existed before it is eligible. Long enough for a
#: bad publish to be yanked, short enough to stay current.
MINIMUM_RELEASE_AGE = "3 days"


def base_preset() -> dict[str, Any]:
    """The shared configuration every repository extends."""
    return {
        "$schema": "https://docs.renovatebot.com/renovate-schema.json",
        "description": "Shared fileworks Renovate policy. Extended, never copied.",
        "extends": ["config:recommended", ":semanticCommits", ":dependencyDashboard"],
        "timezone": "Europe/Berlin",
        "schedule": ["before 6am on monday"],
        "prConcurrentLimit": 5,
        "prHourlyLimit": 2,
        "minimumReleaseAge": MINIMUM_RELEASE_AGE,
        "dependencyDashboardTitle": "Dependency dashboard",
        "labels": ["dependencies"],
        "lockFileMaintenance": {
            "enabled": True,
            "schedule": ["before 6am on the first day of the month"],
        },
        "vulnerabilityAlerts": {
            "labels": ["security"],
            "schedule": ["at any time"],
            "minimumReleaseAge": None,
            "automerge": False,
        },
        "packageRules": [
            {
                "description": (
                    "Low-risk updates merge themselves once every required check is green."
                ),
                "matchUpdateTypes": ["patch", "minor", "digest"],
                "automerge": True,
                "automergeType": "pr",
                "platformAutomerge": True,
            },
            {
                "description": "Majors always get a person; they change behaviour by definition.",
                "matchUpdateTypes": ["major"],
                "automerge": False,
                "labels": ["major-update"],
            },
            {
                "description": (
                    "Publishers, toolchains, codecs, installers, and security-sensitive "
                    "libraries always get a person, at any update type."
                ),
                "matchPackageNames": list(MANUAL_ONLY),
                "automerge": False,
                "labels": ["needs-review"],
            },
            {
                "description": "Group GitHub Actions bumps into one reviewable PR.",
                "matchManagers": ["github-actions"],
                "groupName": "GitHub Actions",
                "automerge": True,
            },
            {
                "description": "Group Python tooling so lint/type/test churn arrives together.",
                "matchManagers": ["pep621", "pip_requirements", "uv"],
                "matchPackageNames": [
                    "ruff",
                    "mypy",
                    "pytest*",
                    "coverage*",
                    "hypothesis",
                ],
                "groupName": "Python tooling",
            },
            {
                "description": "Group JavaScript tooling for the same reason.",
                "matchManagers": ["npm"],
                "matchPackageNames": [
                    "eslint*",
                    "@typescript-eslint/**",
                    "vite*",
                    "vitest*",
                    "typescript",
                ],
                "groupName": "JavaScript tooling",
            },
            {
                "description": "Isolate the Python runtime; it moves everything else with it.",
                "matchPackageNames": ["python"],
                "groupName": "Python runtime",
                "automerge": False,
            },
            {
                "description": "Isolate the Rust/Tauri family; they are coupled and user-facing.",
                "matchManagers": ["cargo"],
                "groupName": "Rust and Tauri",
                "automerge": False,
            },
        ],
    }


@dataclass(frozen=True)
class RepoRenovate:
    """One repository's thin extension of the shared preset."""

    name: str
    repo_class: RepoClass
    preset_source: str

    def config(self, *, inline: bool = False) -> dict[str, Any]:
        """The repository's configuration.

        ``inline`` writes the shared policy into the file instead of extending
        it. That is the honest option until a shared preset repository actually
        exists — a config that extends a preset nobody has published does not
        drift, it simply fails to run. Both forms are generated from the same
        source, so they cannot disagree.
        """
        config: dict[str, Any] = {
            "$schema": "https://docs.renovatebot.com/renovate-schema.json",
        }
        if inline:
            shared = base_preset()
            shared.pop("$schema", None)
            shared["description"] = (
                "Generated from maintenance/renovate.py. Edit the generator, not this file; "
                "it becomes a two-line extends once the shared preset repository exists."
            )
            config.update(shared)
        else:
            config["extends"] = [self.preset_source]
        if self.repo_class == "desktop_application":
            rules = list(config.get("packageRules", []))
            rules.append(
                {
                    "description": "Installer and bundler changes are verified by hand.",
                    "matchPackageNames": ["pyinstaller", "tauri", "@tauri-apps/cli"],
                    "automerge": False,
                }
            )
            config["packageRules"] = rules
        elif self.repo_class == "homebrew_tap":
            config["enabledManagers"] = ["github-actions"]
            config["description"] = (
                "Formula versions are bumped by the release pipeline, not by Renovate."
            )
        return config


def repo_configs(preset_source: str) -> tuple[RepoRenovate, ...]:
    return (
        RepoRenovate("media-sorter", "desktop_application", preset_source),
        RepoRenovate("immich-export", "python_cli", preset_source),
        RepoRenovate("paperless-export", "python_cli", preset_source),
        RepoRenovate("unpacksort", "python_cli", preset_source),
        RepoRenovate("homebrew-tap", "homebrew_tap", preset_source),
    )


def write_preset(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{PRESET_NAME}.json"
    path.write_text(json.dumps(base_preset(), indent=2) + "\n", encoding="utf-8")
    return path


def write_repo_config(repo: RepoRenovate, repo_root: Path, *, inline: bool = False) -> Path:
    path = repo_root / "renovate.json"
    path.write_text(json.dumps(repo.config(inline=inline), indent=2) + "\n", encoding="utf-8")
    return path


def automerge_allowed(package: str, update_type: str) -> bool:
    """Whether the allowlist lets this update merge without a person.

    The check is the same one Renovate will make, expressed here so it can be
    tested — a policy nobody can test is a policy nobody can trust.
    """
    if update_type not in {"patch", "minor", "digest"}:
        return False
    lowered = package.lower()
    for pattern in MANUAL_ONLY:
        if pattern.endswith("*"):
            if lowered.startswith(pattern.rstrip("*").rstrip("/")):
                return False
        elif lowered == pattern:
            return False
    return True


@dataclass(frozen=True)
class AutomationMetrics:
    """One month of Renovate activity, for tuning the limits from evidence."""

    opened: int = 0
    grouped: int = 0
    automerged: int = 0
    manual: int = 0
    failed: int = 0
    stale: int = 0

    @property
    def automerge_rate(self) -> float:
        return 0.0 if self.opened == 0 else self.automerged / self.opened

    @property
    def needs_attention(self) -> int:
        return self.manual + self.failed + self.stale

    def summary(self) -> str:
        return (
            f"{self.opened} opened · {self.automerged} automerged "
            f"({self.automerge_rate:.0%}) · {self.needs_attention} needing attention"
        )

    def recommendation(self) -> str:
        """What to change, once a full cycle has actually been observed."""
        if self.opened == 0:
            return "No updates were opened; nothing to tune yet."
        if self.failed > self.automerged:
            return "More updates failed than merged: tighten the allowlist before raising limits."
        if self.stale > 0:
            return f"{self.stale} update(s) went stale: raise prConcurrentLimit or group harder."
        if self.automerge_rate > 0.8 and self.needs_attention <= 2:
            return "Automation is carrying the load; the current limits are right."
        return "Keep the current limits for another cycle before changing anything."


# --------------------------------------------------------------------------- #
# Metrics baseline                                                             #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class MetricsBaseline:
    """The first month's numbers, recorded so later months mean something.

    Tuning limits without a baseline is guessing with extra steps. This records
    the starting point and refuses to compare against a month nobody measured.
    """

    recorded_on: str | None = None
    metrics: AutomationMetrics | None = None

    @property
    def established(self) -> bool:
        return self.metrics is not None and self.recorded_on is not None

    def compare(self, current: AutomationMetrics) -> str:
        if not self.established or self.metrics is None:
            return (
                "No baseline has been recorded yet. This month's numbers become the "
                "baseline; nothing should be tuned from a single month."
            )
        delta_opened = current.opened - self.metrics.opened
        delta_rate = current.automerge_rate - self.metrics.automerge_rate
        direction = "up" if delta_opened > 0 else "down" if delta_opened < 0 else "flat"
        return (
            f"Opened {direction} by {abs(delta_opened)} against the {self.recorded_on} baseline; "
            f"automerge rate {current.automerge_rate:.0%} "
            f"({'+' if delta_rate >= 0 else ''}{delta_rate:.0%})."
        )


def metrics_markdown(monthly: dict[str, AutomationMetrics], baseline: MetricsBaseline) -> str:
    """The monthly table, plus what it says about the current limits."""
    lines = [
        "| Month | Opened | Grouped | Automerged | Manual | Failed | Stale | Rate |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for month in sorted(monthly):
        item = monthly[month]
        lines.append(
            f"| {month} | {item.opened} | {item.grouped} | {item.automerged} | "
            f"{item.manual} | {item.failed} | {item.stale} | {item.automerge_rate:.0%} |"
        )
    latest = monthly[max(monthly)] if monthly else AutomationMetrics()
    lines += [
        "",
        baseline.compare(latest),
        "",
        f"**Recommendation.** {latest.recommendation()}",
    ]
    return "\n".join(lines)
