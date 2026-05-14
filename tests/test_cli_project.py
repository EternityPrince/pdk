from __future__ import annotations

import sqlite3

from tests.cli_base import CliTestCase
from tests.helpers import editor_env, run_pdk


class CliProjectTest(CliTestCase):
    def test_project_init_creates_isolated_project_store(self):
        project = self.tmp_path / "project"
        project.mkdir()

        global_add = run_pdk(self.tmp_path, "--scope", "global", "add", "review", input="global")
        self.assertEqual(global_add.returncode, 0)

        initialized = run_pdk(self.tmp_path, "project", "init", cwd=project)
        self.assertEqual(initialized.returncode, 0)
        self.assertIn("Created local prompt store", initialized.stderr)
        self.assertIn("Created context config", initialized.stderr)
        self.assertIn("Created .pdkignore", initialized.stderr)
        self.assertIn("pdk context --profile default", initialized.stderr)
        self.assertTrue((project / ".pdk" / "prompts.sqlite3").exists())
        context_config = project / ".pdk" / "context.toml"
        pdkignore = project / ".pdkignore"
        self.assertTrue(context_config.exists())
        self.assertTrue(pdkignore.exists())
        self.assertIn("[context.default]", context_config.read_text(encoding="utf-8"))
        pdkignore_text = pdkignore.read_text(encoding="utf-8")
        self.assertIn(".env", pdkignore_text)
        self.assertIn("node_modules", pdkignore_text)

        project_add = run_pdk(self.tmp_path, "add", "review", input="project", cwd=project)
        self.assertEqual(project_add.returncode, 0)

        project_show = run_pdk(self.tmp_path, "show", "review", cwd=project)
        self.assertEqual(project_show.stdout, "project")

        global_show = run_pdk(self.tmp_path, "--scope", "global", "show", "review", cwd=project)
        self.assertEqual(global_show.stdout, "global")

    def test_project_init_does_not_overwrite_context_templates(self):
        project = self.tmp_path / "project"
        project.mkdir()

        initialized = run_pdk(self.tmp_path, "project", "init", cwd=project)
        self.assertEqual(initialized.returncode, 0)
        context_config = project / ".pdk" / "context.toml"
        pdkignore = project / ".pdkignore"
        context_config.write_text("[context.custom]\nbudget = 1\n", encoding="utf-8")
        pdkignore.write_text("custom-ignore\n", encoding="utf-8")

        repeated = run_pdk(self.tmp_path, "project", "init", cwd=project)
        self.assertEqual(repeated.returncode, 0)
        self.assertEqual(context_config.read_text(encoding="utf-8"), "[context.custom]\nbudget = 1\n")
        self.assertEqual(pdkignore.read_text(encoding="utf-8"), "custom-ignore\n")

    def test_project_scope_is_discovered_from_nested_directories(self):
        project = self.tmp_path / "project"
        nested = project / "src" / "pkg"
        nested.mkdir(parents=True)

        self.assertEqual(run_pdk(self.tmp_path, "project", "init", cwd=project).returncode, 0)
        self.assertEqual(run_pdk(self.tmp_path, "add", "local", input="inside", cwd=project).returncode, 0)

        shown = run_pdk(self.tmp_path, "show", "local", cwd=nested)
        self.assertEqual(shown.returncode, 0)
        self.assertEqual(shown.stdout, "inside")

        status = run_pdk(self.tmp_path, "project", "status", cwd=nested)
        self.assertIn("scope\tproject", status.stdout)
        self.assertIn(f"project\t{project.resolve()}", status.stdout)

    def test_project_scope_errors_when_not_initialized(self):
        missing = run_pdk(self.tmp_path, "--scope", "project", "list", cwd=self.tmp_path)
        self.assertEqual(missing.returncode, 1)
        self.assertIn("project is not initialized", missing.stderr)
        self.assertIn("pdk project init", missing.stderr)

    def test_old_database_migrates_prompts_as_unbound(self):
        home = self.tmp_path / "pdk-home"
        home.mkdir()
        db_path = home / "prompts.sqlite3"
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                CREATE TABLE prompts (
                    name TEXT PRIMARY KEY,
                    body TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                INSERT INTO prompts (name, body, created_at, updated_at)
                VALUES ('legacy', 'old body', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
                """
            )

        shown = run_pdk(self.tmp_path, "show", "legacy")
        self.assertEqual(shown.returncode, 0)
        self.assertEqual(shown.stdout, "old body")

        unbound = run_pdk(self.tmp_path, "list", "--no-project")
        self.assertIn("legacy", unbound.stdout)

    def test_named_project_active_override_and_unbound_prompts(self):
        self.assertEqual(
            run_pdk(self.tmp_path, "project", "create", "client", "--description", "Client work").returncode,
            0,
        )
        self.assertEqual(run_pdk(self.tmp_path, "project", "use", "client").returncode, 0)
        self.assertEqual(run_pdk(self.tmp_path, "add", "scoped", input="project body").returncode, 0)
        self.assertEqual(run_pdk(self.tmp_path, "add", "general", "--no-project", input="general body").returncode, 0)

        active_list = run_pdk(self.tmp_path, "list")
        self.assertIn("scoped", active_list.stdout)
        self.assertNotIn("general", active_list.stdout)

        unbound_list = run_pdk(self.tmp_path, "list", "--no-project")
        self.assertIn("general", unbound_list.stdout)
        self.assertNotIn("scoped", unbound_list.stdout)

        status = run_pdk(self.tmp_path, "project", "status")
        self.assertIn("active_project\tclient", status.stdout)

        self.assertEqual(run_pdk(self.tmp_path, "project", "clear").returncode, 0)
        all_prompts = run_pdk(self.tmp_path, "list")
        self.assertIn("scoped", all_prompts.stdout)
        self.assertIn("general", all_prompts.stdout)

    def test_project_assign_unassign(self):
        self.assertEqual(run_pdk(self.tmp_path, "project", "create", "alpha").returncode, 0)
        self.assertEqual(run_pdk(self.tmp_path, "add", "loose", input="body").returncode, 0)

        assigned = run_pdk(self.tmp_path, "project", "assign", "alpha", "loose")
        self.assertEqual(assigned.returncode, 0)
        self.assertIn("loose", run_pdk(self.tmp_path, "list", "--project", "alpha").stdout)
        self.assertNotIn("loose", run_pdk(self.tmp_path, "list", "--no-project").stdout)

        unassigned = run_pdk(self.tmp_path, "project", "unassign", "loose")
        self.assertEqual(unassigned.returncode, 0)
        self.assertIn("loose", run_pdk(self.tmp_path, "list", "--no-project").stdout)

    def test_project_rename_describe_and_edit(self):
        self.assertEqual(run_pdk(self.tmp_path, "project", "create", "alpha", "Alpha work").returncode, 0)
        self.assertIn("description\tAlpha work", run_pdk(self.tmp_path, "project", "show", "alpha").stdout)
        self.assertEqual(run_pdk(self.tmp_path, "project", "use", "alpha").returncode, 0)
        self.assertEqual(run_pdk(self.tmp_path, "add", "scoped", input="body").returncode, 0)

        renamed = run_pdk(self.tmp_path, "project", "rename", "alpha", "beta")
        self.assertEqual(renamed.returncode, 0)
        self.assertIn("scoped", run_pdk(self.tmp_path, "list", "--project", "beta").stdout)
        self.assertIn("active_project\tbeta", run_pdk(self.tmp_path, "project", "status").stdout)

        described = run_pdk(self.tmp_path, "project", "describe", "beta", "New", "description")
        self.assertEqual(described.returncode, 0)
        self.assertIn("description\tNew description", run_pdk(self.tmp_path, "project", "show", "beta").stdout)

        env = editor_env(self.tmp_path, ["Name: gamma\nDescription:\nEdited description"])
        edited = run_pdk(self.tmp_path, "project", "edit", "beta", env=env)
        self.assertEqual(edited.returncode, 0)
        shown = run_pdk(self.tmp_path, "project", "show", "gamma")
        self.assertIn("description\tEdited description", shown.stdout)

    def test_notes_default_unbound_and_versions(self):
        self.assertEqual(run_pdk(self.tmp_path, "project", "create", "alpha").returncode, 0)
        self.assertEqual(run_pdk(self.tmp_path, "project", "use", "alpha").returncode, 0)

        unbound = run_pdk(self.tmp_path, "note", "add", "--title", "Loose", input="unbound note")
        self.assertEqual(unbound.returncode, 0)
        project_note = run_pdk(
            self.tmp_path,
            "note",
            "add",
            "--title",
            "Project",
            "--project",
            "alpha",
            input="project note",
        )
        self.assertEqual(project_note.returncode, 0)

        unbound_notes = run_pdk(self.tmp_path, "note", "list", "--no-project")
        self.assertIn("Loose", unbound_notes.stdout)
        self.assertNotIn("Project", unbound_notes.stdout)

        project_notes = run_pdk(self.tmp_path, "note", "list", "--project", "alpha")
        self.assertIn("Project", project_notes.stdout)
        self.assertNotIn("Loose", project_notes.stdout)

        note_id = project_notes.stdout.splitlines()[1].split("\t", 1)[0]
        env = editor_env(self.tmp_path, ["project note edited"])
        edited = run_pdk(self.tmp_path, "note", "edit", note_id, env=env)
        self.assertEqual(edited.returncode, 0)

        versions = run_pdk(self.tmp_path, "note", "versions", note_id)
        self.assertIn("project note", versions.stdout)

    def test_note_edit_form_updates_title_and_body_version(self):
        self.assertEqual(run_pdk(self.tmp_path, "note", "add", "Old", input="old body").returncode, 0)
        note_id = run_pdk(self.tmp_path, "note", "list").stdout.splitlines()[1].split("\t", 1)[0]
        env = editor_env(self.tmp_path, ["Title: New\n--- body ---\nnew body"])

        edited = run_pdk(self.tmp_path, "note", "edit", note_id, env=env)
        self.assertEqual(edited.returncode, 0)

        shown = run_pdk(self.tmp_path, "note", "show", note_id)
        self.assertIn("title\tNew", shown.stdout)
        self.assertIn("new body", shown.stdout)
        versions = run_pdk(self.tmp_path, "note", "versions", note_id)
        self.assertIn("Old", versions.stdout)
        self.assertIn("old body", versions.stdout)

    def test_usage_project_filters(self):
        self.assertEqual(run_pdk(self.tmp_path, "project", "create", "alpha").returncode, 0)
        self.assertEqual(run_pdk(self.tmp_path, "project", "use", "alpha").returncode, 0)
        self.assertEqual(run_pdk(self.tmp_path, "add", "scoped", input="project body").returncode, 0)
        self.assertEqual(run_pdk(self.tmp_path, "add", "general", "--no-project", input="general body").returncode, 0)
        self.assertEqual(run_pdk(self.tmp_path, "show", "scoped").returncode, 0)
        self.assertEqual(run_pdk(self.tmp_path, "show", "general").returncode, 0)

        project_usage = run_pdk(self.tmp_path, "usage", "--project", "alpha")
        self.assertIn("scoped", project_usage.stdout)
        self.assertNotIn("general", project_usage.stdout)

        unbound_usage = run_pdk(self.tmp_path, "usage", "--no-project")
        self.assertIn("general", unbound_usage.stdout)
        self.assertNotIn("scoped", unbound_usage.stdout)

