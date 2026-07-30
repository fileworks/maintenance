"""Generating a hermetic Homebrew formula from a lockfile.

The two exporter formulas take the personal-tap shortcut: they run `pip install
name==version` at build time, which means the dependency set is whatever PyPI
serves that day. That is fine for a personal tap and wrong for anything a
stranger installs — `brew audit --strict` objects to it, and an install can
differ between two machines an hour apart.

This module produces the strict form instead: a `Language::Python::Virtualenv`
formula whose every dependency is a pinned `resource` block with its own URL and
sha256, taken from the project's own lockfile. Nothing is resolved at install
time, so two installs of the same formula install the same bytes.

It also writes a test block that does something. A test that only runs
`--version` proves the binary exists; this one creates a fixture, runs the tool
on it, and checks the extracted bytes and the manifest that records where they
came from.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

#: Packages the formula must not vendor: they come from Homebrew itself, and
#: vendoring a second copy is how two Pythons end up in one virtualenv. The root
#: package is excluded separately, by identity — it is the formula, not a
#: resource of it.
EXCLUDED = {"pip", "setuptools", "wheel"}

#: System libraries a pinned resource needs in order to build. `brew audit`
#: enforces this, and rightly: a resource that links against libxml2 without
#: declaring it builds on the maintainer's machine and fails on a clean one.
SYSTEM_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "lxml": ("libxml2", "libxslt"),
    "pillow": ("zlib",),
    "cffi": ("libffi",),
    "pikepdf": ("libxml2",),
}


@dataclass(frozen=True)
class Resource:
    """One pinned dependency: a name, a version, a URL, and a digest."""

    name: str
    version: str
    url: str
    sha256: str

    def render(self) -> str:
        return (
            f'  resource "{self.name}" do\n'
            f'    url "{self.url}"\n'
            f'    sha256 "{self.sha256}"\n'
            f"  end\n"
        )


class LockError(RuntimeError):
    """The lockfile could not be turned into pinned resources."""


def read_lock(
    lock_path: Path,
    *,
    root: str | None = None,
    runtime_only: bool = True,
) -> list[Resource]:
    """Read `uv.lock` into pinned resources, sorted for a stable diff.

    When *runtime_only* is set the runtime dependency graph is walked from the
    root package, because a lockfile contains the development environment too —
    and a formula that vendored PyInstaller would be installing a build tool onto
    a user's machine.

    Only sdists are used. A wheel-only dependency cannot be pinned this way and
    is reported rather than silently dropped, because a formula missing one
    resource fails at install time on somebody else's machine.
    """
    try:
        data = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise LockError(f"{lock_path} could not be read: {exc}") from exc

    packages: dict[str, dict[str, object]] = {
        str(item.get("name", "")): item
        for item in data.get("package", [])
        if isinstance(item, dict)
    }
    root_name = root or _guess_root(packages, lock_path)
    wanted = _runtime_closure(packages, root_name) if runtime_only else set(packages)
    excluded = EXCLUDED | {root_name}

    resources: list[Resource] = []
    missing: list[str] = []
    for name, package in packages.items():
        if name in excluded or name not in wanted:
            continue
        sdist = package.get("sdist")
        if not isinstance(sdist, dict) or not sdist.get("url"):
            missing.append(name)
            continue
        digest = str(sdist.get("hash", ""))
        if not digest.startswith("sha256:"):
            missing.append(name)
            continue
        resources.append(
            Resource(
                name=name,
                version=str(package.get("version", "")),
                url=str(sdist["url"]),
                sha256=digest.removeprefix("sha256:"),
            )
        )

    if missing:
        raise LockError(
            "these packages have no sdist with a sha256 in the lock and cannot be pinned: "
            + ", ".join(sorted(missing))
        )
    return sorted(resources, key=lambda item: item.name)


def _guess_root(packages: dict[str, dict[str, object]], lock_path: Path) -> str:
    """The project's own package — the one whose source is the directory itself."""
    for name, package in packages.items():
        source = package.get("source")
        if (isinstance(source, dict) and "editable" in source) or "virtual" in str(source):
            return name
    fallback = lock_path.parent.name
    if fallback in packages:
        return fallback
    raise LockError("could not identify the root package in the lockfile")


def _dependency_names(package: dict[str, object]) -> list[str]:
    """The `dependencies` table of one lock entry, as plain names."""
    entries = package.get("dependencies")
    if not isinstance(entries, list):
        return []
    return [str(entry["name"]) for entry in entries if isinstance(entry, dict) and "name" in entry]


def _runtime_closure(packages: dict[str, dict[str, object]], root: str) -> set[str]:
    """Every package reachable from the root's *runtime* dependencies.

    Development groups are deliberately not followed: they are how a build tool
    ends up vendored into somebody's install.
    """
    if root not in packages:
        raise LockError(f"the lockfile has no package named {root!r}")

    seen: set[str] = set()
    queue = _dependency_names(packages[root])
    while queue:
        name = queue.pop()
        if name in seen or name not in packages:
            continue
        seen.add(name)
        queue.extend(_dependency_names(packages[name]))
    return seen


