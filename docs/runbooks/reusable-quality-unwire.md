# Un-wire the reusable Python quality workflow

Use this runbook when a consumer must stop depending on
`fileworks/maintenance/.github/workflows/reusable-python-quality.yml`. The
maintenance workflows can remain published and unreferenced; un-wiring is a
consumer-only change.

The three supported consumers and their migration files are:

| Repository | Workflow |
|---|---|
| `immich-export` | `.github/workflows/ci.yml` |
| `paperless-export` | `.github/workflows/ci.yml` |
| `unpacksort` | `.github/workflows/quality.yml` |

## Restore the exact local job

Start from a clean, current consumer checkout and create a branch. Never make
this change directly on `main`.

```console
git status --short
git switch main
git pull --ff-only
git switch -c chore/unwire-reusable-quality
```

Set `workflow` to the path in the table, then locate the commit that introduced
the reusable call. The search must return one commit before continuing.

```console
workflow=.github/workflows/ci.yml
migration_commit="$(git log -n 1 --format=%H \
  -S 'uses: fileworks/maintenance/.github/workflows/reusable-python-quality.yml@' \
  -- "$workflow")"
test -n "$migration_commit"
git show --stat --oneline "$migration_commit"
```

For `unpacksort`, use its different path:

```console
workflow=.github/workflows/quality.yml
```

Apply only the inverse of that commit's workflow-file patch. This restores the
reviewed local job without reverting unrelated files from the migration commit
or later commits.

```console
git show --format= "$migration_commit" -- "$workflow" | git apply --reverse --3way
git diff HEAD -- "$workflow"
```

If the three-way apply reports a conflict, stop. Resolve it by restoring the
local quality steps from `"$migration_commit^:$workflow"` while retaining all
unrelated changes made after the migration; do not replace the entire current
workflow with its historical version.

## Verify the restored contracts

The reusable reference must be gone, and the repository's original local
contracts must be present:

```console
! rg -n 'uses: fileworks/maintenance/.github/workflows/reusable-python-quality.yml@' \
  "$workflow"
git diff HEAD --check
```

Then run the repository-specific checks.

- `immich-export`: retain the Python 3.12/3.13/3.14 matrix, locked environment,
  Ruff, mypy, pytest, and the local build step.
- `paperless-export`: retain the Python 3.12/3.13/3.14 matrix, `uv lock --check`,
  Poppler installation on the same runner as pytest, Ruff, mypy, pytest, and
  the local build step. Its portability and Synology jobs must remain present.
- `unpacksort`: retain the Ubuntu/macOS/Windows × Python 3.12/3.13/3.14 quality
  matrix with `uv sync --locked --all-groups`, plus the unchanged 3×3
  installed-wheel build matrix.

The generated local `docs-links` job and every release workflow are outside
this migration and must remain unchanged. Run any local workflow/configuration
validator available in the repository. GitHub-hosted matrix runs and emitted
check names must be verified on the pull request.

Commit only the consumer workflow, using a non-releasing Wave 0 commit type:

```console
git add "$workflow"
git commit -m "chore(ci): restore local Python quality job"
```

Open a pull request, confirm the restored local check is green, and verify its
required-check/ruleset identity before merging. Do not remove or rename the
required reusable check until its local replacement has emitted successfully.
