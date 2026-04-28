from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from rich.console import Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from textual.app import App, ComposeResult, SuspendNotSupported
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Header, Input, Static

from .editor import EditorError, TextEditor
from .interactive import Clipboard
from .models import Prompt, PromptStats, TagSet, UsageAction
from .store import PromptStore
from .templating import find_variables
from .variables import VariablePrompter


class ClipboardAdapter(Protocol):
    def copy(self, text: str) -> bool:
        ...


@dataclass(frozen=True)
class BrowserFilter:
    query: str | None = None
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class PromptBrowserRow:
    prompt: Prompt
    show_count: int = 0
    edit_count: int = 0
    feedback_count: int = 0
    last_used_at: str | None = None
    variables: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        return self.prompt.name

    @property
    def body(self) -> str:
        return self.prompt.body

    @property
    def tag_label(self) -> str:
        return " ".join(f"#{tag}" for tag in self.prompt.tags) or "-"

    @property
    def variable_label(self) -> str:
        return ", ".join(self.variables) or "-"

    @property
    def project_label(self) -> str:
        return self.prompt.project_name or "unbound"

    @property
    def last_used_label(self) -> str:
        return short_timestamp(self.last_used_at)


def short_timestamp(value: str | None) -> str:
    if value is None:
        return "-"
    return value[:16].replace("T", " ")


def preview_text(value: str, limit: int = 180) -> str:
    collapsed = " ".join(value.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1] + "..."


def toggle_tag(tags: tuple[str, ...], tag: str) -> tuple[str, ...]:
    normalized = TagSet.from_values([tag]).names
    if not normalized:
        return tags
    name = normalized[0]
    if name in tags:
        return tuple(existing for existing in tags if existing != name)
    return (*tags, name)


