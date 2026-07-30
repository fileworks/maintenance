"""Drift reporting: what is out of policy, where, and what to do about it.

The report is the whole product. There is deliberately no "fix everything"
entry point here — remote settings are reconciled by a separate, explicitly
authorized run, and a scheduled job that could silently rewrite repository
settings is a job that will eventually rewrite the wrong one.

What this module does provide is a dry-run plan: exactly which changes *would*
be made, with their prerequisites and their rollback values, so approving them
is a decision made with the diff in hand.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from maintenance.docs import DocIssue
from maintenance.gates import not_applicable
from maintenance.policy import (
    Finding,
    PolicyReport,
    Repository,
    SettingControl,
    setting_controls,
)
from maintenance.worktree import TreeState, unpublished


@dataclass(frozen=True)
class PlannedChange:
    """One remote setting a reconciliation would change, and how to undo it."""

    repository: str
    control_id: str
    setting: str
    current: Any
    desired: Any
    prerequisites: tuple[str, ...] = ()
    blocked_by: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return not self.blocked_by

    def describe(self) -> str:
        state = "ready" if self.ready else f"blocked by {', '.join(self.blocked_by)}"
        return f"{self.repository}: {self.setting} {self.current!r} → {self.desired!r} ({state})"


@dataclass
class DriftReport:
    """Everything one evaluation found, in the order a person would read it."""

    policy: PolicyReport
    documentation: list[DocIssue] = field(default_factory=list)
    planned: list[PlannedChange] = field(default_factory=list)
    #: Condition of the checkouts the file controls above were read from. Empty
    #: when it was not inspected.
    trees: list[TreeState] = field(default_factory=list)
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def clean(self) -> bool:
        return self.policy.compliant and not self.documentation

    @property
    def blocking(self) -> tuple[Finding, ...]:
        """Findings that are actually wrong, as opposed to merely unchecked."""
        return tuple(
            finding
            for finding in self.policy.findings
            if finding.outcome in {"missing", "mismatched", "stale"}
        )

    def summary(self) -> str:
        if self.clean:
            return "Every applicable control is satisfied."
        parts = []
        if self.blocking:
            parts.append(f"{len(self.blocking)} control(s) out of policy")
        unverifiable = self.policy.by_outcome("unverifiable")
        if unverifiable:
            parts.append(f"{len(unverifiable)} unverifiable without authentication")
        if self.documentation:
            parts.append(f"{len(self.documentation)} documentation issue(s)")
        return "; ".join(parts)

    def markdown(self) -> str:
        lines = [
            "# Policy drift",
            "",
            f"Generated {self.generated_at}.",
            "",
            self.summary(),
            "",
        ]
        # Immediately after the verdict, because it is what the verdict is worth.
        drifted = unpublished(self.trees)
        if drifted:
            lines += [
                "## What this verdict describes",
                "",
                "File controls read the checkout, not the published branch. These "
                "checkouts hold work that has not landed, so a control satisfied "
                "here is not necessarily satisfied on the branch anyone visits:",
                "",
            ]
            lines += [f"- {state.describe()}" for state in drifted]
            lines.append("")
        if self.blocking:
            lines += [
                "## Out of policy",
                "",
                "| Repository | Control | Outcome | Remediation |",
                "|---|---|---|---|",
            ]
            for finding in self.blocking:
                lines.append(
                    f"| `{finding.repository}` | {finding.control_id} | {finding.outcome} | "
                    f"{finding.remediation or finding.detail} |"
                )
            lines.append("")
        if self.documentation:
            lines += [
                "## Documentation",
                "",
                "| Repository | Issue | Detail |",
                "|---|---|---|",
            ]
            for issue in self.documentation:
                lines.append(f"| `{issue.repository}` | {issue.kind} | {issue.detail} |")
            lines.append("")
        unverifiable = self.policy.by_outcome("unverifiable")
        if unverifiable:
            lines += [
                "## Not verified",
                "",
                f"{len(unverifiable)} control(s) need an authenticated `gh` session and are "
                "reported as unverifiable rather than assumed compliant.",
                "",
            ]
        if self.planned:
            lines += ["## Would change", ""]
            lines += [f"- {change.describe()}" for change in self.planned]
            lines.append("")
            lines.append(
                "> Nothing above has been applied. Reconciliation is a separate, "
                "explicitly authorized run."
            )
        return "\n".join(lines)

    def to_dict(self) -> dict[str, object]:
        return {
            "generated_at": self.generated_at,
            "clean": self.clean,
            "summary": self.summary(),
            "policy": self.policy.to_dict(),
            "documentation": [
                {
                    "repository": issue.repository,
                    "kind": issue.kind,
                    "detail": issue.detail,
                }
                for issue in self.documentation
            ],
            "planned_changes": [
                {
                    "repository": change.repository,
                    "control": change.control_id,
                    "setting": change.setting,
                    "current": change.current,
                    "desired": change.desired,
                    "ready": change.ready,
                    "blocked_by": list(change.blocked_by),
                }
                for change in self.planned
            ],
        }

    def write(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")
        return path


def plan_settings(
    repository: Repository,
    observed: dict[str, Any],
    report: PolicyReport,
    *,
    controls: tuple[SettingControl, ...] | None = None,
    checks: Sequence[str] | None = None,
) -> list[PlannedChange]:
    """The dry-run: what a reconciliation would change, and what blocks it.

    A control whose prerequisite is not observed green is planned but *blocked*,
    so branch protection can never be applied before the checks it would require
    actually exist.

    *checks* are the context names a pull request actually reports, from
    `reconcile.pull_request_checks`. Branch protection is planned only when they
    are known, because GitHub matches required checks by name and there is no
    safe guess: requiring a name nothing reports makes the branch permanently
    unmergeable, and only the next person to open a pull request finds out.
    """
    green = {
        finding.control_id
        for finding in report.for_repository(repository.name)
        if finding.outcome == "compliant"
    }
    planned: list[PlannedChange] = []
    for control in controls or setting_controls():
        if repository.repo_class not in control.applies_to:
            continue
        desired: Any = control.expected
        blocked_extra: tuple[str, ...] = ()
        current_value = observed.get(control.setting, "<unknown>")
        if desired == "<non-empty>":
            # Another predicate that is not a value. Writing it literally would
            # have set every repository's description to the string
            # "<non-empty>" — and they were already correct, so the plan was
            # proposing to destroy five good descriptions.
            if isinstance(current_value, str) and current_value.strip():
                continue
            desired = repository.description
        if desired == "<class gates>":
            # `required_checks` returns gate *ids* — `lint`, `test`, `build`.
            # Those are not check names and never were: the real ones look like
            # `quality (ubuntu-latest, Python 3.12)`. Using them here would have
            # required nine nonexistent checks on every repository at once.
            if not checks:
                desired = []
                blocked_extra = ("observed pull-request check names",)
            else:
                desired = list(checks)
        current = current_value
        if current == desired:
            continue
        planned.append(
            PlannedChange(
                repository=repository.name,
                control_id=control.control_id,
                setting=control.setting,
                current=current,
                desired=desired,
                prerequisites=control.prerequisites,
                blocked_by=tuple(
                    prerequisite
                    for prerequisite in control.prerequisites
                    if prerequisite not in green
                )
                + blocked_extra,
            )
        )
    return planned


def compliance_matrix(report: PolicyReport, repositories: tuple[Repository, ...]) -> str:
    """The final table: every repository, every control, and its verdict."""
    controls = sorted({finding.control_id for finding in report.findings})
    lines = ["| Control | " + " | ".join(f"`{repo.name}`" for repo in repositories) + " |"]
    lines.append("|---" * (len(repositories) + 1) + "|")
    for control in controls:
        cells = []
        for repo in repositories:
            finding = next(
                (item for item in report.for_repository(repo.name) if item.control_id == control),
                None,
            )
            cells.append("—" if finding is None else _symbol(finding.outcome))
        lines.append(f"| {control} | " + " | ".join(cells) + " |")

    lines.append("")
    lines.append("Legend: ✅ compliant · ⚠️ excepted · ❌ out of policy · ❓ unverifiable · — n/a")
    for repo in repositories:
        skipped = not_applicable(repo.repo_class)
        if skipped:
            lines.append("")
            lines.append(
                f"**`{repo.name}` does not run:** "
                + "; ".join(f"`{gate}` ({reason})" for gate, reason in skipped)
            )
    return "\n".join(lines)


def _symbol(outcome: str) -> str:
    return {
        "compliant": "✅",
        "excepted": "⚠️",
        "missing": "❌",
        "mismatched": "❌",
        "stale": "❌",
        "unverifiable": "❓",
    }.get(outcome, "—")
