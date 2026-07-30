"""Applying remote repository settings — carefully, and only when asked.

Three properties make this safe enough to exist:

*It plans before it acts.* `plan` produces the exact set of changes with their
current and desired values; `apply` will only execute a plan it was handed.

*It is idempotent.* A change whose observed value already matches is not
re-applied, so running twice is the same as running once, and a partially
completed run can simply be re-run.

*It verifies afterwards.* Every applied change is read back. A setting that did
not take is reported as `unverified`, never as applied — a reconciler that
trusts its own writes is a reconciler that quietly drifts.

The GitHub calls go through an injected client, so every path here is testable
without a network and without credentials.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from maintenance.drift import PlannedChange
from maintenance.gates import required_checks
from maintenance.policy import Repository, SettingControl, setting_controls

Outcome = Literal["applied", "skipped", "blocked", "failed", "unverified"]

#: Substrings whose values are never printed, whatever the log level. The
#: reconciler handles a token by construction, so redaction is not optional.
SECRET_MARKERS = ("token", "secret", "password", "key", "authorization")

REDACTED = "[REDACTED]"


def redact(value: Any) -> Any:
    """Remove anything credential-shaped from a value before it is displayed."""
    if isinstance(value, str):
        # A GitHub token is recognisable by shape; redact it wherever it appears,
        # including inside a longer string such as a URL.
        return re.sub(r"gh[pousr]_[A-Za-z0-9]{16,}", REDACTED, value)
    if isinstance(value, dict):
        return {
            key: (
                REDACTED
                if any(marker in str(key).lower() for marker in SECRET_MARKERS)
                else redact(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    return value


# --------------------------------------------------------------------------- #
# The client boundary                                                          #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ApiCall:
    """One request the reconciler wants to make."""

    method: Literal["GET", "PATCH", "PUT", "POST"]
    path: str
    body: dict[str, Any] = field(default_factory=dict)

    def describe(self) -> str:
        body = json.dumps(redact(self.body), sort_keys=True) if self.body else ""
        return f"{self.method} {self.path} {body}".strip()


#: A client takes a call and returns (ok, payload). Injected so the whole module
#: is exercisable without credentials.
Client = Callable[[ApiCall], tuple[bool, dict[str, Any]]]


def gh_client(*, timeout: int = 30) -> Client:
    """A client backed by `gh api`. The only place a credential is used.

    `gh` is used rather than a raw token because it already holds the least
    privilege the user granted it — this module never reads, stores, or prints a
    token of its own.
    """

    def call(request: ApiCall) -> tuple[bool, dict[str, Any]]:
        argv = ["gh", "api", "-X", request.method, request.path]
        for key, value in request.body.items():
            argv += [
                "-f" if isinstance(value, str) else "-F",
                f"{key}={_render(value)}",
            ]
        try:
            completed = subprocess.run(
                argv, capture_output=True, text=True, timeout=timeout, check=False
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return False, {"error": type(exc).__name__}
        if completed.returncode != 0:
            return False, {"error": redact(completed.stderr.strip()[:400])}
        try:
            return True, json.loads(completed.stdout or "{}")
        except json.JSONDecodeError:
            return True, {}

    return call


def _render(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return ",".join(str(item) for item in value)
    return str(value)


# --------------------------------------------------------------------------- #
# Authentication                                                               #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class AuthStatus:
    """Whether an authenticated session exists, and what it may do."""

    authenticated: bool
    account: str | None = None
    scopes: tuple[str, ...] = ()
    organizations: tuple[str, ...] = ()
    detail: str = ""

    #: The least privilege that can do the job. Anything more is not required
    #: and should not be granted.
    REQUIRED_SCOPES = ("repo", "admin:org")

    @property
    def missing_scopes(self) -> tuple[str, ...]:
        return tuple(scope for scope in self.REQUIRED_SCOPES if scope not in self.scopes)

    @property
    def sufficient(self) -> bool:
        return self.authenticated and not self.missing_scopes

    def summary(self) -> str:
        if not self.authenticated:
            return "Not authenticated. Run `gh auth login` and re-run with --authenticated."
        if self.missing_scopes:
            missing = ", ".join(self.missing_scopes)
            return f"Authenticated as {self.account}, missing scopes: {missing}."
        return f"Authenticated as {self.account} with the required scopes."


def check_auth(
    runner: Callable[[list[str]], tuple[int, str, str]] | None = None,
) -> AuthStatus:
    """Ask `gh` what it can do. Never prints or stores the token itself."""
    run = runner or _subprocess_runner()
    code, out, err = run(["auth", "status"])
    if code != 0:
        return AuthStatus(False, detail=redact((err or out).strip()[:200]))

    # `gh` moved this output from stderr to stdout; read both so the answer does
    # not depend on which version happens to be installed.
    status = f"{out}\n{err}"
    account = None
    scopes: list[str] = []
    for line in status.splitlines():
        if "account" in line.lower():
            match = re.search(r"account (\S+)", line)
            if match:
                account = match.group(1)
        if "token scopes" in line.lower():
            scopes = [scope.strip().strip("'\"") for scope in line.split(":", 1)[-1].split(",")]

    organizations: list[str] = []
    org_code, org_out, _ = run(["api", "user/orgs", "--jq", ".[].login"])
    if org_code == 0:
        organizations = [line.strip() for line in org_out.splitlines() if line.strip()]

    return AuthStatus(
        authenticated=True,
        account=account,
        scopes=tuple(scope for scope in scopes if scope),
        organizations=tuple(organizations),
    )


def _subprocess_runner() -> Callable[[list[str]], tuple[int, str, str]]:
    def run(arguments: list[str]) -> tuple[int, str, str]:
        try:
            completed = subprocess.run(
                ["gh", *arguments],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return 1, "", type(exc).__name__
        return completed.returncode, completed.stdout, completed.stderr

    return run


# --------------------------------------------------------------------------- #
# Observation                                                                  #
# --------------------------------------------------------------------------- #


def observe(repository: Repository, owner: str, client: Client) -> dict[str, Any]:
    """Read the settings the policy audits. Read-only, always safe to run."""
    ok, payload = client(ApiCall("GET", f"repos/{owner}/{repository.name}"))
    if not ok:
        return {}
    observed: dict[str, Any] = {
        "description": payload.get("description") or "",
        "homepage": payload.get("homepage") or "",
        "delete_branch_on_merge": payload.get("delete_branch_on_merge"),
        "allow_squash_merge": payload.get("allow_squash_merge"),
        "topics": payload.get("topics", []),
        "security_and_analysis.dependabot_security_updates": _nested(
            payload, "security_and_analysis", "dependabot_security_updates", "status"
        )
        == "enabled",
    }

    ok, actions = client(
        ApiCall("GET", f"repos/{owner}/{repository.name}/actions/permissions/workflow")
    )
    if ok:
        observed["actions.default_workflow_permissions"] = actions.get(
            "default_workflow_permissions"
        )

    ok, protection = client(
        ApiCall("GET", f"repos/{owner}/{repository.name}/branches/main/protection")
    )
    if ok:
        observed["protection.main.required_status_checks"] = sorted(
            _nested(protection, "required_status_checks", "contexts") or []
        )
    elif "not protected" in str(protection.get("error", "")).lower():
        # GitHub 404s an unprotected branch, which is the same status code as
        # "you cannot see this repository". Only the first is an answer, and
        # conflating them would report an unprotected `main` as unverifiable
        # instead of as the mismatch it is.
        observed["protection.main.required_status_checks"] = []
    return observed


def observed_checks(repository: str, owner: str, client: Client) -> tuple[str, ...]:
    """Check names GitHub has actually seen on the default branch.

    Branch protection requires checks *by name*. Requiring a name nothing
    reports does not protect the branch — it makes it permanently unmergeable,
    silently, and only the next person to open a pull request finds out.
    """
    ok, payload = client(ApiCall("GET", f"repos/{owner}/{repository}/commits/main/check-runs"))
    if not ok:
        return ()
    runs = payload.get("check_runs") or []
    return tuple(sorted({str(run.get("name", "")) for run in runs if run.get("name")}))


def _nested(payload: dict[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


# --------------------------------------------------------------------------- #
# Planning and applying                                                        #
# --------------------------------------------------------------------------- #


#: How each control is written. A control without a writer is reported and never
#: guessed at — inventing an endpoint is how a reconciler breaks something.
_WRITERS: dict[str, Callable[[str, str, Any], ApiCall]] = {
    "description": lambda owner, repo, value: ApiCall(
        "PATCH", f"repos/{owner}/{repo}", {"description": value}
    ),
    "delete_branch_on_merge": lambda owner, repo, value: ApiCall(
        "PATCH", f"repos/{owner}/{repo}", {"delete_branch_on_merge": value}
    ),
    "allow_squash_merge": lambda owner, repo, value: ApiCall(
        "PATCH", f"repos/{owner}/{repo}", {"allow_squash_merge": value}
    ),
    "vulnerability_alerts": lambda owner, repo, _value: ApiCall(
        "PUT", f"repos/{owner}/{repo}/vulnerability-alerts"
    ),
    "actions_permissions": lambda owner, repo, value: ApiCall(
        "PUT",
        f"repos/{owner}/{repo}/actions/permissions/workflow",
        {"default_workflow_permissions": value},
    ),
    "default_branch_protection": lambda owner, repo, value: ApiCall(
        "PUT",
        f"repos/{owner}/{repo}/branches/main/protection",
        {"required_status_checks": value},
    ),
}


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


def plan(
    repository: Repository,
    observed: dict[str, Any],
    green_controls: set[str],
    *,
    controls: Sequence[SettingControl] | None = None,
    reported_checks: Sequence[str] | None = None,
) -> list[PlannedChange]:
    """What would change, with prerequisites resolved against observed reality.

    *reported_checks* is the set of check names GitHub has actually seen. Branch
    protection is blocked unless every check it would require is in that set:
    requiring a name that never reports is not protection, it is a branch nobody
    can merge into.
    """
    planned: list[PlannedChange] = []
    for control in controls if controls is not None else setting_controls():
        if repository.repo_class not in control.applies_to:
            continue
        desired: Any = control.expected
        blocked_extra: tuple[str, ...] = ()
        if desired == "<class gates>":
            desired = sorted(required_checks(repository.repo_class))
            if reported_checks is not None:
                absent = [name for name in desired if name not in set(reported_checks)]
                if absent:
                    blocked_extra = ("checks-not-reporting",)
        if desired == "<non-empty>":
            current = observed.get(control.setting)
            if current:
                continue
            desired = repository.description or f"{repository.name} — a fileworks project"
        current = observed.get(control.setting, "<unknown>")
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
                    if prerequisite not in green_controls
                )
                + blocked_extra,
            )
        )
    return planned


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


# --------------------------------------------------------------------------- #
# Staged rollout                                                               #
# --------------------------------------------------------------------------- #


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
