"""One condition, one exit code — across all three published CLIs.

Each tool has its own suite, and each suite is right about its own tool. The
thing no per-repo suite can see is whether the *same* mistake produces the *same*
answer in all three, which is the only property a script driving them can rely
on. `unpacksort ./missing ./out` exited 2 while `paperless-export tax-view
--export-dir ./missing` exited 4, and both READMEs documented 2.

These run the real executables, not imported functions: an exit code is a
property of a built artifact, not of a function someone imported.

By default they run each repository's own virtualenv — the code in this
checkout, which is what a pull request should be judged on. Set
`FILEWORKS_CLI_FROM_PATH=1` to run whatever is installed on `PATH` instead, which
is how the same assertions are re-run against the *published* packages from a
clean environment. The two answers can differ, and when they do the difference
is the point: a fix that has landed but not shipped is still a fix nobody has.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent

#: Every published CLI, and the invocation that names an input path which is not
#: there. Each is the tool's *own* documented shape, not a synthetic one.
MISSING_INPUT: dict[str, list[str]] = {
    "unpacksort": ["{missing}", "{out}"],
    "paperless-export": ["tax-view", "--export-dir", "{missing}"],
    "immich-export": [
        "--mode",
        "sidecar",
        "--server",
        "https://immich.invalid",
        "--api-key",
        "unused",
        "--library-root",
        "{missing}",
        "--out",
        "{out}",
    ],
}

TOOLS = tuple(MISSING_INPUT)

#: "The invocation itself is wrong … Nothing was attempted." — `ExitCode.USAGE`,
#: spelled identically in all three repositories.
USAGE = 2


def executable(tool: str) -> str:
    """This checkout's build, unless asked for the published one."""
    if os.environ.get("FILEWORKS_CLI_FROM_PATH") == "1":
        installed = shutil.which(tool)
        if installed is None:
            pytest.skip(f"{tool} is not installed on PATH")
        return installed
    local = ROOT / tool / ".venv" / "bin" / tool
    if not local.is_file():
        pytest.skip(f"{tool} is not built in {local.parent}; run `uv sync` in {tool}/")
    return str(local)


def invoke(tool: str, arguments: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [executable(tool), *arguments],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        cwd=ROOT,
    )


@pytest.mark.parametrize("tool", TOOLS)
def test_a_missing_input_path_is_a_usage_error_everywhere(tool: str, tmp_path: Path) -> None:
    """The condition all three READMEs document as `2`, asserted against all three.

    Failed for `paperless-export` before the `OutputError` split: `ConfigError`
    said "invalid flags, missing paths" and `OutputError` said "unwritable **or
    missing**", so a missing export directory matched both and got the fatal one.
    """
    arguments = [
        item.format(missing=str(tmp_path / "absent"), out=str(tmp_path / "out"))
        for item in MISSING_INPUT[tool]
    ]

    result = invoke(tool, arguments)

    assert result.returncode == USAGE, (
        f"{tool} exited {result.returncode} for a missing input path; "
        f"its README documents {USAGE}.\n{result.stdout}\n{result.stderr}"
    )


@pytest.mark.parametrize("tool", TOOLS)
def test_help_is_reachable_by_both_spellings(tool: str) -> None:
    """`-h` is not an abbreviation anyone should have to look up.

    One of the three rejected it. Identical output rather than merely a zero
    exit, because a `-h` that prints something *else* is its own surprise.
    """
    short = invoke(tool, ["-h"])
    long = invoke(tool, ["--help"])

    assert short.returncode == 0, f"{tool} rejected -h:\n{short.stderr}"
    assert long.returncode == 0, f"{tool} rejected --help:\n{long.stderr}"
    assert short.stdout == long.stdout
