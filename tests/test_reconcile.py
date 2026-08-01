"""The reconciler: plans before it acts, never writes a blocked change, and
never believes its own writes without reading them back."""

from __future__ import annotations

from typing import Any

from maintenance.drift import PlannedChange
from maintenance.policy import Repository, SettingControl
from maintenance.reconcile import (
    STAGES,
    ApiCall,
    AuthStatus,
    apply,
    check_auth,
    observe,
    observed_checks,
    plan,
    pull_request_checks,
    redact,
    rollout,
    ruleset_checks,
    stage_changes,
)


class FakeClient:
    """A GitHub that records what it was asked to do."""

    def __init__(
        self, state: dict[str, Any] | None = None, *, fail: set[str] | None = None
    ) -> None:
        self.state = state or {}
        self.fail = fail or set()
        self.calls: list[ApiCall] = []

    def __call__(self, call: ApiCall) -> tuple[bool, dict[str, Any]]:
        self.calls.append(call)
        if call.path in self.fail:
            return False, {"error": "refused"}
        if call.method == "GET":
            return True, dict(self.state)
        self.state.update(call.body)
        return True, dict(self.state)

    @property
    def writes(self) -> list[ApiCall]:
        return [call for call in self.calls if call.method != "GET"]


def _repo(name: str = "demo") -> Repository:
    from pathlib import Path

    return Repository(name, "python_cli", Path("/tmp") / name, description="a demo")


class TestRedaction:
    def test_a_token_is_removed_wherever_it_appears(self) -> None:
        assert "ghp_" not in redact("failed for ghp_abcdefghijklmnopqrstuvwxyz012345")

    def test_current_github_credential_shapes_are_removed(self) -> None:
        for token in (
            "github_pat_11AA0_example_abcdefghijklmnopqrstuvwxyz0123456789",
            "ghs_abcdefghijklmnopqrstuvwxyz0123456789",
            "ghu_abcdefghijklmnopqrstuvwxyz012345",
            "gho_abcdefghijklmnopqrstuvwxyz012345",
            "ghr_abcdefghijklmnopqrstuvwxyz012345",
        ):
            cleaned = redact(f"request failed for {token}")
            assert token not in cleaned
            assert "[REDACTED]" in cleaned

    def test_credential_shaped_keys_are_removed(self) -> None:
        cleaned = redact({"token": "abc", "Authorization": "Bearer x", "name": "fine"})

        assert cleaned["token"] == "[REDACTED]"
        assert cleaned["Authorization"] == "[REDACTED]"
        assert cleaned["name"] == "fine"

    def test_nested_values_are_cleaned(self) -> None:
        cleaned = redact({"outer": [{"secret": "x"}, "ghp_abcdefghijklmnopqrstuvwxyz012345"]})

        assert cleaned["outer"][0]["secret"] == "[REDACTED]"
        assert "ghp_" not in cleaned["outer"][1]

    def test_an_api_call_describes_itself_without_leaking(self) -> None:
        call = ApiCall("PATCH", "repos/x/y", {"token": "abc"})

        assert "abc" not in call.describe()


class TestAuth:
    def test_an_unauthenticated_session_says_what_to_run(self) -> None:
        status = check_auth(lambda _arguments: (1, "", "not logged in"))

        assert status.authenticated is False
        assert "gh auth login" in status.summary()

    def test_missing_scopes_are_named(self) -> None:
        def runner(arguments: list[str]) -> tuple[int, str, str]:
            if arguments[0] == "auth":
                return (
                    0,
                    "",
                    "Logged in to github.com account someone\n  - Token scopes: 'repo'",
                )
            return 0, "fileworks\n", ""

        status = check_auth(runner)

        assert status.authenticated is True
        assert status.missing_scopes == ("admin:org",)
        assert status.sufficient is False

    def test_a_sufficient_session_is_recognised(self) -> None:
        def runner(arguments: list[str]) -> tuple[int, str, str]:
            if arguments[0] == "auth":
                return 0, "", "account someone\n  - Token scopes: 'repo', 'admin:org'"
            return 0, "fileworks\n", ""

        status = check_auth(runner)

        assert status.sufficient is True
        assert status.organizations == ("fileworks",)

    def test_the_required_scopes_are_least_privilege(self) -> None:
        # Nothing that could delete a repository.
        assert "delete_repo" not in AuthStatus.REQUIRED_SCOPES


