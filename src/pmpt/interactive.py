from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from typing import TextIO

from .editor import TextEditor
from .models import Prompt, TagSet, UsageAction
from .store import PromptStore
from .ui import ColorMode, ConsoleStyle, PromptFormatter
from .variables import VariablePrompter


@dataclass
class BrowserState:
    query: str | None = None
    tags: tuple[str, ...] = ()


class Clipboard:
    def __init__(self, command: str = "pbcopy") -> None:
        self._command = command

    def available(self) -> bool:
        return shutil.which(self._command) is not None

    def copy(self, text: str) -> bool:
        if not self.available():
            return False
        subprocess.run([self._command], input=text, text=True, check=True)
        return True


class InteractiveBrowser:
    def __init__(
        self,
        store: PromptStore,
        editor: TextEditor,
        stdin: TextIO,
        stdout: TextIO,
        *,
        color: ColorMode,
        clipboard: Clipboard | None = None,
        initial_query: str | None = None,
        initial_tags: tuple[str, ...] = (),
        project_id: int | None = None,
        project_filter: bool = False,
    ) -> None:
        self._store = store
        self._editor = editor
        self._stdin = stdin
        self._stdout = stdout
        self._style = ConsoleStyle(color, stdout)
        self._formatter = PromptFormatter(self._style)
        self._clipboard = clipboard or Clipboard()
        self._state = BrowserState(query=initial_query, tags=initial_tags)
        self._project_id = project_id
        self._project_filter = project_filter

    def run(self) -> int:
        self._line(self._style.paint("Prompt Deck browser", "bold", "magenta"))
        self._line("Type text to search, #tag to filter, / to clear, ? for commands, q to quit.")
        while True:
            prompts = self._matching_prompts()
            self._render_home(prompts)
            command = self._ask("browse> ").strip()
            if command in {"q", "quit", "exit"}:
                return 0
            if command in {"?", "help"}:
                self._render_help()
                continue
            if command in {"r", "refresh"}:
                continue
            if command in {"", "o", "open"}:
                self._open_by_index(prompts, 1)
                continue
            if command == "/":
                self._state = BrowserState()
                continue
            if command == "tags":
                self._render_tags()
                continue
            if command.startswith("#"):
                self._state = BrowserState(tags=TagSet.from_values([command[1:]]).names)
                continue
            if command.startswith("/"):
                self._state = BrowserState(query=command[1:].strip() or None)
                continue
            if command.isdecimal():
                self._open_by_index(prompts, int(command))
                continue
            self._state = BrowserState(query=command or None)

    def _matching_prompts(self) -> list[Prompt]:
        return self._store.list(
            tags=self._state.tags,
            query=self._state.query,
            project_id=self._project_id,
            project_filter=self._project_filter,
        )

    def _render_home(self, prompts: list[Prompt]) -> None:
        filters = []
        if self._state.query:
            filters.append(f"query={self._style.paint(self._state.query, 'yellow')}")
        if self._state.tags:
            filters.append("tags=" + ",".join(self._style.paint(f"#{tag}", "cyan") for tag in self._state.tags))
        suffix = f" ({'; '.join(filters)})" if filters else ""
        self._line("")
        self._line(self._style.paint(f"{len(prompts)} prompt(s){suffix}", "bold"))
        if not prompts:
            self._line(self._style.paint("No prompts found.", "yellow"))
            return
        for index, prompt in enumerate(prompts[:20], 1):
            self._stdout.write(self._formatter.browser_row(index, prompt))
        if len(prompts) > 20:
            self._line(self._style.paint(f"...and {len(prompts) - 20} more. Narrow the search.", "dim"))

    def _render_help(self) -> None:
        self._line("")
        self._line(self._style.paint("Commands", "bold"))
        self._line("  text        search by prompt name, body, or tag")
        self._line("  /text       search explicitly")
        self._line("  #tag        filter by tag")
        self._line("  tags        show tag aggregation")
        self._line("  /           clear search and tag filters")
        self._line("  number      open a prompt")
        self._line("  o/Enter     open the first prompt")
        self._line("  r           refresh")
        self._line("  q           quit")

    def _render_tags(self) -> None:
        tags = self._store.tags(
            project_id=self._project_id,
            project_filter=self._project_filter,
        )
        if not tags:
            self._line(self._style.paint("No tags yet.", "yellow"))
            return
        self._line("")
        self._line(self._style.paint("Tags", "bold"))
        for tag in tags:
            self._line(f"  {self._style.paint('#' + tag.name, 'cyan')}  {tag.prompt_count}")

    def _open_by_index(self, prompts: list[Prompt], index: int) -> None:
        if index < 1 or index > len(prompts):
            self._line(self._style.paint("No prompt at that number.", "red"))
            return
        self._open_prompt(prompts[index - 1].name)

    def _open_prompt(self, name: str) -> None:
        while True:
            prompts = self._matching_prompts()
            names = [prompt.name for prompt in prompts]
            if name not in names:
                self._line(self._style.paint("Current prompt is outside the active filter.", "yellow"))
                return
            index = names.index(name)
            prompt = self._store.get(name)
            self._render_prompt(prompt)
            command = self._ask("prompt> ").strip()
            if command == "":
                self._print_prompt(prompt)
                self._store.record_usage(UsageAction.BROWSE, [prompt.name], detail="show")
                continue
            if command in {"b", "back"}:
                return
            if command in {"q", "quit", "exit"}:
                raise SystemExit(0)
            if command in {"o", "open", "show"}:
                self._print_prompt(prompt)
                self._store.record_usage(UsageAction.BROWSE, [prompt.name], detail="show")
                continue
            if command in {"print"}:
                self._print_prompt(prompt)
                self._store.record_usage(UsageAction.BROWSE, [prompt.name], detail="print")
                continue
            if command in {"n", "next"}:
                if index + 1 >= len(prompts):
                    self._line(self._style.paint("Already at the last prompt.", "yellow"))
                else:
                    name = prompts[index + 1].name
                continue
            if command in {"p", "prev", "previous"}:
                if index == 0:
                    self._line(self._style.paint("Already at the first prompt.", "yellow"))
                else:
                    name = prompts[index - 1].name
                continue
            if command in {"c", "copy"}:
                self._copy_prompt(prompt)
                continue
            if command in {"cf", "copy filled", "copy-filled"}:
                self._copy_filled_prompt(prompt)
                continue
            if command in {"e", "edit"}:
                self._edit_prompt(prompt)
                continue
            if command in {"f", "feedback"}:
                self._add_feedback(prompt)
                continue
            if command in {"t", "tags"}:
                self._edit_tags(prompt)
                continue
            if command in {"v", "versions"}:
                self._show_versions(prompt)
                continue
            if command in {"?", "help"}:
                self._render_prompt_help()
                continue
            if command == "/":
                self._state = BrowserState()
                continue
            if command.startswith("/"):
                self._state = BrowserState(query=command[1:].strip() or None)
                matches = self._matching_prompts()
                if matches:
                    name = matches[0].name
                else:
                    self._line(self._style.paint("No prompts found.", "yellow"))
                continue
            self._line(self._style.paint("Unknown action. Type ? for actions.", "yellow"))

    def _render_prompt(self, prompt: Prompt) -> None:
        self._line("")
        self._line(self._style.paint(prompt.name, "bold", "magenta") + self._formatter.tag_text(prompt))
        self._line(f"created: {prompt.created_at}")
        self._line(f"updated: {prompt.updated_at}")
        self._line(f"project: {prompt.project_name or 'unbound'}")
        self._line(f"tags: {', '.join(prompt.tags) or '-'}")
        self._line("")
        self._stdout.write(prompt.body)
        if not prompt.body.endswith("\n"):
            self._line("")
        self._line(
            self._style.paint("actions:", "dim")
            + " enter/o=show n=next p=prev c=copy cf=copy-filled print=print "
            + "e=edit f=feedback t=tags v=versions b=back q=quit"
        )

    def _render_prompt_help(self) -> None:
        self._line("")
        self._line(self._style.paint("Prompt actions", "bold"))
        self._line("  Enter/o  show full prompt body again")
        self._line("  n/p      next or previous prompt in the active list")
        self._line("  /text    search and jump to the first match")
        self._line("  c        copy raw prompt body with pbcopy when available")
        self._line("  cf       fill variables, then copy the rendered prompt")
        self._line("  print    print full prompt body")
        self._line("  e  edit prompt in $EDITOR")
        self._line("  f  add feedback in $EDITOR")
        self._line("  t  add or remove tags")
        self._line("  v  show previous versions")
        self._line("  b  back to list")
        self._line("  q  quit")

    def _print_prompt(self, prompt: Prompt) -> None:
        self._line("")
        self._stdout.write(prompt.body)
        if not prompt.body.endswith("\n"):
            self._line("")

    def _copy_prompt(self, prompt: Prompt) -> None:
        try:
            copied = self._clipboard.copy(prompt.body)
        except subprocess.CalledProcessError:
            copied = False
        if copied:
            self._store.record_usage(UsageAction.BROWSE, [prompt.name], detail="copy")
            self._line(self._style.paint("Copied to clipboard.", "green"))
        else:
            self._line(self._style.paint("Clipboard command is not available.", "yellow"))

    def _copy_filled_prompt(self, prompt: Prompt) -> None:
        try:
            filled = VariablePrompter(
                self._editor,
                self._stdin,
                self._stdout,
                color="never",
            ).fill(prompt.body)
            copied = self._clipboard.copy(filled)
        except subprocess.CalledProcessError:
            copied = False
        if copied:
            self._store.record_usage(UsageAction.BROWSE, [prompt.name], detail="copy filled")
            self._line(self._style.paint("Copied filled prompt to clipboard.", "green"))
        else:
            self._line(self._style.paint("Clipboard command is not available.", "yellow"))

    def _edit_prompt(self, prompt: Prompt) -> None:
        updated = self._editor.edit(prompt.body)
        self._store.update(prompt.name, updated)
        self._line(self._style.paint("Prompt updated.", "green"))

    def _add_feedback(self, prompt: Prompt) -> None:
        self._line("Opening $EDITOR for feedback.")
        body = self._editor.edit("")
        self._store.add_feedback(prompt.name, body)
        self._line(self._style.paint("Feedback saved.", "green"))

    def _edit_tags(self, prompt: Prompt) -> None:
        self._line("Enter +tag to add or -tag to remove. Separate several by spaces.")
        raw = self._ask("tags> ").strip()
        add = [item[1:] for item in raw.split() if item.startswith("+") and len(item) > 1]
        remove = [item[1:] for item in raw.split() if item.startswith("-") and len(item) > 1]
        if add:
            self._store.add_tags(prompt.name, add)
            self._line(self._style.paint("Tags added: " + ", ".join(TagSet.from_values(add).names), "green"))
        if remove:
            self._store.remove_tags(prompt.name, remove)
            self._line(self._style.paint("Tags removed: " + ", ".join(TagSet.from_values(remove).names), "yellow"))
        if not add and not remove:
            self._line(self._style.paint("No tag changes.", "yellow"))

    def _show_versions(self, prompt: Prompt) -> None:
        versions = self._store.versions(prompt.name)
        if not versions:
            self._line(self._style.paint("No previous versions.", "yellow"))
            return
        self._line("")
        self._line(self._style.paint("Previous versions", "bold"))
        for version in versions[:10]:
            self._line(
                f"  {self._style.paint(str(version.id), 'yellow')} "
                f"{version.created_at} {version.reason}: "
                f"{self._formatter.preview(version.body, 100)}"
            )

    def _ask(self, prompt: str) -> str:
        self._stdout.write(self._style.paint(prompt, "blue"))
        self._stdout.flush()
        line = self._stdin.readline()
        if line == "":
            return "q"
        return line.rstrip("\n")

    def _line(self, text: str) -> None:
        self._stdout.write(text + "\n")
