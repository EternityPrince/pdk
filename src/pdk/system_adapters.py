from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import platform
import shutil
import sys


@dataclass(frozen=True)
class CommandSpec:
    args: tuple[str, ...]

    @property
    def executable(self) -> str:
        return self.args[0]

    @property
    def label(self) -> str:
        path = shutil.which(self.executable)
        suffix = f" ({path})" if path else ""
        return " ".join(self.args) + suffix


@dataclass(frozen=True)
class SystemAdapter:
    name: str
    clipboard_copy_candidates: tuple[CommandSpec, ...]
    clipboard_paste_candidates: tuple[CommandSpec, ...]

    def command_exists(self, name: str) -> bool:
        return shutil.which(name) is not None

    def first_available(self, commands: tuple[CommandSpec, ...]) -> CommandSpec | None:
        for command in commands:
            if self.command_exists(command.executable):
                return command
        return None

    def clipboard_copy_command(self) -> CommandSpec | None:
        return self.first_available(self.clipboard_copy_candidates)

    def clipboard_paste_command(self) -> CommandSpec | None:
        return self.first_available(self.clipboard_paste_candidates)

    def fzf_command(self) -> CommandSpec | None:
        command = CommandSpec(("fzf",))
        return command if self.command_exists(command.executable) else None

    def python_module_available(self, module: str) -> bool:
        return importlib.util.find_spec(module) is not None

    def runtime_label(self) -> str:
        return f"{platform.system()} {platform.release()} / Python {sys.version.split()[0]}"


def current_system_adapter() -> SystemAdapter:
    system = platform.system().lower()
    if system == "darwin":
        return SystemAdapter(
            name="macos",
            clipboard_copy_candidates=(CommandSpec(("pbcopy",)),),
            clipboard_paste_candidates=(CommandSpec(("pbpaste",)),),
        )
    if system == "linux":
        return SystemAdapter(
            name="linux",
            clipboard_copy_candidates=(
                CommandSpec(("wl-copy",)),
                CommandSpec(("xclip", "-selection", "clipboard")),
                CommandSpec(("xsel", "--clipboard", "--input")),
            ),
            clipboard_paste_candidates=(
                CommandSpec(("wl-paste",)),
                CommandSpec(("xclip", "-selection", "clipboard", "-o")),
                CommandSpec(("xsel", "--clipboard", "--output")),
            ),
        )
    return SystemAdapter(name=system or "unknown", clipboard_copy_candidates=(), clipboard_paste_candidates=())
