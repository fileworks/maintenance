# Clean-host release checklist

Automation verifies versions, archive types, filenames, checksums, package
metadata, GitHub assets, PyPI publication, and Homebrew formula inputs. This
checklist is only for behavior that requires a real clean Windows or macOS host.
Run it periodically and after installer, startup, migration, signing, or
operating-system support changes. A completely green automated release does not
wait for this checklist. Record the version, observer, date, and results in the
release notes or a follow-up issue.

MediaSorter is intentionally **unsigned for now**. Windows SmartScreen and
macOS Gatekeeper may therefore warn. The warning is expected; the download must
still come from the official `fileworks/media-sorter` GitHub Release and its
SHA-256 must match the published checksum.

## Before starting

- [ ] Use a host or VM without a development checkout, Python virtual
  environment, Node.js dev server, or previously running MediaSorter backend.
- [ ] Record the release version, operating-system version and architecture,
      observer, and date.
- [ ] Record the expected exporter/UnpackSort versions from
      `maintenance/release-ledger.json`; do not infer them from an old local
      installation.
- [ ] Download only from the official GitHub Release or PyPI.
- [ ] Compare each downloaded file's SHA-256 with `SHA256SUMS`.
  On Windows use `Get-FileHash <file> -Algorithm SHA256`; on macOS use
  `shasum -a 256 <file>`.

## Windows

- [ ] Download the MediaSorter `.msi`, `-setup.exe`, and portable `.zip` from
  the same GitHub Release. Confirm all three appear in `SHA256SUMS`.
- [ ] From a clean VM snapshot, install the `.msi`. Confirm the
  unsigned-publisher warning names the downloaded file; do not bypass a digest
  mismatch.
- [ ] Launch from the Start menu. Confirm the compact orange MediaSorter icon,
  readable compact layout, no terminal window, and no browser/dev-server page.
- [ ] Complete one small copy or move job. Confirm progress updates, the result
  is correct, and source/destination boundaries are respected.
- [ ] Close and reopen twice. Confirm the app starts once, preserves settings
  and history, and does not leave duplicate backend processes.
- [ ] Install the new `.msi` over the previous public version and repeat launch
  and one small job. Confirm settings are preserved, then uninstall it.
- [ ] Restore the clean snapshot and repeat the launch, small-job, upgrade, and
  uninstall checks with the NSIS `-setup.exe`.
- [ ] Extract the portable `.zip` without installing it. Launch its executable,
  complete one small job, close/reopen twice, and confirm no files were written
  beside the executable except documented portable state.
- [ ] Download the UnpackSort `-windows-x64.zip` from its official GitHub
  Release, confirm it appears in `SHA256SUMS`, and extract it without installing.
  Run `unpacksort.exe --version` and `unpacksort.exe --help`.
- [ ] Give the portable UnpackSort executable a disposable source directory
  containing one small ZIP or TAR archive. Confirm it extracts the expected
  bytes and writes `manifest.jsonl` and `report.txt` in the destination.
- [ ] With a supported Python installed, run `py -m pip install --user pipx`
      and `py -m pipx ensurepath`, then open a fresh PowerShell session.
- [ ] Run `pipx install immich-export`, `pipx install paperless-export`, and
      `pipx install unpacksort`. Use `pipx upgrade PACKAGE` only when explicitly
      testing an existing isolated installation.
- [ ] Run `immich-export --version`, `paperless-export --version`, and
  `unpacksort --version`; confirm each matches its published release.
- [ ] Run each tool's `--help`, then one non-destructive dry run or small
  disposable-input operation. Confirm readable progress and a zero exit code.
- [ ] Confirm each installer removes its Start-menu entry and no app process
  remains after uninstall; confirm deleting the portable directory removes that
  copy without affecting user data.

## macOS

- [ ] On the machine's native architecture, download the matching MediaSorter
  `.dmg` and confirm it appears in `SHA256SUMS`. Confirm the expected
  unidentified-developer warning; do not bypass a digest mismatch.
- [ ] Move MediaSorter to Applications and launch it using Finder's **Open**
  confirmation for an unsigned app.
- [ ] Confirm the compact orange MediaSorter icon, readable compact layout, and
  that no Terminal or browser/dev-server window opens.
- [ ] Complete one small copy or move job. Confirm progress updates, the result
  is correct, and source/destination boundaries are respected.
- [ ] Close and reopen twice. Confirm the app starts once, preserves settings
  and history, and does not leave duplicate backend processes.
- [ ] Install over the previous public version and repeat launch and one small
  job. Confirm settings are preserved.
- [ ] On a clean Homebrew host run `brew update`, then install
      `fileworks/tap/immich-export`, `fileworks/tap/paperless-export`, and
      `fileworks/tap/unpacksort`.
- [ ] For an existing installation, run `brew upgrade` for those same three
      fully qualified formula names.
- [ ] Run `immich-export --version`, `paperless-export --version`, and
  `unpacksort --version`; confirm each matches its published release.
- [ ] Run each tool's `--help`, then one non-destructive dry run or small
  disposable-input operation. Confirm readable progress and a zero exit code.
- [ ] Move MediaSorter to Trash and confirm no app process remains.

## Evidence to attach

- [ ] Record every checkbox as pass, fail, or not applicable; do not leave
  blanks.
- [ ] Attach the calculated SHA-256 values and exact artifact filenames.
- [ ] Record any operating-system warning verbatim enough to distinguish the
  expected unsigned warning from corruption or a different publisher.
- [ ] If anything fails, stop follow-on distribution changes, attach
  logs/screenshots, and use the matching recovery playbook in
  [release-playbooks.md](release-playbooks.md).
