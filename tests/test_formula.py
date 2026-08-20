"""A hermetic formula installs the same bytes twice, or it is not hermetic."""

from __future__ import annotations

from pathlib import Path

import pytest

from maintenance.formula import check_hermetic, resource_count
from maintenance.paths import REPO_ROOT


class TestHermeticChecks:
    def test_a_pip_install_formula_is_reported(self) -> None:
        source = """
class Demo < Formula
  def install
    system libexec/"bin/python", "-m", "pip", "install", "--no-cache-dir", "demo==#{version}"
  end
end
"""
        issues = check_hermetic(source, name="demo")

        assert any("install time" in issue.detail for issue in issues)
        assert any("no pinned resources" in issue.detail for issue in issues)

    def test_the_pinned_formulas_are_hermetic(self) -> None:
        """The regression the deleted generator existed to protect, kept as
        static fixtures. It used to `skip` when `generated/` was absent, and a
        skip is never a pass — these are committed, so it always runs."""
        directory = Path(__file__).parent / "fixtures" / "formulas"
        formulas = sorted(directory.glob("*.rb"))

        assert formulas, "the pinned formula fixtures are missing"
        for path in formulas:
            source = path.read_text(encoding="utf-8")
            assert check_hermetic(source, name=path.stem) == [], path.name
            assert resource_count(source) > 0

    def test_the_live_tap_formulas_are_hermetic_too(self) -> None:
        """The ones Homebrew actually serves, checked where they live. This is
        the reason to keep a checker after deleting the second generator."""
        tap = REPO_ROOT.parent / "homebrew-tap" / "Formula"
        if not tap.is_dir():
            pytest.skip(f"the tap is not checked out beside this repo: {tap}")
        for path in sorted(tap.glob("*.rb")):
            source = path.read_text(encoding="utf-8")
            assert check_hermetic(source, name=path.stem) == [], path.name


class TestHermeticIdioms:
    """Both hermetic idioms must pass; neither spelling is the guarantee."""

    def test_the_homebrew_shorthand_passes(self) -> None:
        source = (
            "class Demo < Formula\n"
            "  include Language::Python::Virtualenv\n"
            '  resource "click" do\n  end\n'
            "  def install\n    virtualenv_install_with_resources\n  end\nend\n"
        )

        assert check_hermetic(source, name="demo") == []

    def test_a_local_wheelhouse_with_the_index_forbidden_also_passes(self) -> None:
        # The generated formulas use this form. Requiring the shorthand by name
        # reported "does not install from its declared resources" against a
        # formula that CI had already installed with no index access at all.
        source = (
            "class Demo < Formula\n"
            "  include Language::Python::Virtualenv\n"
            '  resource "click" do\n  end\n'
            "  def install\n"
            '    ENV["PIP_NO_INDEX"] = "1"\n'
            "    resources.each do |resource|\n"
            "      wheelhouse.install resource.cached_download\n"
            "    end\n"
            '    venv = virtualenv_create(libexec, "python3.12")\n'
            '    venv.pip_install Dir[wheelhouse/"*.whl"], build_isolation: false\n'
            "  end\nend\n"
        )

        assert check_hermetic(source, name="demo") == []

    def test_staging_resources_without_forbidding_the_index_still_fails(self) -> None:
        # Half the property is not the property: pip could still reach PyPI.
        source = (
            "class Demo < Formula\n"
            "  include Language::Python::Virtualenv\n"
            '  resource "click" do\n  end\n'
            "  def install\n"
            "    resources.each do |resource|\n"
            "      wheelhouse.install resource.cached_download\n"
            "    end\n"
            "  end\nend\n"
        )

        details = [issue.detail for issue in check_hermetic(source, name="demo")]
        assert "does not install from its declared resources" in details
