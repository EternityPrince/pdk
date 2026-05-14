from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from typing import TextIO

from .editor import TextEditor
from .models import Prompt, TagSet, UsageAction
from .store import PromptStore
from .tokens import count_tokens, token_summary
from .ui import ColorMode, ConsoleStyle, PromptFormatter
from .variables import VariablePrompter


PROMPT_ACTIONS = {
    "": "show",
    "o": "show",
    "open": "show",
    "show": "show",
    "print": "print",
    "b": "back",
    "back": "back",
    "q": "quit",
    "quit": "quit",
    "exit": "quit",
    "n": "next",
    "next": "next",
    "p": "previous",
    "prev": "previous",
    "previous": "previous",
    "c": "copy",
    "copy": "copy",
    "cf": "copy-filled",
    "copy filled": "copy-filled",
    "copy-filled": "copy-filled",
    "e": "edit",
    "edit": "edit",
    "f": "feedback",
    "feedback": "feedback",
    "t": "tags",
    "tags": "tags",
    "v": "versions",
    "versions": "versions",
    "?": "help",
    "help": "help",
}


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
            if not self._handle_browse_command(command, prompts):
                return 0

    def _handle_browse_command(self, command: str, prompts: list[Prompt]) -> bool:
        if command in {"q", "quit", "exit"}:
            return False
        if command in {"?", "help"}:
            self._render_help()
            return True
        if command in {"r", "refresh"}:
            return True
        if command in {"", "o", "open"}:
            self._open_by_index(prompts, 1)
            return True
        if command == "tags":
            self._render_tags()
            return True
        if self._apply_browse_filter(command):
            return True
        if command.isdecimal():
            self._open_by_index(prompts, int(command))
            return True
        self._state = BrowserState(query=command or None)
        return True

    def _apply_browse_filter(self, command: str) -> bool:
        if command == "/":
            self._state = BrowserState()
            return True
        if command.startswith("#"):
            self._state = BrowserState(tags=TagSet.from_values([command[1:]]).names)
            return True
        if command.startswith("/"):
            self._state = BrowserState(query=command[1:].strip() or None)
            return True
        return False

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
            index = self._prompt_index(prompts, name)
            if index is None:
                self._line(self._style.paint("Current prompt is outside the active filter.", "yellow"))
                return
            prompt = self._store.get(name)
            self._render_prompt(prompt)
            command = self._ask("prompt> ").strip()
            next_name = self._handle_prompt_command(command, prompt, prompts, index)
            if next_name is None:
                return
            name = next_name

    def _prompt_index(self, prompts: list[Prompt], name: str) -> int | None:
        names = [prompt.name for prompt in prompts]
        return names.index(name) if name in names else None

    def _handle_prompt_command(
        self,
        command: str,
        prompt: Prompt,
        prompts: list[Prompt],
        index: int,
    ) -> str | None:
        action = PROMPT_ACTIONS.get(command)
        if action == "back":
            return None
        if action == "quit":
            raise SystemExit(0)
        if action in {"show", "print"}:
            self._show_prompt_body(prompt, detail=action)
            return prompt.name
        if action in {"next", "previous"}:
            return self._move_prompt(prompts, index, action)
        if action in {"copy", "copy-filled", "edit", "feedback", "tags", "versions", "help"}:
            self._run_prompt_action(action, prompt)
            return prompt.name
        if command == "/" or command.startswith("/"):
            return self._search_from_prompt(command, prompt.name)
        self._line(self._style.paint("Unknown action. Type ? for actions.", "yellow"))
        return prompt.name

    def _show_prompt_body(self, prompt: Prompt, *, detail: str) -> None:
        self._print_prompt(prompt)
        self._store.record_usage(UsageAction.BROWSE, [prompt.name], detail=detail)

    def _move_prompt(self, prompts: list[Prompt], index: int, action: str) -> str:
        if action == "next" and index + 1 < len(prompts):
            return prompts[index + 1].name
        if action == "previous" and index > 0:
            return prompts[index - 1].name
        message = "Already at the last prompt." if action == "next" else "Already at the first prompt."
        self._line(self._style.paint(message, "yellow"))
        return prompts[index].name

    def _run_prompt_action(self, action: str, prompt: Prompt) -> None:
        handlers = {
            "copy": self._copy_prompt,
            "copy-filled": self._copy_filled_prompt,
            "edit": self._edit_prompt,
            "feedback": self._add_feedback,
            "tags": self._edit_tags,
            "versions": self._show_versions,
        }
        if action == "help":
            self._render_prompt_help()
            return
        handlers[action](prompt)

    def _search_from_prompt(self, command: str, current_name: str) -> str:
        self._state = BrowserState(query=command[1:].strip() or None) if command.startswith("/") else BrowserState()
        matches = self._matching_prompts()
        if matches:
            return matches[0].name
        self._line(self._style.paint("No prompts found.", "yellow"))
        return current_name

    def _render_prompt(self, prompt: Prompt) -> None:
        self._line("")
        self._line(self._style.paint(prompt.name, "bold", "magenta") + self._formatter.tag_text(prompt))
        self._line(f"created: {prompt.created_at}")
        self._line(f"updated: {prompt.updated_at}")
        self._line(f"project: {prompt.project_name or 'unbound'}")
        self._line(f"tokens: {count_tokens(prompt.body)}")
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
            self._line(
                self._style.paint(
                    f"Copied filled prompt to clipboard. {token_summary(prompt.body, filled)}.",
                    "green",
                )
            )
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
