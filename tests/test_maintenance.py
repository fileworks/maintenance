"""The policy tooling itself: it must never claim compliance it did not check."""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from maintenance.docs import (
    check_install_commands,
    check_links,
    check_readme,
    check_structure,
    check_versions,
    render_template,
    status_section,
)
from maintenance.drift import DriftReport, compliance_matrix, plan_settings
from maintenance.gates import GATES, matrix, not_applicable, required_checks
from maintenance.ledger import ReleaseLedger, record, scaffold
from maintenance.paths import REPO_ROOT
from maintenance.policy import (
    FileControl,
    PolicyException,
    Repository,
    SettingControl,
    evaluate,
    file_controls,
    load_exceptions,
    repositories,
    setting_controls,
)
from maintenance.renovate import (
    AutomationMetrics,
    MetricsBaseline,
    metrics_markdown,
)
from maintenance.workflows import (
    CARGO_AUDIT_VERSION,
    DEPENDENCY_AUDIT_JOB,
    DOCS_LINKS_JOB,
    PIP_AUDIT_VERSION,
    alignment_matrix,
    map_gates,
    rename_plan,
)

NOW = datetime(2026, 7, 28, tzinfo=UTC)


def _repo(tmp_path: Path, name: str = "demo", repo_class: str = "python_cli") -> Repository:
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    return Repository(name, repo_class, root)  # type: ignore[arg-type]


