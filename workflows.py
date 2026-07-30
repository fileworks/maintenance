"""Which declared gate each workflow actually runs, and what is unmapped.

The gate registry names the checks branch protection should require. The
workflows name jobs and steps. Those two have to agree, and today they do not:
every repository grew its own names before there was a registry.

Renaming a job is not free — the check name is what protection requires, so a
rename unprotects `main` until the protection rule is updated in the same
breath. This module therefore *maps* rather than renames: it reports which
declared gates each repository already runs, under what name, and which are
missing. The rename is queued with the protection change that needs
authentication anyway, so the two land together.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from maintenance.gates import GateId, gates_for, not_applicable
from maintenance.policy import RepoClass, Repository

#: What a step or job has to look like to count as running a given gate. These
#: are intentionally loose: the question is "does this repository check its
#: formatting", not "does it phrase it the way we would".
GATE_PATTERNS: dict[GateId, tuple[str, ...]] = {
    "format": (r"format\s*--check", r"prettier\s*--check", r"fmt\s*--check"),
    "lint": (r"ruff check", r"eslint", r"\blint\b", r"clippy"),
    "typecheck": (r"\bmypy\b", r"\btsc\b", r"type[- ]?check"),
    "test": (r"\bpytest\b", r"vitest", r"npm test", r"cargo test"),
    "build": (
        r"\bnpm run build\b",
        r"\buv build\b",
        r"cargo build",
        r"python -m build",
    ),
    "package": (r"\bwheel\b", r"pipx install", r"\bmsi\b", r"\bdmg\b", r"tauri build"),
    "dependency-audit": (
        r"pip-audit",
        r"npm audit",
        r"cargo audit",
        r"dependency[- ]audit",
    ),
    "docs-links": (r"link[- ]check", r"lychee", r"markdown-link"),
    "release-integrity": (
        r"release[- ]integrity",
        r"verify.*(release|artifact)",
        r"provenance",
    ),
    "formula-audit": (r"brew audit", r"brew style", r"brew test"),
    "installer-preflight": (
        r"installer",
        r"artifact[- ]preflight",
        r"nsis",
        r"\bmsi\b",
    ),
}

_JOB = re.compile(r"^  ([A-Za-z0-9_-]+):\s*$", re.MULTILINE)


@dataclass(frozen=True)
class GateMapping:
    """One declared gate, and where (if anywhere) the repository runs it."""

    gate: GateId
    present: bool
    #: The workflow file and job the gate was found in.
    workflow: str | None = None
    job: str | None = None
    evidence: str | None = None

    @property
    def status(self) -> str:
        return "runs" if self.present else "missing"


@dataclass
class WorkflowReport:
    """What one repository's workflows do, against what its class requires."""

    repository: str
    repo_class: RepoClass
    mappings: list[GateMapping] = field(default_factory=list)
    #: Jobs that exist but map to no declared gate. Not wrong — just unclaimed.
    unmapped_jobs: list[str] = field(default_factory=list)
    workflows_read: list[str] = field(default_factory=list)

    @property
    def missing(self) -> tuple[GateId, ...]:
        return tuple(mapping.gate for mapping in self.mappings if not mapping.present)

    @property
    def aligned(self) -> bool:
        return not self.missing

    def summary(self) -> str:
        if not self.workflows_read:
            return f"{self.repository}: no workflows found"
        if self.aligned:
            return f"{self.repository}: runs every gate its class requires"
        return f"{self.repository}: missing {', '.join(self.missing)}"


def read_workflows(repo: Repository) -> dict[str, str]:
    directory = repo.path / ".github" / "workflows"
    if not directory.is_dir():
        return {}
    contents: dict[str, str] = {}
    for path in sorted(directory.glob("*.yml")) + sorted(directory.glob("*.yaml")):
        try:
            contents[path.name] = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    return contents


def job_names(workflow: str) -> list[str]:
    """Job keys, which is what a check is called when no `name:` overrides it."""
    inside_jobs = workflow.split("\njobs:", 1)
    if len(inside_jobs) < 2:
        return []
    return _JOB.findall(inside_jobs[1])


