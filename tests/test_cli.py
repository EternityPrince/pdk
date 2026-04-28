from __future__ import annotations

import os
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FAKE_EDITOR = r"""
from pathlib import Path
import os
import sys

path = Path(sys.argv[-1])
values = os.environ["PMPT_FAKE_EDITOR_VALUES"].split("\x1e")
state = Path(os.environ["PMPT_FAKE_EDITOR_STATE"])
index = int(state.read_text(encoding="utf-8")) if state.exists() else 0
path.write_text(values[index], encoding="utf-8")
state.write_text(str(index + 1), encoding="utf-8")
"""


def run_pmpt(
    tmp_path: Path,
    *args: str,
    input: str | None = None,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
):
    full_env = os.environ.copy()
    full_env["PDK_HOME"] = str(tmp_path / "pdk-home")
    full_env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + full_env.get("PYTHONPATH", "")
    if env:
        full_env.update(env)

    return subprocess.run(
        [sys.executable, "-m", "pmpt.cli", *args],
        input=input,
        text=True,
        capture_output=True,
        env=full_env,
        cwd=cwd,
        check=False,
    )


def editor_env(tmp_path: Path, values: list[str]) -> dict[str, str]:
    editor = tmp_path / "fake_editor.py"
    editor.write_text(FAKE_EDITOR, encoding="utf-8")
    state = tmp_path / "fake_editor_state.txt"
    return {
        "EDITOR": f"{sys.executable} {editor}",
        "PMPT_FAKE_EDITOR_VALUES": "\x1e".join(values),
        "PMPT_FAKE_EDITOR_STATE": str(state),
    }


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_help_uses_pdk_program_name(self):
        helped = run_pmpt(self.tmp_path, "--help")
        self.assertEqual(helped.returncode, 0)
        self.assertIn("usage: pdk", helped.stdout)
        self.assertIn("Prompt Deck", helped.stdout)
        self.assertIn("Use cases:", helped.stdout)
        self.assertIn("How scope and projects fit together:", helped.stdout)
        self.assertIn("Examples", helped.stdout)
        self.assertIn("pdk context client-a", helped.stdout)
        self.assertIn('pdk note add "Decision log"', helped.stdout)
        self.assertIn('pdk project create client-a "Client A launch"', helped.stdout)
        self.assertNotIn('pdk note add --title "Decision log" < notes.md', helped.stdout)

    def test_add_show_and_list(self):
        added = run_pmpt(
            self.tmp_path,
            "add",
            "review",
            input="Review this carefully.\nSecond line.",
        )
        self.assertEqual(added.returncode, 0)
        self.assertEqual(added.stdout, "")

        shown = run_pmpt(self.tmp_path, "show", "review")
        self.assertEqual(shown.returncode, 0)
        self.assertEqual(shown.stdout, "Review this carefully.\nSecond line.")
        self.assertEqual(shown.stderr, "")

        listed = run_pmpt(self.tmp_path, "list")
        self.assertEqual(listed.returncode, 0)
        self.assertIn("prompt", listed.stdout)
        self.assertIn("uses", listed.stdout)
        self.assertRegex(listed.stdout, r"review\s+1\s+0\s+0\s+\d{4}-\d{2}-\d{2} \d{2}:\d{2}\s+-")
        self.assertNotIn("Review this carefully", listed.stdout)

    def test_list_orders_prompts_by_usage(self):
        self.assertEqual(run_pmpt(self.tmp_path, "add", "rare", input="rare body").returncode, 0)
        self.assertEqual(run_pmpt(self.tmp_path, "add", "popular", input="popular body").returncode, 0)
        self.assertEqual(run_pmpt(self.tmp_path, "add", "unused", input="unused body").returncode, 0)

        self.assertEqual(run_pmpt(self.tmp_path, "show", "rare").returncode, 0)
        self.assertEqual(run_pmpt(self.tmp_path, "show", "popular").returncode, 0)
        self.assertEqual(run_pmpt(self.tmp_path, "show", "popular").returncode, 0)

        listed = run_pmpt(self.tmp_path, "list")
        names = [line.split()[0] for line in listed.stdout.splitlines()[1:]]
        self.assertEqual(names, ["popular", "rare", "unused"])

    def test_add_duplicate_errors_and_replace_updates(self):
        self.assertEqual(run_pmpt(self.tmp_path, "add", "review", input="old").returncode, 0)

        duplicate = run_pmpt(self.tmp_path, "add", "review", input="new")
        self.assertEqual(duplicate.returncode, 1)
        self.assertEqual(duplicate.stdout, "")
        self.assertIn("already exists", duplicate.stderr)

        replaced = run_pmpt(self.tmp_path, "add", "review", "--replace", input="new")
        self.assertEqual(replaced.returncode, 0)

        shown = run_pmpt(self.tmp_path, "show", "review")
        self.assertEqual(shown.stdout, "new")

    def test_edit_uses_editor_and_keeps_stdout_clean(self):
        self.assertEqual(run_pmpt(self.tmp_path, "add", "editable", input="old").returncode, 0)
        env = editor_env(self.tmp_path, ["edited"])

        edited = run_pmpt(self.tmp_path, "edit", "editable", env=env)
        self.assertEqual(edited.returncode, 0)
        self.assertEqual(edited.stdout, "")

        shown = run_pmpt(self.tmp_path, "show", "editable")
        self.assertEqual(shown.stdout, "edited")

    def test_show_fills_variables_once_with_editor_and_stdout_only_result(self):
        body = "Hello {{name}}\n{{body}}\nAgain {{name}}"
        self.assertEqual(run_pmpt(self.tmp_path, "add", "letter", input=body).returncode, 0)
        env = editor_env(
            self.tmp_path,
            [
                "\n".join(
                    [
                        "# pdk variable form",
                        "--- pdk begin {{name}} ---",
                        "Ada",
                        "--- pdk end {{name}} ---",
                        "--- pdk begin {{body}} ---",
                        "Line 1",
                        "{{name}}",
                        "Line 2",
                        "--- pdk end {{body}} ---",
                        "",
                    ]
                )
            ],
        )

        shown = run_pmpt(self.tmp_path, "show", "letter", env=env)
        self.assertEqual(shown.returncode, 0)
        self.assertEqual(shown.stdout, "Hello Ada\nLine 1\n{{name}}\nLine 2\nAgain Ada")
        self.assertEqual(shown.stderr, "")
        self.assertNotIn("Value for", shown.stdout)

    def test_remove_requires_yes_and_deletes_prompt(self):
        self.assertEqual(run_pmpt(self.tmp_path, "add", "obsolete", input="bye").returncode, 0)

        refused = run_pmpt(self.tmp_path, "rm", "obsolete")
        self.assertEqual(refused.returncode, 1)
        self.assertEqual(refused.stdout, "")

        removed = run_pmpt(self.tmp_path, "rm", "obsolete", "--yes")
        self.assertEqual(removed.returncode, 0)
        self.assertEqual(removed.stdout, "")

        missing = run_pmpt(self.tmp_path, "show", "obsolete")
        self.assertEqual(missing.returncode, 1)
        self.assertEqual(missing.stdout, "")

    def test_tags_can_be_added_removed_aggregated_and_used_for_search(self):
        added = run_pmpt(
            self.tmp_path,
            "add",
            "study-review",
            "--tag",
            "study,school",
            "--tag",
            "writing",
            input="Review my essay",
        )
        self.assertEqual(added.returncode, 0)

        tag_added = run_pmpt(self.tmp_path, "tag", "add", "study-review", "exam")
        self.assertEqual(tag_added.returncode, 0)

        tags = run_pmpt(self.tmp_path, "tags")
        self.assertIn("#study\t1", tags.stdout)
        self.assertIn("#exam\t1", tags.stdout)

        by_tag = run_pmpt(self.tmp_path, "list", "--tag", "study")
        self.assertIn("study-review", by_tag.stdout)
        self.assertIn("#study", by_tag.stdout)
        self.assertNotIn("Review my essay", by_tag.stdout)

        found = run_pmpt(self.tmp_path, "find", "essay", "--tag", "school")
        self.assertIn("study-review", found.stdout)

        tag_removed = run_pmpt(self.tmp_path, "tag", "rm", "study-review", "exam")
        self.assertEqual(tag_removed.returncode, 0)
        tags_after = run_pmpt(self.tmp_path, "tags")
        self.assertNotIn("#exam", tags_after.stdout)

    def test_stats_feedback_and_versions(self):
        self.assertEqual(run_pmpt(self.tmp_path, "add", "coach", input="first").returncode, 0)
        self.assertEqual(
            run_pmpt(self.tmp_path, "add", "coach", "--replace", input="second").returncode,
            0,
        )

        shown = run_pmpt(self.tmp_path, "show", "coach")
        self.assertEqual(shown.stdout, "second")

        feedback = run_pmpt(
            self.tmp_path,
            "feedback",
            "coach",
            input="It sounds too strict; I expected a warmer result.",
        )
        self.assertEqual(feedback.returncode, 0)
        self.assertEqual(feedback.stdout, "")

        listed_feedback = run_pmpt(self.tmp_path, "feedback", "coach", "--list")
        self.assertIn("too strict", listed_feedback.stdout)

        stats = run_pmpt(self.tmp_path, "stats", "coach")
        self.assertIn("coach\t1\t0\t1\t", stats.stdout)

        usage = run_pmpt(self.tmp_path, "usage", "coach")
        self.assertIn("\tshow\tcoach\t-", usage.stdout)
        self.assertIn("\tfeedback\tcoach\t-", usage.stdout)

        versions = run_pmpt(self.tmp_path, "versions", "coach")
        self.assertIn("\treplace\tfirst", versions.stdout)
        version_id = versions.stdout.split("\t", 1)[0]

        old = run_pmpt(self.tmp_path, "versions", "coach", "--show", version_id)
        self.assertEqual(old.stdout, "first")

        refused = run_pmpt(self.tmp_path, "versions", "coach", "--prune")
        self.assertEqual(refused.returncode, 1)

        pruned = run_pmpt(self.tmp_path, "versions", "coach", "--prune", "--yes")
        self.assertEqual(pruned.returncode, 0)
        self.assertEqual(run_pmpt(self.tmp_path, "versions", "coach").stdout, "")

    def test_browse_search_open_print_and_quit(self):
        self.assertEqual(
            run_pmpt(
                self.tmp_path,
                "add",
                "lesson",
                "--tag",
                "study",
                input="Explain fractions clearly.",
            ).returncode,
            0,
        )
        self.assertEqual(
            run_pmpt(self.tmp_path, "add", "work", "--tag", "job", input="Draft an update.").returncode,
            0,
        )

        browsed = run_pmpt(self.tmp_path, "browse", "--plain", "--query", "study", input="1\nprint\nb\nq\n")

        self.assertEqual(browsed.returncode, 0)
        self.assertIn("Prompt Deck browser", browsed.stdout)
        self.assertIn("lesson #study", browsed.stdout)
        self.assertIn("Explain fractions clearly.", browsed.stdout)
        self.assertNotIn("work #job", browsed.stdout)

    def test_browse_falls_back_to_plain_when_not_tty(self):
        self.assertEqual(run_pmpt(self.tmp_path, "add", "plain", input="Plain body").returncode, 0)

        browsed = run_pmpt(self.tmp_path, "browse", input="q\n")

        self.assertEqual(browsed.returncode, 0)
        self.assertIn("Prompt Deck browser", browsed.stdout)

    def test_browse_open_prompt_shows_full_body(self):
        long_body = "Start " + ("detail " * 40) + "full ending"
        self.assertEqual(run_pmpt(self.tmp_path, "add", "long", input=long_body).returncode, 0)

        browsed = run_pmpt(self.tmp_path, "browse", "--plain", input="1\nb\nq\n")

        self.assertEqual(browsed.returncode, 0)
        self.assertIn(long_body, browsed.stdout)
        self.assertIn("full ending", browsed.stdout)

    def test_browse_can_change_tags_inside_prompt_view(self):
        self.assertEqual(
            run_pmpt(self.tmp_path, "add", "lesson", "--tag", "study", input="Body").returncode,
            0,
        )

        browsed = run_pmpt(self.tmp_path, "browse", "--plain", input="1\nt\n+exam -study\nb\nq\n")
        self.assertEqual(browsed.returncode, 0)
        self.assertIn("Tags added: exam", browsed.stdout)
        self.assertIn("Tags removed: study", browsed.stdout)

        tags = run_pmpt(self.tmp_path, "tags")
        self.assertIn("#exam\t1", tags.stdout)
        self.assertNotIn("#study", tags.stdout)

    def test_browse_prompt_view_navigation_search_and_metadata(self):
        self.assertEqual(
            run_pmpt(self.tmp_path, "add", "alpha", "--tag", "first", input="Alpha body").returncode,
            0,
        )
        self.assertEqual(run_pmpt(self.tmp_path, "add", "beta", input="Beta body").returncode, 0)

        browsed = run_pmpt(self.tmp_path, "browse", "--plain", input="\nn\np\n/bet\nb\nq\n")

        self.assertEqual(browsed.returncode, 0)
        self.assertIn("alpha #first", browsed.stdout)
        self.assertIn("Beta body", browsed.stdout)
        self.assertIn("created:", browsed.stdout)
        self.assertIn("updated:", browsed.stdout)
        self.assertIn("project: unbound", browsed.stdout)
        self.assertIn("tags: first", browsed.stdout)

    def test_project_init_creates_isolated_project_store(self):
        project = self.tmp_path / "project"
        project.mkdir()

        global_add = run_pmpt(self.tmp_path, "--scope", "global", "add", "review", input="global")
        self.assertEqual(global_add.returncode, 0)

        initialized = run_pmpt(self.tmp_path, "project", "init", cwd=project)
        self.assertEqual(initialized.returncode, 0)
        self.assertTrue((project / ".pdk" / "prompts.sqlite3").exists())

        project_add = run_pmpt(self.tmp_path, "add", "review", input="project", cwd=project)
        self.assertEqual(project_add.returncode, 0)

        project_show = run_pmpt(self.tmp_path, "show", "review", cwd=project)
        self.assertEqual(project_show.stdout, "project")

        global_show = run_pmpt(self.tmp_path, "--scope", "global", "show", "review", cwd=project)
        self.assertEqual(global_show.stdout, "global")

    def test_project_scope_is_discovered_from_nested_directories(self):
        project = self.tmp_path / "project"
        nested = project / "src" / "pkg"
        nested.mkdir(parents=True)

        self.assertEqual(run_pmpt(self.tmp_path, "project", "init", cwd=project).returncode, 0)
        self.assertEqual(run_pmpt(self.tmp_path, "add", "local", input="inside", cwd=project).returncode, 0)

        shown = run_pmpt(self.tmp_path, "show", "local", cwd=nested)
        self.assertEqual(shown.returncode, 0)
        self.assertEqual(shown.stdout, "inside")

        status = run_pmpt(self.tmp_path, "project", "status", cwd=nested)
        self.assertIn("scope\tproject", status.stdout)
        self.assertIn(f"project\t{project.resolve()}", status.stdout)

    def test_project_scope_errors_when_not_initialized(self):
        missing = run_pmpt(self.tmp_path, "--scope", "project", "list", cwd=self.tmp_path)
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

        shown = run_pmpt(self.tmp_path, "show", "legacy")
        self.assertEqual(shown.returncode, 0)
        self.assertEqual(shown.stdout, "old body")

        unbound = run_pmpt(self.tmp_path, "list", "--no-project")
        self.assertIn("legacy", unbound.stdout)

    def test_named_project_active_override_and_unbound_prompts(self):
        self.assertEqual(
            run_pmpt(self.tmp_path, "project", "create", "client", "--description", "Client work").returncode,
            0,
        )
        self.assertEqual(run_pmpt(self.tmp_path, "project", "use", "client").returncode, 0)
        self.assertEqual(run_pmpt(self.tmp_path, "add", "scoped", input="project body").returncode, 0)
        self.assertEqual(run_pmpt(self.tmp_path, "add", "general", "--no-project", input="general body").returncode, 0)

        active_list = run_pmpt(self.tmp_path, "list")
        self.assertIn("scoped", active_list.stdout)
        self.assertNotIn("general", active_list.stdout)

        unbound_list = run_pmpt(self.tmp_path, "list", "--no-project")
        self.assertIn("general", unbound_list.stdout)
        self.assertNotIn("scoped", unbound_list.stdout)

        status = run_pmpt(self.tmp_path, "project", "status")
        self.assertIn("active_project\tclient", status.stdout)

        self.assertEqual(run_pmpt(self.tmp_path, "project", "clear").returncode, 0)
        all_prompts = run_pmpt(self.tmp_path, "list")
        self.assertIn("scoped", all_prompts.stdout)
        self.assertIn("general", all_prompts.stdout)

    def test_project_assign_unassign(self):
        self.assertEqual(run_pmpt(self.tmp_path, "project", "create", "alpha").returncode, 0)
        self.assertEqual(run_pmpt(self.tmp_path, "add", "loose", input="body").returncode, 0)

        assigned = run_pmpt(self.tmp_path, "project", "assign", "alpha", "loose")
        self.assertEqual(assigned.returncode, 0)
        self.assertIn("loose", run_pmpt(self.tmp_path, "list", "--project", "alpha").stdout)
        self.assertNotIn("loose", run_pmpt(self.tmp_path, "list", "--no-project").stdout)

        unassigned = run_pmpt(self.tmp_path, "project", "unassign", "loose")
        self.assertEqual(unassigned.returncode, 0)
        self.assertIn("loose", run_pmpt(self.tmp_path, "list", "--no-project").stdout)

    def test_project_rename_describe_and_edit(self):
        self.assertEqual(run_pmpt(self.tmp_path, "project", "create", "alpha", "Alpha work").returncode, 0)
        self.assertIn("description\tAlpha work", run_pmpt(self.tmp_path, "project", "show", "alpha").stdout)
        self.assertEqual(run_pmpt(self.tmp_path, "project", "use", "alpha").returncode, 0)
        self.assertEqual(run_pmpt(self.tmp_path, "add", "scoped", input="body").returncode, 0)

        renamed = run_pmpt(self.tmp_path, "project", "rename", "alpha", "beta")
        self.assertEqual(renamed.returncode, 0)
        self.assertIn("scoped", run_pmpt(self.tmp_path, "list", "--project", "beta").stdout)
        self.assertIn("active_project\tbeta", run_pmpt(self.tmp_path, "project", "status").stdout)

        described = run_pmpt(self.tmp_path, "project", "describe", "beta", "New", "description")
        self.assertEqual(described.returncode, 0)
        self.assertIn("description\tNew description", run_pmpt(self.tmp_path, "project", "show", "beta").stdout)

        env = editor_env(self.tmp_path, ["Name: gamma\nDescription:\nEdited description"])
        edited = run_pmpt(self.tmp_path, "project", "edit", "beta", env=env)
        self.assertEqual(edited.returncode, 0)
        shown = run_pmpt(self.tmp_path, "project", "show", "gamma")
        self.assertIn("description\tEdited description", shown.stdout)

    def test_notes_default_unbound_and_versions(self):
        self.assertEqual(run_pmpt(self.tmp_path, "project", "create", "alpha").returncode, 0)
        self.assertEqual(run_pmpt(self.tmp_path, "project", "use", "alpha").returncode, 0)

        unbound = run_pmpt(self.tmp_path, "note", "add", "--title", "Loose", input="unbound note")
        self.assertEqual(unbound.returncode, 0)
        project_note = run_pmpt(
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

        unbound_notes = run_pmpt(self.tmp_path, "note", "list", "--no-project")
        self.assertIn("Loose", unbound_notes.stdout)
        self.assertNotIn("Project", unbound_notes.stdout)

        project_notes = run_pmpt(self.tmp_path, "note", "list", "--project", "alpha")
        self.assertIn("Project", project_notes.stdout)
        self.assertNotIn("Loose", project_notes.stdout)

        note_id = project_notes.stdout.splitlines()[1].split("\t", 1)[0]
        env = editor_env(self.tmp_path, ["project note edited"])
        edited = run_pmpt(self.tmp_path, "note", "edit", note_id, env=env)
        self.assertEqual(edited.returncode, 0)

        versions = run_pmpt(self.tmp_path, "note", "versions", note_id)
        self.assertIn("project note", versions.stdout)

    def test_note_edit_form_updates_title_and_body_version(self):
        self.assertEqual(run_pmpt(self.tmp_path, "note", "add", "Old", input="old body").returncode, 0)
        note_id = run_pmpt(self.tmp_path, "note", "list").stdout.splitlines()[1].split("\t", 1)[0]
        env = editor_env(self.tmp_path, ["Title: New\n--- body ---\nnew body"])

        edited = run_pmpt(self.tmp_path, "note", "edit", note_id, env=env)
        self.assertEqual(edited.returncode, 0)

        shown = run_pmpt(self.tmp_path, "note", "show", note_id)
        self.assertIn("title\tNew", shown.stdout)
        self.assertIn("new body", shown.stdout)
        versions = run_pmpt(self.tmp_path, "note", "versions", note_id)
        self.assertIn("Old", versions.stdout)
        self.assertIn("old body", versions.stdout)

    def test_export_includes_project_context_and_all_store(self):
        self.assertEqual(run_pmpt(self.tmp_path, "project", "create", "alpha").returncode, 0)
        self.assertEqual(run_pmpt(self.tmp_path, "project", "use", "alpha").returncode, 0)
        self.assertEqual(run_pmpt(self.tmp_path, "add", "project-prompt", input="project body").returncode, 0)
        self.assertEqual(
            run_pmpt(self.tmp_path, "feedback", "project-prompt", input="useful comment").returncode,
            0,
        )
        self.assertEqual(run_pmpt(self.tmp_path, "note", "add", "--project", "alpha", input="project note").returncode, 0)
        self.assertEqual(run_pmpt(self.tmp_path, "add", "general", "--no-project", input="general body").returncode, 0)

        active_export = run_pmpt(self.tmp_path, "export")
        self.assertIn("# Prompt Deck Export", active_export.stdout)
        self.assertIn("### alpha", active_export.stdout)
        self.assertIn("### project-prompt", active_export.stdout)
        self.assertIn("useful comment", active_export.stdout)
        self.assertIn("project note", active_export.stdout)
        self.assertNotIn("### general", active_export.stdout)

        all_export = run_pmpt(self.tmp_path, "export", "--all")
        self.assertIn("### project-prompt", all_export.stdout)
        self.assertIn("### general", all_export.stdout)

        positional_context = run_pmpt(self.tmp_path, "context", "alpha")
        self.assertEqual(positional_context.returncode, 0)
        self.assertIn("### project-prompt", positional_context.stdout)
        self.assertNotIn("### general", positional_context.stdout)

    def test_usage_project_filters(self):
        self.assertEqual(run_pmpt(self.tmp_path, "project", "create", "alpha").returncode, 0)
        self.assertEqual(run_pmpt(self.tmp_path, "project", "use", "alpha").returncode, 0)
        self.assertEqual(run_pmpt(self.tmp_path, "add", "scoped", input="project body").returncode, 0)
        self.assertEqual(run_pmpt(self.tmp_path, "add", "general", "--no-project", input="general body").returncode, 0)
        self.assertEqual(run_pmpt(self.tmp_path, "show", "scoped").returncode, 0)
        self.assertEqual(run_pmpt(self.tmp_path, "show", "general").returncode, 0)

        project_usage = run_pmpt(self.tmp_path, "usage", "--project", "alpha")
        self.assertIn("scoped", project_usage.stdout)
        self.assertNotIn("general", project_usage.stdout)

        unbound_usage = run_pmpt(self.tmp_path, "usage", "--no-project")
        self.assertIn("general", unbound_usage.stdout)
        self.assertNotIn("scoped", unbound_usage.stdout)

    def test_context_alias_export_include_since_and_json(self):
        self.assertEqual(run_pmpt(self.tmp_path, "add", "prompt", input="first").returncode, 0)
        self.assertEqual(run_pmpt(self.tmp_path, "add", "prompt", "--replace", input="second").returncode, 0)
        self.assertEqual(run_pmpt(self.tmp_path, "feedback", "prompt", input="comment").returncode, 0)
        self.assertEqual(run_pmpt(self.tmp_path, "note", "add", "--title", "Fact", input="note body").returncode, 0)

        context = run_pmpt(self.tmp_path, "context", "--include", "notes,comments")
        self.assertEqual(context.returncode, 0)
        self.assertIn("## Index", context.stdout)
        self.assertIn("comment", context.stdout)
        self.assertIn("note body", context.stdout)
        self.assertNotIn("## Usage Timeline", context.stdout)
        self.assertNotIn("#### Versions", context.stdout)

        since = run_pmpt(self.tmp_path, "export", "--since", "2999-01-01")
        self.assertIn("### prompt", since.stdout)
        self.assertNotRegex(since.stdout, r"\[\d+\]: comment")

        positional_context = run_pmpt(self.tmp_path, "context", "missing")
        self.assertEqual(positional_context.returncode, 1)
        self.assertIn("project not found: missing", positional_context.stderr)

        exported_json = run_pmpt(self.tmp_path, "export", "--format", "json", "--include", "comments")
        self.assertEqual(exported_json.returncode, 0)
        payload = json.loads(exported_json.stdout)
        self.assertEqual(payload["index"]["prompts"], 1)
        self.assertEqual(payload["prompts"][0]["comments"][0]["body"], "comment")


if __name__ == "__main__":
    unittest.main()
