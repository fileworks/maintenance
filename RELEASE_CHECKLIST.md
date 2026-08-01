# Clean-host release checklist

Automation verifies versions, archive types, filenames, checksums, package
metadata, GitHub assets, PyPI publication, and Homebrew formula inputs. This
checklist is only for behavior that requires a real clean Windows or macOS host.
Run it once per release candidate and record the version, observer, date, and
results in the release notes.

MediaSorter is intentionally **unsigned for now**. Windows SmartScreen and
macOS Gatekeeper may therefore warn. The warning is expected; the download must
still come from the official `fileworks/media-sorter` GitHub Release and its
SHA-256 must match the published checksum.

## Before starting

- [ ] Use a host or VM without a development checkout, Python virtual
  environment, Node.js dev server, or previously running MediaSorter backend.
- [ ] Record the release version, operating-system version and architecture,
  observer, and date.
- [ ] Download only from the official GitHub Release or PyPI.
- [ ] Compare each downloaded file's SHA-256 with `SHA256SUMS.txt`.
  On Windows use `Get-FileHash <file> -Algorithm SHA256`; on macOS use
  `shasum -a 256 <file>`.

## Windows

- [ ] Install the MediaSorter `.msi` from the GitHub Release. Confirm the
  unsigned-publisher warning names the downloaded file; do not bypass a digest
  mismatch.
- [ ] Launch from the Start menu. Confirm the compact orange MediaSorter icon,
  readable compact layout, no terminal window, and no browser/dev-server page.
- [ ] Complete one small copy or move job. Confirm progress updates, the result
  is correct, and source/destination boundaries are respected.
- [ ] Close and reopen twice. Confirm the app starts once, preserves settings
  and history, and does not leave duplicate backend processes.
- [ ] Install the new `.msi` over the previous public version and repeat launch
  and one small job. Confirm settings are preserved.
- [ ] In a fresh PowerShell session run
  `py -m pip install --upgrade immich-export paperless-export unpacksort`.
- [ ] Run `immich-export --version`, `paperless-export --version`, and
  `unpacksort --version`; confirm each matches its published release.
- [ ] Run each tool's `--help`, then one non-destructive dry run or small
  disposable-input operation. Confirm readable progress and a zero exit code.
- [ ] Uninstall MediaSorter from Windows Settings. Confirm its Start-menu entry
  is removed and no app process remains.

## macOS

- [ ] On the machine's native architecture, install the matching MediaSorter
  `.dmg`. Confirm the expected unidentified-developer warning; do not bypass a
  digest mismatch.
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
- [ ] Run `brew update && brew upgrade immich-export paperless-export unpacksort`
  (or `brew install` for tools not already present).
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
- [ ] If anything fails, keep the release as a draft, attach logs/screenshots,
  and use the matching recovery playbook in
  [release-playbooks.md](release-playbooks.md).
