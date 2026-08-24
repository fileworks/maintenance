"""One machine-readable answer to "what is actually released, where?".

The product repositories publish to four channels, and every README that hard-codes a
version becomes wrong the next time one of them ships. So the versions live here
once, each with the target it was verified against and *when* — and anything
that was not verified is marked `unverified` rather than assumed current.

Nothing in this module contacts a network. It takes evidence a caller gathered
and turns it into a ledger, so the same code path works with authenticated `gh`
output and with nothing at all.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

LEDGER_VERSION = "2"

Channel = Literal["github_release", "pypi", "homebrew", "winget"]

#: Every channel, in the order the ledger table presents them. Named once so
#: the table and the type cannot drift apart.
CHANNELS: tuple[Channel, ...] = ("github_release", "pypi", "homebrew", "winget")
VerificationState = Literal["verified", "unverified", "not_applicable", "failed"]
HistoricalKind = Literal["tag_without_release", "empty_release"]
HistoricalWorkflowOutcome = Literal["success", "failure", "cancelled", "unobserved"]

#: How long a verification stays trustworthy before the ledger calls it stale.
FRESHNESS_DAYS = 30


@dataclass(frozen=True)
class HistoricalDisposition:
    """Evidence-backed handling for an unusual historical release object."""

    repository: str
    product: str
    kind: HistoricalKind
    identifier: str
    commit_sha: str | None
    release_id: int | None
    asset_count: int | None
    workflow_run_id: int | None
    workflow_outcome: HistoricalWorkflowOutcome
    intended_asset_state: str
    observed_at: str
    evidence: str
    disposition: str
    reason: str
    recovery_path: str

    def validate(self) -> tuple[str, ...]:
        """Return missing facts rather than allowing an unexplained exception."""
        required = {
            "repository": self.repository,
            "product": self.product,
            "kind": self.kind,
            "identifier": self.identifier,
            "workflow_outcome": self.workflow_outcome,
            "intended_asset_state": self.intended_asset_state,
            "observed_at": self.observed_at,
            "evidence": self.evidence,
            "disposition": self.disposition,
            "reason": self.reason,
            "recovery_path": self.recovery_path,
        }
        issues = [f"{key} is empty" for key, value in required.items() if not value]
        if self.kind not in ("tag_without_release", "empty_release"):
            issues.append(f"unsupported kind {self.kind!r}")
        if self.commit_sha is None or re.fullmatch(r"[0-9a-f]{40}", self.commit_sha) is None:
            issues.append("commit_sha is not a full lowercase Git SHA")
        try:
            observed = datetime.fromisoformat(self.observed_at)
        except ValueError:
            issues.append("observed_at is not ISO-8601")
        else:
            if observed.tzinfo is None:
                issues.append("observed_at has no timezone")
        if self.workflow_outcome == "unobserved":
            if self.workflow_run_id is not None:
                issues.append("unobserved workflow has a run ID")
        elif self.workflow_run_id is None or self.workflow_run_id <= 0:
            issues.append("observed workflow has no positive run ID")
        if self.kind == "tag_without_release":
            if self.release_id is not None:
                issues.append("tag_without_release has a release ID")
            if self.asset_count is not None:
                issues.append("tag_without_release has an asset count")
        if self.kind == "empty_release":
            if self.release_id is None or self.release_id <= 0:
                issues.append("empty_release has no positive release ID")
            if self.asset_count != 0:
                issues.append("empty_release asset_count is not zero")
        return tuple(issues)


@dataclass(frozen=True)
class ChannelEntry:
    """One product on one channel, and what was actually observed there."""

    channel: Channel
    identifier: str
    version: str | None = None
    state: VerificationState = "unverified"
    verified_at: str | None = None
    detail: str = ""

    def stale(self, *, today: datetime | None = None, days: int = FRESHNESS_DAYS) -> bool:
        """Whether this observation is old enough that it may no longer hold."""
        if self.state != "verified" or self.verified_at is None:
            return False
        try:
            observed = datetime.fromisoformat(self.verified_at)
        except ValueError:
            return True
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=UTC)
        now = today or datetime.now(UTC)
        return now - observed > timedelta(days=days)

    @property
    def displayable(self) -> str:
        if self.state == "not_applicable":
            return "—"
        if self.state != "verified" or not self.version:
            return "unverified"
        return self.version


@dataclass
class ProductEntry:
    """One repository and every channel it publishes to."""

    name: str
    repository: str
    owner: str
    channels: list[ChannelEntry] = field(default_factory=list)

    def channel(self, channel: Channel) -> ChannelEntry | None:
        return next((item for item in self.channels if item.channel == channel), None)

    @property
    def released_version(self) -> str | None:
        """The version the product is actually at, if anything verified says so."""
        verified = [item for item in self.channels if item.state == "verified" and item.version]
        if not verified:
            return None
        versions = {item.version for item in verified}
        # Disagreeing channels are a real condition, not a rounding error: the
        # ledger reports the disagreement rather than picking a winner.
        return versions.pop() if len(versions) == 1 else None

    @property
    def channels_disagree(self) -> bool:
        versions = {
            item.version for item in self.channels if item.state == "verified" and item.version
        }
        return len(versions) > 1


@dataclass
class ReleaseLedger:
    """The canonical status of every fileworks product."""

    products: list[ProductEntry] = field(default_factory=list)
    historical_dispositions: list[HistoricalDisposition] = field(default_factory=list)
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    ledger_version: str = LEDGER_VERSION

    def product(self, name: str) -> ProductEntry | None:
        return next((item for item in self.products if item.name == name), None)

    @property
    def unverified(self) -> tuple[tuple[str, Channel], ...]:
        return tuple(
            (product.name, entry.channel)
            for product in self.products
            for entry in product.channels
            if entry.state == "unverified"
        )

    def stale(self, *, today: datetime | None = None) -> tuple[tuple[str, Channel], ...]:
        return tuple(
            (product.name, entry.channel)
            for product in self.products
            for entry in product.channels
            if entry.stale(today=today)
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "ledger_version": self.ledger_version,
            "generated_at": self.generated_at,
            "products": [
                {
                    "name": product.name,
                    "repository": product.repository,
                    "owner": product.owner,
                    "released_version": product.released_version,
                    "channels_disagree": product.channels_disagree,
                    "channels": [asdict(entry) for entry in product.channels],
                }
                for product in self.products
            ],
            "historical_dispositions": [asdict(item) for item in self.historical_dispositions],
        }

    def write(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")
        return path

    @classmethod
    def read(cls, path: Path) -> ReleaseLedger:
        payload = json.loads(path.read_text(encoding="utf-8"))
        ledger_version = str(payload.get("ledger_version", "1"))
        if ledger_version not in {"1", LEDGER_VERSION}:
            raise ValueError(f"unsupported release ledger version {ledger_version}")
        ledger = cls(
            ledger_version=ledger_version,
            generated_at=payload.get("generated_at", ""),
            products=[],
            historical_dispositions=[
                HistoricalDisposition(
                    workflow_run_id=item.get("workflow_run_id"),
                    workflow_outcome=item.get("workflow_outcome", "unobserved"),
                    intended_asset_state=item.get("intended_asset_state", ""),
                    reason=item.get("reason", ""),
                    **{
                        key: value
                        for key, value in item.items()
                        if key
                        not in {
                            "workflow_run_id",
                            "workflow_outcome",
                            "intended_asset_state",
                            "reason",
                        }
                    },
                )
                for item in payload.get("historical_dispositions", [])
            ],
        )
        for item in payload.get("products", []):
            ledger.products.append(
                ProductEntry(
                    name=item["name"],
                    repository=item["repository"],
                    owner=item.get("owner", ""),
                    channels=[ChannelEntry(**entry) for entry in item.get("channels", [])],
                )
            )
        return ledger

    @property
    def historical_issues(self) -> tuple[str, ...]:
        """All malformed or unexplained historical records."""
        issues: list[str] = []
        seen: set[tuple[str, HistoricalKind, str]] = set()
        for item in self.historical_dispositions:
            issues.extend(
                f"{item.repository}/{item.identifier}: {issue}" for issue in item.validate()
            )
            key = (item.repository, item.kind, item.identifier)
            if key in seen:
                issues.append(
                    f"{item.repository}/{item.kind}/{item.identifier}: duplicate disposition"
                )
            seen.add(key)
        return tuple(issues)

    def markdown(self, *, today: datetime | None = None) -> str:
        """The human-readable view, generated from the same data."""
        lines = [
            "| Product | GitHub Release | PyPI | Homebrew | WinGet |",
            "|---|---|---|---|---|",
        ]
        for product in self.products:
            cells = [
                entry.displayable if (entry := product.channel(channel)) else "—"
                for channel in CHANNELS
            ]
            lines.append(f"| `{product.name}` | " + " | ".join(cells) + " |")
        stale = self.stale(today=today)
        if stale:
            lines.append("")
            lines.append(
                f"> {len(stale)} entr{'y' if len(stale) == 1 else 'ies'} "
                f"older than {FRESHNESS_DAYS} days — re-verify before quoting."
            )
        unverified = self.unverified
        if unverified:
            lines.append("")
            lines.append(
                f"> {len(unverified)} channel(s) could not be checked and are shown as "
                "`unverified` rather than assumed current."
            )
        return "\n".join(lines)


def scaffold(owner: str = "fileworks") -> ReleaseLedger:
    """An unverified ledger with every product and channel that should exist.

    Everything starts `unverified` on purpose: filling it in requires evidence,
    and a scaffold that pretended to be verified would be worse than none.
    """
    return ReleaseLedger(
        products=[
            ProductEntry(
                "media-sorter",
                "media-sorter",
                owner,
                [
                    ChannelEntry("github_release", "fileworks/media-sorter"),
                    ChannelEntry(
                        "pypi",
                        "—",
                        state="not_applicable",
                        detail="the desktop app ships installers, not a package",
                    ),
                    ChannelEntry("homebrew", "—", state="not_applicable"),
                    ChannelEntry("winget", "—", state="not_applicable"),
                ],
            ),
            ProductEntry(
                "immich-export",
                "immich-export",
                owner,
                [
                    ChannelEntry("github_release", "fileworks/immich-export"),
                    ChannelEntry("pypi", "immich-export"),
                    ChannelEntry("homebrew", "fileworks/tap/immich-export"),
                    ChannelEntry("winget", "—", state="not_applicable"),
                ],
            ),
            ProductEntry(
                "paperless-export",
                "paperless-export",
                owner,
                [
                    ChannelEntry("github_release", "fileworks/paperless-export"),
                    ChannelEntry("pypi", "paperless-export"),
                    ChannelEntry("homebrew", "fileworks/tap/paperless-export"),
                    ChannelEntry("winget", "—", state="not_applicable"),
                ],
            ),
            ProductEntry(
                "unpacksort",
                "unpacksort",
                owner,
                [
                    ChannelEntry("github_release", "fileworks/unpacksort"),
                    ChannelEntry("pypi", "unpacksort"),
                    ChannelEntry("homebrew", "fileworks/tap/unpacksort"),
                    ChannelEntry("winget", "fileworks.unpacksort"),
                ],
            ),
            ProductEntry(
                "homebrew-tap",
                "homebrew-tap",
                owner,
                [
                    ChannelEntry(
                        "github_release",
                        "—",
                        state="not_applicable",
                        detail="the tap is unversioned infrastructure",
                    ),
                    ChannelEntry("pypi", "—", state="not_applicable"),
                    ChannelEntry("homebrew", "fileworks/tap"),
                    ChannelEntry("winget", "—", state="not_applicable"),
                ],
            ),
        ]
    )


def record(
    ledger: ReleaseLedger,
    product: str,
    channel: Channel,
    *,
    version: str | None,
    state: VerificationState = "verified",
    detail: str = "",
    observed_at: datetime | None = None,
) -> ReleaseLedger:
    """Record one observation, replacing whatever was there before."""
    entry = ledger.product(product)
    if entry is None:
        raise KeyError(f"Unknown product: {product!r}")
    identifier = next(
        (item.identifier for item in entry.channels if item.channel == channel), product
    )
    entry.channels = [item for item in entry.channels if item.channel != channel] + [
        ChannelEntry(
            channel=channel,
            identifier=identifier,
            version=version,
            state=state,
            verified_at=(observed_at or datetime.now(UTC)).isoformat(),
            detail=detail,
        )
    ]
    entry.channels.sort(key=lambda item: item.channel)
    return ledger


def record_historical(ledger: ReleaseLedger, disposition: HistoricalDisposition) -> ReleaseLedger:
    """Add or replace one durable historical disposition."""
    if issues := disposition.validate():
        raise ValueError("; ".join(issues))
    ledger.historical_dispositions = [
        item
        for item in ledger.historical_dispositions
        if (item.repository, item.kind, item.identifier)
        != (disposition.repository, disposition.kind, disposition.identifier)
    ] + [disposition]
    ledger.historical_dispositions.sort(key=lambda item: (item.repository, item.identifier))
    return ledger