def parse_tag_operations(raw: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    add = [item[1:] for item in raw.split() if item.startswith("+") and len(item) > 1]
    remove = [item[1:] for item in raw.split() if item.startswith("-") and len(item) > 1]
    return TagSet.from_values(add).names, TagSet.from_values(remove).names


def build_browser_rows(
    store: PromptStore,
    browser_filter: BrowserFilter,
    *,
    project_id: int | None = None,
    project_filter: bool = False,
) -> list[PromptBrowserRow]:
    prompts = store.list(
        tags=browser_filter.tags,
        query=browser_filter.query,
        project_id=project_id,
        project_filter=project_filter,
    )
    stats_by_name = {
        stats.name: stats
        for stats in store.stats(project_id=project_id, project_filter=project_filter)
    }
    return [row_from_prompt(prompt, stats_by_name.get(prompt.name)) for prompt in prompts]


def row_from_prompt(prompt: Prompt, stats: PromptStats | None = None) -> PromptBrowserRow:
    return PromptBrowserRow(
        prompt=prompt,
        show_count=stats.show_count if stats else 0,
        edit_count=stats.edit_count if stats else 0,
        feedback_count=stats.feedback_count if stats else 0,
        last_used_at=stats.last_used_at if stats else None,
        variables=tuple(find_variables(prompt.body)),
    )


class TextModal(ModalScreen[None]):
    BINDINGS = [
        Binding("escape", "close", "Close", show=False),
        Binding("q", "close", "Close", show=False),
        Binding("enter", "close", "Close", show=False),
    ]

    CSS = """
    TextModal {
        align: center middle;
    }

    #modal-panel {
        width: 80%;
        max-width: 96;
        height: auto;
        max-height: 80%;
        padding: 1 2;
        border: thick $primary;
        background: $surface;
    }
    """

    def __init__(self, title: str, body: str) -> None:
        super().__init__()
        self._title = title
        self._body = body

    def compose(self) -> ComposeResult:
        yield Static(Panel(Markdown(self._body), title=self._title), id="modal-panel")

    def action_close(self) -> None:
        self.dismiss(None)


class TagEditModal(ModalScreen[str | None]):
    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    CSS = """
    TagEditModal {
        align: center middle;
    }

    #tag-panel {
        width: 72;
        max-width: 90%;
        height: auto;
        padding: 1 2;
        border: thick $accent;
        background: $surface;
    }

    #tag-help {
        height: auto;
        margin-bottom: 1;
    }
    """

    def __init__(self, prompt_name: str, current_tags: tuple[str, ...]) -> None:
        super().__init__()
        self._prompt_name = prompt_name
        self._current_tags = current_tags

    def compose(self) -> ComposeResult:
        current = " ".join(f"#{tag}" for tag in self._current_tags) or "-"
        with Vertical(id="tag-panel"):
            yield Static(
                f"[b]{self._prompt_name}[/b]\nCurrent tags: {current}\n"
                "Enter +tag to add and -tag to remove.",
                id="tag-help",
            )
            yield Input(placeholder="+work -draft", id="tag-input")

    def on_mount(self) -> None:
        self.query_one("#tag-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.dismiss(event.value)

    def action_cancel(self) -> None:
        self.dismiss(None)


class PromptDeckTui(App[int]):
    CSS = """
    Screen {
        layout: vertical;
    }

    #topbar {
        height: 5;
        padding: 0 1;
        background: $surface;
    }

    #search {
        width: 100%;
    }

    #filters {
        height: 1;
        color: $text-muted;
    }

    #main {
        height: 1fr;
    }

    #prompt-table {
        width: 45%;
        min-width: 42;
        height: 100%;
        border: solid $primary;
    }

    #detail {
        width: 1fr;
        height: 100%;
        border: solid $accent;
        padding: 1 2;
        overflow-y: auto;
    }

    #status {
        height: 1;
        padding: 0 1;
        color: $text-muted;
        background: $surface;
    }
    """

    BINDINGS = [
        Binding("/", "focus_search", "Search"),
        Binding("escape", "clear_search", "Clear"),
        Binding("c", "copy_selected", "Copy"),
        Binding("f", "fill_copy_selected", "Fill+Copy"),
        Binding("e", "edit_selected", "Edit"),
        Binding("t", "edit_tags", "Tags"),
        Binding("v", "show_versions", "Versions"),
        Binding("question_mark", "show_help", "Help"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        store: PromptStore,
        editor: TextEditor,
        *,
        clipboard: ClipboardAdapter | None = None,
        initial_query: str | None = None,
        initial_tags: tuple[str, ...] = (),
        project_id: int | None = None,
        project_filter: bool = False,
    ) -> None:
        super().__init__()
        self._store = store
        self._editor = editor
        self._clipboard = clipboard or Clipboard()
        self._filter = BrowserFilter(query=initial_query, tags=initial_tags)
        self._project_id = project_id
        self._project_filter = project_filter
        self._rows: list[PromptBrowserRow] = []
        self._rows_by_name: dict[str, PromptBrowserRow] = {}
        self._selected_name: str | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="topbar"):
            yield Input(
                value=self._filter.query or "",
                placeholder="Search prompts, or submit #tag to toggle a tag filter",
                id="search",
            )
            yield Static("", id="filters")
        with Horizontal(id="main"):
            yield DataTable(id="prompt-table")
            yield Static("", id="detail")
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#prompt-table", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True
        table.add_column("prompt", key="prompt", width=24)
        table.add_column("tags", key="tags", width=22)
        table.add_column("uses", key="uses", width=6)
        table.add_column("feedback", key="feedback", width=8)
        table.add_column("last used", key="last_used", width=16)
        self._reload()
        self.query_one("#search", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "search":
            return
        value = event.value.strip()
        if value.startswith("#"):
            self._set_status(f"Press Enter to toggle {value}")
            return
        query = value or None
        if query == self._filter.query:
            return
        self._filter = BrowserFilter(query=query, tags=self._filter.tags)
        self._reload()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "search":
            return
        event.stop()
        value = event.value.strip()
        if value.startswith("#"):
            self._filter = BrowserFilter(
                query=None,
                tags=toggle_tag(self._filter.tags, value[1:]),
            )
            event.input.value = ""
            self._reload()
            return
        self.query_one("#prompt-table", DataTable).focus()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id != "prompt-table":
            return
        self._selected_name = str(event.row_key.value)
        self._render_detail()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "prompt-table":
            return
        self._selected_name = str(event.row_key.value)
        self.action_copy_selected()

    def action_focus_search(self) -> None:
        search = self.query_one("#search", Input)
        search.focus()
        search.cursor_position = len(search.value)

    def action_clear_search(self) -> None:
        search = self.query_one("#search", Input)
        if self._filter.query is None and not search.value:
            self._set_status("Search is already clear.")
            return
        self._filter = BrowserFilter(query=None, tags=self._filter.tags)
        search.value = ""
        self._reload()

    def action_copy_selected(self) -> None:
        row = self._selected_row()
        if row is None:
            self._set_status("No prompt selected.", severity="warning")
            return
        self._copy_text(row.body, row.name, detail="copy")

    def action_fill_copy_selected(self) -> None:
        row = self._selected_row()
        if row is None:
            self._set_status("No prompt selected.", severity="warning")
            return
        try:
            filled = self._run_suspended(
                lambda: VariablePrompter(
                    self._editor,
                    self.console.file,
                    self.console.file,
                    color="never",
                ).fill(row.body)
            )
        except EditorError as exc:
            self._set_status(f"Editor failed: {exc}", severity="error", notify=True)
            return
        self._copy_text(filled, row.name, detail="copy filled", filled=True)

    def action_edit_selected(self) -> None:
        row = self._selected_row()
        if row is None:
            self._set_status("No prompt selected.", severity="warning")
            return
        try:
            updated = self._run_suspended(lambda: self._editor.edit(row.body))
            self._store.update(row.name, updated)
        except EditorError as exc:
            self._set_status(f"Editor failed: {exc}", severity="error", notify=True)
            return
        self._reload(selected_name=row.name, update_status=False)
        self._set_status(f"Updated {row.name}.", severity="information", notify=True)

    async def action_edit_tags(self) -> None:
        row = self._selected_row()
        if row is None:
            self._set_status("No prompt selected.", severity="warning")
            return
        raw = await self.push_screen_wait(TagEditModal(row.name, row.prompt.tags))
        if raw is None:
            return
        add, remove = parse_tag_operations(raw)
        if add:
            self._store.add_tags(row.name, add)
        if remove:
            self._store.remove_tags(row.name, remove)
        if not add and not remove:
            self._set_status("No tag changes.", severity="warning")
            return
        parts = []
        if add:
            parts.append("added " + ", ".join(add))
        if remove:
            parts.append("removed " + ", ".join(remove))
        self._reload(selected_name=row.name, update_status=False)
        self._set_status(f"Tags updated for {row.name}: {'; '.join(parts)}.", notify=True)

    async def action_show_versions(self) -> None:
        row = self._selected_row()
        if row is None:
            self._set_status("No prompt selected.", severity="warning")
            return
        versions = self._store.versions(row.name)
        if not versions:
            await self.push_screen_wait(TextModal("Previous versions", "No previous versions."))
            return
        body = "\n\n".join(
            f"**{version.id}**  {version.created_at}  `{version.reason}`\n\n"
            f"{preview_text(version.body, 240)}"
            for version in versions[:12]
        )
        await self.push_screen_wait(TextModal(f"Previous versions: {row.name}", body))

    async def action_show_help(self) -> None:
        await self.push_screen_wait(
            TextModal(
                "Prompt Deck browser",
                "\n".join(
                    [
                        "`/` focus search",
                        "`#tag` + Enter toggles a tag filter",
                        "`Esc` clears search text",
                        "`Enter` or `c` copies the selected prompt",
                        "`f` fills variables in $EDITOR, then copies",
                        "`e` edits the selected prompt in $EDITOR",
                        "`t` edits tags with +tag and -tag",
                        "`v` shows previous versions",
                        "`q` quits",
                    ]
                ),
            )
        )

    def action_quit(self) -> None:
        self.exit(0)

    def _reload(self, *, selected_name: str | None = None, update_status: bool = True) -> None:
        self._rows = build_browser_rows(
            self._store,
            self._filter,
            project_id=self._project_id,
            project_filter=self._project_filter,
        )
        self._rows_by_name = {row.name: row for row in self._rows}
        table = self.query_one("#prompt-table", DataTable)
        table.clear()
        for row in self._rows:
            table.add_row(
                row.name,
                row.tag_label,
                str(row.show_count),
                str(row.feedback_count),
                row.last_used_label,
                key=row.name,
            )

        preferred = selected_name or self._selected_name
        if preferred not in self._rows_by_name:
            preferred = self._rows[0].name if self._rows else None
        self._selected_name = preferred

        if preferred is not None:
            table.move_cursor(row=list(self._rows_by_name).index(preferred), column=0)
        self._render_filters()
        self._render_detail()
        if update_status:
            self._set_status(f"{len(self._rows)} prompt(s).")

    def _render_filters(self) -> None:
        query = self._filter.query or "-"
        tags = " ".join(f"#{tag}" for tag in self._filter.tags) or "-"
        self.query_one("#filters", Static).update(
            f"query: {query}   tags: {tags}   submit #tag to toggle filters"
        )

    def _render_detail(self) -> None:
        row = self._selected_row()
        detail = self.query_one("#detail", Static)
        if row is None:
            detail.update(
                Panel(
                    Text("No prompts match the active filters.", style="yellow"),
                    title="Preview",
                )
            )
            return

        metadata = Table.grid(padding=(0, 2))
        metadata.add_column(style="bold")
        metadata.add_column()
        metadata.add_row("Project", row.project_label)
        metadata.add_row("Tags", row.tag_label)
        metadata.add_row("Variables", row.variable_label)
        metadata.add_row("Uses", str(row.show_count))
        metadata.add_row("Feedback", str(row.feedback_count))
        metadata.add_row("Created", short_timestamp(row.prompt.created_at))
        metadata.add_row("Updated", short_timestamp(row.prompt.updated_at))
        metadata.add_row("Last used", row.last_used_label)

        title = Text(row.name, style="bold magenta")
        body = row.body if row.body.strip() else "_Empty prompt_"
        detail.update(
            Group(
                Panel(metadata, title=title),
                Markdown(body),
            )
        )

    def _selected_row(self) -> PromptBrowserRow | None:
        if self._selected_name is None:
            return None
        return self._rows_by_name.get(self._selected_name)

    def _copy_text(self, text: str, prompt_name: str, *, detail: str, filled: bool = False) -> None:
        try:
            copied = self._clipboard.copy(text)
        except Exception as exc:
            self._set_status(f"Clipboard failed: {exc}", severity="error", notify=True)
            return
        if not copied:
            self._set_status("Clipboard command is not available.", severity="warning", notify=True)
            return
        self._store.record_usage(UsageAction.BROWSE, [prompt_name], detail=detail)
        self._reload(selected_name=prompt_name, update_status=False)
        message = "Copied filled prompt." if filled else "Copied prompt."
        self._set_status(f"{message} ({prompt_name})", notify=True)

    def _run_suspended(self, action: Callable[[], str]) -> str:
        try:
            with self.suspend():
                return action()
        except SuspendNotSupported:
            return action()

    def _set_status(self, message: str, *, severity: str = "information", notify: bool = False) -> None:
        self.query_one("#status", Static).update(message)
        if not notify:
            return
        try:
            self.notify(message, severity=severity, timeout=2)
        except Exception:
            pass


def run_tui_browser(
    store: PromptStore,
    editor: TextEditor,
    *,
    clipboard: ClipboardAdapter | None = None,
    initial_query: str | None = None,
    initial_tags: tuple[str, ...] = (),
    project_id: int | None = None,
    project_filter: bool = False,
) -> int:
    app = PromptDeckTui(
        store,
        editor,
        clipboard=clipboard,
        initial_query=initial_query,
        initial_tags=initial_tags,
        project_id=project_id,
        project_filter=project_filter,
    )
    result = app.run()
    return int(result or 0)
