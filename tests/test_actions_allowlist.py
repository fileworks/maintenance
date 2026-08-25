"""The allowed-actions policy, checked against the workflows rather than stated.

`actions-allowlist.json` records an organization setting no unauthenticated run
can read. That made it a claim nothing compared anything against: it sat beside
this package unreferenced by any code or test while the standard named it as
authority. The half that *is* checkable from a checkout is the other side of the
same promise — that no workflow in the family uses an action the policy does not
permit, and that every third-party one is pinned to an immutable revision.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from maintenance.paths import REPO_ROOT
from maintenance.policy import (
    ACTIONS_ALLOWLIST_CONTROL,
    ActionsAllowlist,
    Finding,
    Repository,
    evaluate_actions_allowlist,
    read_actions_allowlist,
    repositories,
    workflow_action_references,
)

ALLOWLIST = ActionsAllowlist(
    github_owned_allowed=True,
    verified_allowed=False,
    patterns_allowed=("astral-sh/setup-uv@*", "fileworks/maintenance/*"),
)


def _repo(tmp_path: Path, workflow: str, *, name: str = "sample") -> Repository:
    workflows = tmp_path / name / ".github" / "workflows"
    workflows.mkdir(parents=True, exist_ok=True)
    (workflows / "ci.yml").write_text(workflow, encoding="utf-8")
    return Repository(name=name, repo_class="python_cli", path=tmp_path / name)


def _only(findings: tuple[Finding, ...]) -> Finding:
    assert len(findings) == 1
    return findings[0]


class TestReadingTheAllowlist:
    def test_the_shipped_allowlist_parses(self) -> None:
        allowlist = read_actions_allowlist(REPO_ROOT / "actions-allowlist.json")

        assert allowlist is not None
        assert allowlist.patterns_allowed

    def test_an_absent_file_is_none_rather_than_a_crash(self, tmp_path: Path) -> None:
        assert read_actions_allowlist(tmp_path / "nothing.json") is None

    def test_a_malformed_file_is_none_rather_than_a_crash(self, tmp_path: Path) -> None:
        path = tmp_path / "actions-allowlist.json"
        path.write_text("[not, an, object", encoding="utf-8")

        assert read_actions_allowlist(path) is None


class TestWhatTheWorkflowsUse:
    def test_every_uses_reference_is_collected(self, tmp_path: Path) -> None:
        repo = _repo(
            tmp_path,
            "jobs:\n  a:\n    steps:\n"
            "      - uses: actions/checkout@v7\n"
            "      - uses: astral-sh/setup-uv@" + "a" * 40 + "\n",
        )

        assert workflow_action_references(repo) == (
            "actions/checkout@v7",
            "astral-sh/setup-uv@" + "a" * 40,
        )

    def test_a_repository_without_workflows_yields_nothing(self, tmp_path: Path) -> None:
        (tmp_path / "bare").mkdir()

        assert (
            workflow_action_references(
                Repository(name="bare", repo_class="python_cli", path=tmp_path / "bare")
            )
            == ()
        )


class TestTheVerdict:
    def test_allowed_and_pinned_is_compliant(self, tmp_path: Path) -> None:
        repo = _repo(
            tmp_path,
            "jobs:\n  a:\n    steps:\n"
            "      - uses: actions/checkout@v7\n"
            "      - uses: astral-sh/setup-uv@" + "b" * 40 + "\n",
        )

        finding = _only(evaluate_actions_allowlist([repo], ALLOWLIST))

        assert finding.outcome == "compliant"
        assert finding.control_id == ACTIONS_ALLOWLIST_CONTROL

    def test_a_third_party_action_on_a_mutable_tag_is_a_mismatch(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path, "jobs:\n  a:\n    steps:\n      - uses: astral-sh/setup-uv@v9\n")

        finding = _only(evaluate_actions_allowlist([repo], ALLOWLIST))

        assert finding.outcome == "mismatched"
        assert "not pinned to a commit SHA" in finding.detail

    def test_an_action_nobody_allowed_is_a_mismatch(self, tmp_path: Path) -> None:
        repo = _repo(
            tmp_path,
            "jobs:\n  a:\n    steps:\n      - uses: somebody/else@" + "c" * 40 + "\n",
        )

        finding = _only(evaluate_actions_allowlist([repo], ALLOWLIST))

        assert finding.outcome == "mismatched"
        assert "not on the allowlist" in finding.detail

    def test_github_owned_actions_follow_the_flag_not_the_patterns(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path, "jobs:\n  a:\n    steps:\n      - uses: actions/checkout@v7\n")
        refused = ActionsAllowlist(
            github_owned_allowed=False,
            verified_allowed=False,
            patterns_allowed=ALLOWLIST.patterns_allowed,
        )

        assert _only(evaluate_actions_allowlist([repo], ALLOWLIST)).outcome == "compliant"
        assert _only(evaluate_actions_allowlist([repo], refused)).outcome == "mismatched"

    def test_a_missing_allowlist_is_unverifiable_never_compliant(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path, "jobs:\n  a:\n    steps:\n      - uses: actions/checkout@v7\n")

        finding = _only(evaluate_actions_allowlist([repo], None))

        assert finding.outcome == "unverifiable"
        assert not finding.compliant

    def test_a_repository_with_no_workflows_is_not_reported_at_all(self, tmp_path: Path) -> None:
        (tmp_path / "bare").mkdir()
        repo = Repository(name="bare", repo_class="homebrew_tap", path=tmp_path / "bare")

        assert evaluate_actions_allowlist([repo], ALLOWLIST) == ()


class TestTheRealWorkspace:
    """The check exists to hold *these* repositories, not a fixture."""

    def test_every_sibling_repository_passes_its_own_allowlist(self) -> None:
        workspace = REPO_ROOT.parent
        repos = [repo for repo in repositories(workspace) if repo.path.is_dir()]
        if not any(workflow_action_references(repo) for repo in repos):
            pytest.skip("no sibling repositories are checked out beside this one")

        allowlist = read_actions_allowlist(REPO_ROOT / "actions-allowlist.json")
        offenders = {
            finding.repository: finding.detail
            for finding in evaluate_actions_allowlist(repos, allowlist)
            if not finding.compliant
        }

        assert offenders == {}

    # There is deliberately no "the allowlist names no pattern nothing uses"
    # test here. That question is only answerable with the whole family checked
    # out, and the quality job checks out this repository alone — so an "unused"
    # verdict there would describe the checkout, not the policy. Asserting it
    # anyway failed CI on six patterns that five sibling repositories use every
    # run. Skipping it instead would have been worse: a check that can only
    # skip where it runs is the silence this package exists to break.
