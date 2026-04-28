from __future__ import annotations

import os
from typing import Literal, TextIO

from .models import Prompt

ColorMode = Literal["auto", "always", "never"]


class ConsoleStyle:
    COLORS = {
        "blue": "\033[34m",
        "cyan": "\033[36m",
        "green": "\033[32m",
        "magenta": "\033[35m",
        "red": "\033[31m",
        "yellow": "\033[33m",
        "bold": "\033[1m",
        "dim": "\033[2m",
    }
    RESET = "\033[0m"

    def __init__(self, mode: ColorMode, stream: TextIO) -> None:
        if mode == "always":
            self.enabled = True
        elif mode == "never" or os.environ.get("NO_COLOR"):
            self.enabled = False
        else:
            self.enabled = stream.isatty()

    def paint(self, text: str, *colors: str) -> str:
        if not self.enabled:
            return text
        prefix = "".join(self.COLORS[color] for color in colors)
        return f"{prefix}{text}{self.RESET}"


class PromptFormatter:
    def __init__(self, style: ConsoleStyle) -> None:
        self._style = style

    @staticmethod
    def preview(body: str, limit: int = 72) -> str:
        collapsed = " ".join(body.split())
        if len(collapsed) <= limit:
            return collapsed
        return collapsed[: limit - 1] + "..."

    def tag_text(self, prompt: Prompt) -> str:
        if not prompt.tags:
            return ""
        return " " + " ".join(self._style.paint(f"#{tag}", "cyan") for tag in prompt.tags)

    def prompt_row(self, prompt: Prompt) -> str:
        return (
            f"{self._style.paint(prompt.name, 'bold', 'magenta')}\t"
            f"{self.preview(prompt.body)}"
            f"{self.tag_text(prompt)}\n"
        )

    def browser_row(self, index: int, prompt: Prompt) -> str:
        return (
            f"{self._style.paint(str(index).rjust(2), 'yellow')} "
            f"{self._style.paint(prompt.name, 'bold')}"
            f"{self.tag_text(prompt)}\n"
            f"   {self._style.paint(self.preview(prompt.body, 100), 'dim')}\n"
        )


class StatusReporter:
    def __init__(self, stream: TextIO, color: ColorMode) -> None:
        self._stream = stream
        self._style = ConsoleStyle(color, stream)

    def success(self, message: str) -> None:
        print(self._style.paint(message, "green"), file=self._stream)

    def warning(self, message: str) -> None:
        print(self._style.paint(message, "yellow"), file=self._stream)

    def error(self, message: str) -> None:
        print(f"pmpt: {self._style.paint(message, 'red')}", file=self._stream)
