"""The publication gate holds a draft until the evidence is real."""

from __future__ import annotations

from maintenance.publication import (
    REQUIRED_PLATFORMS,
    ArtifactEvidence,
    PublicationGate,
    SmokeEvidence,
)


def _complete_smoke(platform: str, artifact: str) -> SmokeEvidence:
    return SmokeEvidence(
        platform,
        artifact,
        installed=True,
        launched=True,
        backend_healthy=True,
        branding_correct=True,
        paths_correct=True,
        state_preserved=True,
        second_launch_idempotent=True,
        upgrade_checked=True,
        no_console_window=True,
        observed_by="Niklas",
        observed_on="2026-08-01",
    )


def _full_gate(**overrides: object) -> PublicationGate:
    defaults: dict[str, object] = {
        "version": "1.0.7",
        "artifacts": [
            ArtifactEvidence("MediaSorter_aarch64.dmg", "unsigned", "unsigned"),
        ],
        "smoke": [_complete_smoke(platform, "MediaSorter.dmg") for platform in REQUIRED_PLATFORMS],
    }
    defaults.update(overrides)
    return PublicationGate(**defaults)  # type: ignore[arg-type]


class TestTheDefaultIsHeld:
    def test_an_empty_gate_never_publishes(self) -> None:
        gate = PublicationGate("1.0.7")
        assert not gate.publishable
        assert gate.blockers

    def test_a_missing_platform_is_named_rather_than_ignored(self) -> None:
        gate = _full_gate(smoke=[_complete_smoke("macos-arm64", "a.dmg")])
        assert not gate.publishable
        assert any("windows" in item for item in gate.blockers)
        assert any("macos-x86_64" in item for item in gate.blockers)

    def test_declaring_a_platform_unshipped_covers_it(self) -> None:
        gate = _full_gate(
            smoke=[_complete_smoke("macos-arm64", "a.dmg")],
            not_shipped=["macos-x86_64", "windows"],
        )
        assert gate.publishable

    def test_evidence_for_an_unshipped_platform_is_a_contradiction(self) -> None:
        gate = _full_gate(not_shipped=["windows"])
        assert not gate.publishable
        assert any("decide which is true" in item for item in gate.blockers)

    def test_describing_no_artifacts_blocks(self) -> None:
        gate = _full_gate(artifacts=[])
        assert not gate.publishable
        assert any("nothing can be published" in item for item in gate.blockers)


class TestSmokeEvidence:
    def test_every_unchecked_item_is_named(self) -> None:
        outstanding = SmokeEvidence("macos-arm64", "a.dmg").outstanding()
        assert "installed" in outstanding
        assert "backend healthy" in outstanding
        assert "who observed it" in outstanding

    def test_unattributed_evidence_does_not_count(self) -> None:
        evidence = _complete_smoke("macos-arm64", "a.dmg")
        anonymous = SmokeEvidence(**{**evidence.__dict__, "observed_by": ""})
        assert "who observed it" in anonymous.outstanding()

    def test_windows_must_show_no_console_window(self) -> None:
        evidence = _complete_smoke("windows", "MediaSorter.msi")
        without = SmokeEvidence(**{**evidence.__dict__, "no_console_window": False})
        assert "no console window" in without.outstanding()

    def test_macos_is_not_asked_about_a_console_window(self) -> None:
        evidence = _complete_smoke("macos-arm64", "a.dmg")
        macos = SmokeEvidence(**{**evidence.__dict__, "no_console_window": None})
        assert macos.outstanding() == []


class TestSigningClaims:
    def test_claiming_more_than_was_verified_is_fatal(self) -> None:
        gate = _full_gate(artifacts=[ArtifactEvidence("a.dmg", "signed-and-notarized", "unsigned")])
        assert not gate.publishable
        assert any("publish the truth" in item for item in gate.blockers)

    def test_claiming_less_than_was_verified_is_also_reported(self) -> None:
        # Harmless to users, but the release notes are still wrong.
        gate = _full_gate(artifacts=[ArtifactEvidence("a.dmg", "unsigned", "signed-and-notarized")])
        assert not gate.publishable

    def test_unsigned_is_publishable_when_documented_as_such(self) -> None:
        assert _full_gate().publishable

    def test_notarization_requires_each_part_to_be_verified(self) -> None:
        gate = _full_gate(
            artifacts=[
                ArtifactEvidence(
                    "a.dmg",
                    "signed-and-notarized",
                    "signed-and-notarized",
                    timestamped=True,
                    hardened_runtime=True,
                )
            ]
        )
        assert not gate.publishable
        assert any("stapled ticket" in item for item in gate.blockers)
        assert any("clean machine" in item for item in gate.blockers)

    def test_a_fully_verified_notarized_artifact_passes(self) -> None:
        gate = _full_gate(
            artifacts=[
                ArtifactEvidence(
                    "a.dmg",
                    "signed-and-notarized",
                    "signed-and-notarized",
                    timestamped=True,
                    hardened_runtime=True,
                    stapled=True,
                    trusted_on_clean_machine=True,
                )
            ]
        )
        assert gate.publishable

    def test_an_unknown_state_is_rejected_rather_than_guessed(self) -> None:
        gate = _full_gate(artifacts=[ArtifactEvidence("a.dmg", "probably fine", "ok")])
        assert not gate.publishable
        assert any("is not one of" in item for item in gate.blockers)


class TestChecklist:
    def test_a_held_draft_lists_what_is_missing(self) -> None:
        text = PublicationGate("1.0.7").checklist()
        assert "HELD" in text
        assert "## Outstanding" in text

    def test_a_ready_draft_says_so_and_shows_the_evidence(self) -> None:
        text = _full_gate().checklist()
        assert "READY" in text
        assert "MediaSorter_aarch64.dmg" in text
        assert "Niklas, 2026-08-01" in text

    def test_unshipped_platforms_appear_in_the_record(self) -> None:
        text = _full_gate(
            smoke=[_complete_smoke("macos-arm64", "a.dmg")],
            not_shipped=["macos-x86_64", "windows"],
        ).checklist()
        assert "## Not shipped in this release" in text
        assert "windows" in text
