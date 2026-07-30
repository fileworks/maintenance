"""Release integrity: what must be produced, in what order, and how to recover."""

from __future__ import annotations

from pathlib import Path

from maintenance.release import (
    ARTIFACTS,
    PLAYBOOKS,
    SEQUENCE,
    artifact_manifest,
    check_formula,
    check_metadata,
    check_sequence,
    diagnose,
    manifest_complete,
    playbook_markdown,
    read_formula,
    read_from_default_branch,
    sha256_file,
    verify_checksums,
)

CLI_FILES = [
    "unpacksort-1.0.0.tar.gz",
    "unpacksort-1.0.0-py3-none-any.whl",
    "SHA256SUMS",
]


class TestArtifactManifests:
    def test_a_complete_cli_release_satisfies_its_manifest(self) -> None:
        checks = artifact_manifest("python_cli", CLI_FILES)

        assert manifest_complete(checks)
        assert all(check.present for check in checks)

    def test_a_missing_wheel_blocks(self) -> None:
        checks = artifact_manifest("python_cli", ["unpacksort-1.0.0.tar.gz", "SHA256SUMS"])

        assert not manifest_complete(checks)
        assert [check.spec.name for check in checks if check.blocking] == ["wheel"]

    def test_the_desktop_class_requires_both_mac_architectures(self) -> None:
        names = [spec.name for spec in ARTIFACTS["desktop_application"]]

        assert "macos-arm64-dmg" in names and "macos-x64-dmg" in names

    def test_every_spec_says_how_it_is_verified(self) -> None:
        for specs in ARTIFACTS.values():
            assert all(spec.verification for spec in specs)

    def test_verification_is_more_than_existence(self) -> None:
        for specs in ARTIFACTS.values():
            for spec in specs:
                assert "exists" not in spec.verification.lower()


class TestChecksums:
    def test_a_matching_checksum_file_reports_nothing(self, tmp_path: Path) -> None:
        artifact = tmp_path / "thing.tar.gz"
        artifact.write_bytes(b"payload")
        sums = tmp_path / "SHA256SUMS"
        sums.write_text(f"{sha256_file(artifact)}  thing.tar.gz\n", encoding="utf-8")

        assert verify_checksums(tmp_path, sums) == []

    def test_a_changed_artifact_is_caught(self, tmp_path: Path) -> None:
        artifact = tmp_path / "thing.tar.gz"
        artifact.write_bytes(b"payload")
        sums = tmp_path / "SHA256SUMS"
        sums.write_text(f"{sha256_file(artifact)}  thing.tar.gz\n", encoding="utf-8")
        artifact.write_bytes(b"tampered")

        assert verify_checksums(tmp_path, sums) == ["thing.tar.gz: digest does not match"]

    def test_a_listed_but_absent_artifact_is_caught(self, tmp_path: Path) -> None:
        sums = tmp_path / "SHA256SUMS"
        sums.write_text(f"{'0' * 64}  gone.tar.gz\n", encoding="utf-8")

        assert verify_checksums(tmp_path, sums) == ["gone.tar.gz: listed but not present"]


class TestSequencing:
    def test_the_declared_order_has_a_reason_for_every_step(self) -> None:
        assert all(step.reason for step in SEQUENCE)

    def test_a_correctly_ordered_release_has_no_violations(self) -> None:
        states = {
            "github_release": "published",
            "pypi": "published",
            "homebrew": "published",
        }

        assert check_sequence(states) == []  # type: ignore[arg-type]

    def test_a_formula_published_before_pypi_is_a_violation(self) -> None:
        states = {
            "github_release": "published",
            "pypi": "absent",
            "homebrew": "published",
        }

        violations = check_sequence(states)  # type: ignore[arg-type]

        assert violations[0].channel == "homebrew"
        assert violations[0].missing_prerequisite == "pypi"

    def test_pypi_before_the_github_release_is_a_violation(self) -> None:
        states = {"github_release": "absent", "pypi": "published"}

        assert check_sequence(states)[0].channel == "pypi"  # type: ignore[arg-type]


