from __future__ import annotations

from pdk.tokens import count_tokens
from tests.cli_base import CliTestCase
from tests.helpers import fake_path_env, run_pdk


class CliPrivacyTest(CliTestCase):
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
