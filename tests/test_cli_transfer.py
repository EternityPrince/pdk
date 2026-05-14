from __future__ import annotations

from tests.cli_base import CliTestCase
from tests.helpers import run_pdk


class CliTransferTest(CliTestCase):
    def test_export_includes_project_context_and_all_store(self):
        self.assertEqual(run_pdk(self.tmp_path, "project", "create", "alpha").returncode, 0)
        self.assertEqual(run_pdk(self.tmp_path, "project", "use", "alpha").returncode, 0)
        self.assertEqual(run_pdk(self.tmp_path, "add", "project-prompt", input="project body").returncode, 0)
        self.assertEqual(
            run_pdk(self.tmp_path, "feedback", "project-prompt", input="useful comment").returncode,
            0,
        )
        self.assertEqual(
            run_pdk(self.tmp_path, "note", "add", "--project", "alpha", input="project note").returncode,
            0,
        )
        self.assertEqual(run_pdk(self.tmp_path, "add", "general", "--no-project", input="general body").returncode, 0)

        active_export = run_pdk(self.tmp_path, "export")
        self.assertIn("# Prompt Deck Export", active_export.stdout)
        self.assertIn("### alpha", active_export.stdout)
        self.assertIn("### project-prompt", active_export.stdout)
        self.assertIn("useful comment", active_export.stdout)
        self.assertIn("project note", active_export.stdout)
        self.assertIn("## Usage Timeline", active_export.stdout)
        self.assertNotIn("### general", active_export.stdout)

        all_export = run_pdk(self.tmp_path, "export", "--all")
        self.assertIn("### project-prompt", all_export.stdout)
        self.assertIn("### general", all_export.stdout)

        positional_context = run_pdk(self.tmp_path, "context", "alpha")
        self.assertEqual(positional_context.returncode, 0)
        self.assertIn("### project-prompt", positional_context.stdout)
        self.assertNotIn("### general", positional_context.stdout)

    def test_import_json_round_trips_projects_prompts_notes_and_comments(self):
        source = self.tmp_path / "source"
        target = self.tmp_path / "target"
        self.assertEqual(run_pdk(source, "project", "create", "alpha", "Alpha work").returncode, 0)
        self.assertEqual(run_pdk(source, "project", "use", "alpha").returncode, 0)
        self.assertEqual(run_pdk(source, "add", "review", "--tag", "work", input="Review carefully.").returncode, 0)
        self.assertEqual(run_pdk(source, "feedback", "review", input="Useful.").returncode, 0)
        self.assertEqual(
            run_pdk(
                source,
                "note",
                "add",
                "--project",
                "alpha",
                "--title",
                "Facts",
                input="Project facts.",
            ).returncode,
            0,
        )

        exported = run_pdk(source, "export", "--format", "json")
        self.assertEqual(exported.returncode, 0)

        imported = run_pdk(target, "import", "--format", "json", input=exported.stdout)
        self.assertEqual(imported.returncode, 0)
        self.assertIn("Imported 1 project(s), 1 prompt(s), 1 note(s), 1 comment(s)", imported.stderr)

        project = run_pdk(target, "project", "show", "alpha")
        self.assertIn("description\tAlpha work", project.stdout)
        self.assertIn("review", project.stdout)
        shown = run_pdk(target, "show", "review")
        self.assertEqual(shown.stdout, "Review carefully.")
        self.assertIn("Useful.", run_pdk(target, "feedback", "review", "--list").stdout)
        self.assertIn("Facts", run_pdk(target, "note", "list", "--project", "alpha").stdout)

    def test_import_json_skips_existing_prompts_unless_replace_is_set(self):
        source = self.tmp_path / "source"
        target = self.tmp_path / "target"
        self.assertEqual(run_pdk(source, "add", "review", input="new").returncode, 0)
        exported = run_pdk(source, "export", "--format", "json")

        self.assertEqual(run_pdk(target, "add", "review", input="old").returncode, 0)
        skipped = run_pdk(target, "import", "--format", "json", input=exported.stdout)
        self.assertEqual(skipped.returncode, 0)
        self.assertIn("skipped 1", skipped.stderr)
        self.assertEqual(run_pdk(target, "show", "review").stdout, "old")

        replaced = run_pdk(target, "import", "--format", "json", "--replace", input=exported.stdout)
        self.assertEqual(replaced.returncode, 0)
        self.assertEqual(run_pdk(target, "show", "review").stdout, "new")

    def test_import_markdown_reads_prompt_deck_export(self):
        source = self.tmp_path / "source"
        target = self.tmp_path / "target"
        self.assertEqual(run_pdk(source, "add", "plain", "--tag", "draft", input="Plain body").returncode, 0)
        self.assertEqual(run_pdk(source, "note", "add", "Loose", input="Loose body").returncode, 0)
        exported = run_pdk(source, "export")
        self.assertEqual(exported.returncode, 0)

        imported = run_pdk(target, "import", "--format", "markdown", input=exported.stdout)
        self.assertEqual(imported.returncode, 0)
        self.assertIn("Imported 0 project(s), 1 prompt(s), 1 note(s), 0 comment(s)", imported.stderr)
        self.assertEqual(run_pdk(target, "show", "plain").stdout, "Plain body")
        self.assertIn("Loose", run_pdk(target, "note", "list", "--no-project").stdout)

    def test_import_dry_run_does_not_write(self):
        source = self.tmp_path / "source"
        target = self.tmp_path / "target"
        self.assertEqual(run_pdk(source, "add", "review", input="body").returncode, 0)
        exported = run_pdk(source, "export", "--format", "json")

        dry_run = run_pdk(target, "import", "--dry-run", "--format", "json", input=exported.stdout)
        self.assertEqual(dry_run.returncode, 0)
        self.assertIn("Would import 0 project(s), 1 prompt(s), 0 note(s), 0 comment(s)", dry_run.stderr)
        self.assertNotIn("review", run_pdk(target, "list").stdout)

