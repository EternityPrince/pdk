from __future__ import annotations

import sqlite3

from pdk.tokens import count_tokens
from tests.cli_base import CliTestCase
from tests.helpers import editor_env, fake_path_env, run_pdk


class CliTest(CliTestCase):
    def test_add_show_and_list(self):
        added = run_pdk(
            self.tmp_path,
            "add",
            "review",
            input="Review this carefully.\nSecond line.",
        )
        self.assertEqual(added.returncode, 0)
        self.assertEqual(added.stdout, "")

        shown = run_pdk(self.tmp_path, "show", "review")
        self.assertEqual(shown.returncode, 0)
        self.assertEqual(shown.stdout, "Review this carefully.\nSecond line.")
        self.assertEqual(shown.stderr, f"tokens: {count_tokens(shown.stdout)}\n")

        listed = run_pdk(self.tmp_path, "list")
        self.assertEqual(listed.returncode, 0)
        self.assertIn("prompt", listed.stdout)
        self.assertIn("tokens", listed.stdout)
        self.assertIn("uses", listed.stdout)
        self.assertRegex(
            listed.stdout,
            r"review\s+\d+\s+1\s+0\s+0\s+\d{4}-\d{2}-\d{2} \d{2}:\d{2}\s+-",
        )
        self.assertNotIn("Review this carefully", listed.stdout)

    def test_clip_use_and_fzf_copy_to_clipboard(self):
        clip_file = self.tmp_path / "clipboard.txt"
        env = fake_path_env(
            self.tmp_path,
            {
                "pbcopy": '#!/bin/sh\ncat > "$PDK_CLIP_FILE"\n',
                "fzf": "#!/bin/sh\ncat >/dev/null\nprintf 'review\tunbound\t-\\n'\n",
            },
            {"PDK_CLIP_FILE": str(clip_file)},
        )
        self.assertEqual(run_pdk(self.tmp_path, "add", "review", input="Review body").returncode, 0)

        clipped = run_pdk(self.tmp_path, "clip", "review", env=env)
        self.assertEqual(clipped.returncode, 0)
        self.assertEqual(clipped.stdout, "")
        self.assertIn("Copied review", clipped.stderr)
        self.assertEqual(clip_file.read_text(encoding="utf-8"), "Review body")

        self.assertEqual(run_pdk(self.tmp_path, "use", "review", env=env).returncode, 0)
        self.assertEqual(clip_file.read_text(encoding="utf-8"), "Review body")

        browsed = run_pdk(self.tmp_path, "browse", "--fzf", env=env)
        self.assertEqual(browsed.returncode, 0)
        self.assertEqual(clip_file.read_text(encoding="utf-8"), "Review body")

    def test_index_files_entities_and_digest_use_global_file_database(self):
        docs = self.tmp_path / "docs"
        docs.mkdir()
        prompt_file = docs / "contract.md"
        prompt_file.write_text(
            "Договор с клиентом.\n\nФИО: Иван Петров\nТелефон +7 999 123-45-67\nОплата завтра.",
            encoding="utf-8",
        )

        indexed = run_pdk(self.tmp_path, "index", str(docs))
        self.assertEqual(indexed.returncode, 0)
        self.assertIn(str(prompt_file), indexed.stdout)
        self.assertIn("ru_full_name", indexed.stdout)
        self.assertIn("ru_phone", indexed.stdout)

        files = run_pdk(self.tmp_path, "files")
        self.assertEqual(files.returncode, 0)
        self.assertIn("contract.md", files.stdout)
        file_id = files.stdout.splitlines()[1].split("\t", 1)[0]

        shown = run_pdk(self.tmp_path, "file", "show", file_id)
        self.assertEqual(shown.returncode, 0)
        self.assertIn(f"path\t{prompt_file}", shown.stdout)
        self.assertIn("findings\t2", shown.stdout)

        hidden_entities = run_pdk(self.tmp_path, "file", "entities", file_id)
        self.assertEqual(hidden_entities.returncode, 0)
        self.assertIn("ru_full_name", hidden_entities.stdout)
        self.assertIn("[hidden]", hidden_entities.stdout)
        self.assertNotIn("Иван Петров", hidden_entities.stdout)

        digest = run_pdk(self.tmp_path, "digest", file_id)
        self.assertEqual(digest.returncode, 0)
        self.assertIn("mlx-community/gemma-3-text-4b-it-4bit", digest.stdout)

        shown_after_digest = run_pdk(self.tmp_path, "file", "show", file_id)
        self.assertIn("summary\t", shown_after_digest.stdout)

    def test_completion_scripts_include_shell_commands(self):
        bash = run_pdk(self.tmp_path, "completions", "bash")
        self.assertEqual(bash.returncode, 0)
        self.assertIn("complete -F _pdk_complete pdk", bash.stdout)
        self.assertIn("check", bash.stdout)
        self.assertIn("clip", bash.stdout)
        self.assertIn("privacy", bash.stdout)
        self.assertIn("redact", bash.stdout)
        self.assertIn("scan", bash.stdout)
        self.assertIn("tokens", bash.stdout)
        self.assertIn("use", bash.stdout)

        zsh = run_pdk(self.tmp_path, "completions", "zsh")
        self.assertEqual(zsh.returncode, 0)
        self.assertIn("#compdef pdk", zsh.stdout)

        fish = run_pdk(self.tmp_path, "completions", "fish")
        self.assertEqual(fish.returncode, 0)
        self.assertIn("complete -c pdk", fish.stdout)

    def test_list_orders_prompts_by_usage(self):
        self.assertEqual(run_pdk(self.tmp_path, "add", "rare", input="rare body").returncode, 0)
        self.assertEqual(run_pdk(self.tmp_path, "add", "popular", input="popular body").returncode, 0)
        self.assertEqual(run_pdk(self.tmp_path, "add", "unused", input="unused body").returncode, 0)

        self.assertEqual(run_pdk(self.tmp_path, "show", "rare").returncode, 0)
        self.assertEqual(run_pdk(self.tmp_path, "show", "popular").returncode, 0)
        self.assertEqual(run_pdk(self.tmp_path, "show", "popular").returncode, 0)

        listed = run_pdk(self.tmp_path, "list")
        names = [line.split()[0] for line in listed.stdout.splitlines()[1:]]
        self.assertEqual(names, ["popular", "rare", "unused"])

    def test_add_duplicate_errors_and_replace_updates(self):
        self.assertEqual(run_pdk(self.tmp_path, "add", "review", input="old").returncode, 0)

        duplicate = run_pdk(self.tmp_path, "add", "review", input="new")
        self.assertEqual(duplicate.returncode, 1)
        self.assertEqual(duplicate.stdout, "")
        self.assertIn("already exists", duplicate.stderr)

        replaced = run_pdk(self.tmp_path, "add", "review", "--replace", input="new")
        self.assertEqual(replaced.returncode, 0)

        shown = run_pdk(self.tmp_path, "show", "review")
        self.assertEqual(shown.stdout, "new")

    def test_edit_uses_editor_and_keeps_stdout_clean(self):
        self.assertEqual(run_pdk(self.tmp_path, "add", "editable", input="old").returncode, 0)
        env = editor_env(self.tmp_path, ["edited"])

        edited = run_pdk(self.tmp_path, "edit", "editable", env=env)
        self.assertEqual(edited.returncode, 0)
        self.assertEqual(edited.stdout, "")

        shown = run_pdk(self.tmp_path, "show", "editable")
        self.assertEqual(shown.stdout, "edited")

    def test_show_fills_variables_once_with_editor_and_stdout_only_result(self):
        body = "Hello {{name}}\n{{body}}\nAgain {{name}}"
        self.assertEqual(run_pdk(self.tmp_path, "add", "letter", input=body).returncode, 0)
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

        shown = run_pdk(self.tmp_path, "show", "letter", env=env)
        self.assertEqual(shown.returncode, 0)
        self.assertEqual(shown.stdout, "Hello Ada\nLine 1\n{{name}}\nLine 2\nAgain Ada")
        self.assertEqual(
            shown.stderr,
            f"tokens: template={count_tokens(body)} rendered={count_tokens(shown.stdout)}\n",
        )
        self.assertNotIn("Value for", shown.stdout)

    def test_remove_requires_yes_and_deletes_prompt(self):
        self.assertEqual(run_pdk(self.tmp_path, "add", "obsolete", input="bye").returncode, 0)

        refused = run_pdk(self.tmp_path, "rm", "obsolete")
        self.assertEqual(refused.returncode, 1)
        self.assertEqual(refused.stdout, "")

        removed = run_pdk(self.tmp_path, "rm", "obsolete", "--yes")
        self.assertEqual(removed.returncode, 0)
        self.assertEqual(removed.stdout, "")

        missing = run_pdk(self.tmp_path, "show", "obsolete")
        self.assertEqual(missing.returncode, 1)
        self.assertEqual(missing.stdout, "")

    def test_tags_can_be_added_removed_aggregated_and_used_for_search(self):
        added = run_pdk(
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

        tag_added = run_pdk(self.tmp_path, "tag", "add", "study-review", "exam")
        self.assertEqual(tag_added.returncode, 0)

        tags = run_pdk(self.tmp_path, "tags")
        self.assertIn("#study\t1", tags.stdout)
        self.assertIn("#exam\t1", tags.stdout)

        by_tag = run_pdk(self.tmp_path, "list", "--tag", "study")
        self.assertIn("study-review", by_tag.stdout)
        self.assertIn("#study", by_tag.stdout)
        self.assertNotIn("Review my essay", by_tag.stdout)

        found = run_pdk(self.tmp_path, "find", "essay", "--tag", "school")
        self.assertIn("study-review", found.stdout)

        tag_removed = run_pdk(self.tmp_path, "tag", "rm", "study-review", "exam")
        self.assertEqual(tag_removed.returncode, 0)
        tags_after = run_pdk(self.tmp_path, "tags")
        self.assertNotIn("#exam", tags_after.stdout)

    def test_stats_feedback_and_versions(self):
        self.assertEqual(run_pdk(self.tmp_path, "add", "coach", input="first").returncode, 0)
        self.assertEqual(
            run_pdk(self.tmp_path, "add", "coach", "--replace", input="second").returncode,
            0,
        )

        shown = run_pdk(self.tmp_path, "show", "coach")
        self.assertEqual(shown.stdout, "second")

        feedback = run_pdk(
            self.tmp_path,
            "feedback",
            "coach",
            input="It sounds too strict; I expected a warmer result.",
        )
        self.assertEqual(feedback.returncode, 0)
        self.assertEqual(feedback.stdout, "")

        listed_feedback = run_pdk(self.tmp_path, "feedback", "coach", "--list")
        self.assertIn("too strict", listed_feedback.stdout)

        stats = run_pdk(self.tmp_path, "stats", "coach")
        self.assertIn("coach\t1\t0\t1\t", stats.stdout)

        usage = run_pdk(self.tmp_path, "usage", "coach")
        self.assertIn("\tshow\tcoach\t-", usage.stdout)
        self.assertIn("\tfeedback\tcoach\t-", usage.stdout)

        versions = run_pdk(self.tmp_path, "versions", "coach")
        self.assertIn("\treplace\tfirst", versions.stdout)
        version_id = versions.stdout.split("\t", 1)[0]

        old = run_pdk(self.tmp_path, "versions", "coach", "--show", version_id)
        self.assertEqual(old.stdout, "first")

        refused = run_pdk(self.tmp_path, "versions", "coach", "--prune")
        self.assertEqual(refused.returncode, 1)

        pruned = run_pdk(self.tmp_path, "versions", "coach", "--prune", "--yes")
        self.assertEqual(pruned.returncode, 0)
        self.assertEqual(run_pdk(self.tmp_path, "versions", "coach").stdout, "")

    def test_stats_use_tracks_command_variants_and_errors(self):
        self.assertEqual(run_pdk(self.tmp_path, "add", "coach", input="body").returncode, 0)
        self.assertEqual(run_pdk(self.tmp_path, "show", "coach").returncode, 0)
        self.assertEqual(run_pdk(self.tmp_path, "show", "missing").returncode, 1)
        self.assertEqual(run_pdk(self.tmp_path, "project", "create", "alpha").returncode, 0)

        usage = run_pdk(self.tmp_path, "stats", "use")

        self.assertEqual(usage.returncode, 0)
        self.assertIn("variant\ttotal\tok\terrors\tlast used", usage.stdout)
        self.assertIn("add\t1\t1\t0\t", usage.stdout)
        self.assertIn("show\t2\t1\t1\t", usage.stdout)
        self.assertIn("project create\t1\t1\t0\t", usage.stdout)

    def test_stats_use_can_be_disabled_for_local_privacy(self):
        env = {"PDK_DISABLE_ANALYTICS": "1"}
        self.assertEqual(run_pdk(self.tmp_path, "add", "coach", input="body", env=env).returncode, 0)
        self.assertEqual(run_pdk(self.tmp_path, "show", "coach", env=env).returncode, 0)

        usage = run_pdk(self.tmp_path, "stats", "use", env=env)

        self.assertEqual(usage.returncode, 0)
        self.assertIn("variant\ttotal\tok\terrors\tlast used", usage.stdout)
        self.assertNotIn("add\t", usage.stdout)
        self.assertNotIn("show\t", usage.stdout)

    def test_stats_mem_reports_prompt_and_index_weight(self):
        source_file = self.tmp_path / "source.md"
        source_file.write_text("Indexed file body.", encoding="utf-8")
        self.assertEqual(run_pdk(self.tmp_path, "add", "coach", input="Prompt body").returncode, 0)
        self.assertEqual(run_pdk(self.tmp_path, "feedback", "coach", input="Comment body").returncode, 0)
        self.assertEqual(run_pdk(self.tmp_path, "index", str(source_file)).returncode, 0)

        memory = run_pdk(self.tmp_path, "stats", "mem")

        self.assertEqual(memory.returncode, 0)
        self.assertIn("component\titems\tbytes\thuman\ttokens\tdetail", memory.stdout)
        self.assertIn("prompts\t1\t11\t11 B\t", memory.stdout)
        self.assertIn("feedback\t1\t12\t12 B\t", memory.stdout)
        self.assertIn("indexed_files\t1\t18\t18 B\t", memory.stdout)
        self.assertIn("index_chunks\t1\t18\t18 B\t", memory.stdout)
        self.assertIn("prompt_db_file\t1\t", memory.stdout)
        self.assertIn("index_db_file\t1\t", memory.stdout)

    def test_hygiene_commands_find_rename_and_move_prompts(self):
        self.assertEqual(run_pdk(self.tmp_path, "add", "alpha", "--tag", "review", input="Same body").returncode, 0)
        self.assertEqual(run_pdk(self.tmp_path, "add", "beta", input="same   body").returncode, 0)
        self.assertEqual(run_pdk(self.tmp_path, "add", "fresh", input="Fresh body").returncode, 0)
        self.assertEqual(run_pdk(self.tmp_path, "feedback", "beta", input="Keep this note.").returncode, 0)
        self.assertEqual(run_pdk(self.tmp_path, "project", "create", "client").returncode, 0)

        moved = run_pdk(self.tmp_path, "move", "alpha", "--project", "client")
        self.assertEqual(moved.returncode, 0)
        self.assertIn("Moved 1 prompt(s) to project client", moved.stderr)
        self.assertIn("alpha", run_pdk(self.tmp_path, "list", "--project", "client").stdout)

        unbound = run_pdk(self.tmp_path, "move", "alpha", "--no-project")
        self.assertEqual(unbound.returncode, 0)
        self.assertIn("alpha", run_pdk(self.tmp_path, "list", "--no-project").stdout)

        renamed = run_pdk(self.tmp_path, "rename", "beta", "gamma")
        self.assertEqual(renamed.returncode, 0)
        self.assertIn("Renamed beta to gamma", renamed.stderr)
        self.assertIn("gamma", run_pdk(self.tmp_path, "list").stdout)
        self.assertEqual(run_pdk(self.tmp_path, "show", "beta").returncode, 1)
        self.assertIn("Keep this note.", run_pdk(self.tmp_path, "feedback", "gamma", "--list").stdout)

        db_path = self.tmp_path / "pdk-home" / "prompts.sqlite3"
        with sqlite3.connect(db_path) as conn:
            conn.execute("UPDATE prompts SET updated_at = ? WHERE name = ?", ("2000-01-01T00:00:00+00:00", "gamma"))

        duplicates = run_pdk(self.tmp_path, "duplicates")
        self.assertEqual(duplicates.returncode, 0)
        self.assertIn("group\tprompt\tproject\ttokens\tpreview", duplicates.stdout)
        self.assertIn("alpha", duplicates.stdout)
        self.assertIn("gamma", duplicates.stdout)

        stale = run_pdk(self.tmp_path, "stale", "--days", "1")
        self.assertEqual(stale.returncode, 0)
        self.assertIn("gamma\t2000-01-01 00:00\t-\t0\t-", stale.stdout)
        self.assertNotIn("fresh", stale.stdout)

        doctor = run_pdk(self.tmp_path, "doctor", "--days", "1")
        self.assertEqual(doctor.returncode, 0)
        self.assertIn("prompts\t3", doctor.stdout)
        self.assertIn("projects\t1", doctor.stdout)
        self.assertIn("duplicate_groups\t1", doctor.stdout)
        self.assertIn("stale\t1", doctor.stdout)
        self.assertIn("Recommendations", doctor.stdout)
        self.assertIn("2 prompts have no tags. Add tags with: pdk tag add NAME TAG", doctor.stdout)
        self.assertIn("1 duplicate prompt groups found. Inspect with: pdk duplicates", doctor.stdout)
        self.assertIn("1 prompts look stale. Inspect with: pdk stale --days DAYS", doctor.stdout)

    def test_doctor_recommends_digest_for_indexed_files_without_summaries(self):
        source_file = self.tmp_path / "source.md"
        source_file.write_text("Indexed file needs a summary.", encoding="utf-8")
        self.assertEqual(run_pdk(self.tmp_path, "index", str(source_file)).returncode, 0)

        doctor = run_pdk(self.tmp_path, "doctor")

        self.assertEqual(doctor.returncode, 0)
        self.assertIn("Recommendations", doctor.stdout)
        self.assertIn("1 indexed files have no summaries. Run: pdk digest", doctor.stdout)