class TestObservation:
    def test_reading_settings_makes_no_writes(self) -> None:
        client = FakeClient({"description": "x", "delete_branch_on_merge": True})

        observe(_repo(), "fileworks", client)

        assert client.writes == []

    def test_an_unreachable_repository_observes_nothing(self) -> None:
        client = FakeClient(fail={"repos/fileworks/demo"})

        assert observe(_repo(), "fileworks", client) == {}


class TestPlanning:
    CONTROL = SettingControl("delete_branch_on_merge", "delete_branch_on_merge", expected=True)

    def test_a_matching_setting_produces_no_change(self) -> None:
        changes = plan(_repo(), {"delete_branch_on_merge": True}, set(), controls=[self.CONTROL])

        assert changes == []

    def test_a_differing_setting_is_planned_with_both_values(self) -> None:
        changes = plan(_repo(), {"delete_branch_on_merge": False}, set(), controls=[self.CONTROL])

        assert changes[0].current is False
        assert changes[0].desired is True

    def test_the_gate_placeholder_resolves_to_the_class_checks(self) -> None:
        control = SettingControl(
            "default_branch_protection",
            "protection.main.required_status_checks",
            expected="<class gates>",
            prerequisites=("quality_workflow",),
        )

        changes = plan(_repo(), {}, {"quality_workflow"}, controls=[control])

        assert "test" in changes[0].desired
        assert changes[0].ready is True

    def test_a_missing_prerequisite_blocks_the_change(self) -> None:
        control = SettingControl(
            "default_branch_protection",
            "protection.main.required_status_checks",
            expected="<class gates>",
            prerequisites=("quality_workflow",),
        )

        changes = plan(_repo(), {}, set(), controls=[control])

        assert changes[0].ready is False

    def test_an_existing_description_is_left_alone(self) -> None:
        control = SettingControl("description", "description", expected="<non-empty>")

        assert plan(_repo(), {"description": "already set"}, set(), controls=[control]) == []


class TestApplying:
    def _change(self, **overrides: Any) -> PlannedChange:
        defaults: dict[str, Any] = {
            "repository": "demo",
            "control_id": "delete_branch_on_merge",
            "setting": "delete_branch_on_merge",
            "current": False,
            "desired": True,
        }
        defaults.update(overrides)
        return PlannedChange(**defaults)

    def test_a_dry_run_writes_nothing_but_says_what_it_would_do(self) -> None:
        client = FakeClient()

        report = apply([self._change()], owner="fileworks", client=client, dry_run=True)

        assert client.writes == []
        assert report.results[0].outcome == "skipped"
        assert "would run: PATCH" in report.results[0].detail

    def test_applying_writes_and_verifies(self) -> None:
        client = FakeClient({"delete_branch_on_merge": False})

        report = apply([self._change()], owner="fileworks", client=client, dry_run=False)

        assert report.results[0].outcome == "applied"
        assert client.writes[0].method == "PATCH"

    def test_a_write_that_does_not_read_back_is_unverified_not_applied(self) -> None:
        class Stubborn(FakeClient):
            def __call__(self, call: ApiCall) -> tuple[bool, dict[str, Any]]:
                self.calls.append(call)
                # Accepts the write, then keeps reporting the old value.
                return True, {"delete_branch_on_merge": False}

        report = apply([self._change()], owner="fileworks", client=Stubborn(), dry_run=False)

        assert report.results[0].outcome == "unverified"
        assert "by hand" in report.results[0].detail

    def test_a_blocked_change_is_never_written_even_when_applying(self) -> None:
        client = FakeClient()
        blocked = self._change(
            prerequisites=("quality_workflow",), blocked_by=("quality_workflow",)
        )

        report = apply([blocked], owner="fileworks", client=client, dry_run=False)

        assert client.writes == []
        assert report.results[0].outcome == "blocked"

    def test_a_failed_call_is_reported_with_a_redacted_reason(self) -> None:
        client = FakeClient(fail={"repos/fileworks/demo"})

        report = apply([self._change()], owner="fileworks", client=client, dry_run=False)

        assert report.results[0].outcome == "failed"
        assert report.failures

    def test_a_control_without_a_writer_is_skipped_not_guessed(self) -> None:
        client = FakeClient()

        report = apply(
            [self._change(control_id="something_new", setting="x")],
            owner="fileworks",
            client=client,
            dry_run=False,
        )

        assert client.writes == []
        assert "no writer" in report.results[0].detail

    def test_applying_twice_is_the_same_as_once(self) -> None:
        client = FakeClient({"delete_branch_on_merge": False})
        apply([self._change()], owner="fileworks", client=client, dry_run=False)
        writes_after_first = len(client.writes)

        # The observed value now matches, so planning produces nothing to do.
        assert plan(_repo(), dict(client.state), set(), controls=[TestPlanning.CONTROL]) == []
        assert len(client.writes) == writes_after_first

    def test_the_report_can_produce_a_rollback_record(self) -> None:
        client = FakeClient({"delete_branch_on_merge": False})

        report = apply([self._change()], owner="fileworks", client=client, dry_run=False)

        assert "was false" in report.rollback_script()