class TestPolicyEvaluation:
    def test_a_missing_file_is_missing_not_a_crash(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)

        report = evaluate([repo], controls=[FileControl("readme", "README.md")], settings=[])

        assert report.findings[0].outcome == "missing"
        assert report.compliant is False

    def test_a_present_file_is_compliant(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        (repo.path / "README.md").write_text("# demo", encoding="utf-8")

        report = evaluate([repo], controls=[FileControl("readme", "README.md")], settings=[])

        assert report.findings[0].outcome == "compliant"

    def test_required_content_that_is_absent_is_a_mismatch(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        (repo.path / "LICENSE").write_text("All rights reserved", encoding="utf-8")

        report = evaluate(
            [repo],
            controls=[FileControl("license", "LICENSE", must_contain=("MIT",))],
            settings=[],
        )

        assert report.findings[0].outcome == "mismatched"
        assert "MIT" in report.findings[0].detail

    def test_a_control_that_does_not_apply_is_not_evaluated(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path, repo_class="homebrew_tap")

        report = evaluate(
            [repo],
            controls=[FileControl("changelog", "CHANGELOG.md", applies_to=("python_cli",))],
            settings=[],
        )

        assert report.findings == []

    def test_remote_settings_are_unverifiable_without_authentication(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)

        report = evaluate([repo], controls=[], settings=list(setting_controls()))

        assert all(finding.outcome == "unverifiable" for finding in report.findings)
        assert report.compliant is False  # unverifiable is never compliant

    def test_a_credential_alone_still_verifies_nothing(self, tmp_path: Path) -> None:
        # Being authenticated means a session *could* look, not that it did.
        # Reporting green here would be the compliance tool lying by default.
        repo = _repo(tmp_path)

        report = evaluate(
            [repo], controls=[], settings=list(setting_controls()), authenticated=True
        )

        assert all(finding.outcome == "unverifiable" for finding in report.findings)
        assert report.compliant is False

    def test_observed_settings_are_judged_against_what_was_seen(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)

        report = evaluate(
            [repo],
            controls=[],
            settings=list(setting_controls()),
            authenticated=True,
            observations={
                repo.name: {
                    "description": "does a thing",
                    "delete_branch_on_merge": True,
                    "allow_squash_merge": False,
                    "protection.main.required_status_checks": ["test"],
                    "actions.default_workflow_permissions": "write",
                }
            },
        )

        outcomes = {f.control_id: f.outcome for f in report.findings}
        assert outcomes["description"] == "compliant"
        assert outcomes["delete_branch_on_merge"] == "compliant"
        assert outcomes["default_branch_protection"] == "compliant"
        assert outcomes["allow_squash_merge"] == "mismatched"
        assert outcomes["actions_permissions"] == "mismatched"

    def test_a_setting_the_api_did_not_return_stays_unverifiable(self, tmp_path: Path) -> None:
        # A partial observation must not be read as "the rest are fine".
        repo = _repo(tmp_path)

        report = evaluate(
            [repo],
            controls=[],
            settings=list(setting_controls()),
            authenticated=True,
            observations={repo.name: {"description": "does a thing"}},
        )

        outcomes = {f.control_id: f.outcome for f in report.findings}
        assert outcomes["description"] == "compliant"
        assert outcomes["allow_squash_merge"] == "unverifiable"

    def test_unprotected_main_is_a_mismatch_not_a_pass(self, tmp_path: Path) -> None:
        # An empty required-checks list is what an unprotected branch looks like.
        repo = _repo(tmp_path)

        report = evaluate(
            [repo],
            controls=[],
            settings=list(setting_controls()),
            authenticated=True,
            observations={repo.name: {"protection.main.required_status_checks": []}},
        )

        outcomes = {f.control_id: f.outcome for f in report.findings}
        assert outcomes["default_branch_protection"] == "mismatched"


class TestExceptions:
    def test_a_live_exception_excuses_a_control(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        exception = PolicyException(
            "demo",
            "readme",
            "prototype",
            "owner",
            (NOW + timedelta(days=30)).isoformat(),
        )

        report = evaluate(
            [repo],
            exceptions=[exception],
            controls=[FileControl("readme", "README.md")],
            settings=[],
            today=NOW,
        )

        assert report.findings[0].outcome == "excepted"
        assert report.compliant is True

    def test_an_expired_exception_is_stale_not_compliant(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        exception = PolicyException(
            "demo",
            "readme",
            "prototype",
            "owner",
            (NOW - timedelta(days=1)).isoformat(),
        )

        report = evaluate(
            [repo],
            exceptions=[exception],
            controls=[FileControl("readme", "README.md")],
            settings=[],
            today=NOW,
        )

        assert report.findings[0].outcome == "stale"
        assert report.compliant is False

    def test_an_exception_without_an_owner_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "exceptions.json"
        path.write_text(
            json.dumps(
                {"exceptions": [{"repository": "demo", "control_id": "readme", "reason": "x"}]}
            ),
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="owner"):
            load_exceptions(path)

    def test_an_absent_exception_file_is_simply_empty(self, tmp_path: Path) -> None:
        assert load_exceptions(tmp_path / "nothing.json") == ()


class TestGates:
    def test_each_class_gets_the_gates_it_can_actually_run(self) -> None:
        assert "formula-audit" in required_checks("homebrew_tap")
        assert "formula-audit" not in required_checks("python_cli")
        assert "installer-preflight" in required_checks("desktop_application")

    def test_a_gate_that_does_not_apply_carries_a_reason(self) -> None:
        skipped = dict(not_applicable("homebrew_tap"))

        assert "typecheck" in skipped
        assert skipped["typecheck"]

    def test_gate_names_are_unique_and_stable(self) -> None:
        names = [gate.gate_id for gate in GATES]

        assert len(names) == len(set(names))
        assert "test" in names  # renaming this silently unprotects a branch

    def test_the_matrix_covers_every_class(self) -> None:
        table = matrix()

        assert set(table["test"]) == {
            "desktop_application",
            "python_cli",
            "homebrew_tap",
            "governance_tool",
        }


class TestRenovate:
    def test_the_central_policy_batches_routine_updates_and_automerge_is_green_only(self) -> None:
        policy = json.loads((REPO_ROOT / "renovate-policy.json").read_text(encoding="utf-8"))

        assert policy["prConcurrentLimit"] == 1
        assert policy["branchConcurrentLimit"] == 1
        assert policy["minimumReleaseAge"] == "7 days"
        assert policy["schedule"] == ["before 5am on monday"]
        assert policy["automerge"] is False
        assert policy["automergeType"] == "pr"
        assert policy["automergeStrategy"] == "squash"
        assert policy["platformAutomerge"] is False
        assert policy["ignoreTests"] is False
        assert policy["lockFileMaintenance"] == {"enabled": False}
        # The urgent lane is asserted on its own, below.
        assert policy["vulnerabilityAlerts"]["enabled"] is True

        weekly = next(
            rule
            for rule in policy["packageRules"]
            if rule.get("groupSlug") == "weekly-dependency-updates"
        )
        assert set(weekly["matchUpdateTypes"]) == {
            "minor",
            "patch",
            "pin",
            "pinDigest",
            "digest",
            "bump",
        }
        assert weekly["automerge"] is True
        assert weekly["semanticCommitType"] == "fix"
        assert weekly["semanticCommitScope"] == "deps"

    def test_the_urgent_vulnerability_lane_sets_every_field_explicitly(self) -> None:
        """DEC-05 / F-02.

        The lane used to be `{"enabled": false}`, justified by the claim that
        Renovate's vulnerability PRs bypass schedules and concurrency limits
        anyway. That claim is **unverified against primary documentation**, and
        a security lane is not a good place to rely on an unverified bypass — so
        every field is set explicitly instead of inherited.

        This asserts the *resolved policy shape*, which is what this repository
        owns. It deliberately does **not** assert runtime queue behaviour: these
        fields are declarative defence-in-depth, and claiming they prevent
        queueing would be exactly the unverified inference this replaces.
        """
        policy = json.loads((REPO_ROOT / "renovate-policy.json").read_text(encoding="utf-8"))
        lane = policy["vulnerabilityAlerts"]

        assert lane["enabled"] is True
        # No soak: waiting is the risk this lane exists to remove.
        assert lane["minimumReleaseAge"] is None
        # The explicit no-calendar schedule, not an empty list.
        assert lane["schedule"] == ["at any time"]
        # Never batched — a security fix has to be reviewable on its own.
        assert lane["groupName"] is None
        assert lane["labels"] == ["security"]
        # 0 is Renovate's "no limit", so an urgent fix is never held behind the
        # single weekly branch.
        assert lane["prConcurrentLimit"] == 0
        assert lane["branchConcurrentLimit"] == 0
        # Speed of proposal, not of merge: a security update still gets a human.
        assert lane["automerge"] is False
        assert lane["dependencyDashboardApproval"] is False

    def test_the_urgent_lane_does_not_inherit_the_weekly_lane_by_omission(self) -> None:
        """Every field the routine lane sets is answered here, or inherited on purpose."""
        policy = json.loads((REPO_ROOT / "renovate-policy.json").read_text(encoding="utf-8"))
        lane = policy["vulnerabilityAlerts"]

        inheritable = (
            "minimumReleaseAge",
            "schedule",
            "prConcurrentLimit",
            "branchConcurrentLimit",
        )
        for field in inheritable:
            assert field in lane, f"{field} would be inherited from the weekly lane"
            assert lane[field] != policy[field], (
                f"{field} matches the routine lane, so the urgent lane is not urgent"
            )

    def test_every_consumer_extends_the_policy_by_its_exact_spelling(self) -> None:
        """A preset reference is resolved as a literal string, not as a path.

        `github>fileworks/maintenance:renovate-policy` resolves the *preset*
        `renovate-policy`. Writing `renovate-policy.json` looks equivalent and
        is not — so a consumer with the wrong spelling silently inherits
        nothing, including the urgent lane this change adds. It would look
        configured and behave as if it were not.

        Skipped rather than failed when the sibling checkout is absent: this is
        a local multi-repository workspace, and CI checks out one repository.
        """
        workspace = REPO_ROOT.parent
        checked = 0
        for name in (
            "media-sorter",
            "immich-export",
            "paperless-export",
            "unpacksort",
            "homebrew-tap",
        ):
            config = workspace / name / "renovate.json"
            if not config.is_file():
                continue
            checked += 1
            extends = json.loads(config.read_text(encoding="utf-8")).get("extends")
            assert extends == ["github>fileworks/maintenance:renovate-policy"], (
                f"{name} does not extend the central policy by its exact spelling: {extends}"
            )
        if checked == 0:
            pytest.skip("no sibling consumer checkouts in this workspace")

    def test_the_routine_lane_keeps_its_seven_day_soak(self) -> None:
        """Guard rail: adding an urgent lane must not loosen the routine one.

        The plan is explicit that the routine soak is not to be changed to 14
        days — or to anything else — without a separate measured decision.
        """
        policy = json.loads((REPO_ROOT / "renovate-policy.json").read_text(encoding="utf-8"))

        assert policy["minimumReleaseAge"] == "7 days"
        assert policy["prConcurrentLimit"] == 1
        assert policy["branchConcurrentLimit"] == 1

    def test_the_central_policy_holds_every_breaking_risk_update_for_approval(self) -> None:
        policy = json.loads((REPO_ROOT / "renovate-policy.json").read_text(encoding="utf-8"))

        manual = next(
            rule
            for rule in policy["packageRules"]
            if rule.get("semanticCommitScope") == "deps-major"
        )
        assert set(manual["matchUpdateTypes"]) == {"major", "replacement", "rollback"}
        assert manual["dependencyDashboardApproval"] is True
        assert manual["automerge"] is False
        assert manual["semanticCommitType"] == "chore"

    def test_metrics_recommend_nothing_before_a_cycle_has_run(self) -> None:
        assert "nothing to tune" in AutomationMetrics().recommendation()

    def test_metrics_call_out_more_failures_than_merges(self) -> None:
        metrics = AutomationMetrics(opened=10, automerged=2, failed=5)

        assert "inspect failures" in metrics.recommendation()
        assert "20%" in metrics.summary()


class TestLedger:
    def test_the_scaffold_starts_unverified(self) -> None:
        ledger = scaffold()

        assert ledger.product("unpacksort") is not None
        assert all(
            entry.state in {"unverified", "not_applicable"}
            for product in ledger.products
            for entry in product.channels
        )

    def test_recording_an_observation_marks_it_verified(self) -> None:
        ledger = record(scaffold(), "immich-export", "pypi", version="0.0.4", observed_at=NOW)

        product = ledger.product("immich-export")
        assert product is not None
        entry = product.channel("pypi")
        assert entry is not None
        assert entry.state == "verified"
        assert entry.displayable == "0.0.4"

    def test_disagreeing_channels_are_reported_not_resolved(self) -> None:
        ledger = record(scaffold(), "immich-export", "pypi", version="0.0.4", observed_at=NOW)
        ledger = record(ledger, "immich-export", "homebrew", version="0.0.3", observed_at=NOW)

        product = ledger.product("immich-export")
        assert product.channels_disagree is True  # type: ignore[union-attr]
        assert product.released_version is None  # type: ignore[union-attr]

    def test_an_old_observation_goes_stale(self) -> None:
        ledger = record(
            scaffold(),
            "immich-export",
            "pypi",
            version="0.0.4",
            observed_at=NOW - timedelta(days=90),
        )

        assert ("immich-export", "pypi") in ledger.stale(today=NOW)

    def test_unverified_channels_are_listed(self) -> None:
        assert ("unpacksort", "pypi") in scaffold().unverified

    def test_the_markdown_never_claims_an_unverified_version(self) -> None:
        text = scaffold().markdown()

        assert "unverified" in text

    def test_a_ledger_round_trips_through_disk(self, tmp_path: Path) -> None:
        ledger = record(scaffold(), "unpacksort", "pypi", version="1.0.0", observed_at=NOW)
        path = ledger.write(tmp_path / "ledger.json")

        reloaded = ReleaseLedger.read(path)

        assert reloaded.product("unpacksort").released_version == "1.0.0"  # type: ignore[union-attr]


class TestDocumentation:
    def test_a_missing_section_is_reported(self) -> None:
        issues = check_structure("demo", "python_cli", "# demo\n\n## Install\n")

        assert any("Overview" in issue.detail for issue in issues)

    def test_a_cli_without_an_install_line_is_reported(self) -> None:
        issues = check_install_commands("demo", "python_cli", "# demo\n")

        assert len(issues) == 2  # pipx and brew

    def test_a_documented_install_satisfies_the_check(self) -> None:
        markdown = "pipx install demo\nbrew install fileworks/tap/demo\n"

        assert check_install_commands("demo", "python_cli", markdown) == ()

    def test_an_ip_address_is_not_mistaken_for_a_version(self) -> None:
        ledger = record(scaffold(), "unpacksort", "pypi", version="1.0.0", observed_at=NOW)

        issues = check_versions("unpacksort", "Runs on http://127.0.0.1:8000", ledger)

        assert issues == ()

    def test_a_stale_quoted_version_is_reported(self) -> None:
        ledger = record(scaffold(), "unpacksort", "pypi", version="1.0.0", observed_at=NOW)

        issues = check_versions("unpacksort", "Install unpacksort 0.9.0 today", ledger)

        assert issues and "0.9.0" in issues[0].detail

    def test_a_version_quoted_without_a_verified_channel_is_unverifiable(self) -> None:
        issues = check_versions("unpacksort", "version 1.2.3", scaffold())

        assert issues[0].kind == "unverifiable_version"

    def test_a_broken_relative_link_is_reported(self, tmp_path: Path) -> None:
        issues = check_links("demo", "See [the licence](LICENSE)", tmp_path)

        assert issues and "LICENSE" in issues[0].detail

    def test_external_links_are_not_checked_offline(self, tmp_path: Path) -> None:
        assert check_links("demo", "[home](https://example.com)", tmp_path) == ()

    def test_a_missing_readme_short_circuits(self, tmp_path: Path) -> None:
        issues = check_readme("demo", "python_cli", tmp_path)

        assert len(issues) == 1
        assert issues[0].kind == "missing_readme"

    def test_the_status_section_is_generated_from_the_ledger(self) -> None:
        ledger = record(scaffold(), "unpacksort", "pypi", version="1.0.0", observed_at=NOW)

        section = status_section("unpacksort", ledger)

        assert "1.0.0" in section
        assert "unverified" in section  # the other channels, honestly

    def test_a_template_renders_with_its_status_block(self) -> None:
        text = render_template(
            "python_cli",
            name="unpacksort",
            description="d",
            package="unpacksort",
            ledger=scaffold(),
        )

        assert "## Status" in text
        assert "pipx install unpacksort" in text


class TestDriftReport:
    def test_a_clean_report_says_so(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        (repo.path / "README.md").write_text("# demo", encoding="utf-8")
        policy = evaluate([repo], controls=[FileControl("readme", "README.md")], settings=[])

        report = DriftReport(policy=policy)

        assert report.clean is True
        assert "satisfied" in report.summary()

    def test_unverifiable_controls_are_separated_from_failures(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        policy = evaluate(
            [repo],
            controls=[FileControl("readme", "README.md")],
            settings=list(setting_controls()),
        )

        report = DriftReport(policy=policy)

        assert len(report.blocking) == 1  # only the genuinely missing README
        assert "unverifiable" in report.summary()

    def test_the_markdown_states_that_nothing_was_applied(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        policy = evaluate([repo], controls=[], settings=[])
        planned = plan_settings(repo, {"delete_branch_on_merge": False}, policy)

        text = DriftReport(policy=policy, planned=planned).markdown()

        assert "Nothing above has been applied" in text

    def test_a_change_whose_prerequisite_is_red_is_blocked(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path, repo_class="desktop_application")
        policy = evaluate([repo], controls=[], settings=[])
        control = SettingControl(
            "default_branch_protection",
            "protection.main.required_status_checks",
            expected="<class gates>",
            prerequisites=("quality_workflow",),
        )

        planned = plan_settings(repo, {}, policy, controls=(control,), checks=["lint"])

        assert planned[0].ready is False
        assert planned[0].blocked_by == ("quality_workflow",)

    def test_a_change_whose_prerequisite_is_green_is_ready(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path, repo_class="desktop_application")
        (repo.path / ".github" / "workflows").mkdir(parents=True)
        (repo.path / ".github" / "workflows" / "ci.yml").write_text("on: push", encoding="utf-8")
        policy = evaluate(
            [repo],
            controls=[FileControl("quality_workflow", ".github/workflows/ci.yml")],
            settings=[],
        )
        control = SettingControl(
            "default_branch_protection",
            "protection.main.required_status_checks",
            expected="<class gates>",
            prerequisites=("quality_workflow",),
        )

        observed = ["Backend — lint / typecheck / test", "Frontend — typecheck / build"]

        planned = plan_settings(repo, {}, policy, controls=(control,), checks=observed)

        assert planned[0].ready is True
        # The names a pull request actually reports — not gate ids. This
        # previously asserted `"installer-preflight" in desired`, which is a gate
        # id and matches no check GitHub ever produces.
        assert planned[0].desired == observed

    def test_branch_protection_is_never_planned_from_gate_ids(self, tmp_path: Path) -> None:
        # The regression this replaces: `<class gates>` resolved to
        # `required_checks()`, so a plan would have required nine nonexistent
        # contexts — `format`, `lint`, `test` — on every repository at once,
        # making all five permanently unmergeable.
        repo = _repo(tmp_path, repo_class="desktop_application")
        (repo.path / ".github" / "workflows").mkdir(parents=True)
        (repo.path / ".github" / "workflows" / "ci.yml").write_text("on: push", encoding="utf-8")
        policy = evaluate(
            [repo],
            controls=[FileControl("quality_workflow", ".github/workflows/ci.yml")],
            settings=[],
        )
        control = SettingControl(
            "default_branch_protection",
            "protection.main.required_status_checks",
            expected="<class gates>",
            prerequisites=("quality_workflow",),
        )

        planned = plan_settings(repo, {}, policy, controls=(control,))

        assert planned[0].desired == []
        assert planned[0].ready is False
        assert "observed pull-request check names" in planned[0].blocked_by

    def test_the_matrix_marks_unverifiable_distinctly(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        policy = evaluate([repo], controls=[], settings=list(setting_controls()))

        table = compliance_matrix(policy, (repo,))

        assert "❓" in table
        assert "unverifiable" in table


class TestWorkspaceShape:
    def test_all_six_governed_repositories_are_named(self, tmp_path: Path) -> None:
        names = {repo.name for repo in repositories(tmp_path)}

        assert names == {
            "media-sorter",
            "immich-export",
            "paperless-export",
            "unpacksort",
            "homebrew-tap",
            "maintenance",
        }

    def test_every_file_control_states_why_it_exists(self) -> None:
        assert all(control.rationale for control in file_controls())

    def test_every_setting_control_states_why_it_exists(self) -> None:
        assert all(control.rationale for control in setting_controls())


class TestAlternativePaths:
    def test_an_alternative_filename_satisfies_the_control(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        (repo.path / ".github" / "workflows").mkdir(parents=True)
        (repo.path / ".github" / "workflows" / "quality.yml").write_text(
            "on: push", encoding="utf-8"
        )

        report = evaluate(
            [repo],
            controls=[
                FileControl(
                    "quality_workflow",
                    ".github/workflows/ci.yml",
                    alternatives=(".github/workflows/quality.yml",),
                )
            ],
            settings=[],
        )

        assert report.findings[0].outcome == "compliant"

    def test_the_absence_message_names_every_accepted_path(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)

        report = evaluate(
            [repo],
            controls=[FileControl("quality_workflow", "a.yml", alternatives=("b.yml",))],
            settings=[],
        )

        assert "a.yml or b.yml" in report.findings[0].detail


class TestWorkflowMapping:
    def _repo_with(self, tmp_path: Path, filename: str, content: str) -> Repository:
        repo = _repo(tmp_path, repo_class="python_cli")
        workflows = repo.path / ".github" / "workflows"
        workflows.mkdir(parents=True, exist_ok=True)
        (workflows / filename).write_text(content, encoding="utf-8")
        return repo

    def test_a_gate_is_found_wherever_it_is_phrased(self, tmp_path: Path) -> None:
        repo = self._repo_with(
            tmp_path,
            "ci.yml",
            "name: ci\njobs:\n  quality:\n    steps:\n      - run: uv run pytest -q\n",
        )

        report = map_gates(repo)

        test_gate = next(item for item in report.mappings if item.gate == "test")
        assert test_gate.present is True
        assert test_gate.job == "quality"

    def test_a_gate_that_is_absent_is_reported_missing(self, tmp_path: Path) -> None:
        repo = self._repo_with(tmp_path, "ci.yml", "name: ci\njobs:\n  quality:\n    steps: []\n")

        assert "test" in map_gates(repo).missing
        assert map_gates(repo).aligned is False

    def test_a_repository_without_workflows_says_so(self, tmp_path: Path) -> None:
        assert "no workflows" in map_gates(_repo(tmp_path)).summary()

    def test_a_job_running_several_gates_is_never_renamed(self, tmp_path: Path) -> None:
        repo = self._repo_with(
            tmp_path,
            "ci.yml",
            "name: ci\njobs:\n  quality:\n    steps:\n"
            "      - run: ruff check .\n"
            "      - run: uv run mypy\n"
            "      - run: uv run pytest -q\n",
        )

        plans, multi = rename_plan(map_gates(repo))

        assert plans == []
        assert len(multi) == 1
        assert set(multi[0].gates) == {"lint", "typecheck", "test"}
        assert "split it" in multi[0].describe()

    def test_a_job_running_exactly_one_gate_is_renamed(self, tmp_path: Path) -> None:
        repo = self._repo_with(
            tmp_path,
            "ci.yml",
            "name: ci\njobs:\n  audit:\n    steps:\n      - run: pip-audit\n",
        )

        plans, multi = rename_plan(map_gates(repo))

        assert multi == []
        assert plans[0].current_job == "audit"
        assert plans[0].desired_check == "dependency-audit"

    def test_a_job_already_named_after_its_gate_is_left_alone(self, tmp_path: Path) -> None:
        repo = self._repo_with(
            tmp_path,
            "ci.yml",
            "name: ci\njobs:\n  dependency-audit:\n    steps:\n      - run: pip-audit\n",
        )

        plans, _multi = rename_plan(map_gates(repo))

        assert plans == []

    def test_the_matrix_marks_inapplicable_gates_distinctly(self, tmp_path: Path) -> None:
        repo = self._repo_with(
            tmp_path,
            "ci.yml",
            "name: ci\njobs:\n  quality:\n    steps:\n      - run: uv run pytest\n",
        )

        table = alignment_matrix([map_gates(repo)])

        assert "formula-audit" not in table.split("\n\n")[0]
        assert "does not run" in table


class TestMetricsBaseline:
    def test_nothing_is_tuned_from_a_single_month(self) -> None:
        baseline = MetricsBaseline()

        assert baseline.established is False
        assert "become the baseline" in baseline.compare(AutomationMetrics(opened=10))

    def test_a_later_month_is_compared_against_the_baseline(self) -> None:
        baseline = MetricsBaseline("2026-08", AutomationMetrics(opened=10, automerged=6))

        summary = baseline.compare(AutomationMetrics(opened=14, automerged=12))

        assert "up by 4" in summary
        assert "2026-08 baseline" in summary

    def test_the_table_renders_every_recorded_month(self) -> None:
        table = metrics_markdown(
            {
                "2026-08": AutomationMetrics(opened=10, automerged=6),
                "2026-09": AutomationMetrics(opened=8, automerged=7),
            },
            MetricsBaseline("2026-08", AutomationMetrics(opened=10, automerged=6)),
        )

        assert "2026-08" in table and "2026-09" in table
        assert "Recommendation" in table


class TestSharedWorkflows:
    def test_the_shared_workflows_are_reusable_and_least_privileged(self) -> None:
        for name in ("reusable-python-quality.yml", "reusable-docs-links.yml"):
            source = (REPO_ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
            assert "workflow_call:" in source
            assert "permissions:\n  contents: read" in source

    def test_the_shared_workflows_never_publish(self) -> None:
        for path in (REPO_ROOT / ".github" / "workflows").glob("reusable-*.yml"):
            source = path.read_text(encoding="utf-8")
            for forbidden in (
                "pypi",
                "twine",
                "softprops/action-gh-release",
                "id-token",
            ):
                assert forbidden not in source.lower(), f"{path.name} must not publish"

    def test_the_legacy_non_callable_workflow_directory_is_gone(self) -> None:
        assert not (REPO_ROOT / "workflows-shared").exists()

    def test_every_nested_action_is_pinned_to_a_full_commit(self) -> None:
        for path in (REPO_ROOT / ".github" / "workflows").glob("reusable-*.yml"):
            source = path.read_text(encoding="utf-8")
            revisions = re.findall(r"^\s*- uses: [^@\s]+@([^\s#]+)$", source, re.MULTILINE)

            assert revisions, f"{path.name} must invoke at least one pinned action"
            assert all(re.fullmatch(r"[0-9a-f]{40}", revision) for revision in revisions)

    def test_the_quality_workflow_exposes_the_bounded_consumer_inputs(self) -> None:
        source = (REPO_ROOT / ".github/workflows/reusable-python-quality.yml").read_text(
            encoding="utf-8"
        )

        for name in (
            "working-directory",
            "python-version",
            "runs-on",
            "sync-mode",
            "install-poppler",
            "typecheck-target",
            "audit",
        ):
            assert f"      {name}:" in source

        assert "all-extras-dev|all-groups) ;;" in source
        sync_commands = [
            line.strip() for line in source.splitlines() if line.strip().startswith("run: uv sync")
        ]
        assert sync_commands == [
            'run: uv sync --locked --all-extras --dev --python "$PYTHON_VERSION"',
            'run: uv sync --locked --all-groups --python "$PYTHON_VERSION"',
        ]

    def test_poppler_is_installed_conditionally_on_the_reusable_job_runner(self) -> None:
        source = (REPO_ROOT / ".github/workflows/reusable-python-quality.yml").read_text(
            encoding="utf-8"
        )
        poppler_step = source.index("- name: Install Poppler on the test runner")
        first_sync_step = source.index("- name: Install the locked all-extras")

        assert "if: inputs.install-poppler" in source[poppler_step:first_sync_step]
        assert "packages: poppler-utils" in source[poppler_step:first_sync_step]
        assert poppler_step < first_sync_step

    def test_working_directory_applies_to_sync_and_every_quality_gate(self) -> None:
        source = (REPO_ROOT / ".github/workflows/reusable-python-quality.yml").read_text(
            encoding="utf-8"
        )

        assert source.count("working-directory: ${{ inputs.working-directory }}") == 7

    def test_the_generated_docs_links_job_remains_a_local_emitter(self) -> None:
        source = (REPO_ROOT / ".github/workflows/quality.yml").read_text(encoding="utf-8")

        assert "Generated by maintenance/workflows.py" in DOCS_LINKS_JOB
        assert "uses: fileworks/maintenance" not in DOCS_LINKS_JOB
        assert "Generated by maintenance/workflows.py" in source
        assert "uses: fileworks/maintenance/.github/workflows/reusable-docs-links.yml" not in source

    def test_the_unwire_runbook_names_every_supported_consumer_and_exact_restore(self) -> None:
        source = (REPO_ROOT / "docs/runbooks/reusable-quality-unwire.md").read_text(
            encoding="utf-8"
        )

        for repository, workflow in (
            ("immich-export", ".github/workflows/ci.yml"),
            ("paperless-export", ".github/workflows/ci.yml"),
            ("unpacksort", ".github/workflows/quality.yml"),
        ):
            assert repository in source
            assert workflow in source

        assert "git apply --reverse --3way" in source
        assert "chore(ci): restore local Python quality job" in source

    def test_the_quality_workflow_exposes_its_revision(self) -> None:
        source = (REPO_ROOT / ".github/workflows/reusable-python-quality.yml").read_text(
            encoding="utf-8"
        )

        assert "outputs:" in source
        assert "revision" in source

    def test_the_gate_step_names_match_the_registry(self) -> None:
        source = (REPO_ROOT / ".github/workflows/reusable-python-quality.yml").read_text(
            encoding="utf-8"
        )

        for gate in ("format", "lint", "typecheck", "test", "dependency-audit"):
            assert f"- name: {gate}" in source, gate

    def test_the_shared_typecheck_always_has_an_explicit_target(self) -> None:
        source = (REPO_ROOT / ".github/workflows/reusable-python-quality.yml").read_text(
            encoding="utf-8"
        )

        assert "typecheck-target:" in source
        assert 'uv run mypy --strict "$MYPY_TARGET"' in source

    def test_generated_dependency_audit_represents_every_shipped_ecosystem(
        self,
    ) -> None:
        assert "uv export --locked --all-extras --no-dev --no-emit-project" in (
            DEPENDENCY_AUDIT_JOB
        )
        assert f"pip-audit=={PIP_AUDIT_VERSION}" in DEPENDENCY_AUDIT_JOB
        assert "npm audit --omit=dev --audit-level=high" in DEPENDENCY_AUDIT_JOB
        assert f"cargo-audit --locked --version {CARGO_AUDIT_VERSION}" in (DEPENDENCY_AUDIT_JOB)
        assert "uv run pip-audit" not in DEPENDENCY_AUDIT_JOB

    # The technique, not the assertion, is POSIX-only: it puts a `#!/bin/sh` shim
    # named `uvx` on an emptied PATH, and `cmd.exe` will not run an extensionless
    # shebang script. The generated command itself is still asserted above and on
    # the POSIX runners. Left as a skip rather than a Windows shim so the shape of
    # what is proven stays the same everywhere it runs.
    @pytest.mark.skipif(os.name == "nt", reason="the fake-binary shim relies on a shebang")
    def test_generated_pinned_auditor_command_starts_in_a_clean_environment(
        self, tmp_path: Path
    ) -> None:
        command = re.search(
            rf"uvx --from pip-audit=={re.escape(PIP_AUDIT_VERSION)} "
            r"pip-audit --version",
            DEPENDENCY_AUDIT_JOB,
        )
        assert command is not None
        binary = tmp_path / "uvx"
        binary.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\"\n", encoding="utf-8")
        binary.chmod(0o755)
        environment = dict(os.environ)
        environment["PATH"] = str(tmp_path)

        result = subprocess.run(
            command.group(0),
            shell=True,
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )

        assert result.returncode == 0
        assert result.stdout.strip() == (
            f"--from pip-audit=={PIP_AUDIT_VERSION} pip-audit --version"
        )


class TestAuditSectionsAreSeparate:
    """File findings and setting findings answer different questions.

    They are also fixed in different places — one by editing the repository,
    one by calling GitHub — so a section that mixed them would send the reader
    to the wrong remedy.
    """

    def test_setting_findings_do_not_appear_under_repository_files(self, tmp_path: Path) -> None:
        from maintenance.audit import run as audit_run

        (tmp_path / "media-sorter").mkdir()
        report = audit_run(
            tmp_path,
            authenticated=True,
            observations={"media-sorter": {"description": ""}},
        )
        sections = {section.name: section for section in report.sections}

        assert any("description" in line for line in sections["Remote settings"].findings)
        assert not any("description" in line for line in sections["Repository files"].findings)


class TestPredicatesAreNotValues:
    """`expected` sometimes states a rule, and a rule must never be written."""

    def test_a_satisfied_description_is_not_rewritten(self, tmp_path: Path) -> None:
        # The regression: `<non-empty>` was planned as the desired *value*, so a
        # run would have set all five descriptions to the literal string
        # "<non-empty>" — destroying five correct descriptions to satisfy a
        # predicate they already satisfied.
        repo = _repo(tmp_path)
        policy = evaluate([repo], controls=[], settings=[])
        control = SettingControl("description", "description", expected="<non-empty>")

        planned = plan_settings(
            repo, {"description": "already a good description"}, policy, controls=(control,)
        )

        assert planned == []

    def test_an_empty_description_is_planned_as_the_intended_text(self, tmp_path: Path) -> None:
        root = tmp_path / "demo"
        root.mkdir(parents=True, exist_ok=True)
        repo = Repository("demo", "python_cli", root, "What the tool actually does")
        policy = evaluate([repo], controls=[], settings=[])
        control = SettingControl("description", "description", expected="<non-empty>")

        planned = plan_settings(repo, {"description": ""}, policy, controls=(control,))

        assert planned[0].desired == "What the tool actually does"
        assert "<non-empty>" not in str(planned[0].desired)