DEFAULT_TEST_BLOCK = """  test do
    # A test that only runs --version proves the binary exists. This one proves
    # the tool does its job: it builds a small archive, unpacks it, and checks
    # both the extracted bytes and the manifest that records where they came from.
    require "fileutils"

    (testpath/"source").mkpath
    (testpath/"source/hello.txt").write("hello from the formula test\\n")
    system "tar", "-czf", testpath/"fixture.tar.gz", "-C", testpath/"source", "hello.txt"

    system bin/"{command}", testpath/"fixture.tar.gz", testpath/"out"

    extracted = Dir.glob("#{{testpath}}/out/**/hello.txt").first
    refute_nil extracted, "unpacksort did not extract the fixture"
    assert_equal "hello from the formula test\\n", File.read(extracted)

    manifest = Dir.glob("#{{testpath}}/out/**/*manifest*").first
    refute_nil manifest, "unpacksort did not write a manifest"
    assert_match "hello.txt", File.read(manifest)
  end
"""


@dataclass(frozen=True)
class FormulaSpec:
    """Everything a formula needs that is not in the lockfile."""

    name: str
    class_name: str
    description: str
    homepage: str
    version: str
    #: Filled in at publish time from the real sdist. Left empty deliberately
    #: until it exists: a placeholder digest that looks real is worse than none.
    url: str = ""
    sha256: str = ""
    license_name: str = "MIT"
    python: str = "python@3.12"
    command: str | None = None

    @property
    def complete(self) -> bool:
        return bool(self.url and self.sha256)


def render(spec: FormulaSpec, resources: list[Resource]) -> str:
    """Render the strict formula. Refuses to invent a URL or a digest."""
    command = spec.command or spec.name
    header = [
        "# Generated by maintenance/formula.py from the project's uv.lock.",
        "# Every dependency is pinned; nothing is resolved at install time.",
        "# Regenerate rather than editing by hand.",
        f"class {spec.class_name} < Formula",
        "  include Language::Python::Virtualenv",
        "",
        f'  desc "{spec.description}"',
        f'  homepage "{spec.homepage}"',
    ]
    if spec.complete:
        header += [f'  url "{spec.url}"', f'  sha256 "{spec.sha256}"']
    else:
        header += [
            "  # url and sha256 are written by the release pipeline from the published",
            "  # sdist. The formula is intentionally not installable until then.",
            '  url "PENDING"',
            '  sha256 "PENDING"',
        ]
    header += [
        f'  license "{spec.license_name}"',
        "",
        f'  depends_on "{spec.python}"',
    ]

    # System libraries the pinned resources need. Sorted and de-duplicated so
    # the generated file diffs cleanly.
    system_libraries = sorted(
        {
            library
            for resource in resources
            for library in SYSTEM_DEPENDENCIES.get(resource.name, ())
        }
    )
    header += [f'  uses_from_macos "{library}"' for library in system_libraries]
    header.append("")

    body = [resource.render() for resource in resources]

    install = [
        "",
        "  def install",
        f'    virtualenv_install_with_resources(using: "{spec.python}")',
        "  end",
        "",
    ]

    return (
        "\n".join(header)
        + "\n".join(body)
        + "\n".join(install)
        + DEFAULT_TEST_BLOCK.format(command=command)
        + "end\n"
    )


def generate(
    spec: FormulaSpec,
    lock_path: Path,
    *,
    root: str | None = None,
    runtime_only: bool = True,
) -> str:
    return render(spec, read_lock(lock_path, root=root, runtime_only=runtime_only))


# --------------------------------------------------------------------------- #
# Checking an existing formula                                                 #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class HermeticIssue:
    formula: str
    detail: str


#: Install-time resolution: the thing a hermetic formula must not do.
#:
#: The pattern allows for Ruby's argument quoting — a formula writes
#: `"-m", "pip", "install", "name==#{version}"`, so `pip` and `install` are not
#: adjacent words. Matching only adjacent words missed every real case.
_RESOLVES_AT_INSTALL = (
    re.compile(r"[\"']pip[\"']\s*,\s*[\"']install[\"']"),
    re.compile(r"pip\s+install\b"),
)


def check_hermetic(source: str, *, name: str) -> list[HermeticIssue]:
    """Whether a formula installs a fixed set of bytes, or whatever PyPI serves."""
    issues: list[HermeticIssue] = []
    if "Language::Python::Virtualenv" not in source:
        issues.append(HermeticIssue(name, "does not use Language::Python::Virtualenv"))
    if not re.search(r"^\s*resource\s+\"", source, re.MULTILINE):
        issues.append(
            HermeticIssue(name, "declares no pinned resources, so its dependency set is not fixed")
        )
    for pattern in _RESOLVES_AT_INSTALL:
        if pattern.search(source):
            issues.append(
                HermeticIssue(
                    name,
                    "resolves dependencies at install time; two installs can differ",
                )
            )
            break
    if not _installs_only_declared_resources(source):
        issues.append(HermeticIssue(name, "does not install from its declared resources"))
    return issues


def _installs_only_declared_resources(source: str) -> bool:
    """Whether the install step can only use bytes the formula already declared.

    Two idioms establish that, and requiring the first by name reported a false
    positive against the second.

    `virtualenv_install_with_resources` is the Homebrew shorthand. The longer form
    stages every declared resource into a local wheelhouse and installs from it
    with `PIP_NO_INDEX` set, which is if anything stricter: it forbids index
    access outright and installs prebuilt wheels rather than building sdists.

    Checked as a property rather than a spelling, because the guarantee is "a
    fixed set of bytes", not "this method name".
    """
    if "virtualenv_install_with_resources" in source:
        return True
    stages_every_resource = re.search(r"resources\s*\.each\b", source) is not None
    forbids_the_index = re.search(r"PIP_NO_INDEX[\"']?\]?\s*=\s*[\"']1[\"']", source) is not None
    return stages_every_resource and forbids_the_index


def resource_count(source: str) -> int:
    return len(re.findall(r"^\s*resource\s+\"", source, re.MULTILINE))
