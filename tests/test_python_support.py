"""The CI matrix, `requires-python` and the classifiers are one claim, checked.

They live in two files and were never compared, so they drifted in both
directions at once: `unpacksort` ran 3.14 in CI while its classifiers named 3.12
only, and the two exporters classified 3.13 with no Python matrix in CI at all.
One tool tested more than it promised; two promised more than they tested.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from maintenance.policy import (
    KNOWN_PYTHONS,
    PYTHON_SUPPORT_CONTROL,
    PythonSupport,
    Repository,
    classifier_pythons,
    evaluate_python_support,
    matrix_pythons,
    read_python_support,
)

WORKFLOW = """\
jobs:
  quality:
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, windows-latest]
        python: ["3.12", "3.14"]
    steps:
      - uses: actions/setup-python@v7
        with:
          python-version: ${{ matrix.python }}

  audit:
    steps:
      - uses: actions/setup-python@v7
        with:
          python-version: "3.13"
"""

BLOCK_LIST = """\
jobs:
  test:
    strategy:
      matrix:
        python-version:
          - "3.12"
          - "3.13"
"""


def support(**overrides: object) -> PythonSupport:
    defaults: dict[str, object] = {
        "repository": "demo",
        "tested": ("3.12", "3.13", "3.14"),
        "classified": ("3.12", "3.13", "3.14"),
        "requires_python": ">=3.12",
    }
    return PythonSupport(**{**defaults, **overrides})  # type: ignore[arg-type]


class TestReadingTheMatrix:
    def test_it_reads_an_inline_matrix(self) -> None:
        assert matrix_pythons(WORKFLOW) == ("3.12", "3.14")

    def test_a_pinned_setup_step_is_not_a_supported_version(self) -> None:
        """The audit job pins 3.13 for itself. That is one job, not a promise."""
        assert "3.13" not in matrix_pythons(WORKFLOW)

    def test_it_reads_a_block_list_matrix(self) -> None:
        assert matrix_pythons(BLOCK_LIST) == ("3.12", "3.13")

    def test_a_workflow_with_no_matrix_tests_nothing(self) -> None:
        assert matrix_pythons("jobs:\n  quality:\n    runs-on: ubuntu-latest\n") == ()


class TestReadingTheClassifiers:
    def test_it_reads_the_versioned_classifiers(self) -> None:
        assert classifier_pythons(
            [
                "Programming Language :: Python :: 3.12",
                "Programming Language :: Python :: 3.13",
                "Topic :: System :: Archiving",
            ]
        ) == ("3.12", "3.13")

    def test_three_colon_only_is_a_different_claim_and_is_ignored(self) -> None:
        """`3 :: Only` says "not Python 2". It does not say "runs on 3.13"."""
        assert classifier_pythons(["Programming Language :: Python :: 3 :: Only"]) == ()


class TestAgreement:
    def test_agreeing_is_agreeing(self) -> None:
        assert support().agrees is True

    def test_tested_but_not_claimed_is_reported(self) -> None:
        """`unpacksort`'s condition: CI ran 3.14, the package disclaimed it."""
        result = support(tested=("3.12", "3.14"), classified=("3.12", "3.13"))

        assert result.tested_not_claimed == ("3.14",)
        assert "3.14" in result.describe()
        assert result.agrees is False

    def test_claimed_but_not_tested_is_reported(self) -> None:
        """The exporters' condition: 3.13 classified, no Python matrix at all."""
        result = support(tested=(), classified=("3.12", "3.13"))

        assert result.claimed_not_tested == ("3.12", "3.13")
        assert result.agrees is False

    def test_requires_python_admitting_an_undeclared_version_is_reported(self) -> None:
        result = support(tested=("3.12",), classified=("3.12",), requires_python=">=3.12")

        assert result.admitted_not_declared == ("3.13", "3.14")
        assert "requires-python" in result.describe()

    def test_the_admitted_set_is_bounded_by_released_versions(self) -> None:
        """Without a ceiling this would report every Python that has not shipped."""
        assert support().admitted == KNOWN_PYTHONS

    def test_a_higher_floor_admits_less(self) -> None:
        result = support(requires_python=">=3.14", tested=("3.14",), classified=("3.14",))

        assert result.admitted == ("3.14",)
        assert result.agrees is True

    def test_an_unparseable_bound_admits_nothing_rather_than_guessing(self) -> None:
        result = support(requires_python="", tested=("3.12",), classified=("3.12",))

        assert result.admitted == ()


class TestAgainstTheRealRepositories:
    @pytest.mark.parametrize("name", ["immich-export", "paperless-export", "unpacksort"])
    def test_every_published_package_agrees_with_itself(self, name: str) -> None:
        root = Path(__file__).resolve().parent.parent.parent
        repo = Repository(name, "python_cli", root / name)
        if not (repo.path / "pyproject.toml").is_file():
            pytest.skip(f"{name} is not checked out beside maintenance/")

        result = read_python_support(repo)

        assert result is not None
        assert result.agrees, f"{name}: {result.describe()}"

    def test_the_control_reports_per_repository(self, tmp_path: Path) -> None:
        (tmp_path / "demo").mkdir()
        (tmp_path / "demo" / "pyproject.toml").write_text(
            '[project]\nname = "demo"\nrequires-python = ">=3.14"\n'
            'classifiers = ["Programming Language :: Python :: 3.14"]\n',
            encoding="utf-8",
        )

        findings = evaluate_python_support([Repository("demo", "python_cli", tmp_path / "demo")])

        assert [item.control_id for item in findings] == [PYTHON_SUPPORT_CONTROL]
        assert findings[0].outcome == "mismatched"
        assert "3.14" in findings[0].detail

    def test_a_missing_package_is_unverifiable_not_compliant(self, tmp_path: Path) -> None:
        findings = evaluate_python_support([Repository("gone", "python_cli", tmp_path / "gone")])

        assert findings[0].outcome == "unverifiable"

    def test_a_class_the_control_does_not_apply_to_is_skipped(self, tmp_path: Path) -> None:
        assert evaluate_python_support([Repository("tap", "homebrew_tap", tmp_path)]) == ()
