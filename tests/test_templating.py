import unittest

from pmpt.templating import find_variables, render_template


class TemplatingTest(unittest.TestCase):
    def test_find_variables_returns_unique_names_in_appearance_order(self):
        self.assertEqual(
            find_variables("{{first}} {{second}} {{first}}"),
            ["first", "second"],
        )

    def test_render_template_reuses_repeated_value(self):
        text = "{{name}}\nAgain: {{name}}"
        self.assertEqual(render_template(text, {"name": "Ada"}), "Ada\nAgain: Ada")

    def test_render_template_inserts_values_literally(self):
        text = "{{outer}} {{inner}}"
        self.assertEqual(
            render_template(text, {"outer": "{{inner}}", "inner": "done"}),
            "{{inner}} done",
        )

    def test_prompt_without_variables_is_unchanged(self):
        text = "plain prompt"
        self.assertEqual(find_variables(text), [])
        self.assertEqual(render_template(text, {}), text)


if __name__ == "__main__":
    unittest.main()
