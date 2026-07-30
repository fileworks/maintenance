# Cross-repository maintenance

The policy the five `fileworks` repositories are held to, and a read-only check
of whether they meet it.

```console
python -m maintenance.cli            # the drift report
python -m maintenance.cli --matrix   # the compliance matrix
python -m maintenance.cli --json out.json --strict
```

Nothing here writes to a repository or touches a remote setting. That separation
is deliberate: a tool that can both audit and fix will eventually be run against
production settings by accident.

## What is where

| File | What it holds |
|---|---|
| `policy.py` | The desired-state manifest: repository classes, required files, audited settings, and the exception schema. Plus the evaluator. |
| `gates.py` | Stable gate names and the class × gate matrix. Renaming a gate silently unprotects a branch, so the names live here once. |
| `renovate.py` | The shared Renovate policy, the per-repository generator, and the automerge allowlist. |
| `ledger.py` | The canonical machine-readable release ledger. |
| `docs.py` | README information architecture, install-command checks, version-drift checks against the ledger, and link checks. |
| `drift.py` | The report, the dry-run plan for remote settings, and the compliance matrix. |
| `release-ledger.json` | The generated ledger. Regenerate it; do not hand-edit it. |
| `exceptions.json` | Documented, dated, owned exceptions. Absent means none. |

## The five outcomes

`compliant` · `missing` · `mismatched` · `excepted` · `stale` · `unverifiable`

The last one carries the weight. A control that needs an authenticated `gh`
session is reported `unverifiable`, never `compliant` — claiming compliance for
something nobody checked is the failure a compliance tool exists to prevent.

## Renovate

The shared policy lives in `renovate.py` and is generated into each repository.
Until a shared preset repository exists, the generated files **inline** the
policy rather than extending a preset that has not been published: a config
extending something that does not exist does not drift, it simply fails to run.
Both forms come from the same generator, so they cannot disagree.

Automerge is narrow on purpose. Patch and minor updates merge themselves once
every required check is green; publishers, toolchains, codecs, installers, and
security-sensitive libraries always wait for a person, at every update type.
Security advisories are surfaced immediately and are **not** automerged.

## Gate alignment

`workflows.py` maps each repository's workflows onto the declared gates. It does
not rename anything: a job's name is the check branch protection requires, so a
rename unprotects `main` until the protection rule is updated in the same
change — which needs authentication. The renames are therefore *queued*.

Observed on 2026-07-28:

| Gate | `media-sorter` | `immich-export` | `paperless-export` | `unpacksort` | `homebrew-tap` |
|---|---|---|---|---|---|
| build | ✅ | ✅ | ✅ | ✅ | — |
| dependency-audit | ❌ | ❌ | ❌ | ✅ | — |
| docs-links | ❌ | ❌ | ❌ | ❌ | ❌ |
| format | ✅ | ✅ | ✅ | ✅ | — |
| formula-audit | — | — | — | — | ✅ |
| installer-preflight | ✅ | — | — | — | — |
| lint | ✅ | ✅ | ✅ | ✅ | — |
| package | ✅ | ❌ | ❌ | ✅ | — |
| release-integrity | ❌ | ✅ | ✅ | ✅ | — |
| test | ✅ | ✅ | ✅ | ✅ | — |
| typecheck | ✅ | ✅ | ✅ | ✅ | — |

Four of the five repositories run one job that covers several gates
(`quality`, `backend`). Those cannot be renamed to any single gate name without
silently unrequiring the others, so they are reported for a decision — split the
job, or keep requiring its current name — rather than rewritten.

`docs-links` is missing everywhere. Adding it means five copies of the same
script until there is a shared home for it, so it waits on the same approval as
the Renovate preset.

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

## Waiting on you

These are the parts that cannot be done without a decision or a credential. They
are listed here rather than half-done.

| # | Needs | Why it is blocked |
|---|---|---|
| 1 | `gh auth login` with org access | Every remote setting — descriptions, topics, merge settings, security features, Actions permissions, branch protection — reads as `unverifiable` until an authenticated run supplies the observed values. The dry-run plan is already implemented; it just has nothing to compare against. |
| 2 | Approval to create a shared `.github` repository | Then the generated `renovate.json` files become two-line `extends`, and the community health files move out of the five repositories. Until then they are repository-local and generated. |
| 3 | A decision on `CODEOWNERS` | `media-sorter`, `immich-export`, `paperless-export` and the new `homebrew-tap` file route review to `@gykonik`; `unpacksort` routes to `@NikAcc`. One of those is probably wrong, and guessing which would misroute reviews. |
| 4 | Approval of the icon family | The identity work (directions, glyphs, the exact orange, the proofs) is a design review, not an implementation task, and replacing public assets without approval is not reversible in the way code is. |
| 5 | unpacksort channel setup | PyPI trusted publishing, the GitHub release, the Homebrew formula, and the WinGet identity. The formula cannot be written before the package has a URL and a checksum to point at. |

## Regenerating

```console
python - <<'EOF'
from pathlib import Path
from maintenance.renovate import repo_configs, write_preset, write_repo_config

write_preset(Path("maintenance/renovate"))
for config in repo_configs("github>fileworks/.github//renovate/fileworks-base"):
    write_repo_config(config, Path(config.name), inline=True)
EOF
```

The ledger is regenerated by recording observations against `ledger.scaffold()`;
see `maintenance/tests/test_maintenance.py` for the shape.
