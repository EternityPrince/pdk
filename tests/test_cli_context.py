from __future__ import annotations

import json

from tests.cli_base import CliTestCase
from tests.helpers import fake_path_env, run_pdk


class CliContextTest(CliTestCase):
    def test_context_can_include_indexed_file_sources(self):
        docs = self.tmp_path / "docs"
        docs.mkdir()
        source_file = docs / "context.txt"
        source_file.write_text(
            "Email ivan@example.com\n"
            + "Alpha context sentence. " * 100
            + "TAIL FULL TEXT ONLY.",
            encoding="utf-8",
        )

        indexed = run_pdk(self.tmp_path, "index", str(source_file))
        self.assertEqual(indexed.returncode, 0)
        files = run_pdk(self.tmp_path, "files")
        file_id = files.stdout.splitlines()[1].split("\t", 1)[0]

        by_id = run_pdk(self.tmp_path, "context", "--file", file_id)
        self.assertEqual(by_id.returncode, 0)
        self.assertIn("## Files", by_id.stdout)
        self.assertIn(f"### {source_file}", by_id.stdout)
        self.assertIn("#### Summary", by_id.stdout)
        self.assertNotIn("TAIL FULL TEXT ONLY", by_id.stdout)

        by_path = run_pdk(self.tmp_path, "context", "--file", str(source_file), "--format", "json")
        self.assertEqual(by_path.returncode, 0)
        by_path_payload = json.loads(by_path.stdout)
        self.assertEqual(by_path_payload["files"][0]["path"], str(source_file))
        self.assertEqual(by_path_payload["files"][0]["id"], int(file_id))
        self.assertIsNone(by_path_payload["files"][0]["text"])

        shown_after_fallback = run_pdk(self.tmp_path, "file", "show", file_id)
        self.assertNotIn("summary\t", shown_after_fallback.stdout)

        full = run_pdk(self.tmp_path, "context", "--file", file_id, "--file-detail", "full")
        self.assertEqual(full.returncode, 0)
        self.assertIn("#### Full Text", full.stdout)
        self.assertIn("TAIL FULL TEXT ONLY", full.stdout)

        redacted = run_pdk(self.tmp_path, "context", "--file", file_id, "--file-detail", "full", "--redact")
        self.assertEqual(redacted.returncode, 0)
        self.assertNotIn("ivan@example.com", redacted.stdout)
        self.assertIn("<EMAIL_1>", redacted.stdout)

        missing = run_pdk(self.tmp_path, "context", "--file", str(docs / "missing.txt"))
        self.assertEqual(missing.returncode, 1)
        self.assertIn("indexed file not found:", missing.stderr)
        self.assertIn("run `pdk index TARGET` first", missing.stderr)

        exported = run_pdk(self.tmp_path, "export")
        self.assertEqual(exported.returncode, 0)
        self.assertNotIn("## Files", exported.stdout)

    def test_context_directory_selects_indexed_files_with_filters(self):
        docs = self.tmp_path / "docs"
        docs.mkdir()
        keep = docs / "keep.md"
        keep.write_text("Keep directory context", encoding="utf-8")
        ignored = docs / "ignored.md"
        ignored.write_text("Ignored by pdkignore", encoding="utf-8")
        excluded = docs / "excluded.txt"
        excluded.write_text("Excluded by CLI", encoding="utf-8")
        outside = self.tmp_path / "outside.md"
        outside.write_text("Outside explicit file", encoding="utf-8")
        env_file = self.tmp_path / ".env"
        env_file.write_text("TOKEN=secret", encoding="utf-8")
        node_file = self.tmp_path / "node_modules" / "pkg.txt"
        node_file.parent.mkdir()
        node_file.write_text("Node module text", encoding="utf-8")
        pycache_file = self.tmp_path / "__pycache__" / "cache.py"
        pycache_file.parent.mkdir()
        pycache_file.write_text("Cached python text", encoding="utf-8")
        (self.tmp_path / ".pdkignore").write_text("ignored.md\n", encoding="utf-8")

        indexed = run_pdk(
            self.tmp_path,
            "index",
            str(docs),
            str(outside),
            str(env_file),
            str(node_file),
            str(pycache_file),
        )
        self.assertEqual(indexed.returncode, 0)

        dir_only = run_pdk(self.tmp_path, "context", "--dir", str(docs), cwd=self.tmp_path)
        self.assertEqual(dir_only.returncode, 0)
        self.assertIn(str(keep), dir_only.stdout)
        self.assertNotIn(str(outside), dir_only.stdout)

        selected = run_pdk(
            self.tmp_path,
            "context",
            "--dir",
            str(docs),
            "--file",
            str(outside),
            "--exclude",
            "excluded.txt",
            cwd=self.tmp_path,
        )
        self.assertEqual(selected.returncode, 0)
        self.assertIn("## Files", selected.stdout)
        self.assertIn(str(keep), selected.stdout)
        self.assertIn(str(outside), selected.stdout)
        self.assertNotIn(str(ignored), selected.stdout)
        self.assertNotIn(str(excluded), selected.stdout)

        root_selected = run_pdk(self.tmp_path, "context", "--dir", str(self.tmp_path), cwd=self.tmp_path)
        self.assertEqual(root_selected.returncode, 0)
        self.assertIn(str(keep), root_selected.stdout)
        self.assertNotIn(str(env_file), root_selected.stdout)
        self.assertNotIn(str(node_file), root_selected.stdout)
        self.assertNotIn(str(pycache_file), root_selected.stdout)

        explicit_builtin = run_pdk(
            self.tmp_path,
            "context",
            "--dir",
            str(self.tmp_path),
            "--file",
            str(env_file),
            cwd=self.tmp_path,
        )
        self.assertEqual(explicit_builtin.returncode, 0)
        self.assertIn(str(env_file), explicit_builtin.stdout)

        excluded_explicit = run_pdk(
            self.tmp_path,
            "context",
            "--file",
            str(outside),
            "--exclude",
            "outside.md",
            cwd=self.tmp_path,
        )
        self.assertEqual(excluded_explicit.returncode, 0)
        self.assertNotIn(str(outside), excluded_explicit.stdout)

        included = run_pdk(
            self.tmp_path,
            "context",
            "--dir",
            str(docs),
            "--include",
            "*.md",
            "--exclude",
            "keep.md",
            "--format",
            "json",
            cwd=self.tmp_path,
        )
        self.assertEqual(included.returncode, 0)
        included_payload = json.loads(included.stdout)
        included_paths = [item["path"] for item in included_payload["files"]]
        self.assertNotIn(str(keep), included_paths)
        self.assertNotIn(str(ignored), included_paths)
        self.assertNotIn(str(excluded), included_paths)

        empty = self.tmp_path / "empty"
        empty.mkdir()
        missing = run_pdk(self.tmp_path, "context", "--dir", str(empty), cwd=self.tmp_path)
        self.assertEqual(missing.returncode, 1)
        self.assertIn(f"no indexed files found under {empty}; run `pdk index DIR` first", missing.stderr)

    def test_context_profiles_load_project_context_toml_and_merge_cli(self):
        project = self.tmp_path / "project"
        project.mkdir()
        self.assertEqual(run_pdk(self.tmp_path, "project", "init", cwd=project).returncode, 0)
        docs = project / "docs"
        docs.mkdir()
        doc = docs / "doc.md"
        doc.write_text("Email ivan@example.com\n" + "Profile directory text. " * 80, encoding="utf-8")
        excluded = docs / "skip.md"
        excluded.write_text("Profile excluded text", encoding="utf-8")
        readme = project / "README.md"
        readme.write_text("Profile README text", encoding="utf-8")
        extra = project / "extra.md"
        extra.write_text("Extra CLI file text", encoding="utf-8")

        indexed = run_pdk(self.tmp_path, "index", "docs", "README.md", "extra.md", cwd=project)
        self.assertEqual(indexed.returncode, 0)
        (project / ".pdk" / "context.toml").write_text(
            "\n".join(
                [
                    "[context.default]",
                    'dirs = ["docs"]',
                    'files = ["README.md"]',
                    'exclude = ["skip.md"]',
                    'file_detail = "summary"',
                    "budget = 12000",
                    "redact = true",
                    "",
                    "[context.docs]",
                    'dirs = ["docs"]',
                    'files = ["README.md"]',
                    'file_detail = "summary"',
                    "budget = 8000",
                    "redact = true",
                ]
            ),
            encoding="utf-8",
        )

        profiled = run_pdk(self.tmp_path, "context", "--profile", "default", "--format", "json", cwd=project)
        self.assertEqual(profiled.returncode, 0, profiled.stderr)
        payload = json.loads(profiled.stdout)
        self.assertEqual(payload["metadata"]["budget"], 12000)
        paths = [item["path"] for item in payload["files"]]
        self.assertIn("docs/doc.md", paths)
        self.assertIn("README.md", paths)
        self.assertNotIn("docs/skip.md", paths)
        self.assertTrue(all(item["detail"] == "summary" for item in payload["files"]))
        self.assertTrue(all(item["text"] is None for item in payload["files"]))
        self.assertNotIn("ivan@example.com", profiled.stdout)
        self.assertIn("<EMAIL_1>", profiled.stdout)

        merged = run_pdk(
            self.tmp_path,
            "context",
            "--profile",
            "default",
            "--budget",
            "9000",
            "--file",
            str(extra),
            "--exclude",
            "doc.md",
            "--format",
            "json",
            cwd=project,
        )
        self.assertEqual(merged.returncode, 0)
        merged_payload = json.loads(merged.stdout)
        merged_paths = [item["path"] for item in merged_payload["files"]]
        self.assertEqual(merged_payload["metadata"]["budget"], 9000)
        self.assertIn("extra.md", merged_paths)
        self.assertIn("README.md", merged_paths)
        self.assertNotIn("docs/doc.md", merged_paths)

        missing = run_pdk(self.tmp_path, "context", "--profile", "missing", cwd=project)
        self.assertEqual(missing.returncode, 1)
        self.assertIn("context profile not found: missing", missing.stderr)

        (project / ".pdk" / "context.toml").write_text("[context.default\n", encoding="utf-8")
        malformed = run_pdk(self.tmp_path, "context", "--profile", "default", cwd=project)
        self.assertEqual(malformed.returncode, 1)
        self.assertIn("malformed context config", malformed.stderr)
        self.assertIn(".pdk/context.toml", malformed.stderr)

    def test_context_profile_modules_group_indexed_files_and_compact_markdown(self):
        project = self.tmp_path / "module-project"
        project.mkdir()
        self.assertEqual(run_pdk(self.tmp_path, "project", "init", cwd=project).returncode, 0)
        runtime = project / "src" / "runtime"
        storage = project / "src" / "storage"
        runtime.mkdir(parents=True)
        storage.mkdir(parents=True)
        runtime_file = runtime / "cli.py"
        runtime_file.write_text("def main():\n    return 'runtime'\n", encoding="utf-8")
        storage_file = storage / "db.ts"
        storage_file.write_text("export const db = 'storage';\n", encoding="utf-8")
        skipped = runtime / "skip.txt"
        skipped.write_text("skip me", encoding="utf-8")

        indexed = run_pdk(self.tmp_path, "index", "src", cwd=project)
        self.assertEqual(indexed.returncode, 0)
        self.assertIn("src/runtime/cli.py", indexed.stdout)
        self.assertIn("src/storage/db.ts", indexed.stdout)

        (project / ".pdk" / "context.toml").write_text(
            "\n".join(
                [
                    "[context.default]",
                    'file_detail = "full"',
                    "compact = true",
                    "",
                    "[[context.default.modules]]",
                    'name = "runtime"',
                    'description = "CLI orchestration"',
                    'dirs = ["src/runtime"]',
                    'include = ["*.py"]',
                    'depends_on = ["storage"]',
                    "",
                    "[[context.default.modules]]",
                    'name = "storage"',
                    'files = ["src/storage/db.ts"]',
                    'include = ["*.ts"]',
                ]
            ),
            encoding="utf-8",
        )

        payload_result = run_pdk(self.tmp_path, "context", "--profile", "default", "--format", "json", cwd=project)
        self.assertEqual(payload_result.returncode, 0, payload_result.stderr)
        payload = json.loads(payload_result.stdout)
        self.assertTrue(payload["metadata"]["compact"])
        self.assertEqual([module["name"] for module in payload["modules"]], ["runtime", "storage"])
        modules_by_path = {file["path"]: file["modules"] for file in payload["files"]}
        self.assertEqual(modules_by_path["src/runtime/cli.py"], ["runtime"])
        self.assertEqual(modules_by_path["src/storage/db.ts"], ["storage"])
        self.assertNotIn("src/runtime/skip.txt", modules_by_path)

        packed = run_pdk(self.tmp_path, "context", "--profile", "default", cwd=project)
        self.assertEqual(packed.returncode, 0)
        self.assertIn("## Modules", packed.stdout)
        self.assertIn("| runtime | storage |", packed.stdout)
        self.assertIn("### Module: runtime", packed.stdout)
        self.assertIn("#### src/runtime/cli.py", packed.stdout)
        self.assertIn("export const db", packed.stdout)
        self.assertNotIn("- id:", packed.stdout)

    def test_context_profile_requires_project_but_plain_context_still_works(self):
        plain = run_pdk(self.tmp_path, "context")
        self.assertEqual(plain.returncode, 0)
        self.assertIn("# Prompt Deck Context", plain.stdout)

        profiled = run_pdk(self.tmp_path, "context", "--profile", "default")
        self.assertEqual(profiled.returncode, 1)
        self.assertIn("context profiles require a project; run `pdk project init` first", profiled.stderr)

    def test_context_redacts_prompt_note_comment_and_file_text(self):
        source_file = self.tmp_path / "secret.txt"
        source_file.write_text("File email file@example.com", encoding="utf-8")
        self.assertEqual(run_pdk(self.tmp_path, "add", "secret", input="Prompt email prompt@example.com").returncode, 0)
        self.assertEqual(
            run_pdk(self.tmp_path, "feedback", "secret", input="Comment email comment@example.com").returncode,
            0,
        )
        self.assertEqual(
            run_pdk(
                self.tmp_path,
                "note",
                "add",
                "--title",
                "Secret",
                input="Note email note@example.com",
            ).returncode,
            0,
        )
        self.assertEqual(run_pdk(self.tmp_path, "index", str(source_file)).returncode, 0)

        context = run_pdk(
            self.tmp_path,
            "context",
            "--file",
            str(source_file),
            "--file-detail",
            "full",
            "--redact",
        )

        self.assertEqual(context.returncode, 0)
        self.assertNotIn("prompt@example.com", context.stdout)
        self.assertNotIn("comment@example.com", context.stdout)
        self.assertNotIn("note@example.com", context.stdout)
        self.assertNotIn("file@example.com", context.stdout)
        self.assertIn("<EMAIL_1>", context.stdout)

    def test_context_privacy_profile_affects_redaction(self):
        config_dir = self.tmp_path / "pdk-home"
        config_dir.mkdir()
        (config_dir / "privacy.toml").write_text(
            "\n".join(
                [
                    "[profiles.client_a]",
                    "disabled = []",
                    "",
                    "[[profiles.client_a.patterns]]",
                    'name = "client_ticket"',
                    'label = "Client ticket"',
                    'regex = "\\\\bCA-[0-9]{5}\\\\b"',
                    "score = 0.75",
                ]
            ),
            encoding="utf-8",
        )
        self.assertEqual(run_pdk(self.tmp_path, "add", "ticket", input="Ticket CA-12345").returncode, 0)

        plain = run_pdk(self.tmp_path, "context", "--redact")
        self.assertEqual(plain.returncode, 0)
        self.assertIn("CA-12345", plain.stdout)

        profiled = run_pdk(self.tmp_path, "context", "--redact", "--privacy-profile", "client_a")
        self.assertEqual(profiled.returncode, 0)
        self.assertNotIn("CA-12345", profiled.stdout)
        self.assertIn("<CLIENT_TICKET_1>", profiled.stdout)

    def test_context_budget_copy_and_dry_run_daily_driver_options(self):
        clip_file = self.tmp_path / "clipboard.txt"
        env = fake_path_env(
            self.tmp_path,
            {
                "pbcopy": '#!/bin/sh\ncat > "$PDK_CLIP_FILE"\n',
            },
            {"PDK_CLIP_FILE": str(clip_file)},
        )
        source_file = self.tmp_path / "context.txt"
        source_file.write_text("FULL FILE TEXT " * 20, encoding="utf-8")
        self.assertEqual(run_pdk(self.tmp_path, "add", "daily", input="FULL PROMPT TEXT " * 20).returncode, 0)
        self.assertEqual(run_pdk(self.tmp_path, "note", "add", "--title", "Daily", input="Daily note").returncode, 0)
        self.assertEqual(run_pdk(self.tmp_path, "index", str(source_file)).returncode, 0)

        under = run_pdk(self.tmp_path, "context", "--budget", "100000")
        self.assertEqual(under.returncode, 0)
        self.assertNotIn("context token budget exceeded", under.stderr)

        over = run_pdk(self.tmp_path, "context", "--budget", "1")
        self.assertEqual(over.returncode, 0)
        self.assertIn("context token budget exceeded", over.stderr)

        copied = run_pdk(self.tmp_path, "context", "--copy", env=env)
        self.assertEqual(copied.returncode, 0)
        self.assertEqual(copied.stdout, "")
        self.assertIn("Copied context to clipboard", copied.stderr)
        self.assertIn("# Prompt Deck Context", clip_file.read_text(encoding="utf-8"))

        copied_over = run_pdk(self.tmp_path, "context", "--copy", "--budget", "1", env=env)
        self.assertEqual(copied_over.returncode, 0)
        self.assertEqual(copied_over.stdout, "")
        self.assertIn("context token budget exceeded", copied_over.stderr)
        self.assertIn("Copied context to clipboard", copied_over.stderr)

        dry_run = run_pdk(
            self.tmp_path,
            "context",
            "--file",
            str(source_file),
            "--file-detail",
            "full",
            "--dry-run",
            "--budget",
            "1",
        )
        self.assertEqual(dry_run.returncode, 0)
        self.assertIn("prompts\t1", dry_run.stdout)
        self.assertIn("notes\t1", dry_run.stdout)
        self.assertIn("comments\t0", dry_run.stdout)
        self.assertIn("files\t1", dry_run.stdout)
        self.assertIn("estimated_tokens\t", dry_run.stdout)
        self.assertIn("budget_status\tover", dry_run.stdout)
        self.assertNotIn("FULL PROMPT TEXT", dry_run.stdout)
        self.assertNotIn("FULL FILE TEXT", dry_run.stdout)

        conflict = run_pdk(self.tmp_path, "context", "--dry-run", "--copy", env=env)
        self.assertEqual(conflict.returncode, 1)
        self.assertIn("--dry-run cannot be combined with --copy", conflict.stderr)

    def test_context_alias_export_include_since_and_json(self):
        self.assertEqual(run_pdk(self.tmp_path, "add", "prompt", input="first").returncode, 0)
        self.assertEqual(run_pdk(self.tmp_path, "add", "prompt", "--replace", input="second").returncode, 0)
        self.assertEqual(run_pdk(self.tmp_path, "feedback", "prompt", input="comment").returncode, 0)
        self.assertEqual(run_pdk(self.tmp_path, "note", "add", "--title", "Fact", input="note body").returncode, 0)

        exported = run_pdk(self.tmp_path, "export")
        self.assertEqual(exported.returncode, 0)
        self.assertIn("# Prompt Deck Export", exported.stdout)
        self.assertIn("comment", exported.stdout)
        self.assertIn("note body", exported.stdout)
        self.assertIn("## Usage Timeline", exported.stdout)
        self.assertIn("#### Versions", exported.stdout)

        context = run_pdk(self.tmp_path, "context")
        self.assertEqual(context.returncode, 0)
        self.assertIn("# Prompt Deck Context", context.stdout)
        self.assertIn("## Index", context.stdout)
        self.assertIn("comment", context.stdout)
        self.assertIn("note body", context.stdout)
        self.assertNotIn("## Usage Timeline", context.stdout)
        self.assertNotIn("#### Versions", context.stdout)

        full_context = run_pdk(self.tmp_path, "context", "--include", "usage,versions")
        self.assertEqual(full_context.returncode, 0)
        self.assertIn("## Usage Timeline", full_context.stdout)
        self.assertIn("#### Versions", full_context.stdout)

        context_json = run_pdk(self.tmp_path, "context", "--format", "json", "--include", "usage,versions")
        self.assertEqual(context_json.returncode, 0)
        context_payload = json.loads(context_json.stdout)
        self.assertEqual(context_payload["metadata"]["include"], ["comments", "notes", "prompts", "usage", "versions"])
        self.assertEqual(context_payload["prompts"][0]["comments"][0]["body"], "comment")
        self.assertEqual(context_payload["notes"][0]["body"], "note body")
        self.assertGreaterEqual(context_payload["index"]["usage"], 1)

        since = run_pdk(self.tmp_path, "export", "--since", "2999-01-01")
        self.assertIn("### prompt", since.stdout)
        self.assertNotRegex(since.stdout, r"\[\d+\]: comment")

        positional_context = run_pdk(self.tmp_path, "context", "missing")
        self.assertEqual(positional_context.returncode, 1)
        self.assertIn("project not found: missing", positional_context.stderr)

        exported_json = run_pdk(self.tmp_path, "export", "--format", "json", "--include", "comments")
        self.assertEqual(exported_json.returncode, 0)
        payload = json.loads(exported_json.stdout)
        self.assertEqual(payload["index"]["prompts"], 1)
        self.assertEqual(payload["prompts"][0]["comments"][0]["body"], "comment")