class TestStagedRollout:
    def _change(self, control: str) -> PlannedChange:
        return PlannedChange("demo", control, control, current=None, desired=True)

    def test_the_waves_run_cheapest_and_most_reversible_first(self) -> None:
        assert STAGES[0][0] == "presentation"
        assert STAGES[-1][0] == "protection"

    def test_changes_are_grouped_into_their_waves(self) -> None:
        staged = stage_changes(
            [self._change("default_branch_protection"), self._change("description")]
        )

        assert [name for name, _wave in staged] == ["presentation", "protection"]

    def test_an_unknown_control_lands_in_its_own_wave(self) -> None:
        staged = stage_changes([self._change("something_new")])

        assert staged[0][0] == "other"

    def test_a_failing_wave_stops_the_rollout(self) -> None:
        client = FakeClient(fail={"repos/fileworks/demo"})

        reports = rollout(
            [self._change("description"), self._change("default_branch_protection")],
            owner="fileworks",
            client=client,
            dry_run=False,
        )

        assert [name for name, _report in reports] == ["presentation"]

    def test_a_dry_run_rollout_touches_nothing(self) -> None:
        client = FakeClient()

        rollout(
            [self._change("description"), self._change("default_branch_protection")],
            owner="fileworks",
            client=client,
            dry_run=True,
        )

        assert client.writes == []


class TestProtectionNeedsReportingChecks:
    """Branch protection may only require checks GitHub has actually seen.

    The failure this guards against is quiet and total: protection applies
    cleanly, and then every pull request waits forever on a check that no
    workflow reports. Nothing is broken until somebody tries to merge.
    """

    @staticmethod
    def _protection(repo: Repository, reported: tuple[str, ...] | None) -> PlannedChange:
        control = SettingControl(
            "default_branch_protection",
            "protection.main.required_status_checks",
            expected="<class gates>",
            rationale="only green code reaches main",
        )
        changes = plan(repo, {}, set(), controls=[control], reported_checks=reported)
        assert len(changes) == 1
        return changes[0]

    def test_blocked_when_the_required_checks_never_report(self) -> None:
        change = self._protection(_repo(), reported=("quality (ubuntu-latest, Python 3.12)",))
        assert not change.ready
        assert "checks-not-reporting" in change.blocked_by

    def test_ready_once_every_required_check_reports(self) -> None:
        repo = _repo()
        desired = self._protection(repo, reported=None).desired
        change = self._protection(repo, reported=tuple(desired))
        assert change.ready
        assert "checks-not-reporting" not in change.blocked_by

    def test_a_partial_match_is_still_blocked(self) -> None:
        repo = _repo()
        desired = list(self._protection(repo, reported=None).desired)
        change = self._protection(repo, reported=tuple(desired[:-1]))
        assert not change.ready

    def test_unchecked_when_no_observation_was_made(self) -> None:
        # `reported_checks=None` means "not asked", which must not be read as
        # "nothing reports" — an offline plan should not silently gain a blocker.
        change = self._protection(_repo(), reported=None)
        assert "checks-not-reporting" not in change.blocked_by


class TestObservedChecks:
    def test_reads_the_names_off_the_default_branch(self) -> None:
        client = FakeClient({"check_runs": [{"name": "test"}, {"name": "lint"}, {"name": "test"}]})
        assert observed_checks("demo", "fileworks", client) == ("lint", "test")

    def test_an_unreachable_repository_reports_nothing(self) -> None:
        client = FakeClient(fail={"repos/fileworks/demo/commits/main/check-runs"})
        assert observed_checks("demo", "fileworks", client) == ()


class TestObservingProtection:
    """An unprotected branch is an answer; an unreachable one is not."""

    class _Client:
        def __init__(self, error: str) -> None:
            self.error = error

        def __call__(self, call: ApiCall) -> tuple[bool, dict[str, Any]]:
            if call.path.endswith("/branches/main/protection"):
                return False, {"error": self.error}
            if call.path.endswith("/actions/permissions/workflow"):
                return False, {}
            return True, {"description": "d"}

    def test_an_unprotected_branch_reads_as_no_required_checks(self) -> None:
        client = self._Client("HTTP 404: Branch not protected (https://api.github.com/…)")
        observed = observe(_repo(), "fileworks", client)
        assert observed["protection.main.required_status_checks"] == []

    def test_an_unreachable_branch_stays_absent(self) -> None:
        # Reported as unverifiable downstream, which is the honest outcome for
        # "we could not look" — not the same as "nothing is required".
        client = self._Client("HTTP 403: Resource not accessible by integration")
        observed = observe(_repo(), "fileworks", client)
        assert "protection.main.required_status_checks" not in observed


