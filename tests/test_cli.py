from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

from pdk.tokens import count_tokens


ROOT = Path(__file__).resolve().parents[1]
FAKE_EDITOR = r"""
from pathlib import Path
import os
import sys

path = Path(sys.argv[-1])
values = os.environ["PDK_FAKE_EDITOR_VALUES"].split("\x1e")
state = Path(os.environ["PDK_FAKE_EDITOR_STATE"])
index = int(state.read_text(encoding="utf-8")) if state.exists() else 0
path.write_text(values[index], encoding="utf-8")
state.write_text(str(index + 1), encoding="utf-8")
"""


def run_pdk(
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
        [sys.executable, "-m", "pdk.cli", *args],
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
        "PDK_FAKE_EDITOR_VALUES": "\x1e".join(values),
        "PDK_FAKE_EDITOR_STATE": str(state),
    }


def fake_path_env(tmp_path: Path, commands: dict[str, str], extra: dict[str, str] | None = None) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name, body in commands.items():
        path = bin_dir / name
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)
    env = {"PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", "")}
    if extra:
        env.update(extra)
    return env


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_packaging_exposes_only_pdk_console_script(self):
        with (ROOT / "pyproject.toml").open("rb") as file:
            pyproject = tomllib.load(file)

        self.assertEqual(pyproject["project"]["scripts"], {"pdk": "pdk.cli:main"})

    def test_help_uses_pdk_program_name(self):
        helped = run_pdk(self.tmp_path, "--help")
        self.assertEqual(helped.returncode, 0)
        self.assertIn("usage: pdk", helped.stdout)
        self.assertIn("Prompt Deck", helped.stdout)
        self.assertIn("AI context", helped.stdout)
        self.assertIn("Workflows:", helped.stdout)
        self.assertIn("How scope and projects fit together:", helped.stdout)
        self.assertIn("Examples", helped.stdout)
        self.assertIn("pdk session build sport", helped.stdout)
        self.assertIn("pdk show workout --context", helped.stdout)
        self.assertIn("pdk context client-a", helped.stdout)
        self.assertIn("pdk context client-a --dir src --redact --budget 12000", helped.stdout)
        self.assertIn("pdk context --profile default --copy", helped.stdout)
        self.assertNotIn('pdk note add --title "Decision log" < notes.md', helped.stdout)

    def test_readme_documents_v02_context_workflow(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("Prompt Deck is a local AI context kit", readme)
        self.assertIn("## Session context from Markdown folders", readme)
        self.assertIn("pdk session build sport", readme)
        self.assertIn("pdk show workout --context", readme)
        self.assertIn("saved session context", readme)
        self.assertIn("pdk context --profile default --copy", readme)
        self.assertIn("`pdk context` is the lower-level, universal context builder", readme)
        self.assertIn("`pdk export` is different again", readme)

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

    def test_check_defaults_to_clipboard_and_reports_text_stats(self):
        clipboard_text = "Hello clipboard\nSecond line"
        env = fake_path_env(
            self.tmp_path,
            {
                "pbpaste": "#!/bin/sh\nprintf 'Hello clipboard\\nSecond line'\n",
            },
        )

        checked = run_pdk(self.tmp_path, "check", env=env)

        self.assertEqual(checked.returncode, 0)
        self.assertEqual(checked.stderr, "")
        self.assertIn("source\tclipboard", checked.stdout)
        self.assertIn(f"tokens\t{count_tokens(clipboard_text)}", checked.stdout)
        self.assertIn("characters\t27", checked.stdout)
        self.assertIn("lines\t2", checked.stdout)
        self.assertIn("words\t4", checked.stdout)
        self.assertIn("empty\tno", checked.stdout)
        self.assertIn("secret_warnings\t-", checked.stdout)

    def test_tokens_defaults_to_clipboard_and_prints_only_count(self):
        clipboard_text = "Hello clipboard\nSecond line"
        env = fake_path_env(
            self.tmp_path,
            {
                "pbpaste": "#!/bin/sh\nprintf 'Hello clipboard\\nSecond line'\n",
            },
        )

        counted = run_pdk(self.tmp_path, "tokens", env=env)

        self.assertEqual(counted.returncode, 0)
        self.assertEqual(counted.stdout, f"{count_tokens(clipboard_text)}\n")
        self.assertEqual(counted.stderr, "")

        alias = run_pdk(self.tmp_path, "tok", env=env)
        self.assertEqual(alias.returncode, 0)
        self.assertEqual(alias.stdout, f"{count_tokens(clipboard_text)}\n")

        detailed = run_pdk(self.tmp_path, "tokens", "--stdin", "--details", input=clipboard_text)
        self.assertEqual(detailed.returncode, 0)
        self.assertIn("source\tstdin", detailed.stdout)
        self.assertIn(f"tokens\t{count_tokens(clipboard_text)}", detailed.stdout)
        self.assertIn("tokenizer\t", detailed.stdout)

    def test_check_can_read_stdin_or_file(self):
        stdin_checked = run_pdk(self.tmp_path, "check", "--stdin", input="one two\n")
        self.assertEqual(stdin_checked.returncode, 0)
        self.assertIn("source\tstdin", stdin_checked.stdout)
        self.assertIn("words\t2", stdin_checked.stdout)

        prompt_file = self.tmp_path / "prompt.md"
        prompt_file.write_text("api_key=sk-abcdefghijklmnopqrstuvwxyz", encoding="utf-8")
        file_checked = run_pdk(self.tmp_path, "check", "--file", str(prompt_file))
        self.assertEqual(file_checked.returncode, 0)
        self.assertIn(f"source\t{prompt_file}", file_checked.stdout)
        self.assertIn("secret_warnings\t", file_checked.stdout)
        self.assertNotIn("secret_warnings\t-", file_checked.stdout)

    def test_check_show_spans_detects_russian_private_data(self):
        text = "ФИО: Иван Петров. Свяжитесь: +7 999 123-45-67, паспорт 4510 123456, email ivan@example.com"

        checked = run_pdk(self.tmp_path, "check", "--stdin", "--show-spans", input=text)

        self.assertEqual(checked.returncode, 0)
        self.assertIn("private_findings\t4", checked.stdout)
        self.assertIn("finding\tentity\tstart\tend\tscore\tdetector\tpreview", checked.stdout)
        self.assertIn("\tru_full_name\t", checked.stdout)
        self.assertIn("\tru_phone\t", checked.stdout)
        self.assertIn("\tru_passport\t", checked.stdout)
        self.assertIn("\temail\t", checked.stdout)
        self.assertNotIn("Иван Петров", checked.stdout)
        self.assertNotIn("ivan@example.com", checked.stdout)
        self.assertNotIn("+7 999 123-45-67", checked.stdout)

    def test_redact_replaces_private_data_with_placeholders(self):
        text = "Email ivan@example.com, phone +7 999 123-45-67, again ivan@example.com."

        redacted = run_pdk(self.tmp_path, "redact", "--stdin", input=text)

        self.assertEqual(redacted.returncode, 0)
        self.assertEqual(
            redacted.stdout,
            "Email <EMAIL_1>, phone <RU_PHONE_1>, again <EMAIL_1>.",
        )

    def test_scan_defaults_to_clipboard_and_prints_summary_table(self):
        env = fake_path_env(
            self.tmp_path,
            {
                "pbpaste": "#!/bin/sh\nprintf 'Email ivan@example.com\\n'\n",
            },
        )

        scanned = run_pdk(self.tmp_path, "scan", env=env)

        self.assertEqual(scanned.returncode, 0)
        self.assertIn("source", scanned.stdout)
        self.assertIn("findings", scanned.stdout)
        self.assertIn("clipboard", scanned.stdout)
        self.assertIn("email", scanned.stdout)
        self.assertNotIn("ivan@example.com", scanned.stdout)

    def test_scan_accepts_files_and_directories_with_details(self):
        docs = self.tmp_path / "docs"
        docs.mkdir()
        first = docs / "first.md"
        second = docs / "second.txt"
        first.write_text("ФИО: Иван Петров", encoding="utf-8")
        second.write_text("Contact ivan@example.com", encoding="utf-8")

        scanned = run_pdk(self.tmp_path, "scan", str(docs), "--details")

        self.assertEqual(scanned.returncode, 0)
        self.assertIn(str(first), scanned.stdout)
        self.assertIn(str(second), scanned.stdout)
        self.assertIn("ru_full_name", scanned.stdout)
        self.assertIn("email", scanned.stdout)
        self.assertNotIn("Иван Петров", scanned.stdout)
        self.assertNotIn("ivan@example.com", scanned.stdout)

    def test_check_and_redact_accept_positional_file(self):
        prompt_file = self.tmp_path / "prompt.md"
        prompt_file.write_text("Email ivan@example.com", encoding="utf-8")

        checked = run_pdk(self.tmp_path, "check", str(prompt_file))
        self.assertEqual(checked.returncode, 0)
        self.assertIn(f"source\t{prompt_file}", checked.stdout)
        self.assertIn("email address", checked.stdout)

        redacted = run_pdk(self.tmp_path, "redact", str(prompt_file))
        self.assertEqual(redacted.returncode, 0)
        self.assertEqual(redacted.stdout, "Email <EMAIL_1>")

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

    def test_privacy_config_adds_custom_regex_patterns(self):
        config_dir = self.tmp_path / "pdk-home"
        config_dir.mkdir()
        (config_dir / "privacy.toml").write_text(
            "\n".join(
                [
                    "[privacy]",
                    "disabled = []",
                    "",
                    "[[patterns]]",
                    'name = "client_code"',
                    'label = "Client code"',
                    'regex = "\\\\bCL-[0-9]{4}\\\\b"',
                    "score = 0.9",
                ]
            ),
            encoding="utf-8",
        )

        checked = run_pdk(self.tmp_path, "check", "--stdin", "--show-spans", input="Use CL-2048")
        self.assertEqual(checked.returncode, 0)
        self.assertIn("\tclient_code\t", checked.stdout)
        self.assertIn("Client code", checked.stdout)

        listed = run_pdk(self.tmp_path, "privacy", "list")
        self.assertEqual(listed.returncode, 0)
        self.assertIn("client_code\tClient code\t0.90", listed.stdout)

    def test_privacy_profiles_add_project_specific_patterns_in_global_config(self):
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

        default_check = run_pdk(self.tmp_path, "check", "--stdin", "--show-spans", input="Ticket CA-12345")
        self.assertEqual(default_check.returncode, 0)
        self.assertIn("private_findings\t0", default_check.stdout)

        profile_check = run_pdk(
            self.tmp_path,
            "check",
            "--stdin",
            "--profile",
            "client_a",
            "--show-spans",
            input="Ticket CA-12345",
        )
        self.assertEqual(profile_check.returncode, 0)
        self.assertIn("\tclient_ticket\t", profile_check.stdout)

        profiles = run_pdk(self.tmp_path, "privacy", "profiles")
        self.assertEqual(profiles.returncode, 0)
        self.assertIn("client_a", profiles.stdout)

        listed = run_pdk(self.tmp_path, "privacy", "list", "--profile", "client_a")
        self.assertEqual(listed.returncode, 0)
        self.assertIn("client_ticket\tClient ticket\t0.75", listed.stdout)

    def test_privacy_model_reports_global_and_profile_config(self):
        config_dir = self.tmp_path / "pdk-home"
        config_dir.mkdir()
        (config_dir / "privacy.toml").write_text(
            "\n".join(
                [
                    "[model]",
                    "enabled = true",
                    'model = "base-model"',
                    "threshold = 0.7",
                    "",
                    "[profiles.client_a.model]",
                    'model = "client-model"',
                    "threshold = 0.9",
                ]
            ),
            encoding="utf-8",
        )

        default_model = run_pdk(self.tmp_path, "privacy", "model")
        self.assertEqual(default_model.returncode, 0)
        self.assertIn("enabled\tyes", default_model.stdout)
        self.assertIn("model\tbase-model", default_model.stdout)
        self.assertIn("threshold\t0.70", default_model.stdout)

        profile_model = run_pdk(self.tmp_path, "privacy", "model", "--profile", "client_a")
        self.assertEqual(profile_model.returncode, 0)
        self.assertIn("model\tclient-model", profile_model.stdout)
        self.assertIn("threshold\t0.90", profile_model.stdout)

    def test_privacy_init_writes_config_template(self):
        initialized = run_pdk(self.tmp_path, "privacy", "init")
        self.assertEqual(initialized.returncode, 0)
        config = self.tmp_path / "pdk-home" / "privacy.toml"
        self.assertTrue(config.exists())
        self.assertIn("[[patterns]]", config.read_text(encoding="utf-8"))
        self.assertIn("[profiles.client_a]", config.read_text(encoding="utf-8"))
        self.assertIn("[model]", config.read_text(encoding="utf-8"))

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

    def test_browse_search_open_print_and_quit(self):
        self.assertEqual(
            run_pdk(
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
            run_pdk(self.tmp_path, "add", "work", "--tag", "job", input="Draft an update.").returncode,
            0,
        )

        browsed = run_pdk(self.tmp_path, "browse", "--plain", "--query", "study", input="1\nprint\nb\nq\n")

        self.assertEqual(browsed.returncode, 0)
        self.assertIn("Prompt Deck browser", browsed.stdout)
        self.assertIn("lesson #study", browsed.stdout)
        self.assertIn("Explain fractions clearly.", browsed.stdout)
        self.assertNotIn("work #job", browsed.stdout)

    def test_browse_falls_back_to_plain_when_not_tty(self):
        self.assertEqual(run_pdk(self.tmp_path, "add", "plain", input="Plain body").returncode, 0)

        browsed = run_pdk(self.tmp_path, "browse", input="q\n")

        self.assertEqual(browsed.returncode, 0)
        self.assertIn("Prompt Deck browser", browsed.stdout)

    def test_browse_open_prompt_shows_full_body(self):
        long_body = "Start " + ("detail " * 40) + "full ending"
        self.assertEqual(run_pdk(self.tmp_path, "add", "long", input=long_body).returncode, 0)

        browsed = run_pdk(self.tmp_path, "browse", "--plain", input="1\nb\nq\n")

        self.assertEqual(browsed.returncode, 0)
        self.assertIn(long_body, browsed.stdout)
        self.assertIn("full ending", browsed.stdout)

    def test_browse_can_change_tags_inside_prompt_view(self):
        self.assertEqual(
            run_pdk(self.tmp_path, "add", "lesson", "--tag", "study", input="Body").returncode,
            0,
        )

        browsed = run_pdk(self.tmp_path, "browse", "--plain", input="1\nt\n+exam -study\nb\nq\n")
        self.assertEqual(browsed.returncode, 0)
        self.assertIn("Tags added: exam", browsed.stdout)
        self.assertIn("Tags removed: study", browsed.stdout)

        tags = run_pdk(self.tmp_path, "tags")
        self.assertIn("#exam\t1", tags.stdout)
        self.assertNotIn("#study", tags.stdout)

    def test_browse_prompt_view_navigation_search_and_metadata(self):
        self.assertEqual(
            run_pdk(self.tmp_path, "add", "alpha", "--tag", "first", input="Alpha body").returncode,
            0,
        )
        self.assertEqual(run_pdk(self.tmp_path, "add", "beta", input="Beta body").returncode, 0)

        browsed = run_pdk(self.tmp_path, "browse", "--plain", input="\nn\np\n/bet\nb\nq\n")

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

    def test_secret_warnings_and_redacted_exports(self):
        added = run_pdk(self.tmp_path, "add", "secret", input="api_key=sk-abcdefghijklmnopqrstuvwxyz")
        self.assertEqual(added.returncode, 0)
        self.assertIn("may contain secret-like data", added.stderr)

        exported = run_pdk(self.tmp_path, "export", "--format", "json")
        self.assertEqual(exported.returncode, 0)
        self.assertIn("export may contain secret-like data", exported.stderr)
        self.assertIn("sk-abcdefghijklmnopqrstuvwxyz", exported.stdout)

        redacted = run_pdk(self.tmp_path, "export", "--format", "json", "--redact")
        self.assertEqual(redacted.returncode, 0)
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz", redacted.stdout)
        self.assertIn("[REDACTED]", redacted.stdout)
        self.assertNotIn("export may contain secret-like data", redacted.stderr)

        markdown = run_pdk(self.tmp_path, "context", "--redact")
        self.assertEqual(markdown.returncode, 0)
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz", markdown.stdout)
        self.assertIn("<SECRET_ASSIGNMENT_1>", markdown.stdout)

    def test_security_lock_unlock_encrypts_global_store(self):
        env = {"PDK_PASSPHRASE": "correct horse battery staple"}
        self.assertEqual(run_pdk(self.tmp_path, "add", "secure", input="body").returncode, 0)

        status = run_pdk(self.tmp_path, "security", "status")
        self.assertEqual(status.returncode, 0)
        self.assertIn("encrypted\tno", status.stdout)

        locked = run_pdk(self.tmp_path, "security", "lock", env=env)
        self.assertEqual(locked.returncode, 0)
        self.assertIn("Encrypted global store", locked.stderr)
        self.assertIn("encrypted\tyes", run_pdk(self.tmp_path, "security", "status").stdout)

        blocked = run_pdk(self.tmp_path, "show", "secure")
        self.assertEqual(blocked.returncode, 1)
        self.assertIn("global store is encrypted", blocked.stderr)

        unlocked = run_pdk(self.tmp_path, "security", "unlock", env=env)
        self.assertEqual(unlocked.returncode, 0)
        self.assertIn("Decrypted global store", unlocked.stderr)
        self.assertEqual(run_pdk(self.tmp_path, "show", "secure").stdout, "body")

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


if __name__ == "__main__":
    unittest.main()
