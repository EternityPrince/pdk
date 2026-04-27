from __future__ import annotations

import os
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
    full_env["PMPT_HOME"] = str(tmp_path / "pmpt-home")
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
        self.assertIn("review\tReview this carefully. Second line.", listed.stdout)

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
        env = editor_env(self.tmp_path, ["Ada", "Line 1\n{{name}}\nLine 2"])

        shown = run_pmpt(self.tmp_path, "show", "letter", env=env)
        self.assertEqual(shown.returncode, 0)
        self.assertEqual(shown.stdout, "Hello Ada\nLine 1\n{{name}}\nLine 2\nAgain Ada")
        self.assertIn("Value for {{name}}", shown.stderr)
        self.assertIn("Value for {{body}}", shown.stderr)
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
        self.assertIn("study-review\tReview my essay", by_tag.stdout)
        self.assertIn("#study", by_tag.stdout)

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

        browsed = run_pmpt(self.tmp_path, "browse", "--query", "study", input="1\np\nb\nq\n")

        self.assertEqual(browsed.returncode, 0)
        self.assertIn("pmpt browser", browsed.stdout)
        self.assertIn("lesson #study", browsed.stdout)
        self.assertIn("Explain fractions clearly.", browsed.stdout)
        self.assertNotIn("work #job", browsed.stdout)

    def test_browse_can_change_tags_inside_prompt_view(self):
        self.assertEqual(
            run_pmpt(self.tmp_path, "add", "lesson", "--tag", "study", input="Body").returncode,
            0,
        )

        browsed = run_pmpt(self.tmp_path, "browse", input="1\nt\n+exam -study\nb\nq\n")
        self.assertEqual(browsed.returncode, 0)
        self.assertIn("Tags added: exam", browsed.stdout)
        self.assertIn("Tags removed: study", browsed.stdout)

        tags = run_pmpt(self.tmp_path, "tags")
        self.assertIn("#exam\t1", tags.stdout)
        self.assertNotIn("#study", tags.stdout)

    def test_project_init_creates_isolated_project_store(self):
        project = self.tmp_path / "project"
        project.mkdir()

        global_add = run_pmpt(self.tmp_path, "--scope", "global", "add", "review", input="global")
        self.assertEqual(global_add.returncode, 0)

        initialized = run_pmpt(self.tmp_path, "project", "init", cwd=project)
        self.assertEqual(initialized.returncode, 0)
        self.assertTrue((project / ".pmpt" / "prompts.sqlite3").exists())

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


if __name__ == "__main__":
    unittest.main()
