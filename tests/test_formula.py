"""A hermetic formula installs the same bytes twice, or it is not hermetic."""

from __future__ import annotations

from pathlib import Path

import pytest

from maintenance.formula import (
    EXCLUDED,
    SYSTEM_DEPENDENCIES,
    FormulaSpec,
    LockError,
    Resource,
    check_hermetic,
    generate,
    read_lock,
    render,
    resource_count,
)
from maintenance.paths import REPO_ROOT

# Composed rather than interpolated: the surrounding TOML is full of braces, so
# neither an f-string nor `.format()` can template it without escaping every one.
_CLICK_SDIST = (
    'sdist = { url = "https://files.pythonhosted.org/packages/x/click-8.4.2.tar.gz",'
    ' hash = "sha256:' + "a" * 64 + '" }'
)
_PYINSTALLER_SDIST = (
    'sdist = { url = "https://files.pythonhosted.org/packages/y/'
    'pyinstaller-6.15.0.tar.gz", hash = "sha256:' + "b" * 64 + '" }'
)

LOCK = (
    """
version = 1

[[package]]
name = "demo"
version = "1.0.0"
source = { editable = "." }
dependencies = [
    { name = "click" },
]

[[package]]
name = "click"
version = "8.4.2"
source = { registry = "https://pypi.org/simple" }
"""
    + _CLICK_SDIST
    + """

[[package]]
name = "pyinstaller"
version = "6.15.0"
source = { registry = "https://pypi.org/simple" }
"""
    + _PYINSTALLER_SDIST
    + "\n"
)


def _lock(tmp_path: Path, content: str = LOCK) -> Path:
    path = tmp_path / "uv.lock"
    path.write_text(content, encoding="utf-8")
    return path


def _spec(**overrides: str) -> FormulaSpec:
    defaults = {
        "name": "demo",
        "class_name": "Demo",
        "description": "A demo",
        "homepage": "https://example.invalid/demo",
        "version": "1.0.0",
    }
    defaults.update(overrides)
    return FormulaSpec(**defaults)


class TestLockReading:
    def test_only_the_runtime_graph_is_pinned(self, tmp_path: Path) -> None:
        resources = read_lock(_lock(tmp_path), root="demo")

        # PyInstaller is in the lock but nothing at runtime depends on it.
        assert [resource.name for resource in resources] == ["click"]

    def test_the_whole_lock_can_be_read_when_asked(self, tmp_path: Path) -> None:
        resources = read_lock(_lock(tmp_path), root="demo", runtime_only=False)

        assert {resource.name for resource in resources} == {"click", "pyinstaller"}

    def test_resources_are_sorted_for_a_stable_diff(self, tmp_path: Path) -> None:
        resources = read_lock(_lock(tmp_path), root="demo", runtime_only=False)

        assert [resource.name for resource in resources] == sorted(
            resource.name for resource in resources
        )

    def test_a_dependency_without_an_sdist_digest_is_refused(self, tmp_path: Path) -> None:
        broken = LOCK.replace(f'hash = "sha256:{"a" * 64}"', 'hash = "md5:whatever"')

        with pytest.raises(LockError, match="cannot be pinned"):
            read_lock(_lock(tmp_path, broken), root="demo")

    def test_an_unknown_root_is_refused_rather_than_guessed(self, tmp_path: Path) -> None:
        with pytest.raises(LockError, match="no package named"):
            read_lock(_lock(tmp_path), root="not-here")

    def test_the_python_toolchain_is_never_vendored(self) -> None:
        assert {"pip", "setuptools", "wheel"} <= EXCLUDED

    def test_the_root_package_is_never_a_resource_of_itself(self, tmp_path: Path) -> None:
        resources = read_lock(_lock(tmp_path), root="demo", runtime_only=False)

        assert "demo" not in {resource.name for resource in resources}


class TestRendering:
    def test_a_generated_formula_is_hermetic(self, tmp_path: Path) -> None:
        source = generate(_spec(), _lock(tmp_path), root="demo")

        assert check_hermetic(source, name="demo") == []
        assert resource_count(source) == 1

    def test_a_pending_release_is_not_given_a_fake_digest(self, tmp_path: Path) -> None:
        source = generate(_spec(), _lock(tmp_path), root="demo")

        assert 'sha256 "PENDING"' in source
        assert "not installable until then" in source

    def test_a_published_release_carries_its_real_digest(self, tmp_path: Path) -> None:
        spec = _spec(url="https://example.invalid/demo-1.0.0.tar.gz", sha256="c" * 64)

        source = generate(spec, _lock(tmp_path), root="demo")

        assert f'sha256 "{"c" * 64}"' in source
        assert "PENDING" not in source
        assert spec.complete is True

    def test_system_libraries_are_declared_for_resources_that_need_them(self) -> None:
        resources = [
            Resource("lxml", "5.0", "https://example.invalid/lxml.tar.gz", "d" * 64),
        ]

        source = render(_spec(), resources)

        assert 'uses_from_macos "libxml2"' in source
        assert 'uses_from_macos "libxslt"' in source

    def test_system_libraries_are_not_invented_for_pure_python(self, tmp_path: Path) -> None:
        source = generate(_spec(), _lock(tmp_path), root="demo")

        assert "uses_from_macos" not in source

    def test_the_declared_mapping_covers_the_native_dependencies_in_use(self) -> None:
        assert "lxml" in SYSTEM_DEPENDENCIES
        assert SYSTEM_DEPENDENCIES["lxml"] == ("libxml2", "libxslt")

    def test_generation_is_deterministic(self, tmp_path: Path) -> None:
        lock = _lock(tmp_path)

        assert generate(_spec(), lock, root="demo") == generate(_spec(), lock, root="demo")


class TestTestBlock:
    def test_the_test_block_does_more_than_check_the_version(self, tmp_path: Path) -> None:
        source = generate(_spec(), _lock(tmp_path), root="demo")

        assertions = [line for line in source.split("test do")[1].splitlines() if "assert" in line]
        assert assertions
        assert not any("--version" in line or "--help" in line for line in assertions)
        assert "assert_equal" in source
        assert "manifest" in source

    def test_the_test_block_uses_the_command_name(self, tmp_path: Path) -> None:
        source = generate(_spec(command="demo-cli"), _lock(tmp_path), root="demo")

        assert 'bin/"demo-cli"' in source


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

    def test_the_shipped_generated_formulas_are_hermetic(self) -> None:
        directory = REPO_ROOT / "generated"
        if not directory.is_dir():
            pytest.skip("formulas have not been generated in this checkout")
        for path in sorted(directory.glob("*.rb")):
            source = path.read_text(encoding="utf-8")
            assert check_hermetic(source, name=path.stem) == [], path.name
            assert resource_count(source) > 0


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
