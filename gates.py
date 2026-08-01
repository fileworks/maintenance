"""Stable gate names, and which ones each repository class owes.

A gate name is a contract with branch protection: renaming `test` to `tests`
silently unprotects a branch, because the required check it names no longer
exists. So the names live here once, and both the workflows and the protection
rules are generated from them.

A gate that does not apply to a class is *documented as not applicable* rather
than quietly absent — the difference between "we thought about it" and "we
forgot" is the whole value of a policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from maintenance.policy import RepoClass

GateId = Literal[
    "format",
    "lint",
    "typecheck",
    "test",
    "build",
    "package",
    "dependency-audit",
    "docs-links",
    "release-integrity",
    "formula-audit",
    "installer-preflight",
]


@dataclass(frozen=True)
class Gate:
    """One required check, and what it means when it is red."""

    gate_id: GateId
    description: str
    #: Classes this gate applies to; anything else records a documented reason.
    applies_to: tuple[RepoClass, ...]
    not_applicable_reason: str = ""
    blocking: bool = True


GATES: tuple[Gate, ...] = (
    Gate(
        "format",
        "Source formatting is canonical.",
        ("desktop_application", "python_cli", "governance_tool"),
    ),
    Gate(
        "lint",
        "No lint findings at the configured level.",
        ("desktop_application", "python_cli", "governance_tool"),
    ),
    Gate(
        "typecheck",
        "Static types check cleanly.",
        ("desktop_application", "python_cli", "governance_tool"),
        not_applicable_reason="A tap holds Ruby formulas; `brew audit` covers their correctness.",
    ),
    Gate(
        "test",
        "The unit and integration suites pass.",
        ("desktop_application", "python_cli", "governance_tool"),
    ),
    Gate(
        "build",
        "The product builds from a clean tree.",
        ("desktop_application", "python_cli"),
    ),
    Gate(
        "package",
        "A distributable artifact is produced and is installable.",
        ("desktop_application", "python_cli"),
    ),
    Gate(
        "dependency-audit",
        "No known-vulnerable dependency in the locked set.",
        ("desktop_application", "python_cli", "governance_tool"),
        not_applicable_reason="A tap pins upstream releases; their own audits apply.",
    ),
    Gate(
        "docs-links",
        "Documented commands and links resolve.",
        ("desktop_application", "python_cli", "homebrew_tap", "governance_tool"),
    ),
    Gate(
        "release-integrity",
        "Version, tag, changelog, and artifact names agree.",
        ("desktop_application", "python_cli"),
    ),
    Gate(
        "formula-audit",
        "`brew audit --strict` and a real install test pass.",
        ("homebrew_tap",),
        not_applicable_reason="Only a tap has formulas.",
    ),
    Gate(
        "installer-preflight",
        "Installers are produced and their signing state is recorded.",
        ("desktop_application",),
        not_applicable_reason="Only the desktop product ships installers.",
    ),
)


def gates_for(repo_class: RepoClass) -> tuple[Gate, ...]:
    return tuple(gate for gate in GATES if repo_class in gate.applies_to)


def required_checks(repo_class: RepoClass) -> tuple[str, ...]:
    """Exactly the check names branch protection should require."""
    return tuple(gate.gate_id for gate in gates_for(repo_class) if gate.blocking)


def not_applicable(repo_class: RepoClass) -> tuple[tuple[str, str], ...]:
    """Gates this class does not run, each with the reason it does not."""
    return tuple(
        (
            gate.gate_id,
            gate.not_applicable_reason or "not applicable to this repository class",
        )
        for gate in GATES
        if repo_class not in gate.applies_to
    )


def matrix() -> dict[str, dict[str, str]]:
    """The full class × gate table, for the compliance matrix."""
    classes: tuple[RepoClass, ...] = (
        "desktop_application",
        "python_cli",
        "homebrew_tap",
        "governance_tool",
    )
    return {
        gate.gate_id: {
            repo_class: ("required" if repo_class in gate.applies_to else "not applicable")
            for repo_class in classes
        }
        for gate in GATES
    }
