# Cross-repository compliance

Generated 2026-07-28T13:37:24.201021+00:00.

| Area | Result |
|---|---|
| Repository files | clean |
| Remote settings | not checked |
| Documentation | clean |
| Quality gates | clean |
| Renovate | clean |
| Package metadata | clean |
| Formulas | 8 finding(s) |
| Identity assets | clean |
| Identity rollout | clean |
| Release channels | 4 finding(s) |

### Remote settings

Not checked: needs an authenticated `gh` session; reported as unverifiable

### Formulas

- immich-export: the test block only checks --version or --help, which proves the binary exists and nothing more
- immich-export: declares no pinned resources, so its dependency set is not fixed
- immich-export: resolves dependencies at install time; two installs can differ
- immich-export: does not install from its declared resources
- paperless-export: the test block only checks --version or --help, which proves the binary exists and nothing more
- paperless-export: declares no pinned resources, so its dependency set is not fixed
- paperless-export: resolves dependencies at install time; two installs can differ
- paperless-export: does not install from its declared resources

### Release channels

- unpacksort/github_release: unverified
- unpacksort/homebrew: unverified
- unpacksort/pypi: unverified
- unpacksort/winget: unverified

## Controls

| Control | `media-sorter` | `immich-export` | `paperless-export` | `unpacksort` | `homebrew-tap` |
|---|---|---|---|---|---|
| actions_permissions | ❓ | ❓ | ❓ | ❓ | ❓ |
| allow_squash_merge | ❓ | ❓ | ❓ | ❓ | ❓ |
| changelog | ✅ | ✅ | ✅ | ✅ | — |
| codeowners | ✅ | ✅ | ✅ | ✅ | ✅ |
| contributing | ✅ | ✅ | ✅ | ✅ | ✅ |
| default_branch_protection | ❓ | ❓ | ❓ | ❓ | ❓ |
| delete_branch_on_merge | ❓ | ❓ | ❓ | ❓ | ❓ |
| description | ❓ | ❓ | ❓ | ❓ | ❓ |
| license | ✅ | ✅ | ✅ | ✅ | ✅ |
| python_project | — | ✅ | ✅ | ✅ | — |
| quality_workflow | ✅ | ✅ | ✅ | ✅ | ✅ |
| readme | ✅ | ✅ | ✅ | ✅ | ✅ |
| release_workflow | ✅ | ✅ | ✅ | ✅ | — |
| renovate | ✅ | ✅ | ✅ | ✅ | ✅ |
| security_policy | ✅ | ✅ | ✅ | ✅ | ✅ |
| vulnerability_alerts | ❓ | ❓ | ❓ | ❓ | ❓ |

Legend: ✅ compliant · ⚠️ excepted · ❌ out of policy · ❓ unverifiable · — n/a

**`media-sorter` does not run:** `formula-audit` (Only a tap has formulas.)

**`immich-export` does not run:** `formula-audit` (Only a tap has formulas.); `installer-preflight` (Only the desktop product ships installers.)

**`paperless-export` does not run:** `formula-audit` (Only a tap has formulas.); `installer-preflight` (Only the desktop product ships installers.)

**`unpacksort` does not run:** `formula-audit` (Only a tap has formulas.); `installer-preflight` (Only the desktop product ships installers.)

**`homebrew-tap` does not run:** `format` (not applicable to this repository class); `lint` (not applicable to this repository class); `typecheck` (A tap holds Ruby formulas; `brew audit` covers their correctness.); `test` (not applicable to this repository class); `build` (not applicable to this repository class); `package` (not applicable to this repository class); `dependency-audit` (A tap pins upstream releases; their own audits apply.); `release-integrity` (not applicable to this repository class); `installer-preflight` (Only the desktop product ships installers.)

## Gates

| Gate | `media-sorter` | `immich-export` | `paperless-export` | `unpacksort` | `homebrew-tap` |
|---|---|---|---|---|---|
| build | ✅ | ✅ | ✅ | ✅ | — |
| dependency-audit | ✅ | ✅ | ✅ | ✅ | — |
| docs-links | ✅ | ✅ | ✅ | ✅ | ✅ |
| format | ✅ | ✅ | ✅ | ✅ | — |
| formula-audit | — | — | — | — | ✅ |
| installer-preflight | ✅ | — | — | — | — |
| lint | ✅ | ✅ | ✅ | ✅ | — |
| package | ✅ | ✅ | ✅ | ✅ | — |
| release-integrity | ✅ | ✅ | ✅ | ✅ | — |
| test | ✅ | ✅ | ✅ | ✅ | — |
| typecheck | ✅ | ✅ | ✅ | ✅ | — |

✅ runs · ❌ required but not found · — not applicable to this class

**`media-sorter` does not run:** `formula-audit` (Only a tap has formulas.)

**`immich-export` does not run:** `formula-audit` (Only a tap has formulas.); `installer-preflight` (Only the desktop product ships installers.)

**`paperless-export` does not run:** `formula-audit` (Only a tap has formulas.); `installer-preflight` (Only the desktop product ships installers.)

**`unpacksort` does not run:** `formula-audit` (Only a tap has formulas.); `installer-preflight` (Only the desktop product ships installers.)

**`homebrew-tap` does not run:** `format` (not applicable to this repository class); `lint` (not applicable to this repository class); `typecheck` (A tap holds Ruby formulas; `brew audit` covers their correctness.); `test` (not applicable to this repository class); `build` (not applicable to this repository class); `package` (not applicable to this repository class); `dependency-audit` (A tap pins upstream releases; their own audits apply.); `release-integrity` (not applicable to this repository class); `installer-preflight` (Only the desktop product ships installers.)
