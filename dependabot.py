"""GitHub-native dependency updates for every fileworks repository.

The repositories are independent and do not need a shared configuration
repository. This module is the single source for generated repository-local
``.github/dependabot.yml`` files and the protected auto-merge workflow.

Dependabot is part of GitHub and starts monitoring as soon as its configuration
lands on the default branch. Unlike the former Renovate files, this does not
silently depend on an uninstalled GitHub App.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

AUTOMERGE_UPDATE_TYPES = frozenset(
    {
        "major",
        "minor",
        "patch",
        "digest",
        "lockfile",
        "security",
    }
)

DEFAULT_COOLDOWN_DAYS = 3
AUTOMERGE_WORKFLOW = """\
# Generated from maintenance/dependabot.py. Edit the generator, not this file.
name: Dependabot auto-merge

on:
  pull_request:

permissions:
  contents: read
  pull-requests: read

jobs:
  enable-auto-merge:
    if: >-
      github.event.pull_request.user.login == 'dependabot[bot]' &&
      github.event.pull_request.base.ref == github.event.repository.default_branch
    runs-on: ubuntu-latest
    permissions:
      contents: write
      pull-requests: write
    steps:
      - name: Enable protected squash auto-merge
        run: gh pr merge --auto --squash "$PR_URL"
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          PR_URL: ${{ github.event.pull_request.html_url }}
"""


@dataclass(frozen=True)
class Ecosystem:
    """One package manager and the manifest directories Dependabot monitors."""

    name: str
    directories: tuple[str, ...]


@dataclass(frozen=True)
class RepoDependabot:
    """The complete dependency-manager coverage for one repository."""

    name: str
    ecosystems: tuple[Ecosystem, ...]

    def config(self) -> dict[str, Any]:
        updates: list[dict[str, Any]] = []
        for ecosystem in self.ecosystems:
            location: dict[str, Any]
            if len(ecosystem.directories) == 1:
                location = {"directory": ecosystem.directories[0]}
            else:
                location = {"directories": list(ecosystem.directories)}
            updates.append(
                {
                    "package-ecosystem": ecosystem.name,
                    **location,
                    "schedule": {
                        "interval": "weekly",
                        "day": "monday",
                        "time": "05:00",
                        "timezone": "Europe/Berlin",
                    },
                    "cooldown": {"default-days": DEFAULT_COOLDOWN_DAYS},
                    "open-pull-requests-limit": 5,
                    "rebase-strategy": "auto",
                    "labels": ["dependencies"],
                    "commit-message": {"prefix": "chore(deps)"},
                    "groups": {
                        f"{ecosystem.name}-compatible": {
                            "patterns": ["*"],
                            "update-types": ["minor", "patch"],
                        }
                    },
                }
            )
        return {"version": 2, "updates": updates}


def repo_configs() -> tuple[RepoDependabot, ...]:
    """Return all repositories and every applicable manifest location."""
    python = (Ecosystem("uv", ("/",)), Ecosystem("github-actions", ("/",)))
    return (
        RepoDependabot(
            "media-sorter",
            (
                Ecosystem("uv", ("/backend",)),
                Ecosystem("npm", ("/", "/frontend")),
                Ecosystem("cargo", ("/frontend/src-tauri",)),
                Ecosystem("github-actions", ("/",)),
            ),
        ),
        RepoDependabot("immich-export", python),
        RepoDependabot("paperless-export", python),
        RepoDependabot("unpacksort", python),
        RepoDependabot("homebrew-tap", (Ecosystem("github-actions", ("/",)),)),
        RepoDependabot("maintenance", python),
    )


def _quote(value: str) -> str:
    return f'"{value}"'


def render_config(repo: RepoDependabot) -> str:
    """Render deterministic, human-readable YAML without another dependency."""
    lines = [
        "# Generated from maintenance/dependabot.py. Edit the generator, not this file.",
        "version: 2",
        "updates:",
    ]
    for item in repo.config()["updates"]:
        assert isinstance(item, dict)
        lines.append(f"  - package-ecosystem: {_quote(str(item['package-ecosystem']))}")
        if "directory" in item:
            lines.append(f"    directory: {_quote(str(item['directory']))}")
        else:
            lines.append("    directories:")
            directories = item["directories"]
            assert isinstance(directories, list)
            lines.extend(f"      - {_quote(str(directory))}" for directory in directories)
        lines += [
            "    schedule:",
            '      interval: "weekly"',
            '      day: "monday"',
            '      time: "05:00"',
            '      timezone: "Europe/Berlin"',
            "    cooldown:",
            f"      default-days: {DEFAULT_COOLDOWN_DAYS}",
            "    open-pull-requests-limit: 5",
            '    rebase-strategy: "auto"',
            '    labels: ["dependencies"]',
            "    commit-message:",
            '      prefix: "chore(deps)"',
            "    groups:",
            f"      {item['package-ecosystem']}-compatible:",
            '        patterns: ["*"]',
            '        update-types: ["minor", "patch"]',
        ]
    return "\n".join(lines) + "\n"


def write_repo_config(repo: RepoDependabot, repo_root: Path) -> tuple[Path, Path]:
    """Write the config and auto-merge workflow into one repository."""
    github = repo_root / ".github"
    workflows = github / "workflows"
    workflows.mkdir(parents=True, exist_ok=True)
    config_path = github / "dependabot.yml"
    workflow_path = workflows / "dependabot-automerge.yml"
    config_path.write_text(render_config(repo), encoding="utf-8")
    workflow_path.write_text(AUTOMERGE_WORKFLOW, encoding="utf-8")
    return config_path, workflow_path


def automerge_allowed(update_type: str) -> bool:
    """Whether an update may enter GitHub's protected auto-merge queue."""
    return update_type in AUTOMERGE_UPDATE_TYPES


def complete_pipeline(check_states: dict[str, str], required: set[str]) -> bool:
    """Only fresh explicit success for every required context permits merge."""
    return bool(required) and all(check_states.get(check) == "success" for check in required)


@dataclass(frozen=True)
class AutomationMetrics:
    """One month of dependency-update activity, for evidence-based tuning."""

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
        if self.opened == 0:
            return "No updates were opened; nothing to tune yet."
        if self.failed > self.automerged:
            return "More updates failed than merged: inspect failures before raising limits."
        if self.stale > 0:
            return f"{self.stale} update(s) went stale: raise the PR limit or group harder."
        if self.automerge_rate > 0.8 and self.needs_attention <= 2:
            return "Automation is carrying the load; the current limits are right."
        return "Keep the current limits for another cycle before changing anything."


@dataclass(frozen=True)
class MetricsBaseline:
    """The first month's numbers, recorded so later months mean something."""

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
    """Render monthly dependency automation metrics and a recommendation."""
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
