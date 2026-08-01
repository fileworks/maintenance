"""Whether automated MediaSorter evidence permits publication.

A green tag pipeline publishes without waiting for a human clean-host run.
Artifact identity and signing claims remain hard gates because automation can
prove them exactly. Physical-host observations remain typed, reviewable
follow-up evidence: useful for periodic confidence and installer changes, but
not a routine release blocker.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

#: Every platform recommended for periodic clean-host confidence evidence.
REQUIRED_PLATFORMS: tuple[str, ...] = ("macos-arm64", "macos-x86_64", "windows")

#: The signing states an artifact may be in. `unsigned` is a legitimate,
#: publishable state — it just has to be the documented one too.
SIGNING_STATES: tuple[str, ...] = ("unsigned", "signed", "signed-and-notarized")


@dataclass(frozen=True)
class ArtifactEvidence:
    """One artifact, what the release notes say about it, and what was checked.

    *documented_state* is the claim; *verified_state* is the observation. They
    are separate fields precisely so they can disagree and be caught.
    """

    filename: str
    documented_state: str
    verified_state: str
    #: Only meaningful for `signed-and-notarized`, and each must be observed
    #: rather than assumed — a stapled ticket is not implied by notarization.
    timestamped: bool = False
    hardened_runtime: bool = False
    stapled: bool = False
    trusted_on_clean_machine: bool = False

    def problems(self) -> list[str]:
        issues: list[str] = []
        for label, state in (
            ("documented", self.documented_state),
            ("verified", self.verified_state),
        ):
            if state not in SIGNING_STATES:
                issues.append(
                    f"{self.filename}: {label} state {state!r} is not one of "
                    + ", ".join(SIGNING_STATES)
                )
        if issues:
            return issues

        if self.documented_state != self.verified_state:
            issues.append(
                f"{self.filename}: documented as {self.documented_state!r} but "
                f"verified as {self.verified_state!r} — publish the truth or "
                f"re-verify, never the difference"
            )
            return issues

        if self.verified_state == "signed-and-notarized":
            for label, checked in (
                ("a trusted timestamp", self.timestamped),
                ("the hardened runtime", self.hardened_runtime),
                ("a stapled ticket", self.stapled),
                ("trust on a clean machine", self.trusted_on_clean_machine),
            ):
                if not checked:
                    issues.append(f"{self.filename}: {label} was not verified")
        return issues


@dataclass(frozen=True)
class SmokeEvidence:
    """One optional clean-machine run: what was installed and observed.

    `observed_by` and `observed_on` are required for the same reason an
    exception needs an owner and an expiry — evidence nobody signed is a note,
    not a record, and six months later nobody can tell which machine it was.
    """

    platform: str
    artifact: str
    installed: bool = False
    launched: bool = False
    backend_healthy: bool = False
    branding_correct: bool = False
    paths_correct: bool = False
    state_preserved: bool = False
    second_launch_idempotent: bool = False
    upgrade_checked: bool = False
    #: Windows only: the installer must not leave a console window behind it.
    no_console_window: bool | None = None
    observed_by: str = ""
    observed_on: str = ""

    def outstanding(self) -> list[str]:
        missing = [
            label
            for label, checked in (
                ("installed", self.installed),
                ("launched", self.launched),
                ("backend healthy", self.backend_healthy),
                ("branding correct", self.branding_correct),
                ("paths correct", self.paths_correct),
                ("state preserved", self.state_preserved),
                ("second launch idempotent", self.second_launch_idempotent),
                ("upgrade checked", self.upgrade_checked),
            )
            if not checked
        ]
        if self.platform.startswith("windows") and not self.no_console_window:
            missing.append("no console window")
        if not self.observed_by:
            missing.append("who observed it")
        if not self.observed_on:
            missing.append("when it was observed")
        return missing


@dataclass(frozen=True)
class PublicationGate:
    """The automated publication decision and post-release advisories."""

    version: str
    artifacts: Sequence[ArtifactEvidence] = field(default_factory=tuple)
    smoke: Sequence[SmokeEvidence] = field(default_factory=tuple)
    #: Platforms deliberately not shipped in this release. Naming one is a
    #: decision that appears in the checklist; leaving one out silently is not.
    not_shipped: Sequence[str] = field(default_factory=tuple)

    @property
    def blockers(self) -> list[str]:
        found: list[str] = []

        for artifact in self.artifacts:
            found.extend(artifact.problems())

        if not self.artifacts:
            found.append("no artifacts were described, so nothing can be published")
        return found

    @property
    def advisories(self) -> list[str]:
        """Non-blocking physical-host evidence still worth collecting."""
        found: list[str] = []
        covered = {evidence.platform for evidence in self.smoke}
        for platform in REQUIRED_PLATFORMS:
            if platform in covered or platform in self.not_shipped:
                continue
            found.append(f"{platform}: no clean-machine evidence recorded")

        for platform in self.not_shipped:
            if platform not in REQUIRED_PLATFORMS:
                found.append(f"{platform!r} is not a platform this release covers")

        for evidence in self.smoke:
            if evidence.platform in self.not_shipped:
                found.append(
                    f"{evidence.platform}: recorded as not shipped, but there is "
                    f"evidence for it — reconcile the record"
                )
            for item in evidence.outstanding():
                found.append(f"{evidence.platform} ({evidence.artifact}): {item}")
        return found

    @property
    def publishable(self) -> bool:
        return not self.blockers

    def checklist(self) -> str:
        """Render the hard gate and optional post-release evidence."""
        verdict = (
            "READY — every check is accounted for."
            if self.publishable
            else f"HELD — {len(self.blockers)} item(s) outstanding."
        )
        lines = [f"# MediaSorter {self.version} — publication gate", "", verdict, ""]

        if self.blockers:
            lines += ["## Outstanding", ""]
            lines += [f"- {item}" for item in self.blockers]
            lines.append("")

        if self.advisories:
            lines += ["## Post-release follow-up", ""]
            lines += [f"- {item}" for item in self.advisories]
            lines.append("")

        lines += ["## Artifacts", ""]
        if self.artifacts:
            lines += ["| Artifact | Documented | Verified |", "|---|---|---|"]
            lines += [
                f"| `{item.filename}` | {item.documented_state} | {item.verified_state} |"
                for item in self.artifacts
            ]
        else:
            lines.append("None described.")
        lines.append("")

        lines += ["## Clean-machine runs", ""]
        if self.smoke:
            for evidence in self.smoke:
                missing = evidence.outstanding()
                state = "complete" if not missing else f"{len(missing)} outstanding"
                who = evidence.observed_by or "unattributed"
                when = evidence.observed_on or "undated"
                lines.append(
                    f"- **{evidence.platform}** (`{evidence.artifact}`) — {state}; {who}, {when}"
                )
        else:
            lines.append("None recorded.")
        lines.append("")

        if self.not_shipped:
            lines += [
                "## Not shipped in this release",
                "",
                *[f"- {platform}" for platform in self.not_shipped],
                "",
            ]
        return "\n".join(lines)
