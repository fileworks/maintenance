"""The hermetic-formula check. One property, asserted about someone else's output.

A hermetic formula installs the same bytes twice: every dependency is a pinned
`resource` with its own URL and sha256, and nothing is resolved at install time.

This module used to *also* render such formulas from a lockfile, which made two
generators for one artifact (`A-09`) — this one and `homebrew-tap`'s
`bump_formula.py`, which is the one whose output Homebrew actually serves. Two
producers of the same file drift, and only one of them was ever installed, so
the reference renderer is gone and what remains is the part that was never
duplicated: the check that says whether a formula is hermetic.

The formulas it used to emit are kept as static fixtures under
`tests/fixtures/formulas/`, so the regression they represent outlives the
generator that happened to produce them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

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


#: The formula's own `url`, as distinct from a `resource` block's. Anchored to
#: two-space indentation because that is the only depth `render` writes it at:
#: a resource's URL is indented four, and matching it would report a
#: dependency's version as the formula's.
_FORMULA_URL = re.compile(r'^  url "([^"]+)"', re.MULTILINE)

#: `immich_export-0.2.1.tar.gz` and `unpacksort-1.1.0.tar.gz` — PyPI normalises
#: the distribution name but leaves the version alone.
_SDIST_VERSION = re.compile(r"-(\d[^-/]*)\.(?:tar\.gz|zip)$")


def sdist_version(source: str) -> str | None:
    """The version a rendered formula installs, read back out of its sdist URL.

    The formula has no `version` stanza — Homebrew infers it from the URL, and
    so does this. Returns `None` for the deliberately incomplete `PENDING` form
    and for anything else it cannot read, because a formula whose version cannot
    be established is not a formula reporting version zero.
    """
    match = _FORMULA_URL.search(source)
    if match is None:
        return None
    version = _SDIST_VERSION.search(match.group(1))
    return version.group(1) if version else None
