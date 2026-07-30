# Release recovery playbooks

Each section is one state the world can be left in, how to recognise it, and
what to do. The `Never` lines are the actions that turn a recoverable state
into an unrecoverable one.

## Partial publish

**Symptom.** The tag and GitHub Release exist, but a later channel does not.

1. Confirm the release commit is the one CI went green on.
2. Re-run the publish job for the missing channel only; the workflow is idempotent.
3. If PyPI rejected the upload as a duplicate, the artifact is already there — verify its digest against the release asset rather than republishing.
4. Re-run the formula bump last, once PyPI serves the sdist.

> **Never.** Never bump the version to force a fresh publish. A version that was never released to some channels is repaired, not skipped over.

## Duplicate trigger

**Symptom.** Two release runs started for the same tag.

1. Let the first run finish; cancel the second.
2. PyPI rejects the duplicate upload, which is the desired outcome.
3. Check the tap received exactly one bump — a second would be a no-op commit.

> **Never.** Never delete and re-push the tag. Consumers may already have fetched it.

## Formula bump failed

**Symptom.** PyPI has the release; the formula still points at the previous version.

1. Read the queued bump issue in the tap; it records the requested formula and version.
2. Confirm the PyPI sdist URL and sha256 by fetching them.
3. Re-dispatch the bump, or edit the formula with those exact values and open a PR.
4. brew audit --strict --online and brew install --build-from-source before merging.

> **Never.** Never hand-edit url or sha256 without fetching them; a wrong digest fails at install time on somebody else's machine.

## Artifact mismatch

**Symptom.** A published artifact's digest does not match what CI built.

1. Treat the published artifact as untrusted until it is explained.
2. Compare the release asset against the CI run's artifact for the same SHA.
3. If they differ, yank the release, then investigate before republishing.
4. Record the incident in the release ledger with state `failed`.

> **Never.** Never overwrite the artifact in place. The mismatch is evidence.

## Channel could not be checked

**Symptom.** A channel's state is unknown because the check could not run.

1. Record it as `unverified` in the ledger — never as published.
2. Re-run the audit with an authenticated session.
3. Until then, no documentation may quote a version for that channel.

## Publication order

| Channel | Only after | Why |
|---|---|---|
| `github_release` | — | the tag's evidence; everything else references it |
| `pypi` | github_release | the sdist the formula will point at must exist before the formula does |
| `homebrew` | pypi | a formula needs the published URL and digest; it cannot be written earlier |
| `winget` | github_release | the manifest references the GitHub asset and its digest |