class TestDiagnosis:
    APPLICABLE = ("github_release", "pypi", "homebrew")

    def test_a_healthy_release_needs_no_playbook(self) -> None:
        result = diagnose(
            {
                "github_release": "published",
                "pypi": "published",
                "homebrew": "published",
            },
            applicable=self.APPLICABLE,  # type: ignore[arg-type]
        )

        assert result.healthy is True
        assert result.playbook is None

    def test_a_mismatch_is_reported_ahead_of_anything_else(self) -> None:
        result = diagnose(
            {"github_release": "mismatched", "pypi": "absent", "homebrew": "absent"},
            applicable=self.APPLICABLE,  # type: ignore[arg-type]
        )

        assert result.playbook is not None
        assert result.playbook.key == "artifact_mismatch"

    def test_an_unverified_channel_never_reads_as_published(self) -> None:
        result = diagnose(
            {
                "github_release": "published",
                "pypi": "unverified",
                "homebrew": "published",
            },
            applicable=self.APPLICABLE,  # type: ignore[arg-type]
        )

        assert result.healthy is False
        assert result.playbook is not None and result.playbook.key == "unverified_channel"

    def test_a_stale_formula_routes_to_the_formula_playbook(self) -> None:
        result = diagnose(
            {"github_release": "published", "pypi": "published", "homebrew": "absent"},
            applicable=self.APPLICABLE,  # type: ignore[arg-type]
        )

        assert result.playbook is not None
        assert result.playbook.key == "partial_publish"

    def test_nothing_published_is_not_a_partial_publish(self) -> None:
        result = diagnose(
            {"github_release": "absent", "pypi": "absent", "homebrew": "absent"},
            applicable=self.APPLICABLE,  # type: ignore[arg-type]
        )

        assert result.playbook is None
        assert "nothing has been published" in result.detail


class TestPlaybooks:
    def test_every_playbook_has_steps(self) -> None:
        assert all(playbook.steps for playbook in PLAYBOOKS)

    def test_the_dangerous_ones_say_what_never_to_do(self) -> None:
        for key in (
            "partial_publish",
            "duplicate_trigger",
            "failed_formula_update",
            "artifact_mismatch",
        ):
            playbook = next(item for item in PLAYBOOKS if item.key == key)
            assert playbook.never, key

    def test_the_document_includes_the_publication_order(self) -> None:
        markdown = playbook_markdown()

        assert "Publication order" in markdown
        assert "`homebrew`" in markdown
        assert "Never." in markdown


class TestMetadata:
    def test_the_shipped_clis_declare_the_family_metadata(self) -> None:
        for repo in ("immich-export", "paperless-export", "unpacksort"):
            source = Path(repo, "pyproject.toml")
            if not source.is_file():
                continue
            assert check_metadata(repo, source.read_text(encoding="utf-8")) == []

    def test_a_missing_url_is_reported(self) -> None:
        issues = check_metadata(
            "demo",
            '[project]\nname = "demo"\nversion = "1"\n[project.scripts]\ndemo = "demo:app"\n',
        )

        assert any(issue.field == "urls.Homepage" for issue in issues)

    def test_a_console_script_named_after_something_else_is_reported(self) -> None:
        issues = check_metadata(
            "demo",
            '[project]\n[project.urls]\nHomepage = "x"\nIssues = "y"\nChangelog = "z"\n'
            '[project.scripts]\nsomething-else = "demo:app"\n',
        )

        assert any("console script" in issue.detail for issue in issues)


class TestFormulas:
    FORMULA = """
class Demo < Formula
  url "https://files.pythonhosted.org/packages/ab/demo-1.2.3.tar.gz"
  sha256 "%s"
  test do
    assert_match "demo", shell_output("#{bin}/demo --version")
  end
end
""" % ("a" * 64)

    def test_the_facts_are_read_without_executing_ruby(self) -> None:
        facts = read_formula(self.FORMULA, name="demo")

        assert facts.version == "1.2.3"
        assert facts.sha256 == "a" * 64
        assert facts.has_test_block is True

    def test_a_version_only_test_block_is_called_out(self) -> None:
        issues = check_formula(read_formula(self.FORMULA, name="demo"), "1.2.3")

        assert any("nothing more" in issue.detail for issue in issues)

    def test_a_stale_formula_version_is_caught(self) -> None:
        issues = check_formula(read_formula(self.FORMULA, name="demo"), "2.0.0")

        assert any("2.0.0" in issue.detail for issue in issues)

    def test_a_formula_without_a_digest_is_incomplete(self) -> None:
        facts = read_formula('class Demo < Formula\n  url "x"\nend\n', name="demo")

        assert facts.complete is False
        assert any("sha256" in issue.detail for issue in check_formula(facts, None))

    def test_the_default_branch_is_read_rather_than_the_checkout(self) -> None:
        calls: list[list[str]] = []

        def runner(arguments: list[str]) -> tuple[int, str]:
            calls.append(arguments)
            if arguments[0] == "show":
                return 0, "class Demo < Formula\nend\n"
            return 0, "feature-branch\n"

        read = read_from_default_branch(Path(), "Formula/demo.rb", runner=runner)

        assert read.revision == "origin/main"
        assert read.working_tree_diverged is True
        assert calls[0][1].startswith("origin/main:")

    def test_a_missing_default_branch_falls_back_and_says_so(self, tmp_path: Path) -> None:
        (tmp_path / "Formula").mkdir()
        (tmp_path / "Formula" / "demo.rb").write_text(
            "class Demo < Formula\nend\n", encoding="utf-8"
        )

        read = read_from_default_branch(
            tmp_path, "Formula/demo.rb", runner=lambda _arguments: (1, "")
        )

        assert read.revision == "working tree"
        assert read.working_tree_diverged is True
