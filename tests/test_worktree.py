"""A verdict about a checkout must say it is about a checkout."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from maintenance.drift import DriftReport
from maintenance.policy import PolicyReport
from maintenance.worktree import GitRunner, TreeState, inspect, unpublished


def _runner(
    *, branch: str = "main", status: str = "", ahead: str = "0", git_dir_ok: bool = True
) -> GitRunner:
    def run(_path: Path, arguments: Sequence[str]) -> tuple[int, str]:
        head = list(arguments)[:2]
        if head == ["rev-parse", "--git-dir"]:
            return (0, ".git\n") if git_dir_ok else (128, "")
        if head == ["rev-parse", "--abbrev-ref"]:
            return 0, f"{branch}\n"
        if head == ["status", "--porcelain"]:
            return 0, status
        if head == ["rev-list", "--count"]:
            return 0, f"{ahead}\n"
        return 1, ""

    return run


class TestInspect:
    def test_a_clean_checkout_publishes_what_it_checks(self, tmp_path: Path) -> None:
        state = inspect("demo", tmp_path, runner=_runner())

        assert state is not None
        assert state.publishes_what_it_checks
        assert "matches main" in state.describe()

    def test_a_directory_that_is_not_a_repository_is_none_not_clean(self, tmp_path: Path) -> None:
        # The distinction that matters: "could not look" must never render as a
        # clean bill of health.
        assert inspect("demo", tmp_path, runner=_runner(git_dir_ok=False)) is None

    def test_a_missing_directory_is_none(self) -> None:
        assert inspect("demo", Path("/nonexistent-xyz"), runner=_runner()) is None

    def test_uncommitted_files_are_counted_and_named(self, tmp_path: Path) -> None:
        state = inspect("demo", tmp_path, runner=_runner(status=" M a.py\n?? b.py\n M c.py\n"))

        assert state is not None
        assert state.dirty_files == 3
        assert not state.publishes_what_it_checks
        assert "3 uncommitted file(s)" in state.describe()

    def test_unpushed_commits_are_counted(self, tmp_path: Path) -> None:
        state = inspect("demo", tmp_path, runner=_runner(ahead="2"))

        assert state is not None
        assert state.unpushed_commits == 2
        assert "2 unpushed commit(s)" in state.describe()

    def test_both_conditions_are_reported_together(self, tmp_path: Path) -> None:
        state = inspect("demo", tmp_path, runner=_runner(status=" M a.py\n", ahead="1"))

        assert state is not None
        detail = state.describe()
        assert "1 uncommitted file(s)" in detail
        assert "1 unpushed commit(s)" in detail

    def test_a_branch_whose_upstream_is_gone_still_measures_against_main(
        self, tmp_path: Path
    ) -> None:
        # The case that hid unmerged work: `@{u}` is gone, but origin/main is not.
        state = inspect("demo", tmp_path, runner=_runner(branch="orphaned-branch", ahead="4"))

        assert state is not None
        assert state.unpushed_commits == 4
        assert "orphaned-branch" in state.describe()


class TestReporting:
    def test_only_drifted_checkouts_are_listed(self) -> None:
        clean = TreeState("a", "main", 0, 0)
        dirty = TreeState("b", "main", 2, 0)

        assert unpublished([clean, dirty]) == (dirty,)

    def test_the_report_states_what_its_verdict_describes(self) -> None:
        report = DriftReport(
            policy=PolicyReport(findings=[]),
            trees=[TreeState("media-sorter", "wip", 14, 2)],
        )

        markdown = report.markdown()

        assert "What this verdict describes" in markdown
        assert "14 uncommitted file(s)" in markdown
        assert "2 unpushed commit(s)" in markdown

    def test_a_clean_workspace_adds_no_caveat(self) -> None:
        report = DriftReport(
            policy=PolicyReport(findings=[]),
            trees=[TreeState("media-sorter", "main", 0, 0)],
        )

        assert "What this verdict describes" not in report.markdown()