def map_gates(repo: Repository) -> WorkflowReport:
    """Find each required gate in the repository's workflows, or report it missing."""
    workflows = read_workflows(repo)
    report = WorkflowReport(
        repository=repo.name,
        repo_class=repo.repo_class,
        workflows_read=sorted(workflows),
    )

    claimed_jobs: set[str] = set()
    for gate in gates_for(repo.repo_class):
        patterns = GATE_PATTERNS.get(gate.gate_id, ())
        found: GateMapping | None = None
        for filename, content in workflows.items():
            for pattern in patterns:
                match = re.search(pattern, content, re.IGNORECASE)
                if match is None:
                    continue
                job = _enclosing_job(content, match.start())
                if job:
                    claimed_jobs.add(f"{filename}:{job}")
                found = GateMapping(
                    gate=gate.gate_id,
                    present=True,
                    workflow=filename,
                    job=job,
                    evidence=match.group(0),
                )
                break
            if found:
                break
        report.mappings.append(found or GateMapping(gate=gate.gate_id, present=False))

    for filename, content in workflows.items():
        for job in job_names(content):
            if f"{filename}:{job}" not in claimed_jobs:
                report.unmapped_jobs.append(f"{filename}:{job}")

    return report


def _enclosing_job(workflow: str, offset: int) -> str | None:
    """The job a match sits in — the last job header before it."""
    before = workflow[:offset]
    matches = _JOB.findall(before)
    return matches[-1] if matches else None


def alignment_matrix(reports: list[WorkflowReport]) -> str:
    """The table that says which repository runs which gate."""
    gates = sorted({mapping.gate for report in reports for mapping in report.mappings})
    header = "| Gate | " + " | ".join(f"`{report.repository}`" for report in reports) + " |"
    lines = [header, "|---" * (len(reports) + 1) + "|"]
    for gate in gates:
        cells = []
        for report in reports:
            mapping = next((item for item in report.mappings if item.gate == gate), None)
            if mapping is None:
                cells.append("—")
            else:
                cells.append("✅" if mapping.present else "❌")
        lines.append(f"| {gate} | " + " | ".join(cells) + " |")

    lines.append("")
    lines.append("✅ runs · ❌ required but not found · — not applicable to this class")
    for report in reports:
        skipped = not_applicable(report.repo_class)
        if skipped:
            lines.append("")
            lines.append(
                f"**`{report.repository}` does not run:** "
                + "; ".join(f"`{gate}` ({reason})" for gate, reason in skipped)
            )
    return "\n".join(lines)


@dataclass(frozen=True)
class RenamePlan:
    """The queued rename, held until protection can be updated with it."""

    repository: str
    workflow: str
    current_job: str
    desired_check: GateId

    def describe(self) -> str:
        return (
            f"{self.repository}/{self.workflow}: job `{self.current_job}` "
            f"→ check `{self.desired_check}`"
        )


@dataclass(frozen=True)
class MultiGateJob:
    """A job that runs several gates, so no single rename is correct for it."""

    repository: str
    workflow: str
    job: str
    gates: tuple[GateId, ...]

    def describe(self) -> str:
        return (
            f"{self.repository}/{self.workflow}: job `{self.job}` runs "
            f"{', '.join(self.gates)} — split it, or require the job name as it stands"
        )


def rename_plan(report: WorkflowReport) -> tuple[list[RenamePlan], list[MultiGateJob]]:
    """Renames that are unambiguous, and the jobs where no rename would be.

    A job that runs four gates cannot be renamed to one of them: whichever name
    was chosen, the other three would silently stop being required. Those are
    returned separately so the decision — split the job, or keep requiring its
    current name — is made by a person rather than by this function.
    """
    by_job: dict[tuple[str, str], list[GateId]] = {}
    for mapping in report.mappings:
        if not mapping.present or mapping.job is None or mapping.workflow is None:
            continue
        by_job.setdefault((mapping.workflow, mapping.job), []).append(mapping.gate)

    plans: list[RenamePlan] = []
    multi: list[MultiGateJob] = []
    for (workflow, job), gates in sorted(by_job.items()):
        if len(gates) > 1:
            multi.append(MultiGateJob(report.repository, workflow, job, tuple(sorted(gates))))
            continue
        if job == gates[0]:
            continue
        plans.append(RenamePlan(report.repository, workflow, job, gates[0]))
    return plans, multi


# --------------------------------------------------------------------------- #
# Generating the missing gates                                                 #
# --------------------------------------------------------------------------- #

