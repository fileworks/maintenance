<img src=".github/icon.svg" alt="" width="72" height="72" align="left">

# Cross-repository maintenance

The executable policy all six `fileworks` Git repositories are held to, including
this governance repository, and a read-only check of whether they meet it.

## Overview

This repository is internal governance tooling, not another end-user product.
It evaluates local files and, only with an explicitly authenticated flag, reads
remote settings.

It *can* mutate remotes — `maintenance/reconcile_apply.py` applies a plan — but
nothing the CLI loads can reach that module. The separation is a file, not a
promise, and `tests/test_apply_boundary.py` asserts it by importing the CLI in a
clean interpreter and checking the writer never arrives.

## Usage

```console
python -m maintenance.cli            # the drift report
python -m maintenance.cli --matrix   # the compliance matrix
python -m maintenance.cli --json out.json --strict
```

None of the commands above writes to a repository or touches a remote setting.
That separation is deliberate: a tool that can both audit and fix will
eventually be run against production settings by accident. Applying a plan is a
separate module a caller has to import on purpose (`A-08`); it refuses to write
in dry-run mode and never writes a change whose prerequisites are not green.

## What is where

| File | What it holds |
|---|---|
| `policy.py` | The desired-state manifest: repository classes, required files, audited settings, and the exception schema. Plus the evaluator. |
| `gates.py` | Stable gate names and the class × gate matrix. Renaming a gate silently unprotects a branch, so the names live here once. |
| `renovate-policy.json` | The centrally shared Renovate policy used by every managed repository. |
| `.github/workflows/reusable-*.yml` | Callable, read-only CI building blocks for repository workflows. |
| `renovate.py` | Dependency-automation metrics and recommendations. |
| `ledger.py` | The canonical machine-readable release ledger. |
| `docs.py` | README information architecture, install-command checks, version-drift checks against the ledger, and link checks. |
| `deployments.py` | Canonical GitHub Release versus Deployment environments and workflow checks. |
| `drift.py` | The report, the dry-run plan for remote settings, and the compliance matrix. |
| `formula.py`, `generated/` | The sdist-oriented reference generator and frozen regression fixtures. Live release formulas are generated and owned by `homebrew-tap`. |
| `identity/social_previews.py` | The semantic copy and shared layout for all six public GitHub social previews. |
| `release-ledger.json` | The generated ledger. Regenerate it; do not hand-edit it. |
| `exceptions.json` | Documented, dated, owned exceptions. Absent means none. |

## Policy

## The six outcomes

`compliant` · `missing` · `mismatched` · `excepted` · `stale` · `unverifiable`

The last one carries the weight. A control that needs an authenticated `gh`
session is reported `unverifiable`, never `compliant` — claiming compliance for
something nobody checked is the failure a compliance tool exists to prevent.

## Dependency automation

`renovate-policy.json` is a GitHub-hosted shared Renovate preset. Every managed
repository has only a minimal `renovate.json` that extends
`github>fileworks/maintenance:renovate-policy`, so changes to the central policy
apply everywhere without generating or synchronizing copied configuration.

The Mend Renovate App is installed for the whole `fileworks` organization, so
`maintenance` and every managed repository inherit it automatically. Its
installation grants the required repository, pull-request, issue, workflow,
status/check, and vulnerability-alert access. No repository Actions secret or
deploy key is needed. GitHub's Dependency Graph and Dependabot alerts remain
enabled for visibility. Dependabot version updates and automated security-update
PRs remain disabled so Renovate is the only update author.

Minor, patch, pin, digest, and bump updates are batched into one weekly PR, wait
until releases are seven days old, and are squash-merged by Renovate only after
all observed status checks pass. The batch refreshes the affected lockfiles;
standalone lock-file-maintenance branches are disabled so they cannot create a
second weekly PR. The batch uses `fix(deps)`, so managed products can publish at
most one routine dependency patch release per week.
Major, replacement, and rollback updates remain on the Dependency Dashboard
until explicitly approved and are never auto-merged. Renovate's special
vulnerability-alert PR mode is disabled because it bypasses schedules and
concurrency limits; security fixes follow the same weekly non-major or
approval-only major path, so they cannot create a stacked PR.

## Gate alignment

`workflows.py` maps each repository's workflows onto the declared gates. It does
not rename anything: a job's name is the check branch protection requires, so a
rename unprotects `main` until the protection rule is updated in the same
change — which needs authentication. The renames are therefore *queued*.

