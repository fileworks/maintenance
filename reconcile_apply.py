"""The half of reconciliation that writes. Importing this is the decision.

`A-08`. Everything here mutates a remote: it applies a plan, or rolls one out
wave by wave. Everything in `reconcile` only looks.

That separation used to be a convention — `cli.py` simply happened not to call
`apply` — and a convention is not a boundary. It is now a file, with a test
asserting `maintenance.cli` never reaches this module, directly or through
anything it imports. The audit tool cannot mutate a repository because the code
that mutates repositories is not in the graph it loads, which is a stronger
statement than "nobody wired it up yet".

Nothing here writes in dry-run mode, and a blocked change is never written in
either mode: a prerequisite that is not green is the reason a change is unsafe,
not a formality.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from maintenance.drift import PlannedChange
from maintenance.reconcile import (
    _WRITERS,
    ApiCall,
    Client,
    Outcome,
    _nested,
    redact,
)


def _required_checks_write(
    owner: str,
    repository: str,
    contexts: Sequence[str],
    client: Client,
) -> tuple[ApiCall | None, str]:
    """Choose the protection mechanism that currently owns ``main``.

    Legacy branch protection and repository rulesets have different write
    endpoints. Discovery immediately before the write avoids creating a second,
    conflicting policy, and ruleset updates preserve every unrelated rule.
    """
    protection_path = f"repos/{owner}/{repository}/branches/main/protection"
    legacy_ok, _legacy = client(ApiCall("GET", protection_path))
    if legacy_ok:
        return (
            ApiCall(
                "PATCH",
                f"{protection_path}/required_status_checks",
                {"strict": True, "contexts": list(contexts)},
            ),
            "",
        )

    ok, summaries = client(ApiCall("GET", f"repos/{owner}/{repository}/rulesets"))
    if not ok or not isinstance(summaries, list):
        return None, "neither legacy protection nor repository rulesets could be read"

    candidates: list[dict[str, Any]] = []
    for summary in summaries:
        if not isinstance(summary, dict) or summary.get("enforcement") != "active":
            continue
        ok, ruleset = client(
            ApiCall(
                "GET",
                f"repos/{owner}/{repository}/rulesets/{summary.get('id')}",
            )
        )
        if not ok:
            continue
        matching_rules = [
            rule
            for rule in ruleset.get("rules") or []
            if isinstance(rule, dict) and rule.get("type") == "required_status_checks"
        ]
        if len(matching_rules) == 1:
            candidates.append(ruleset)

    if len(candidates) != 1:
        return (
            None,
            f"expected exactly one active required-status-check ruleset, found {len(candidates)}",
        )

    ruleset = candidates[0]
    rules = deepcopy(ruleset.get("rules") or [])
    target = next(
        rule
        for rule in rules
        if isinstance(rule, dict) and rule.get("type") == "required_status_checks"
    )
    parameters = target.setdefault("parameters", {})
    parameters["required_status_checks"] = [{"context": context} for context in contexts]
    return (
        ApiCall(
            "PUT",
            f"repos/{owner}/{repository}/rulesets/{ruleset.get('id')}",
            {"rules": rules},
        ),
        "",
    )


@dataclass(frozen=True)
class Applied:
    """One change, what happened to it, and what was seen afterwards."""

    change: PlannedChange
    outcome: Outcome
    detail: str = ""
    observed_after: Any = None
    #: Kept so a bad change can be put back by hand.
    rollback_value: Any = None

    def describe(self) -> str:
        return (
            f"{self.change.repository}: {self.change.setting} — {self.outcome}. {self.detail}"
        ).strip()


@dataclass
class ReconcileReport:
    dry_run: bool
    results: list[Applied] = field(default_factory=list)

    @property
    def applied(self) -> list[Applied]:
        return [item for item in self.results if item.outcome == "applied"]

    @property
    def failures(self) -> list[Applied]:
        return [item for item in self.results if item.outcome in {"failed", "unverified"}]

    def summary(self) -> str:
        mode = "Dry run" if self.dry_run else "Applied"
        return (
            f"{mode}: {len(self.applied)} change(s), "
            f"{len([r for r in self.results if r.outcome == 'blocked'])} blocked, "
            f"{len(self.failures)} needing attention."
        )

    def rollback_script(self) -> str:
        """The commands that would put every applied change back."""
        lines = ["# Rollback for this run. Review before executing."]
        for result in self.applied:
            lines.append(
                f"# {result.change.repository}: {result.change.setting} "
                f"was {json.dumps(redact(result.rollback_value))}"
            )
        return "\n".join(lines) + "\n"


def apply(
    changes: Sequence[PlannedChange],
    *,
    owner: str,
    client: Client,
    dry_run: bool = True,
    verify: bool = True,
) -> ReconcileReport:
    """Execute a plan, or describe exactly what executing it would do.

    Nothing is written in dry-run mode, and a blocked change is never written in
    either mode: a prerequisite that is not green is the reason the change is
    unsafe, not a formality.
    """
    report = ReconcileReport(dry_run=dry_run)

    for change in changes:
        if not change.ready:
            report.results.append(
                Applied(
                    change,
                    "blocked",
                    f"prerequisite not met: {', '.join(change.blocked_by)}",
                    rollback_value=change.current,
                )
            )
            continue

        if change.control_id == "default_branch_protection":
            call, error = _required_checks_write(owner, change.repository, change.desired, client)
            if call is None:
                report.results.append(Applied(change, "failed", error))
                continue
        else:
            writer = _WRITERS.get(change.control_id)
            if writer is None:
                report.results.append(
                    Applied(change, "skipped", "no writer is defined for this control")
                )
                continue
            call = writer(owner, change.repository, change.desired)
        if dry_run:
            report.results.append(
                Applied(
                    change,
                    "skipped",
                    f"would run: {call.describe()}",
                    rollback_value=change.current,
                )
            )
            continue

        ok, payload = client(call)
        if not ok:
            report.results.append(
                Applied(
                    change,
                    "failed",
                    str(redact(payload.get("error", "the call failed"))),
                    rollback_value=change.current,
                )
            )
            continue

        if not verify:
            report.results.append(Applied(change, "applied", rollback_value=change.current))
            continue

        # Read back. A write that reports success but did not take is the
        # failure mode this whole module exists to catch.
        observed_after: Any
        if change.control_id == "default_branch_protection":
            if "/rulesets/" in call.path:
                seen_ok, seen = client(ApiCall("GET", call.path))
                observed_after = sorted(_ruleset_required_checks(seen))
            else:
                seen_ok, seen = client(ApiCall("GET", call.path.rsplit("/", 1)[0]))
                observed_after = sorted(_nested(seen, "required_status_checks", "contexts") or [])
            matched = seen_ok and observed_after == sorted(change.desired)
        else:
            seen_ok, seen = client(ApiCall("GET", f"repos/{owner}/{change.repository}"))
            observed_after = seen.get(change.setting.split(".")[0]) if seen_ok else None
            matched = seen_ok and _verified(change, seen)
        report.results.append(
            Applied(
                change,
                "applied" if matched else "unverified",
                "" if matched else "the change did not read back; check it by hand",
                observed_after=redact(observed_after),
                rollback_value=change.current,
            )
        )

    return report


def _verified(change: PlannedChange, payload: dict[str, Any]) -> bool:
    key = change.setting.split(".")[0]
    if key not in payload:
        return False
    return bool(payload[key] == change.desired)


def _ruleset_required_checks(ruleset: dict[str, Any]) -> tuple[str, ...]:
    contexts: set[str] = set()
    for rule in ruleset.get("rules") or []:
        if not isinstance(rule, dict) or rule.get("type") != "required_status_checks":
            continue
        for check in (rule.get("parameters") or {}).get("required_status_checks") or []:
            context = str((check or {}).get("context", "")).strip()
            if context:
                contexts.add(context)
    return tuple(sorted(contexts))


#: Settings are rolled out in waves, cheapest and most reversible first. A
#: description is trivially undone; branch protection is not, so it goes last
#: and only after the checks it requires have been observed green.
STAGES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("presentation", ("description", "homepage", "topics")),
    ("merge-behaviour", ("delete_branch_on_merge", "allow_squash_merge")),
    ("security", ("vulnerability_alerts", "actions_permissions")),
    ("protection", ("default_branch_protection",)),
)


def stage_changes(
    changes: Sequence[PlannedChange],
) -> list[tuple[str, list[PlannedChange]]]:
    """Group a plan into the waves it should be applied in."""
    staged: list[tuple[str, list[PlannedChange]]] = []
    for name, controls in STAGES:
        wave = [change for change in changes if change.control_id in controls]
        if wave:
            staged.append((name, wave))
    known = {control for _name, controls in STAGES for control in controls}
    remainder = [change for change in changes if change.control_id not in known]
    if remainder:
        staged.append(("other", remainder))
    return staged


def rollout(
    changes: Sequence[PlannedChange],
    *,
    owner: str,
    client: Client,
    dry_run: bool = True,
    stop_on_failure: bool = True,
) -> list[tuple[str, ReconcileReport]]:
    """Apply the plan wave by wave, stopping at the first wave that goes wrong.

    Continuing past a failed wave would apply branch protection on top of a
    repository whose earlier settings did not take, which is precisely the state
    that is hardest to reason about afterwards.
    """
    reports: list[tuple[str, ReconcileReport]] = []
    for name, wave in stage_changes(changes):
        report = apply(wave, owner=owner, client=client, dry_run=dry_run)
        reports.append((name, report))
        if stop_on_failure and report.failures:
            break
    return reports
