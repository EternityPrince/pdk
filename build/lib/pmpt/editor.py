from __future__ import annotations

import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TextIO


class EditorError(Exception):
    pass


class TextEditor:
    def __init__(self, command: list[str]) -> None:
        if not command:
            raise EditorError("EDITOR is empty")
        self._command = command

    @classmethod
    def from_environment(cls) -> TextEditor:
        editor = os.environ.get("EDITOR") or "vi"
        return cls(shlex.split(editor))

    def edit(self, initial: str = "") -> str:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".txt",
            prefix="pmpt-",
            delete=False,
        ) as tmp:
            tmp.write(initial)
            tmp_path = Path(tmp.name)

        try:
            returncode = self._run(tmp_path)
            if returncode != 0:
                raise EditorError(f"editor exited with status {returncode}")
            return tmp_path.read_text(encoding="utf-8")
        finally:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass

    def read_or_edit(self, stdin: TextIO) -> str:
        if stdin.isatty():
            return self.edit("")
        return stdin.read()

    def _run(self, path: Path) -> int:
        command = [*self._command, str(path)]
        try:
            with open("/dev/tty", "r", encoding="utf-8") as tty_in, open(
                "/dev/tty",
                "w",
                encoding="utf-8",
            ) as tty_out:
                result = subprocess.run(
                    command,
                    stdin=tty_in,
                    stdout=tty_out,
                    stderr=tty_out,
                    check=False,
                )
        except OSError:
            result = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=sys.stderr,
                stderr=sys.stderr,
                check=False,
            )
        return result.returncode
