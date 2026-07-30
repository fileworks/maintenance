"""The audit must report what it checked, and never claim what it did not."""

from __future__ import annotations

import json
from pathlib import Path

from maintenance.audit import AuditReport, AuditSection, run


class TestSections:
    def test_an_unchecked_section_is_never_clean(self) -> None:
        section = AuditSection("Remote settings", [], checked=False, note="needs auth")

        assert section.clean is False
        assert "not checked" in section.summary()

    def test_a_section_with_findings_counts_them(self) -> None:
        assert "2 finding(s)" in AuditSection("Docs", ["a", "b"]).summary()

    def test_a_report_is_not_clean_while_anything_has_findings(self) -> None:
        report = AuditReport(sections=[AuditSection("A"), AuditSection("B", ["x"])])

        assert report.clean is False

    def test_an_unchecked_section_does_not_by_itself_make_a_report_dirty(self) -> None:
        report = AuditReport(
            sections=[
                AuditSection("A"),
                AuditSection("B", [], checked=False, note="needs auth"),
            ]
        )

        assert report.clean is True


class TestRun:
    def test_it_runs_against_the_real_workspace_without_credentials(self) -> None:
        report = run(Path.cwd(), ledger_path=Path("maintenance/release-ledger.json"))

        names = {section.name for section in report.sections}
        assert {
            "Repository files",
            "Documentation",
            "Quality gates",
            "Formulas",
        } <= names

    def test_remote_settings_are_unchecked_without_authentication(self) -> None:
        report = run(Path.cwd())

        remote = next(section for section in report.sections if section.name == "Remote settings")
        assert remote.checked is False
        assert "authenticated" in remote.note

    # These two replace assertions that the five real sibling repositories were
    # currently in policy. That is not a property of this module: it is the thing
    # the module exists to *report*, so a repository legitimately out of policy
    # turned into a failing unit test here. Worse, they passed only because this
    # workspace held unmerged work — the same files that made `security_policy`
    # read as satisfied while media-sorter's `main` had no SECURITY.md at all.
    #
    # What is worth locking is that the audit reports a problem rather than
    # skipping it, which a fixture can state exactly.
    def test_a_repository_missing_its_files_is_reported_not_skipped(self, tmp_path: Path) -> None:
        for name in ("media-sorter", "immich-export", "homebrew-tap"):
            (tmp_path / name).mkdir()

        report = run(tmp_path)

        files = next(item for item in report.sections if item.name == "Repository files")
        assert files.findings
        assert any("README" in finding for finding in files.findings)
        assert files.clean is False

    def test_a_repository_absent_from_the_workspace_is_not_called_compliant(
        self, tmp_path: Path
    ) -> None:
        # Nothing on disk must never read as a clean bill of health.
        report = run(tmp_path)

        gates = next(item for item in report.sections if item.name == "Quality gates")
        assert gates.clean is False or gates.checked is False

    def test_the_markdown_names_what_was_not_checked(self) -> None:
        markdown = run(Path.cwd()).markdown()

        assert "Not checked:" in markdown
        assert "## Controls" in markdown and "## Gates" in markdown

    def test_the_json_form_round_trips(self) -> None:
        payload = json.loads(json.dumps(run(Path.cwd()).to_dict()))

        assert payload.get("sections")
