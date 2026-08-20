"""A-08 — the audit tool cannot mutate a repository, structurally.

`maintenance.cli` reports drift. `maintenance.reconcile_apply` writes to remote
settings. Those were separated by a convention — the CLI simply happened not to
call `apply` — and the README went further and claimed no writer existed at all.

A convention is not a boundary. This asserts the stronger property: the module
that writes is not in the import graph the CLI loads, so a future caller has to
add an import to reach it, and that import is the decision being made.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

_PROBE = """
import sys
import maintenance.cli  # noqa: F401
reached = sorted(name for name in sys.modules if "reconcile_apply" in name)
print(",".join(reached))
"""


def _modules_reachable_from_cli() -> list[str]:
    """Import the CLI in a clean interpreter and see what came with it.

    A subprocess, not an `ast` walk of the imports: a transitive import three
    modules deep is exactly the one a reader would miss, and only the loader
    knows the real answer.
    """
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return [name for name in result.stdout.strip().split(",") if name]


class TestTheCliCannotWrite:
    def test_importing_the_cli_does_not_load_the_apply_module(self) -> None:
        assert _modules_reachable_from_cli() == []

    def test_the_probe_would_notice_if_it_did(self) -> None:
        """The control. A probe that always prints nothing proves nothing."""
        probe = _PROBE.replace(
            "import maintenance.cli  # noqa: F401",
            "import maintenance.reconcile_apply  # noqa: F401",
        )
        result = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            timeout=120,
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert "maintenance.reconcile_apply" in result.stdout


class TestTheWriterIsWhereItSaysItIs:
    def test_every_mutating_entry_point_lives_in_the_apply_module(self) -> None:
        from maintenance import reconcile, reconcile_apply

        for name in ("apply", "rollout", "stage_changes"):
            assert hasattr(reconcile_apply, name), name
            assert not hasattr(reconcile, name), f"{name} is still reachable from the read side"

    def test_the_read_side_still_offers_what_the_cli_needs(self) -> None:
        from maintenance import reconcile

        for name in ("observe", "gh_client", "pull_request_checks", "plan"):
            assert hasattr(reconcile, name), name