The table is generated by `maintenance.workflows.alignment_matrix`; run the
audit to get the current state instead of maintaining a dated copy here:

```console
python -m maintenance.cli --matrix
```

Several repositories run one job that covers several gates
(`quality`, `backend`). Those cannot be renamed to any single gate name without
silently unrequiring the others, so they are reported for a decision — split the
job, or keep requiring its current name — rather than rewritten.

Product workflows stay repository-local because their matrices, native
dependencies, and packaging differ. They can call the read-only reusable
workflows in this repository with a commit-pinned job-level `uses:` reference.
Callers retain their own triggers, permissions, and matrices; required-check
migrations remain explicit. Release and publishing jobs are deliberately never
shared.

```yaml
jobs:
  quality:
    uses: fileworks/maintenance/.github/workflows/reusable-python-quality.yml@<commit-sha>
    with:
      python-version: "3.14"
      runs-on: ubuntu-latest
      working-directory: "."
      sync-mode: all-extras-dev
      install-poppler: false
      typecheck-target: "."
      audit: false
```

Treat switching an existing required job to a reusable call as a ruleset
migration and verify the emitted check before requiring it. Where the existing
check identity must stay exact, keep the thin caller job local or share a
composite action instead. The reusable workflow accepts only the
`all-extras-dev` and `all-groups` sync modes; it never executes a caller-provided
shell fragment. Its Poppler option installs the native package on the same Linux
runner that executes the tests.

The generated repository-local `docs-links` jobs remain local. Maintenance's own
quality workflow also remains local because it checks out into a subdirectory,
and `homebrew-tap` is not a Python consumer. If maintenance must be removed from a
product's CI dependency chain, follow the
[reusable-quality un-wire runbook](docs/runbooks/reusable-quality-unwire.md).

## The approved identity

Recorded in `identity/decision.json`, which is what the export and the audit both
read — approval is data, not a memory of a conversation.

| | |
|---|---|
| Family | `literal` — Apertures construction, contents reworked to say what each tool does |
| Orange | ember `#C2410C` (4.85:1 on paper, 3.38:1 on slate) |
| Approved | 2026-07-28 |

`identity/rollout.py` writes it into all ten display locations: a preview icon in
each repository's `.github/`, the MediaSorter window icon, and the Tauri bundle
rasters at 32, 128 and 256 px. Rasters come from `rsvg-convert`; when that is not
installed the PNG step is **skipped and reported** rather than faked, because a
missing icon is obvious and a wrong one is not.

The audit checks that what is on display is still the family that was approved.

## Recorded operating decisions

| Area | Decision |
|---|---|
| Policy distribution | Keep generated repository-local files. The independent projects do not need a shared `.github` repository. |
| Review ownership | Keep every existing `CODEOWNERS` mapping unchanged. Ownership changes require a separate explicit decision. |
| Desktop signing | Publish MediaSorter unsigned for now and describe the expected operating-system warning accurately. Signing and notarization remain documented future hardening, not a release blocker. |
| Visual identity | Keep the compact literal icon family approved on 2026-07-28. Material replacement still requires a new visual review. |
| Human release evidence | Use the single [clean-host release checklist](RELEASE_CHECKLIST.md) after automated artifact and channel verification. |
| Publication model | A green release pipeline publishes a GitHub Release. Protected `github-release`, `pypi`, `homebrew`, and `winget` environments record the applicable channel deployments. |

## Development

### Renovate verification

The organization-wide Renovate installation covers all repositories and is not
suspended. Every repository's minimal `renovate.json` extends the shared policy,
which Renovate resolves from this repository on every run; there is no
generation or per-repository synchronization step.

The hosted App supplies its own credentials. Keep Dependabot automated security
fixes disabled while leaving the Dependency Graph and Dependabot alerts enabled;
the alerts remain visible while Renovate's normal updates preserve the one-branch
lifecycle.

The ledger is regenerated from reviewed, read-only observations with
`maintenance/.venv/bin/python -m maintenance.refresh_release_ledger` from the
workspace root. Use `--check` in CI; never hand-edit the generated JSON.

## Security

Remote observations are fail-closed: unavailable settings remain
`unverifiable`. Reconciliation evidence is recursively redacted for current
GitHub credential shapes and secret-named fields before it reaches reports.
Never place credentials in the ledger, exception file, fixtures, or command
arguments.

## License

Licensed under the [MIT License](LICENSE).