class TestPullRequestChecks:
    """Required contexts must come from what a pull request actually reports."""

    class Runs(FakeClient):
        def __call__(self, call: ApiCall) -> tuple[bool, dict[str, Any]]:
            self.calls.append(call)
            if "/actions/runs?" in call.path:
                return True, {
                    "workflow_runs": [
                        {"id": 2, "workflow_id": 10},
                        {"id": 1, "workflow_id": 10},
                        {"id": 3, "workflow_id": 20},
                    ]
                }
            if call.path.endswith("/runs/2/jobs"):
                return True, {"jobs": [{"name": "quality (ubuntu-latest, Python 3.12)"}]}
            if call.path.endswith("/runs/3/jobs"):
                return True, {
                    "jobs": [
                        {"name": "docs-links", "conclusion": "success"},
                        {"name": "scheduled-scale", "conclusion": "skipped"},
                        {"name": ""},
                    ]
                }
            return False, {}

    def test_it_reads_the_expanded_job_names(self) -> None:
        names = pull_request_checks("demo", "fileworks", self.Runs())

        # Matrix-expanded, because GitHub expanded them — not reimplemented here.
        assert names == ("docs-links", "quality (ubuntu-latest, Python 3.12)")

    def test_conditionally_skipped_jobs_are_never_made_required(self) -> None:
        names = pull_request_checks("demo", "fileworks", self.Runs())

        assert "scheduled-scale" not in names

    def test_only_the_newest_run_of_each_workflow_is_sampled(self) -> None:
        client = self.Runs()

        pull_request_checks("demo", "fileworks", client)

        # Run 1 is an older run of workflow 10 and must not be fetched; asking
        # for it would mix names from a workflow revision that no longer exists.
        assert not [call for call in client.calls if call.path.endswith("/runs/1/jobs")]

    def test_an_unreachable_repository_yields_nothing_rather_than_a_guess(self) -> None:
        assert (
            pull_request_checks(
                "demo",
                "fileworks",
                FakeClient(
                    fail={
                        "repos/fileworks/demo/actions/runs"
                        "?event=pull_request&status=completed&per_page=30"
                    }
                ),
            )
            == ()
        )


class TestRulesets:
    """A ruleset protects `main` just as legacy protection does."""

    class WithRuleset(FakeClient):
        def __call__(self, call: ApiCall) -> tuple[bool, dict[str, Any]]:
            self.calls.append(call)
            if call.path == "repos/fileworks/demo":
                return True, {"description": "a demo", "delete_branch_on_merge": True}
            if call.path.endswith("/branches/main/protection"):
                return False, {"error": "Branch not protected"}
            if call.path.endswith("/rulesets"):
                return True, [  # type: ignore[return-value]
                    {"id": 7, "enforcement": "active"},
                    {"id": 8, "enforcement": "disabled"},
                ]
            if call.path.endswith("/rulesets/7"):
                return True, {
                    "rules": [
                        {"type": "pull_request", "parameters": {}},
                        {
                            "type": "required_status_checks",
                            "parameters": {
                                "required_status_checks": [
                                    {"context": "quality (ubuntu-latest, Python 3.12)"},
                                    {"context": "docs-links"},
                                ]
                            },
                        },
                    ]
                }
            return False, {}

    def test_ruleset_contexts_are_read(self) -> None:
        assert ruleset_checks("demo", "fileworks", self.WithRuleset()) == (
            "docs-links",
            "quality (ubuntu-latest, Python 3.12)",
        )

    def test_a_disabled_ruleset_is_not_counted(self) -> None:
        client = self.WithRuleset()

        ruleset_checks("demo", "fileworks", client)

        assert not [call for call in client.calls if call.path.endswith("/rulesets/8")]

    def test_a_ruleset_protected_branch_is_not_reported_unprotected(self) -> None:
        # The false positive: reading only the legacy endpoint said `main` was
        # unprotected on four repositories that were protected by a ruleset.
        repo = _repo()

        observed = observe(repo, "fileworks", self.WithRuleset())

        assert observed["protection.main.required_status_checks"] == [
            "docs-links",
            "quality (ubuntu-latest, Python 3.12)",
        ]
