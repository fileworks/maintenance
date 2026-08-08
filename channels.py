"""What each publication channel is serving right now.

`ledger.py` answers "what did somebody record?". This module answers "what would
a user installing today actually get?" — and the whole reason it exists is that
on 2026-08-04 those two answers differed for two products while every check that
looked passed, because each of them was reading the record rather than the thing
the record describes.

Two rules hold everywhere below.

*A reader never raises and never guesses.* Any network, authentication, parse or
missing-entity failure returns `None`, which the comparison turns into
`unverifiable`. An offline audit therefore degrades instead of failing, and — the
part that matters — an unreachable channel can never be mistaken for an agreeing
one.

*This module reads and compares. It does not amend.* Recording an observation
stays an explicit act in `ledger.record`. A tool that both audits the ledger and
edits it cannot be trusted about either.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from maintenance.formula import sdist_version
from maintenance.ledger import Channel, ChannelEntry, ProductEntry, ReleaseLedger
from maintenance.policy import LEDGER_CHANNEL_CONTROL, Finding, RepoClass
from maintenance.reconcile import ApiCall, Client

#: The tap is infrastructure, not a release: it has no version to disagree
#: about, and comparing it to one would manufacture a finding on every run.
UNVERSIONED = "unversioned"

USER_AGENT = "fileworks-maintenance/1 (+https://github.com/fileworks)"

ChannelOutcome = Literal["compliant", "stale", "unverifiable"]

#: Takes a URL, returns the body, or `None` for any failure at all.
Fetch = Callable[[str], str | None]

#: Takes a GitHub API path, returns the decoded object, or `None`.
JsonFetch = Callable[[str], dict[str, object] | None]

#: Takes an owner and a repository, returns the latest released version.
ReleaseReader = Callable[[str, str], str | None]

#: Takes one identifier — a distribution name, or a formula name.
VersionReader = Callable[[str], str | None]


def http_get(url: str, *, timeout: int = 15) -> str | None:
    """Fetch a public URL, or `None`. Never raises, whatever went wrong."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body: bytes = response.read()
    except (urllib.error.URLError, OSError, ValueError):
        return None
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        return None


_LEADING_V = re.compile(r"^v(?=\d)")


def normalise(version: str) -> str:
    """`v1.2.3` and `1.2.3` are one release; tags spell it one way and PyPI the other."""
    return _LEADING_V.sub("", version.strip())


# --------------------------------------------------------------------------- #
# The readers                                                                  #
# --------------------------------------------------------------------------- #


def pypi_version(name: str, *, fetch: Fetch = http_get) -> str | None:
    """The version PyPI currently serves for a distribution."""
    body = fetch(f"https://pypi.org/pypi/{name}/json")
    if body is None:
        return None
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    info = payload.get("info")
    if not isinstance(info, dict):
        return None
    version = info.get("version")
    return version if isinstance(version, str) and version else None


def tap_version(
    formula: str,
    *,
    owner: str = "fileworks",
    repository: str = "homebrew-tap",
    fetch: Fetch = http_get,
) -> str | None:
    """The version the tap's default branch installs for one formula.

    Read over raw HTTP rather than through `gh`: the tap is public, and a check
    that quietly needs credentials is a check that quietly stops running. The
    version comes back out of the sdist URL through the same parser the formula
    generator writes against, so the two cannot drift apart.
    """
    source = fetch(
        f"https://raw.githubusercontent.com/{owner}/{repository}/HEAD/Formula/{formula}.rb"
    )
    return None if source is None else sdist_version(source)


def github_release_version(owner: str, repository: str, *, fetch_json: JsonFetch) -> str | None:
    """The latest published release, excluding drafts and pre-releases.

    `releases/latest` already means exactly that, so there is no filtering to get
    wrong here: a repository whose only releases are drafts or pre-releases
    answers 404, and 404 is `None`. The draft and prerelease flags are still
    checked, because trusting one endpoint's semantics without reading what it
    returned is how a pre-release ends up recorded as shipped.
    """
    payload = fetch_json(f"/repos/{owner}/{repository}/releases/latest")
    if payload is None or payload.get("draft") or payload.get("prerelease"):
        return None
    tag = payload.get("tag_name")
    return normalise(tag) if isinstance(tag, str) and tag else None


def gh_json(client: Client) -> JsonFetch:
    """Adapt `reconcile.gh_client` to the failure-tolerant shape used here.

    `gh_client` already swallows its own exceptions and answers `(False, …)`, so
    the adaptation is only about turning that into the `None` this module reads.
    """

    def fetch(path: str) -> dict[str, object] | None:
        ok, payload = client(ApiCall("GET", path))
        return payload if ok else None

    return fetch


