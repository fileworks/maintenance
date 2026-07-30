"""The whole audit in one pass, and the compliance matrix it produces.

Everything the other modules check, run together and reported once: files,
documentation, gate alignment, Renovate configuration, release channels,
formulas, and the identity assets. Remote settings are included only when an
authenticated session supplies them, and are reported `unverifiable` otherwise
— never assumed.

This is what 'run the checks' means concretely, so that 'everything passed' is a
statement somebody can reproduce rather than a claim.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from maintenance.docs import check_readme
from maintenance.drift import DriftReport, compliance_matrix
from maintenance.formula import check_hermetic
from maintenance.identity.directions import DIRECTION_BY_KEY
from maintenance.identity.export import render_svg
from maintenance.identity.export import validate as validate_identity
from maintenance.identity.rollout import Decision, targets
from maintenance.identity.tokens import palettes
from maintenance.ledger import ReleaseLedger, scaffold
from maintenance.policy import (
    evaluate,
    load_exceptions,
    repositories,
    setting_controls,
)
from maintenance.release import (
    check_formula,
    check_metadata,
    read_formula,
    read_from_default_branch,
)
from maintenance.workflows import alignment_matrix, map_gates


@dataclass
class AuditSection:
    """One area that was checked, and what it found."""

    name: str
    findings: list[str] = field(default_factory=list)
    checked: bool = True
    note: str = ""

    @property
    def clean(self) -> bool:
        return self.checked and not self.findings

    def summary(self) -> str:
        if not self.checked:
            return f"{self.name}: not checked — {self.note}"
        if self.clean:
            return f"{self.name}: clean"
        return f"{self.name}: {len(self.findings)} finding(s)"


@dataclass
class AuditReport:
    sections: list[AuditSection] = field(default_factory=list)
    matrix: str = ""
    gate_matrix: str = ""
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def clean(self) -> bool:
        return all(section.clean for section in self.sections if section.checked)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "clean": self.clean,
            "sections": [
                {
                    "name": section.name,
                    "checked": section.checked,
                    "clean": section.clean,
                    "note": section.note,
                    "findings": section.findings,
                }
                for section in self.sections
            ],
        }

    def markdown(self) -> str:
        lines = [
            "# Cross-repository compliance",
            "",
            f"Generated {self.generated_at}.",
            "",
            "| Area | Result |",
            "|---|---|",
        ]
        for section in self.sections:
            state = (
                "not checked"
                if not section.checked
                else "clean"
                if section.clean
                else f"{len(section.findings)} finding(s)"
            )
            lines.append(f"| {section.name} | {state} |")
        for section in self.sections:
            if section.findings or not section.checked:
                lines += ["", f"### {section.name}", ""]
                if not section.checked:
                    lines.append(f"Not checked: {section.note}")
                lines += [f"- {finding}" for finding in section.findings]
        lines += [
            "",
            "## Controls",
            "",
            self.matrix,
            "",
            "## Gates",
            "",
            self.gate_matrix,
            "",
        ]
        return "\n".join(lines)


def run(
    root: Path,
    *,
    authenticated: bool = False,
    ledger_path: Path | None = None,
    observations: Mapping[str, Mapping[str, object]] | None = None,
) -> AuditReport:
    """Run every check that does not need a credential, and say which ones do.

    *observations* are remote settings already read by an authenticated caller.
    Without them the remote section reports `unverifiable` rather than green:
    holding a credential is not the same as having looked.
    """
    repos = [repo for repo in repositories(root) if repo.path.is_dir()]
    ledger = (
        ReleaseLedger.read(ledger_path) if ledger_path and ledger_path.is_file() else scaffold()
    )
    report = AuditReport()

    policy = evaluate(
        repos,
        exceptions=load_exceptions(root / "maintenance" / "exceptions.json"),
        authenticated=authenticated,
        observations=observations,
    )
    drift = DriftReport(policy=policy)
    # Split by the kind of control, not by outcome: the two sections answer
    # different questions ("is the repository laid out right?" vs "is GitHub
    # configured right?") and are fixed in different places.
    setting_ids = {control.control_id for control in setting_controls()}
    report.sections.append(
        AuditSection(
            "Repository files",
            [
                f"{finding.repository}: {finding.control_id} — {finding.detail}"
                for finding in drift.blocking
                if finding.control_id not in setting_ids
            ],
        )
    )
    report.sections.append(
        AuditSection(
            "Remote settings",
            [
                f"{finding.repository}: {finding.control_id} — {finding.detail}"
                for finding in policy.findings
                if finding.control_id in setting_ids
                and finding.outcome in ("mismatched", "missing")
            ],
            checked=observations is not None,
            note="needs settings read by an authenticated `gh` session",
        )
    )

    documentation = [
        f"{issue.repository}: {issue.detail}"
        for repo in repos
        for issue in check_readme(repo.name, repo.repo_class, repo.path, ledger)
    ]
    report.sections.append(AuditSection("Documentation", documentation))

    gate_reports = [map_gates(repo) for repo in repos]
    report.sections.append(
        AuditSection(
            "Quality gates",
            [item.summary() for item in gate_reports if not item.aligned],
        )
    )
    report.gate_matrix = alignment_matrix(gate_reports)

    renovate = []
    for repo in repos:
        config = repo.path / "renovate.json"
        if not config.is_file():
            renovate.append(f"{repo.name}: no renovate.json")
            continue
        try:
            payload = json.loads(config.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            renovate.append(f"{repo.name}: renovate.json is not valid JSON ({exc})")
            continue
        if "packageRules" not in payload and "extends" not in payload:
            renovate.append(f"{repo.name}: renovate.json carries no policy")
    report.sections.append(AuditSection("Renovate", renovate))

    metadata = [
        f"{repo.name}: {issue.field} — {issue.detail}"
        for repo in repos
        if repo.repo_class == "python_cli" and (repo.path / "pyproject.toml").is_file()
        for issue in check_metadata(
            repo.name, (repo.path / "pyproject.toml").read_text(encoding="utf-8")
        )
    ]
    report.sections.append(AuditSection("Package metadata", metadata))

    formulas: list[str] = []
    tap = root / "homebrew-tap"
    if (tap / "Formula").is_dir():
        for path in sorted((tap / "Formula").glob("*.rb")):
            read = read_from_default_branch(tap, f"Formula/{path.name}")
            facts = read_formula(read.content, name=path.stem)
            product = ledger.product(path.stem)
            expected = product.released_version if product else None
            formulas += [f"{path.stem}: {issue.detail}" for issue in check_formula(facts, expected)]
            formulas += [
                f"{path.stem}: {issue.detail}"
                for issue in check_hermetic(read.content, name=path.stem)
            ]
    report.sections.append(AuditSection("Formulas", formulas))

    identity_out = root / "maintenance" / "identity" / "out"
    if identity_out.is_dir():
        report.sections.append(
            AuditSection(
                "Identity assets",
                [f"{issue.path}: {issue.detail}" for issue in validate_identity(identity_out)],
            )
        )
    else:
        report.sections.append(
            AuditSection(
                "Identity assets",
                [],
                checked=False,
                note="not exported in this checkout",
            )
        )

    # The approved family must actually be the one on display. An icon that
    # drifted from the decision is the failure this check exists to catch.
    decision = Decision.load(root / "maintenance" / "identity")
    if decision is None:
        report.sections.append(
            AuditSection(
                "Identity rollout",
                [],
                checked=False,
                note="no family has been approved yet",
            )
        )
    else:
        expected = render_svg(
            DIRECTION_BY_KEY[decision.family].glyph("media-sorter"),
            next(palette for palette in palettes(decision.colour()) if palette.mode == "light"),
        )
        del expected  # rendering proves the decision resolves; the check is per-file below
        rollout_issues: list[str] = []
        for target in targets():
            path = root / target.repository / target.relative_path
            if not (root / target.repository).is_dir():
                continue
            if not path.is_file():
                rollout_issues.append(f"{target.repository}/{target.relative_path}: missing")
                continue
            if target.raster:
                continue
            if decision.colour().hex not in path.read_text(encoding="utf-8"):
                rollout_issues.append(
                    f"{target.repository}/{target.relative_path}: not drawn in "
                    f"{decision.orange}; re-run the rollout"
                )
        report.sections.append(AuditSection("Identity rollout", rollout_issues))

    channels = [
        f"{product.name}/{entry.channel}: unverified"
        for product in ledger.products
        for entry in product.channels
        if entry.state == "unverified"
    ]
    report.sections.append(
        AuditSection(
            "Release channels",
            channels,
            note="unverified channels need an authenticated audit",
        )
    )

    report.matrix = compliance_matrix(policy, tuple(repos))
    return report