#: The docs-links job, generated into each repository from this one source.
#:
#: It is inlined rather than a `uses:` reference because there is no shared
#: workflow repository yet — and a config that references one that does not
#: exist does not drift, it simply fails to run. When the shared home is
#: approved, this becomes a two-line `uses:` and the body moves there.
DOCS_LINKS_JOB = """
  docs-links:
    name: docs-links
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      # Generated by maintenance/workflows.py — regenerate, do not hand-edit.
      # Dependency-free on purpose: a link checker that needs a marketplace
      # action is a link checker that breaks when that action moves.
      - name: docs-links
        shell: python
        run: |
          import pathlib, re, sys

          link = re.compile(r"\\[[^\\]]*\\]\\(([^)\\s]+)\\)")
          skip = {
              ".git", ".venv", "node_modules", "dist", "build", "target",
              "site-packages", "_internal", "resources", "vendor",
          }
          problems = []

          for markdown in pathlib.Path(".").rglob("*.md"):
              if any(part in skip for part in markdown.parts):
                  continue
              for target in link.findall(markdown.read_text(encoding="utf-8", errors="replace")):
                  if target.startswith(("http://", "https://", "mailto:", "#")):
                      continue
                  if not (markdown.parent / target.split("#")[0]).exists():
                      problems.append(f"{markdown}: {target} does not exist")

          for problem in problems:
              print(problem)
          sys.exit(1 if problems else 0)
"""

#: Audit tools are CI tooling, not product runtime dependencies. Pin them here so
#: a clean checkout executes the same scanner version in every repository.
PIP_AUDIT_VERSION = "2.9.0"
CARGO_AUDIT_VERSION = "0.22.2"

#: The dependency-audit job for a uv-managed Python project. Optional frontend
#: and Rust locks are detected so the same generated job represents the shipped
#: dependency sets of both the small exporters and MediaSorter.
DEPENDENCY_AUDIT_JOB = """
  dependency-audit:
    name: dependency-audit
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      # astral-sh/setup-uv v9.0.0
      - uses: astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9
      # Generated by maintenance/workflows.py — regenerate, do not hand-edit.
      - name: Export the shipped Python dependency set
        working-directory: ${{ hashFiles('backend/uv.lock') != '' && 'backend' || '.' }}
        run: >-
          uv export --locked --all-extras --no-dev --no-emit-project
          --format requirements-txt
          --output-file dependency-audit-requirements.txt
      - name: Python dependency audit (pip-audit __PIP_AUDIT_VERSION__)
        working-directory: ${{ hashFiles('backend/uv.lock') != '' && 'backend' || '.' }}
        run: |
          uvx --from pip-audit==__PIP_AUDIT_VERSION__ pip-audit --version
          uvx --from pip-audit==__PIP_AUDIT_VERSION__ pip-audit \
            --requirement dependency-audit-requirements.txt --strict
      - name: Frontend production dependency audit
        if: hashFiles('frontend/package-lock.json') != ''
        working-directory: frontend
        run: |
          npm --version
          npm audit --omit=dev --audit-level=high
      - name: Validate reviewed dependency suppressions
        if: hashFiles('dependency-audit-suppressions.json') != ''
        run: python scripts/validate_dependency_suppressions.py --check
      - name: Rust dependency audit (cargo-audit __CARGO_AUDIT_VERSION__)
        if: hashFiles('frontend/src-tauri/Cargo.lock') != ''
        working-directory: frontend/src-tauri
        shell: bash
        run: |
          cargo install cargo-audit --locked --version __CARGO_AUDIT_VERSION__
          audit_args=()
          if [[ -f ../../dependency-audit-suppressions.json ]]; then
            while IFS= read -r advisory; do
              audit_args+=(--ignore "$advisory")
            done < <(python ../../scripts/validate_dependency_suppressions.py --ecosystem rust)
          fi
          cargo audit --version
          cargo audit "${audit_args[@]}"
"""
DEPENDENCY_AUDIT_JOB = DEPENDENCY_AUDIT_JOB.replace(
    "__PIP_AUDIT_VERSION__", PIP_AUDIT_VERSION
).replace("__CARGO_AUDIT_VERSION__", CARGO_AUDIT_VERSION)

GENERATED_JOBS: dict[GateId, str] = {
    "docs-links": DOCS_LINKS_JOB,
    "dependency-audit": DEPENDENCY_AUDIT_JOB,
}


#: The marker that identifies a job this module wrote. A job without it was
#: written by a person and is never touched.
GENERATED_MARKER = "Generated by maintenance/workflows.py"


