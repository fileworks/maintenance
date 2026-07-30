"""Whether a repository's checkout still says what its published branch says.

Every file control in this package reads the working tree. That is the right
input while a change is being prepared and the wrong one for the question people
actually ask a compliance report: *is the published repository in policy?*

Those answers diverge whenever a checkout holds work that has not landed, and
they diverged badly in practice — three controls read as satisfied because the
files they wanted existed only in an unmerged commit. `media-sorter` was reported
as having a security policy while `main` had none.

So the report states the checkout's condition alongside its verdict. It does not
try to evaluate the remote tree instead: fetching and reading another revision is
a different, heavier operation, and a report that silently did it would be
answering a question nobody asked. Saying "this verdict describes a checkout that
is 14 files dirty and 2 commits ahead" is enough for a reader to know what the
verdict is worth.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

#: Runs a git command in a directory and returns (returncode, stdout).
GitRunner = Callable[[Path, Sequence[str]], tuple[int, str]]


def _git(path: Path, arguments: Sequence[str]) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return completed.returncode, completed.stdout


@dataclass(frozen=True)
class TreeState:
    """What a checkout holds that its published branch does not."""

    repository: str
    branch: str
    dirty_files: int
    unpushed_commits: int

    @property
    def publishes_what_it_checks(self) -> bool:
        """Whether a file control's verdict also describes the published branch."""
        return self.dirty_files == 0 and self.unpushed_commits == 0

    def describe(self) -> str:
        if self.publishes_what_it_checks:
            return f"{self.repository}: matches {self.branch}"
        parts: list[str] = []
        if self.dirty_files:
            parts.append(f"{self.dirty_files} uncommitted file(s)")
        if self.unpushed_commits:
            parts.append(f"{self.unpushed_commits} unpushed commit(s)")
        return f"{self.repository}: {' and '.join(parts)} on {self.branch}"


def inspect(repository: str, path: Path, *, runner: GitRunner | None = None) -> TreeState | None:
    """Read one checkout's condition. `None` when it is not a git repository.

    Never fatal and never fetches: a report that could not look must say so
    rather than imply the checkout was clean.
    """
    run = runner or _git
    if not path.is_dir():
        return None
    code, _ = run(path, ["rev-parse", "--git-dir"])
    if code != 0:
        return None

    _, branch_out = run(path, ["rev-parse", "--abbrev-ref", "HEAD"])
    branch = branch_out.strip() or "HEAD"

    _, status_out = run(path, ["status", "--porcelain"])
    dirty = len([line for line in status_out.splitlines() if line.strip()])

    # Against the published branch, not the tracking branch: a local branch whose
    # upstream was deleted is exactly the case that hid unmerged work here.
    ahead = 0
    for upstream in ("origin/main", "origin/master"):
        code, count_out = run(path, ["rev-list", "--count", f"{upstream}..HEAD"])
        if code == 0 and count_out.strip().isdigit():
            ahead = int(count_out.strip())
            break

    return TreeState(repository, branch, dirty, ahead)


def unpublished(states: Sequence[TreeState]) -> tuple[TreeState, ...]:
    return tuple(state for state in states if not state.publishes_what_it_checks)
