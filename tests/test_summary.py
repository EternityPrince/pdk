from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from pdk.summary import DEFAULT_SUMMARY_MODEL, generate_summary


class FakeTokenizer:
    chat_template = "template"

    def apply_chat_template(self, messages, add_generation_prompt: bool):
        return "CHAT:" + messages[0]["content"]


class SummaryTest(TestCase):
    def test_generate_summary_uses_mlx_model_and_chat_template(self):
        calls = {}

        def fake_generate(model, tokenizer, *, prompt, max_tokens, verbose):
            calls["model"] = model
            calls["prompt"] = prompt
            calls["max_tokens"] = max_tokens
            calls["verbose"] = verbose
            return "  summary  "

        with patch("pdk.summary._load_mlx_model", return_value=("model", FakeTokenizer())):
            with patch.dict("sys.modules", {"mlx_lm": SimpleNamespace(generate=fake_generate)}):
                summary = generate_summary("Документ", max_tokens=123)

        self.assertEqual(summary, "summary")
        self.assertEqual(calls["model"], "model")
        self.assertIn("CHAT:", calls["prompt"])
        self.assertIn("Документ", calls["prompt"])
        self.assertEqual(calls["max_tokens"], 123)
        self.assertFalse(calls["verbose"])

    def test_default_summary_model_is_gemma_3_4b(self):
        self.assertEqual(DEFAULT_SUMMARY_MODEL, "mlx-community/gemma-3-text-4b-it-4bit")
