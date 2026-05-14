from __future__ import annotations

from tests.cli_base import CliTestCase
from tests.helpers import editor_env, fake_path_env, run_pdk


class CliSessionTest(CliTestCase):
    def test_session_init_list_and_build_markdown_modules(self):
        project = self.tmp_path / "project"
        project.mkdir()

        initialized = run_pdk(self.tmp_path, "session", "init", cwd=project)
        self.assertEqual(initialized.returncode, 0)
        self.assertTrue((project / "context").is_dir())
        self.assertTrue((project / "context" / "base" / "profile.md").exists())
        self.assertTrue((project / "context" / "base" / "preferences.md").exists())
        self.assertTrue((project / "context" / "base" / "goals.md").exists())
        self.assertTrue((project / "context" / "food" / "nutrition.md").exists())
        self.assertTrue((project / "context" / "sport" / "training.md").exists())
        self.assertTrue((project / "context" / "study" / "learning.md").exists())
        self.assertTrue((project / "context" / "work" / "projects.md").exists())
        config = (project / ".pdk" / "context.toml").read_text(encoding="utf-8")
        self.assertIn("[context.default]", config)
        self.assertIn("[session]", config)
        self.assertIn('root = "context"', config)
        self.assertIn('file_detail = "full"', config)
        self.assertIn("compact = true", config)
        self.assertIn("budget = 16000", config)
        self.assertIn("[session.modules.base]", config)
        self.assertIn("[session.modules.food]", config)
        self.assertIn("[session.modules.sport]", config)
        self.assertIn("[session.modules.study]", config)
        self.assertIn("[session.modules.work]", config)

        (project / "context" / "base" / "profile.md").write_text("Base profile fact\n", encoding="utf-8")
        (project / "context" / "sport" / "training.md").write_text("Sport training fact\n", encoding="utf-8")
        (project / "context" / "food" / "nutrition.md").write_text("Food fact\n", encoding="utf-8")
        repeated = run_pdk(self.tmp_path, "session", "init", cwd=project)
        self.assertEqual(repeated.returncode, 0)
        self.assertEqual(
            (project / "context" / "base" / "profile.md").read_text(encoding="utf-8"),
            "Base profile fact\n",
        )

        listed = run_pdk(self.tmp_path, "session", "list", cwd=project)
        self.assertEqual(listed.returncode, 0)
        self.assertIn("base", listed.stdout)
        self.assertIn("sport", listed.stdout)
        self.assertIn("root\tcontext", listed.stdout)
        self.assertIn("file_detail\tfull", listed.stdout)
        self.assertIn("context/sport", listed.stdout)

        nested = project / "nested" / "deeper"
        nested.mkdir(parents=True)
        nested_listed = run_pdk(self.tmp_path, "session", "list", cwd=nested)
        self.assertEqual(nested_listed.returncode, 0)
        self.assertIn("base", nested_listed.stdout)
        self.assertIn("context/food", nested_listed.stdout)

        built = run_pdk(
            self.tmp_path,
            "session",
            "build",
            "sport",
            cwd=project,
        )
        self.assertEqual(built.returncode, 0)
        self.assertIn("# Prompt Deck Session", built.stdout)
        self.assertIn("Saved session state .pdk/session.md", built.stderr)
        self.assertNotIn("## Question", built.stdout)
        self.assertIn("- base", built.stdout)
        self.assertIn("- sport", built.stdout)
        self.assertIn("Base profile fact", built.stdout)
        self.assertIn("Sport training fact", built.stdout)
        self.assertNotIn("Food fact", built.stdout)

        shown_session = run_pdk(self.tmp_path, "session", "show", cwd=project)
        self.assertEqual(shown_session.returncode, 0)
        self.assertEqual(shown_session.stdout, built.stdout)

        self.assertEqual(
            run_pdk(
                self.tmp_path,
                "add",
                "workout",
                input="User request:\n{{request}}\n",
                cwd=project,
            ).returncode,
            0,
        )
        env = editor_env(
            self.tmp_path,
            [
                "\n".join(
                    [
                        "# pdk variable form",
                        "--- pdk begin {{request}} ---",
                        "Подбери 20-минутную тренировку после зала",
                        "--- pdk end {{request}} ---",
                        "",
                    ]
                )
            ],
        )
        prompt_with_context = run_pdk(self.tmp_path, "show", "workout", "--context", cwd=project, env=env)
        self.assertEqual(prompt_with_context.returncode, 0)
        self.assertIn("Подбери 20-минутную тренировку после зала", prompt_with_context.stdout)
        self.assertIn("# Prompt Deck Session", prompt_with_context.stdout)
        self.assertIn("Sport training fact", prompt_with_context.stdout)
        self.assertLess(
            prompt_with_context.stdout.index("Подбери 20-минутную тренировку после зала"),
            prompt_with_context.stdout.index("# Prompt Deck Session"),
        )

        output_path = project / "session.md"
        written = run_pdk(
            self.tmp_path,
            "session",
            "build",
            "sport",
            "--no-index",
            "--output",
            str(output_path),
            cwd=project,
        )
        self.assertEqual(written.returncode, 0)
        self.assertEqual(written.stdout, "")
        self.assertIn("Wrote session", written.stderr)
        self.assertIn("Sport training fact", output_path.read_text(encoding="utf-8"))

    def test_clip_prompt_with_session_context(self):
        project = self.tmp_path / "project"
        project.mkdir()
        self.assertEqual(run_pdk(self.tmp_path, "session", "init", cwd=project).returncode, 0)
        (project / "context" / "base" / "profile.md").write_text("Base profile fact\n", encoding="utf-8")
        (project / "context" / "sport" / "training.md").write_text("Sport training fact\n", encoding="utf-8")

        built = run_pdk(self.tmp_path, "session", "build", "sport", cwd=project)
        self.assertEqual(built.returncode, 0)
        self.assertIn("Saved session state", built.stderr)

        added = run_pdk(self.tmp_path, "add", "workout", input="Plan: {{request}}\n", cwd=project)
        self.assertEqual(added.returncode, 0)

        clip_file = self.tmp_path / "prompt-context-clipboard.txt"
        env = fake_path_env(
            self.tmp_path,
            {
                "pbcopy": '#!/bin/sh\ncat > "$PDK_CLIP_FILE"\n',
            },
            {"PDK_CLIP_FILE": str(clip_file)},
        )
        env.update(
            editor_env(
                self.tmp_path,
                [
                    "\n".join(
                        [
                            "# pdk variable form",
                            "--- pdk begin {{request}} ---",
                            "20-minute recovery workout",
                            "--- pdk end {{request}} ---",
                            "",
                        ]
                    )
                ],
            )
        )

        clipped = run_pdk(self.tmp_path, "clip", "workout", "--context", cwd=project, env=env)
        self.assertEqual(clipped.returncode, 0)
        self.assertEqual(clipped.stdout, "")
        self.assertIn("Copied workout", clipped.stderr)
        clipboard = clip_file.read_text(encoding="utf-8")
        self.assertIn("Plan: 20-minute recovery workout", clipboard)
        self.assertIn("# Prompt Deck Session", clipboard)
        self.assertIn("Sport training fact", clipboard)

    def test_clip_prompt_with_context_errors_without_session_state(self):
        project = self.tmp_path / "project"
        project.mkdir()
        self.assertEqual(run_pdk(self.tmp_path, "session", "init", cwd=project).returncode, 0)
        self.assertEqual(run_pdk(self.tmp_path, "add", "workout", input="Plan body", cwd=project).returncode, 0)

        clip_file = self.tmp_path / "missing-session-clipboard.txt"
        env = fake_path_env(
            self.tmp_path,
            {
                "pbcopy": '#!/bin/sh\ncat > "$PDK_CLIP_FILE"\n',
            },
            {"PDK_CLIP_FILE": str(clip_file)},
        )

        clipped = run_pdk(self.tmp_path, "clip", "workout", "--context", cwd=project, env=env)
        self.assertEqual(clipped.returncode, 1)
        self.assertEqual(clipped.stdout, "")
        self.assertIn("session state not found", clipped.stderr)
        self.assertFalse(clip_file.exists())

    def test_session_clear_removes_only_saved_state(self):
        project = self.tmp_path / "project"
        project.mkdir()
        self.assertEqual(run_pdk(self.tmp_path, "session", "init", cwd=project).returncode, 0)
        (project / "context" / "base" / "profile.md").write_text("Base profile fact\n", encoding="utf-8")
        (project / "context" / "sport" / "training.md").write_text("Sport training fact\n", encoding="utf-8")

        built = run_pdk(self.tmp_path, "session", "build", "sport", cwd=project)
        self.assertEqual(built.returncode, 0)
        self.assertTrue((project / ".pdk" / "session.md").exists())

        cleared = run_pdk(self.tmp_path, "session", "clear", cwd=project)
        self.assertEqual(cleared.returncode, 0)
        self.assertEqual(cleared.stdout, "")
        self.assertIn("Cleared session state .pdk/session.md", cleared.stderr)
        self.assertFalse((project / ".pdk" / "session.md").exists())
        self.assertTrue((project / ".pdk" / "context.toml").exists())
        self.assertTrue((project / "context" / "sport" / "training.md").exists())

        shown = run_pdk(self.tmp_path, "session", "show", cwd=project)
        self.assertEqual(shown.returncode, 1)
        self.assertIn("session state not found", shown.stderr)

        repeated = run_pdk(self.tmp_path, "session", "clear", cwd=project)
        self.assertEqual(repeated.returncode, 0)
        self.assertEqual(repeated.stdout, "")
        self.assertIn("No session state to clear", repeated.stderr)

    def test_session_init_custom_root_and_config_errors(self):
        project = self.tmp_path / "project"
        project.mkdir()

        initialized = run_pdk(self.tmp_path, "session", "init", "my-context", cwd=project)
        self.assertEqual(initialized.returncode, 0)
        self.assertTrue((project / "my-context" / "base" / "profile.md").exists())
        config = (project / ".pdk" / "context.toml").read_text(encoding="utf-8")
        self.assertIn('root = "my-context"', config)
        self.assertIn('dirs = ["my-context/base"]', config)

        legacy = self.tmp_path / "legacy"
        legacy.mkdir()
        self.assertEqual(run_pdk(self.tmp_path, "project", "init", cwd=legacy).returncode, 0)
        missing = run_pdk(self.tmp_path, "session", "list", cwd=legacy)
        self.assertEqual(missing.returncode, 1)
        self.assertIn(f"session config not found: {legacy.resolve() / '.pdk' / 'context.toml'}", missing.stderr)

        outside = self.tmp_path / "outside"
        outside.mkdir()
        no_project = run_pdk(self.tmp_path, "session", "list", cwd=outside)
        self.assertEqual(no_project.returncode, 1)
        self.assertIn("session requires a project; run `pdk session init` first", no_project.stderr)

    def test_session_build_default_all_dry_run_and_errors(self):
        project = self.tmp_path / "project"
        project.mkdir()
        self.assertEqual(run_pdk(self.tmp_path, "session", "init", cwd=project).returncode, 0)
        (project / "context" / "base" / "goals.md").write_text("Private base goal text.\n", encoding="utf-8")
        (project / "context" / "food" / "nutrition.md").write_text("Food module text.\n", encoding="utf-8")
        (project / "context" / "sport" / "training.md").write_text("Sport module text.\n", encoding="utf-8")
        (project / "context" / "study" / "learning.md").write_text("Study module text.\n", encoding="utf-8")
        (project / "context" / "work" / "projects.md").write_text("Work project text.\n", encoding="utf-8")

        default_build = run_pdk(self.tmp_path, "session", "build", cwd=project)
        self.assertEqual(default_build.returncode, 0)
        self.assertIn("- base", default_build.stdout)
        self.assertNotIn("- work", default_build.stdout)
        self.assertIn("Private base goal text.", default_build.stdout)
        self.assertNotIn("## Question", default_build.stdout)

        combined = run_pdk(self.tmp_path, "session", "build", "food", "sport", cwd=project)
        self.assertEqual(combined.returncode, 0)
        included_modules = [
            line.removeprefix("- ")
            for line in combined.stdout.splitlines()
            if line in ("- base", "- food", "- sport")
        ]
        self.assertEqual(included_modules, ["base", "food", "sport"])
        self.assertEqual(combined.stdout.count("- base"), 1)
        self.assertIn("Food module text.", combined.stdout)
        self.assertIn("Sport module text.", combined.stdout)

        all_build = run_pdk(self.tmp_path, "session", "build", "all", cwd=project)
        self.assertEqual(all_build.returncode, 0)
        for module in ("base", "food", "sport", "study", "work"):
            self.assertIn(f"- {module}", all_build.stdout)
        self.assertIn("Food module text.", all_build.stdout)
        self.assertIn("Sport module text.", all_build.stdout)
        self.assertIn("Study module text.", all_build.stdout)
        self.assertIn("Work project text.", all_build.stdout)

        all_dry_run = run_pdk(
            self.tmp_path,
            "session",
            "build",
            "all",
            "--dry-run",
            "--budget",
            "1",
            "--file-detail",
            "summary",
            cwd=project,
        )
        self.assertEqual(all_dry_run.returncode, 0)
        self.assertIn("session dry run", all_dry_run.stdout)
        self.assertIn("modules\tbase, food, sport, study, work", all_dry_run.stdout)
        self.assertIn("estimated_tokens", all_dry_run.stdout)
        self.assertIn("file_detail\tsummary", all_dry_run.stdout)
        self.assertIn("budget\t1", all_dry_run.stdout)
        self.assertIn("budget_status\tover", all_dry_run.stdout)
        self.assertNotIn("Private base goal text.", all_dry_run.stdout)
        self.assertNotIn("Work project text.", all_dry_run.stdout)

        conflict = run_pdk(self.tmp_path, "session", "build", "--dry-run", "--copy", cwd=project)
        self.assertEqual(conflict.returncode, 1)
        self.assertIn("--dry-run cannot be combined with --copy", conflict.stderr)

        missing = run_pdk(self.tmp_path, "session", "build", "missing", cwd=project)
        self.assertEqual(missing.returncode, 1)
        self.assertIn("unknown session module: missing", missing.stderr)

        removed_question_flag = run_pdk(self.tmp_path, "session", "build", "sport", "-q", "question", cwd=project)
        self.assertEqual(removed_question_flag.returncode, 2)
        self.assertIn("unrecognized arguments", removed_question_flag.stderr)

        empty = project / "empty"
        empty.mkdir()
        (project / ".pdk" / "context.toml").write_text(
            "\n".join(
                [
                    "[session]",
                    'root = "empty"',
                    'default_modules = ["empty"]',
                    'file_detail = "full"',
                    "compact = true",
                    "budget = 16000",
                    "redact = false",
                    "",
                    "[session.modules.empty]",
                    'description = "Empty module"',
                    'dirs = ["empty"]',
                ]
            ),
            encoding="utf-8",
        )
        no_files = run_pdk(self.tmp_path, "session", "build", cwd=project)
        self.assertEqual(no_files.returncode, 1)
        self.assertIn("no files found for session modules: empty", no_files.stderr)

    def test_session_build_copy_no_index_and_redact(self):
        project = self.tmp_path / "project"
        project.mkdir()
        self.assertEqual(run_pdk(self.tmp_path, "session", "init", cwd=project).returncode, 0)
        profile = project / "context" / "base" / "profile.md"
        training = project / "context" / "sport" / "training.md"
        profile.write_text("Base copy fact\nEmail user@example.com\n", encoding="utf-8")
        training.write_text("Old indexed sport fact\n", encoding="utf-8")

        self.assertEqual(run_pdk(self.tmp_path, "index", "context/base", "context/sport", cwd=project).returncode, 0)
        training.write_text("New unindexed sport fact\n", encoding="utf-8")

        cached = run_pdk(self.tmp_path, "session", "build", "sport", "--no-index", cwd=project)
        self.assertEqual(cached.returncode, 0)
        self.assertIn("Old indexed sport fact", cached.stdout)
        self.assertNotIn("New unindexed sport fact", cached.stdout)

        refreshed = run_pdk(self.tmp_path, "session", "build", "sport", cwd=project)
        self.assertEqual(refreshed.returncode, 0)
        self.assertIn("New unindexed sport fact", refreshed.stdout)

        clip_file = self.tmp_path / "session-clipboard.txt"
        env = fake_path_env(
            self.tmp_path,
            {
                "pbcopy": '#!/bin/sh\ncat > "$PDK_CLIP_FILE"\n',
            },
            {"PDK_CLIP_FILE": str(clip_file)},
        )
        copied = run_pdk(self.tmp_path, "session", "build", "sport", "--copy", env=env, cwd=project)
        self.assertEqual(copied.returncode, 0)
        self.assertEqual(copied.stdout, "")
        self.assertIn("Copied session to clipboard", copied.stderr)
        self.assertIn("# Prompt Deck Session", clip_file.read_text(encoding="utf-8"))

        plain = run_pdk(self.tmp_path, "session", "build", "sport", cwd=project)
        self.assertEqual(plain.returncode, 0)
        self.assertIn("user@example.com", plain.stdout)

        redacted = run_pdk(self.tmp_path, "session", "build", "sport", "--redact", cwd=project)
        self.assertEqual(redacted.returncode, 0)
        self.assertNotIn("user@example.com", redacted.stdout)
        self.assertIn("<EMAIL_1>", redacted.stdout)

    def test_audio_lists_models_and_appends_text_to_session_module(self):
        models = run_pdk(self.tmp_path, "audio", "--list-models")
        self.assertEqual(models.returncode, 0)
        self.assertIn("large-v3-turbo", models.stdout)
        self.assertIn("faster-whisper-large-v3-turbo", models.stdout)

        project = self.tmp_path / "project"
        project.mkdir()
        self.assertEqual(run_pdk(self.tmp_path, "session", "init", cwd=project).returncode, 0)

        captured = run_pdk(
            self.tmp_path,
            "audio",
            "--text",
            "Новая вводная для рабочего контекста.",
            "--module",
            "work",
            "--heading",
            "Inbox",
            "--no-timestamp",
            cwd=project,
        )

        self.assertEqual(captured.returncode, 0)
        self.assertEqual(captured.stdout, "Новая вводная для рабочего контекста.\n")
        self.assertIn("Appended audio note", captured.stderr)
        inbox = project / "context" / "work" / "inbox.md"
        self.assertIn("## Inbox", inbox.read_text(encoding="utf-8"))
        self.assertIn("- Новая вводная для рабочего контекста.", inbox.read_text(encoding="utf-8"))

    def test_audio_appends_text_to_explicit_markdown_file(self):
        target = self.tmp_path / "notes.md"
        target.write_text("# Notes\n\n## Facts\n\n- Existing\n\n## Later\n\n- Keep here\n", encoding="utf-8")

        captured = run_pdk(
            self.tmp_path,
            "audio",
            "--text",
            "Second fact",
            "--append",
            str(target),
            "--heading",
            "Facts",
            "--no-timestamp",
        )

        self.assertEqual(captured.returncode, 0)
        self.assertEqual(captured.stdout, "Second fact\n")
        self.assertIn("Appended audio note", captured.stderr)
        self.assertEqual(
            target.read_text(encoding="utf-8"),
            "# Notes\n\n## Facts\n\n- Existing\n\n- Second fact\n\n## Later\n\n- Keep here\n",
        )