def _strip_generated(content: str, gate: GateId) -> str:
    """Remove a previously generated job, leaving hand-written ones alone."""
    pattern = re.compile(rf"\n  {re.escape(gate)}:\n(?:.*?\n)*?(?=\n  [A-Za-z0-9_-]+:\n|\Z)")
    match = pattern.search(content)
    if match is None or GENERATED_MARKER not in match.group(0):
        return content
    return content[: match.start()] + content[match.end() :]


def add_jobs(
    workflow_path: Path,
    gates: Sequence[GateId],
    *,
    replace: bool = True,
) -> tuple[bool, str]:
    """Write the generated jobs into a workflow, idempotently.

    A job this module previously generated is replaced, so regenerating after a
    fix updates every repository. A job with the same name that somebody wrote by
    hand is left exactly as it is — it has no generated marker, and overwriting
    it would be this tool destroying work it did not do.
    """
    if not workflow_path.is_file():
        return False, f"{workflow_path} does not exist"

    original = workflow_path.read_text(encoding="utf-8")
    content = original
    written: list[GateId] = []

    for gate in gates:
        if gate not in GENERATED_JOBS:
            continue
        if f"\n  {gate}:" in content:
            if not replace:
                continue
            stripped = _strip_generated(content, gate)
            if stripped == content:
                continue  # hand-written; leave it
            content = stripped
        content = content.rstrip("\n") + "\n" + GENERATED_JOBS[gate]
        written.append(gate)

    if content == original:
        return False, "nothing to change"
    workflow_path.write_text(content, encoding="utf-8")
    return True, f"wrote {', '.join(written)}"


#: The package gate for a uv-managed CLI: build the wheel, install only that
#: wheel, and run the console script. `uv build` alone proves a build; this
#: proves the artifact somebody actually receives works.
PACKAGE_JOB = """
  package:
    name: package
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      # astral-sh/setup-uv v9.0.0
      - uses: astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9
      # Generated by maintenance/workflows.py — regenerate, do not hand-edit.
      - name: Build the distributions
        run: uv build
      - name: package
        shell: bash
        run: |
          set -euo pipefail
          wheel=$(ls dist/*.whl)
          python -m venv /tmp/package-check
          /tmp/package-check/bin/pip install --quiet "$wheel"
          # The console script must exist and answer, from the wheel alone.
          /tmp/package-check/bin/${{ github.event.repository.name }} --version
"""

#: The release-integrity gate: every place a version is written must agree.
#: A tag that says 1.0.6 while a manifest says 1.0.5 ships an installer whose
#: about box lies.
RELEASE_INTEGRITY_JOB = """
  release-integrity:
    name: release-integrity
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      # Generated by maintenance/workflows.py — regenerate, do not hand-edit.
      - name: release-integrity
        shell: python
        run: |
          import json, pathlib, re, sys

          found = {}

          package_json = pathlib.Path("frontend/package.json")
          if package_json.is_file():
              found["frontend/package.json"] = json.loads(package_json.read_text())["version"]

          tauri = pathlib.Path("frontend/src-tauri/tauri.conf.json")
          if tauri.is_file():
              config = json.loads(tauri.read_text())
              version = config.get("version") or config.get("package", {}).get("version")
              if version:
                  found["tauri.conf.json"] = version

          version_py = pathlib.Path("backend/app/_version.py")
          if version_py.is_file():
              match = re.search(r'__version__\\s*=\\s*"([^"]+)"', version_py.read_text())
              if match:
                  found["backend/app/_version.py"] = match.group(1)

          changelog = pathlib.Path("CHANGELOG.md")
          if changelog.is_file():
              match = re.search(r"(\\d+\\.\\d+\\.\\d+)", changelog.read_text())
              if match:
                  found["CHANGELOG.md"] = match.group(1)

          if not found:
              print("no version sources found")
              sys.exit(1)

          for source, version in sorted(found.items()):
              print(f"{source}: {version}")

          distinct = set(found.values())
          if len(distinct) > 1:
              print(f"\\nversions disagree: {sorted(distinct)}")
              sys.exit(1)
          print("\\nevery version source agrees")
"""


GENERATED_JOBS["package"] = PACKAGE_JOB
GENERATED_JOBS["release-integrity"] = RELEASE_INTEGRITY_JOB
