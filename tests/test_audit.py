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

    def test_every_repository_runs_its_class_gates(self) -> None:
        report = run(Path.cwd())

        gates = next(section for section in report.sections if section.name == "Quality gates")
        assert gates.findings == []

    def test_repository_files_and_documentation_are_clean(self) -> None:
        report = run(Path.cwd(), ledger_path=Path("maintenance/release-ledger.json"))

        for name in (
            "Repository files",
            "Documentation",
            "Renovate",
            "Package metadata",
        ):
            section = next(item for item in report.sections if item.name == name)
            assert section.findings == [], f"{name}: {section.findings}"

    def test_the_markdown_names_what_was_not_checked(self) -> None:
        markdown = run(Path.cwd()).markdown()

        assert "Not checked:" in markdown
        assert "## Controls" in markdown and "## Gates" in markdown

    def test_the_json_form_round_trips(self) -> None:
        payload = json.loads(json.dumps(run(Path.cwd()).to_dict()))

        assert payload.get("sections")
