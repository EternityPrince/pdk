from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from textual.widgets import DataTable, Static

from pmpt.models import UsageAction
from pmpt.store import PromptStore
from pmpt.tokens import count_tokens, token_summary
from pmpt.tui import (
    BrowserFilter,
    PromptDeckTui,
    build_browser_rows,
    parse_tag_operations,
    toggle_tag,
)


class FakeClipboard:
    def __init__(self) -> None:
        self.values: list[str] = []

    def copy(self, text: str) -> bool:
        self.values.append(text)
        return True


class FakeEditor:
    def __init__(self, value: str) -> None:
        self.value = value

    def edit(self, initial: str = "") -> str:
        return self.value


def variable_form(name: str, value: str) -> str:
    return "\n".join(
        [
            "# pdk variable form",
            f"--- pdk begin {{{{{name}}}}} ---",
            value,
            f"--- pdk end {{{{{name}}}}} ---",
            "",
        ]
    )


class TuiViewModelTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def store(self) -> PromptStore:
        return PromptStore(self.tmp_path / "prompts.sqlite3")

    def test_view_model_includes_filtering_stats_feedback_and_variables(self):
        store = self.store()
        store.add("lesson", "Explain {{topic}} clearly.", tags=["study"])
        store.add("work", "Draft an update.", tags=["job"])
        store.record_usage(UsageAction.SHOW, ["lesson"])
        store.add_feedback("lesson", "Too dry.")

        rows = build_browser_rows(store, BrowserFilter(query="explain"))

        self.assertEqual([row.name for row in rows], ["lesson"])
        self.assertEqual(rows[0].variables, ("topic",))
        self.assertEqual(rows[0].show_count, 1)
        self.assertEqual(rows[0].feedback_count, 1)
        self.assertEqual(rows[0].tag_label, "#study")
        self.assertEqual(rows[0].token_count, count_tokens("Explain {{topic}} clearly."))

    def test_tag_helpers_normalize_toggle_and_parse_operations(self):
        self.assertEqual(toggle_tag((), "Work"), ("work",))
        self.assertEqual(toggle_tag(("work", "review"), "work"), ("review",))
        self.assertEqual(
            parse_tag_operations("+Work +review -Draft"),
            (("work", "review"), ("draft",)),
        )


class TuiPilotTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def store(self) -> PromptStore:
        return PromptStore(self.tmp_path / "prompts.sqlite3")

    async def test_live_search_filters_table_and_updates_selection(self):
        store = self.store()
        store.add("lesson", "Explain fractions clearly.", tags=["study"])
        store.add("work", "Draft an update.", tags=["job"])
        app = PromptDeckTui(store, FakeEditor(""), clipboard=FakeClipboard())

        async with app.run_test(size=(110, 32), notifications=True) as pilot:
            await pilot.pause()
            table = app.query_one("#prompt-table", DataTable)
            self.assertEqual(table.row_count, 2)

            await pilot.press("f", "r", "a")
            await pilot.pause()

            self.assertEqual(table.row_count, 1)
            self.assertEqual(app._selected_name, "lesson")
            await pilot.press("q")

    async def test_hash_tag_submitted_in_search_toggles_filter(self):
        store = self.store()
        store.add("lesson", "Explain fractions clearly.", tags=["study"])
        store.add("work", "Draft an update.", tags=["job"])
        app = PromptDeckTui(store, FakeEditor(""), clipboard=FakeClipboard())

        async with app.run_test(size=(110, 32), notifications=True) as pilot:
            await pilot.pause()
            table = app.query_one("#prompt-table", DataTable)

            await pilot.press("#", "s", "t", "u", "d", "y", "enter")
            await pilot.pause()

            self.assertEqual(table.row_count, 1)
            self.assertEqual(app._selected_name, "lesson")

            await pilot.press("#", "s", "t", "u", "d", "y", "enter")
            await pilot.pause()

            self.assertEqual(table.row_count, 2)
            await pilot.press("q")

    async def test_copy_selected_prompt_from_table(self):
        store = self.store()
        store.add("lesson", "Explain fractions clearly.", tags=["study"])
        clipboard = FakeClipboard()
        app = PromptDeckTui(store, FakeEditor(""), clipboard=clipboard)

        async with app.run_test(size=(110, 32), notifications=True) as pilot:
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("c")
            await pilot.pause()

            self.assertEqual(clipboard.values, ["Explain fractions clearly."])
            self.assertEqual(app.query_one("#status", Static).content, "Copied prompt. (lesson)")
            await pilot.press("q")

    async def test_fill_and_copy_selected_prompt(self):
        store = self.store()
        store.add("lesson", "Explain {{topic}} clearly.", tags=["study"])
        clipboard = FakeClipboard()
        app = PromptDeckTui(
            store,
            FakeEditor(variable_form("topic", "fractions")),
            clipboard=clipboard,
        )

        async with app.run_test(size=(110, 32), notifications=True) as pilot:
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("f")
            await pilot.pause()

            self.assertEqual(clipboard.values, ["Explain fractions clearly."])
            self.assertEqual(
                app.query_one("#status", Static).content,
                "Copied filled prompt. "
                f"{token_summary('Explain {{topic}} clearly.', clipboard.values[0])}. "
                "(lesson)",
            )
            await pilot.press("q")