@dataclass(frozen=True)
class Readers:
    """The three readers as one injectable unit, so tests need no network."""

    pypi: VersionReader
    homebrew: VersionReader
    github_release: ReleaseReader


def live_readers(client: Client) -> Readers:
    """The readers pointed at the real channels, with `gh` for GitHub Releases."""
    fetch_json = gh_json(client)
    return Readers(
        pypi=pypi_version,
        homebrew=tap_version,
        github_release=lambda owner, repository: github_release_version(
            owner, repository, fetch_json=fetch_json
        ),
    )


def unreadable() -> Readers:
    """Readers for an offline run: everything is `unverifiable`, nothing is guessed."""
    return Readers(
        pypi=lambda _name: None,
        homebrew=lambda _formula: None,
        github_release=lambda _owner, _repository: None,
    )


# --------------------------------------------------------------------------- #
# The comparison                                                               #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ChannelComparison:
    """One product on one channel: what was recorded, and what is actually there."""

    product: str
    channel: Channel
    identifier: str
    recorded: str | None
    observed: str | None

    @property
    def outcome(self) -> ChannelOutcome:
        if self.observed is None:
            return "unverifiable"
        return "compliant" if self.observed == self.recorded else "stale"

    def describe(self) -> str:
        if self.observed is None:
            return (
                f"{self.channel} could not be read for `{self.identifier}`, "
                "so the recorded version is unverified"
            )
        return (
            f"`{self.product}` on {self.channel} (`{self.identifier}`): "
            f"ledger records {self.recorded or 'nothing'}, "
            f"the channel serves {self.observed}"
        )


def _read(entry: ChannelEntry, product: ProductEntry, readers: Readers) -> str | None:
    """Ask the one reader that applies to this channel, if there is one."""
    if entry.channel == "pypi":
        return readers.pypi(entry.identifier)
    if entry.channel == "homebrew":
        # `fileworks/tap/immich-export` — the formula is the last segment.
        return readers.homebrew(entry.identifier.rsplit("/", 1)[-1])
    if entry.channel == "github_release":
        # `fileworks/immich-export`, falling back to the ledger's own fields so
        # an identifier that is only a repository name still resolves.
        owner, _, name = entry.identifier.rpartition("/")
        return readers.github_release(owner or product.owner, name or product.repository)
    # WinGet has no reader yet. `unverifiable` is the honest answer; inventing
    # one would be the exact failure this module exists to prevent.
    return None


def compare_ledger_to_channels(
    ledger: ReleaseLedger,
    readers: Readers,
    *,
    products: tuple[str, ...] | None = None,
) -> tuple[ChannelComparison, ...]:
    """Compare every applicable recorded version against the channel serving it.

    This control asks one question: is a recorded version still true? So a
    channel that records no version is skipped — `not_applicable` ones, the
    unversioned tap, and ones never verified. None of them makes a claim that
    could be wrong, and "this was never checked" is already `ledger.unverified`'s
    job. Two controls reporting the same condition is worse than one reporting
    it well.
    """
    comparisons: list[ChannelComparison] = []
    for product in ledger.products:
        if products is not None and product.name not in products:
            continue
        for entry in product.channels:
            if entry.state == "not_applicable" or entry.version in (None, "", UNVERSIONED):
                continue
            observed = _read(entry, product, readers)
            comparisons.append(
                ChannelComparison(
                    product=product.name,
                    channel=entry.channel,
                    identifier=entry.identifier,
                    recorded=entry.version,
                    observed=None if observed is None else normalise(observed),
                )
            )
    return tuple(comparisons)


def findings(
    comparisons: tuple[ChannelComparison, ...],
    classes: dict[str, RepoClass],
) -> tuple[Finding, ...]:
    """Turn comparisons into policy findings, one per product × channel.

    A product the caller has no class for is dropped rather than guessed at: a
    finding needs a class, and the ledger does not carry one.
    """
    results: list[Finding] = []
    for comparison in comparisons:
        repo_class = classes.get(comparison.product)
        if repo_class is None:
            continue
        results.append(
            Finding(
                repository=comparison.product,
                repo_class=repo_class,
                control_id=LEDGER_CHANNEL_CONTROL,
                outcome=comparison.outcome,
                detail=comparison.describe(),
                remediation=(
                    "re-verify the channel and record the observation with `ledger.record`"
                    if comparison.outcome == "stale"
                    else ""
                ),
            )
        )
    return tuple(results)
