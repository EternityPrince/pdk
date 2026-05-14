from __future__ import annotations

from tests.cli_base import CliTestCase
from tests.helpers import run_pdk


class CliBrowserTest(CliTestCase):
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

