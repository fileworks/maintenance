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
from maintenance.workflows import MEDIA_SORTER_REQUIRED_CONTEXTS

Outcome = Literal["applied", "skipped", "blocked", "failed", "unverified"]

#: Substrings whose values are never printed, whatever the log level. The
#: reconciler handles a token by construction, so redaction is not optional.
SECRET_MARKERS = ("token", "secret", "password", "key", "authorization")

REDACTED = "[REDACTED]"
_GITHUB_TOKEN = re.compile(
    r"(?:"
    r"github_pat_[A-Za-z0-9_]{20,}"
    r"|ghs_[A-Za-z0-9.\-_]{36,}"
    r"|gh[pour]_[A-Za-z0-9_]{16,}"
    r")"
)


def redact(value: Any) -> Any:
    """Remove anything credential-shaped from a value before it is displayed."""
    if isinstance(value, str):
        # A GitHub token is recognisable by shape; redact it wherever it appears,
        # including inside a longer string such as a URL.
        return _GITHUB_TOKEN.sub(REDACTED, value)
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
        argv, standard_input = _gh_request(request)
        try:
            completed = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                input=standard_input,
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


def _gh_request(request: ApiCall) -> tuple[list[str], str | None]:
    """Render a request without flattening JSON arrays or nested objects.

    Passing lists through repeated ``gh api -F`` fields is ambiguous: a list of
    status contexts became one comma-separated context, and nested branch
    protection data could not be represented at all. ``--input -`` preserves
    the request body exactly and keeps credentials out of command arguments.
    """
    argv = ["gh", "api", "-X", request.method, request.path]
    if not request.body:
        return argv, None
    return [*argv, "--input", "-"], json.dumps(request.body)


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
        #
        # But "no *legacy* protection" is not "unprotected": a ruleset enforces
        # the same things through a different endpoint, and four of these five
        # repositories use one. Reading only the legacy endpoint reported them
        # all as having an unprotected `main` while they were in fact protected.
        observed["protection.main.required_status_checks"] = sorted(
            ruleset_checks(repository.name, owner, client)
        )
    return observed


def ruleset_checks(repository: str, owner: str, client: Client) -> tuple[str, ...]:
    """Required check contexts enforced by active rulesets on the default branch.

    Rulesets are the mechanism GitHub steers people towards now, and they are
    invisible to `branches/main/protection`. A repository protected by one looks
    exactly like an unprotected repository from there.
    """
    ok, payload = client(ApiCall("GET", f"repos/{owner}/{repository}/rulesets"))
    if not ok or not isinstance(payload, list):
        return ()

    contexts: set[str] = set()
    for summary in payload:
        if not isinstance(summary, dict) or summary.get("enforcement") != "active":
            continue
        ok, ruleset = client(
            ApiCall("GET", f"repos/{owner}/{repository}/rulesets/{summary.get('id')}")
        )
        if not ok:
            continue
        for rule in ruleset.get("rules") or []:
            if not isinstance(rule, dict) or rule.get("type") != "required_status_checks":
                continue
            parameters = rule.get("parameters") or {}
            for check in parameters.get("required_status_checks") or []:
                context = str((check or {}).get("context", "")).strip()
                if context:
                    contexts.add(context)
    return tuple(sorted(contexts))


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


def pull_request_checks(repository: str, owner: str, client: Client) -> tuple[str, ...] | None:
    """The names a pull request will actually report, which is what to require.

    `observed_checks` reads the default branch, and that is the wrong sample in
    two ways. A release commit merged with `[skip ci]` has no check runs at all,
    so the answer comes back empty — `immich-export` and `paperless-export` both
    look like that right now. And a job that only runs on `push` shows up there
    while never reporting on a pull request; requiring `media-sorter`'s
    "Create release (if warranted)" would block every pull request forever.

    So the sample is the most recent completed `pull_request` run of each
    workflow, and the names are the job names GitHub produced — already expanded
    across the matrix, which is the only way to get `quality (ubuntu-latest,
    Python 3.12)` right without reimplementing matrix expansion.

    Returns `None` when the names could not be read at all, and a tuple —
    possibly empty — when they were. Collapsing both into `()` meant one
    transient API failure was indistinguishable from "this repository emits no
    pull-request checks", and the caller then planned to *empty* a correct
    required-context list. That is the same mistake `observe_settings` avoids
    by leaving an unreachable repository out of its mapping entirely.
    """
    ok, payload = client(
        ApiCall(
            "GET",
            f"repos/{owner}/{repository}/actions/runs"
            "?event=pull_request&status=completed&per_page=30",
        )
    )
    if not ok:
        return None

    latest_per_workflow: dict[Any, dict[str, Any]] = {}
    for run in payload.get("workflow_runs") or []:
        if not isinstance(run, dict):
            continue
        key = run.get("workflow_id")
        seen = latest_per_workflow.get(key)
        # Runs come back newest first; keep the first of each workflow.
        if seen is None:
            latest_per_workflow[key] = run

    names: set[str] = set()
    for run in latest_per_workflow.values():
        ok, jobs = client(
            ApiCall("GET", f"repos/{owner}/{repository}/actions/runs/{run.get('id')}/jobs")
        )
        # A partial read is not a smaller answer, it is a wrong one: the names
        # this run would have contributed would look like names nothing emits.
        if not ok:
            return None
        for job in jobs.get("jobs") or []:
            # A conditionally skipped job appears in the run payload, but it
            # does not report a successful check that branch protection can
            # require. Treating scheduled scale tiers as required contexts
            # would leave every ordinary pull request waiting forever.
            if job.get("conclusion") == "skipped":
                continue
            name = str(job.get("name", "")).strip()
            if name:
                names.add(name)
    return tuple(sorted(names))


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
}


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
            # Both sides are compared as canonically sorted lists. GitHub
            # returns the required contexts in its own order and `observed`
            # already sorts them, so an unsorted desired list reported drift
            # between two identical sets.
            desired = (
                sorted(MEDIA_SORTER_REQUIRED_CONTEXTS)
                if repository.name == "media-sorter"
                else sorted(required_checks(repository.repo_class))
            )
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


# --------------------------------------------------------------------------- #
# Staged rollout                                                               #
# --------------------------------------------------------------------------- #
